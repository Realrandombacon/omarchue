#!/usr/bin/env python3
"""Omarchue bridge helper — the only code that talks to the Hue bridge.

One-shot CLI driven by QML through Quickshell's Process. Design rules
inherited from the two existing Omarchy Hue plugins' hard-won lessons:

- stdout is machine JSON, always; human-readable text goes to stderr only.
- Exit codes carry the error taxonomy: 0 ok, 1 network, 2 unpaired,
  3 bad response, 4 usage.
- The API username never crosses into argv, logs, or the QML process.
- TLS is pinned to the Signify Hue root CA (hue_bridge_cacert.pem); the
  bridge's cert SAN names its 16-hex bridge id, not its IP, so we resolve
  that hostname to the IP ourselves for the duration of each request.
- HTTP redirects are refused (a compromised bridge must not be able to
  302 an authenticated URL elsewhere) and response sizes are capped.
- A network failure never looks like "no lights": bad responses exit
  non-zero with partial JSON on stdout, and callers keep their last
  good state.
"""

import argparse
import colorsys
import json
import math
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Vendored hue-entertainment DTLS modules (Apache-2.0, see vendor/).
_VENDOR_DIR = str(Path(__file__).resolve().parent / "vendor")
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)

EX_OK = 0
EX_NETWORK = 1
EX_UNPAIRED = 2
EX_BAD_RESPONSE = 3
EX_USAGE = 4

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PAIR_SECONDS = 90
PAIR_RETRY_SECS = 2
REQUEST_TIMEOUT = 6

STATE_PATH = (Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
              / "omarchy" / "settings" / "hue.json")
CACERT_PATH = Path(__file__).resolve().parent / "hue_bridge_cacert.pem"
# Test-only override (used by tests/fake_bridge.py); never set by the plugin.
TEST_BASE_URL = os.environ.get("HUE_BRIDGE_URL")

_USERNAME_RE = re.compile(r"^[0-9A-Za-z-]{20,64}$")
# Bridge-supplied names end up in QML Text elements (Text.AutoText): strip
# control, bidi and zero-width characters so a crafted name can't confuse
# the renderer.
_SANITIZE_RE = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁠-⁯﻿]")


def sanitize(text):
    return _SANITIZE_RE.sub("", str(text or "")).strip()


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def fail(code, error, **extra):
    out = {"ok": False, "code": code, "error": error}
    out.update(extra)
    emit(out)
    sys.exit(code)


# ---------------------------------------------------------------- TLS ----

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(req, timeout, ctx=None):
    """Open a request, always refusing redirects. With a TLS context, build
    a dedicated opener so the pinned CA is actually used."""
    if ctx is None:
        return _OPENER.open(req, timeout=timeout)
    handler = urllib.request.HTTPSHandler(context=ctx)
    opener = urllib.request.build_opener(_NoRedirect, handler)
    return opener.open(req, timeout=timeout)


class _BridgeResolver:
    """Patch getaddrinfo so the bridge-id hostname resolves to the IP.

    The bridge's certificate SAN lists <bridgeid>.local (or the bare
    16-hex id); connecting by IP would fail hostname verification. For the
    duration of a request we answer getaddrinfo for that hostname with the
    known IP, keeping full CA + hostname verification intact.
    """

    def __init__(self, bridge_id, bridge_ip):
        self._hostname = bridge_id.lower()
        self._ip = bridge_ip
        self._original = None

    def _getaddrinfo(self, host, *args, **kwargs):
        if isinstance(host, str) and host.lower() == self._hostname:
            host = self._ip
        return self._original(host, *args, **kwargs)

    def __enter__(self):
        self._original = socket.getaddrinfo
        socket.getaddrinfo = self._getaddrinfo
        return self

    def __exit__(self, *exc):
        socket.getaddrinfo = self._original
        return False


def _tls_context(verify_hostname=True):
    ctx = ssl.create_default_context(cafile=str(CACERT_PATH))
    if not verify_hostname:
        # Still CA-pinned (an unrelated certificate is rejected), we just
        # skip the SAN check — used once during discovery, before we know
        # the bridge id.
        ctx.check_hostname = False
    return ctx


def _http(method, url, body=None, timeout=REQUEST_TIMEOUT, ctx=None,
          headers=None, cap=MAX_RESPONSE_BYTES):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _open(req, timeout, ctx) as resp:
            raw = resp.read(cap + 1)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = None
        return e.code, payload
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError):
        fail(EX_NETWORK, "bridge unreachable")
    if len(raw) > cap:
        fail(EX_BAD_RESPONSE, "response too large")
    try:
        return 200, json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError):
        fail(EX_BAD_RESPONSE, "malformed JSON response")


# ------------------------------------------------------- credentials ----

def load_creds():
    try:
        raw = STATE_PATH.read_text()
        creds = json.loads(raw)
    except FileNotFoundError:
        fail(EX_UNPAIRED, "not paired")
    except (OSError, ValueError):
        fail(EX_UNPAIRED, "credential file unreadable")
    if not creds.get("username") or not creds.get("bridgeId"):
        fail(EX_UNPAIRED, "credential file incomplete")
    return creds


def save_creds(creds):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(creds, fh)
        fh.write("\n")
    os.replace(tmp, STATE_PATH)


def bridge_base(creds):
    """Base URL for authenticated v1 paths (.../api/<username>)."""
    if TEST_BASE_URL:
        return TEST_BASE_URL.rstrip("/") + "/api/" + creds["username"]
    return "https://{}/api/{}".format(creds["bridgeId"].lower(), creds["username"])


def bridge_request(method, path, body=None, creds=None, timeout=REQUEST_TIMEOUT):
    """TLS-pinned request to the bridge. `path` is relative to the v1 user
    base (.../api/<username>). Returns (payload, http_status)."""
    creds = creds or load_creds()
    url = bridge_base(creds) + path
    if TEST_BASE_URL:
        status, payload = _http(method, url, body, timeout=timeout)
    else:
        with _BridgeResolver(creds["bridgeId"], creds["bridgeIp"]):
            status, payload = _http(method, url, body, timeout=timeout,
                                    ctx=_tls_context())
    if status == 401:
        fail(EX_UNPAIRED, "bridge rejected the application key")
    return payload, status


def v2_request(method, path, body=None, timeout=REQUEST_TIMEOUT):
    """TLS-pinned CLIP v2 request; the v1 username doubles as the v2
    application key. `path` is relative to the /clip/v2 root, e.g.
    "/resource/scene"."""
    creds = load_creds()
    headers = {"hue-application-key": creds["username"]}
    if TEST_BASE_URL:
        url = TEST_BASE_URL.rstrip("/") + "/clip/v2" + path
        status, payload = _http(method, url, body, timeout=timeout,
                                headers=headers)
    else:
        url = "https://{}/clip/v2{}".format(creds["bridgeId"].lower(), path)
        with _BridgeResolver(creds["bridgeId"], creds["bridgeIp"]):
            status, payload = _http(method, url, body, timeout=timeout,
                                    headers=headers, ctx=_tls_context())
    if status == 401:
        fail(EX_UNPAIRED, "bridge rejected the application key")
    return payload, status


def v2_error(payload, _status=None):
    """v2 responses carry errors as payload["errors"] entries; anything
    else (a v1-style error list, junk, None) is not a valid v2 answer."""
    if isinstance(payload, dict):
        errors = payload.get("errors") or []
        if errors:
            fail(EX_BAD_RESPONSE, str(errors[0]))
        return
    fail(EX_BAD_RESPONSE, "unexpected v2 response")


def v2_data(payload, status):
    """v2_error + unwrap the data array."""
    v2_error(payload, status)
    return payload.get("data") if isinstance(payload, dict) else None


# ------------------------------------------------------- discovery ------

def discover_bridges():
    """mDNS first (gives IP + bridge id in one shot, no rate limit), then
    the Philips discovery endpoint as fallback (rate-limited per IP)."""
    bridges = []
    try:
        out = subprocess.run(
            ["timeout", "5", "avahi-browse", "-t", "-r", "_hue._tcp"],
            capture_output=True, text=True, timeout=8)
        ip = None
        bridgeid = None
        for line in out.stdout.splitlines():
            m = re.search(r"address = \[([0-9a-fA-F:.]+)\]", line)
            if m:
                ip = m.group(1)
            m = re.search(r"bridgeid=([0-9A-Fa-f]{16})", line)
            if m:
                bridgeid = m.group(1).upper()
            if line.strip().startswith("=") and "IPv" in line:
                if ip and bridgeid and not any(b["bridgeid"] == bridgeid for b in bridges):
                    bridges.append({"ip": ip, "bridgeid": bridgeid})
                ip = bridgeid = None
        if ip and bridgeid and not any(b["bridgeid"] == bridgeid for b in bridges):
            bridges.append({"ip": ip, "bridgeid": bridgeid})
    except (OSError, subprocess.SubprocessError):
        pass
    if not bridges:
        try:
            with open("/dev/null"):
                pass
            req = urllib.request.Request("https://discovery.meethue.com/")
            with urllib.request.build_opener().open(req, timeout=5) as resp:
                for entry in json.loads(resp.read(65536).decode())[:5]:
                    if entry.get("internalipaddress"):
                        bridges.append({"ip": entry["internalipaddress"],
                                        "bridgeid": None})
        except Exception:
            pass
    return bridges


def read_bridge_config(ip):
    """One unauthenticated probe: returns {bridgeid, name} or None."""
    try:
        if TEST_BASE_URL:
            status, payload = _http("GET", TEST_BASE_URL.rstrip("/") + "/config")
        else:
            status, payload = _http(
                "GET", "https://{}/api/config".format(ip), timeout=5,
                ctx=_tls_context(verify_hostname=False))
        if status != 200 or not isinstance(payload, dict):
            return None
        bridgeid = payload.get("bridgeid")
        if not isinstance(bridgeid, str) or not re.fullmatch(r"[0-9A-Fa-f]{16}", bridgeid):
            return None
        return {"bridgeid": bridgeid, "name": sanitize(payload.get("name") or "Hue Bridge")}
    except Exception:
        return None


# ------------------------------------------------------- color math -----

def xy_to_rgb(x, y, brightness=0.75):
    """CIE 1931 xy -> sRGB at a fixed display luminance (chromaticity only)."""
    try:
        x = float(x); y = float(y)
        if y <= 1e-9 or x < 0 or y < 0 or x > 1 or y > 1:
            return None
        Y = 1.0
        X = (Y / y) * x
        Z = (Y - x * Y - y * Y) / y
        # sRGB D65 matrix
        r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
        g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
        b = 0.0557 * X - 0.2040 * Y + 1.0570 * Z
        rgb = [min(1.0, max(0.0, c)) ** (1 / 2.2) for c in (r, g, b)]
        m = max(rgb)
        if m <= 1e-6:
            return None
        scale = brightness / m
        return [min(1.0, c * scale) for c in rgb]
    except (TypeError, ValueError):
        return None


def hs_to_rgb(hue, sat, value=0.75):
    try:
        return list(colorsys.hsv_to_rgb((float(hue) % 65536) / 65536.0,
                                        min(1.0, float(sat) / 254.0), value))
    except (TypeError, ValueError):
        return None


def ct_to_rgb(mirek, value=0.9):
    """Approximate blackbody color for a mired value."""
    try:
        mirek = float(mirek)
        if mirek <= 0:
            return None
        t = 1e6 / mirek
        t = min(6600.0, max(1900.0, t)) / 100.0
        if t <= 66:
            r = 255.0
            g = 99.47 * math.log(t) - 161.12
        else:
            r = 329.7 * (t - 60) ** -0.1332
            g = 288.12 * (t - 60) ** -0.0755
        b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.52 * math.log(t - 10) - 305.04)
        norm = [min(255.0, max(0.0, c)) / 255.0 for c in (r, g, b)]
        mx = max(norm)
        return [c / mx * value if mx > 0 else value for c in norm] if mx > 0 else None
    except (TypeError, ValueError):
        return None


def to_hex(rgb):
    if not rgb:
        return "#1c1c1c"
    return "#{:02x}{:02x}{:02x}".format(*(int(round(255 * c)) for c in rgb))


def light_hex(light_state):
    """Chromaticity of a light as a hex string, for tints."""
    if light_state.get("xy"):
        rgb = xy_to_rgb(*light_state["xy"])
        if rgb:
            return to_hex(rgb)
    if light_state.get("hue") is not None and light_state.get("sat") is not None:
        rgb = hs_to_rgb(light_state["hue"], light_state["sat"])
        if rgb:
            return to_hex(rgb)
    if light_state.get("ct") is not None:
        rgb = ct_to_rgb(light_state["ct"])
        if rgb:
            return to_hex(rgb)
    return "#c8a25e"  # warm default


# ---------------------------------------------------- normalization -----

def normalize_light(light_id, data):
    state = data.get("state") or {}
    caps = ((data.get("capabilities") or {}).get("control") or {})
    has_bri = "bri" in state
    has_ct = "ct" in state
    has_color = "hue" in state and "sat" in state
    ct_min = ct_max = None
    ct_caps = caps.get("ct") or {}
    if isinstance(ct_caps.get("min"), int) and isinstance(ct_caps.get("max"), int):
        ct_min, ct_max = ct_caps["min"], ct_caps["max"]
    xy = state.get("xy") if isinstance(state.get("xy"), list) and len(state["xy"]) == 2 else None
    reachable = state.get("reachable", True) is True
    on = state.get("on") is True
    bri = state.get("bri")
    return {
        "id": str(light_id),
        "name": sanitize(data.get("name") or "Light"),
        "on": bool(on),
        "bri": bri if isinstance(bri, int) else None,
        "xy": xy,
        "hex": light_hex(state) if on else "#1c1c1c",
        "ct": state.get("ct"),
        "ctMin": ct_min or 153,
        "ctMax": ct_max or 500,
        "hasBri": has_bri,
        "hasCt": has_ct,
        "hasColor": has_color,
        "reachable": reachable,
        "type": sanitize(data.get("type") or ""),
    }


def group_tint(group, lights_by_id):
    """Average chromaticity of the group's ON lights. group action.bri is
    the bridge's stale record of the last command — never trusted here."""
    member_ids = group.get("lights") or []
    rgbs = []
    for lid in member_ids:
        light = lights_by_id.get(str(lid))
        if not light or not light["on"] or not light["reachable"]:
            continue
        state = light  # already normalized
        rgb = None
        if state["xy"]:
            rgb = xy_to_rgb(*state["xy"])
        elif state["hasColor"]:
            raw = light.get("_raw") or {}
            rgb = hs_to_rgb(raw.get("hue"), raw.get("sat"))
        elif state["ct"] is not None:
            rgb = ct_to_rgb(state["ct"])
        if rgb:
            rgbs.append(rgb)
    action = group.get("action") or {}
    if not rgbs:
        # No lit members: fall back to the group's last commanded color,
        # dimmed, so an off room still hints at what it was.
        if action.get("xy"):
            rgb = xy_to_rgb(*action["xy"], 0.25)
        elif action.get("hue") is not None:
            rgb = hs_to_rgb(action["hue"], action.get("sat", 254), 0.25)
        elif action.get("ct") is not None:
            rgb = ct_to_rgb(action["ct"], 0.25)
        else:
            rgb = [0.18, 0.12, 0.06]
        return to_hex(rgb)
    avg = [sum(c[i] for c in rgbs) / len(rgbs) for i in range(3)]
    return to_hex(avg)


def normalize_group(group_id, data, lights_by_id):
    members = [str(l) for l in (data.get("lights") or [])]
    on_members = [lights_by_id[i] for i in members if i in lights_by_id
                  and lights_by_id[i]["on"] and lights_by_id[i]["reachable"]]
    avg_bri = (sum(l["bri"] for l in on_members if l["bri"] is not None)
               // len(on_members)) if on_members else None
    action = data.get("action") or {}
    return {
        "id": str(group_id),
        "name": sanitize(data.get("name") or "Room"),
        "type": sanitize(data.get("type") or ""),      # Room / Zone / Luminaire
        "class": sanitize(data.get("class") or ""),
        "on": data.get("state", {}).get("any_on") is True,
        "bri": avg_bri,
        "tintHex": group_tint(data, lights_by_id) if lights_by_id
                   else (to_hex(xy_to_rgb(*(action.get("xy") or [0, 0]), 0.25)
                                if action.get("xy") else None)),
        "lightIds": members,
        "sceneIds": [str(s) for s in (data.get("scenes") or [])],
    }


def v1_error(payload, _status=None):
    """v1 responses carry errors as [{"error": {...}}] lists."""
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict) and "error" in entry:
                desc = (entry["error"] or {}).get("description", "bridge error")
                code_type = (entry["error"] or {}).get("type")
                if code_type == 1:
                    fail(EX_UNPAIRED, "unauthorized")
                fail(EX_BAD_RESPONSE, str(desc))
    return False


# ------------------------------------------------------ subcommands -----

def cmd_discover(_args):
    bridges = discover_bridges()
    for b in bridges:
        if not b.get("bridgeid"):
            info = read_bridge_config(b["ip"])
            if info:
                b["bridgeid"] = info["bridgeid"]
                b["name"] = info["name"]
    emit({"ok": True, "bridges": [b for b in bridges if b.get("bridgeid")]})
    sys.exit(EX_OK)


def cmd_pair(args):
    """Streamed JSON lines so the QML side can show progress live:
    discovering -> press-button(secondsLeft) -> paired."""
    if TEST_BASE_URL:
        # Headless pairing path against the fake bridge.
        save_creds({"bridgeIp": "127.0.0.1", "bridgeId": "fakebridge",
                    "username": "TESTUSERNAME1234567890AB", "apiVersion": "v1"})
        emit({"ok": True, "event": "paired"})
        sys.exit(EX_OK)

    emit({"event": "discovering"})
    ip, bridgeid = args.ip, args.bridgeid
    if not ip:
        bridges = discover_bridges()
        if not bridges:
            fail(EX_NETWORK, "no bridge found on this network")
        ip = bridges[0]["ip"]
        bridgeid = bridges[0].get("bridgeid")
    if not bridgeid:
        info = read_bridge_config(ip)
        if not info:
            fail(EX_NETWORK, "bridge at {} did not identify itself".format(ip))
        bridgeid = info["bridgeid"]

    deadline = time.monotonic() + PAIR_SECONDS
    body = {"devicetype": "omarchue#panel", "generateclientkey": True}
    username = None
    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        emit({"event": "press-button", "secondsLeft": max(0, remaining)})
        url = "https://{}/api".format(bridgeid.lower())
        with _BridgeResolver(bridgeid, ip):
            status, payload = _http("POST", url, body, timeout=5,
                                    ctx=_tls_context())
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict) and "success" in entry:
                    username = (entry["success"] or {}).get("username")
                    break
                if isinstance(entry, dict) and entry.get("error", {}).get("type") == 101:
                    pass  # link button not pressed yet
        if username and _USERNAME_RE.fullmatch(username):
            break
        time.sleep(PAIR_RETRY_SECS)
    if not username:
        fail(EX_UNPAIRED, "link button was not pressed in time")

    creds = {"bridgeIp": ip, "bridgeId": bridgeid.upper(),
             "username": username, "apiVersion": "v1"}
    save_creds(creds)
    emit({"event": "paired", "bridge": {"ip": ip, "bridgeid": bridgeid.upper(),
                                        "apiVersion": "v1"}})
    sys.exit(EX_OK)


def cmd_get_status(_args):
    """Ambient snapshot: rooms + scenes, no lights payload (bar widget)."""
    creds = load_creds()
    groups, st = bridge_request("GET", "/groups")
    v1_error(groups, st)
    scenes = []
    try:
        scenes, _ = bridge_request("GET", "/scenes")
    except SystemExit:
        scenes = []  # scenes are decorative for the ambient view
    if not isinstance(groups, dict):
        fail(EX_BAD_RESPONSE, "unexpected groups payload")
    out_groups = []
    for gid, data in (groups or {}).items():
        if not isinstance(data, dict):
            continue
        # Same canonical filter as get-state: Entertainment and auto-created
        # LightGroups (motion apps, Hue Sync, …) are not user-facing rooms.
        if data.get("type") not in ("Room", "Zone"):
            continue
        action = data.get("action") or {}
        tint = "#1c1c1c"
        if action.get("xy"):
            tint = to_hex(xy_to_rgb(*action["xy"], 0.6) or [0.1, 0.1, 0.1])
        elif action.get("hue") is not None:
            tint = to_hex(hs_to_rgb(action["hue"], action.get("sat", 254), 0.6))
        out_groups.append({
            "id": str(gid),
            "name": sanitize(data.get("name") or "Room"),
            "type": sanitize(data.get("type") or ""),
            "class": sanitize(data.get("class") or ""),
            "on": data.get("state", {}).get("any_on") is True,
            "bri": action.get("bri"),
            "tintHex": tint,
            "lightIds": [str(l) for l in (data.get("lights") or [])],
            "sceneIds": [str(s) for s in (data.get("scenes") or [])],
        })
    emit({"ok": True, "groups": out_groups, "scenes": _normalize_scenes(scenes)})


def _normalize_scenes(raw_scenes):
    out = []
    for sid, data in (raw_scenes or {}).items() if isinstance(raw_scenes, dict) else []:
        if not isinstance(data, dict):
            continue
        out.append({
            "id": str(sid),
            "name": sanitize(data.get("name") or "Scene"),
            "group": str(data.get("group")) if data.get("group") else None,
            "type": sanitize(data.get("type") or ""),
        })
    return out


def cmd_get_state(_args):
    """Full snapshot in one request: GET /api/<user> returns lights, groups
    and scenes together — one round trip for all 41 lights."""
    creds = load_creds()
    full, st = bridge_request("GET", "")
    v1_error(full, st)
    if not isinstance(full, dict) or "lights" not in full \
            or "groups" not in full:
        # A payload that is "successful" but structurally wrong must fail
        # loudly — returning empty models would look like "no lights".
        fail(EX_BAD_RESPONSE, "unexpected full-state payload")
    lights = {}
    for lid, data in (full.get("lights") or {}).items():
        if isinstance(data, dict):
            lights[str(lid)] = normalize_light(lid, data)
            lights[str(lid)]["_raw"] = data.get("state") or {}
    groups = []
    for gid, data in (full.get("groups") or {}).items():
        if isinstance(data, dict) and data.get("type") in ("Room", "Zone"):
            groups.append(normalize_group(gid, data, lights))
    for g in groups:
        g.pop("_raw", None)
    for l in lights.values():
        l.pop("_raw", None)
    emit({"ok": True,
          "bridge": {"ip": creds["bridgeIp"], "bridgeid": creds["bridgeId"]},
          "groups": groups, "lights": lights,
          "scenes": _normalize_scenes(full.get("scenes"))})


def _read_body(args):
    """Action body: --body '<json>' when the caller is QML (Quickshell's
    Process.write + stdinEnabled=false does not deliver stdin data in
    0.3.1), stdin as a fallback for manual/pipe use."""
    raw = getattr(args, "body", None)
    if raw is None:
        raw = sys.stdin.read(MAX_RESPONSE_BYTES)
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
        return body
    except (ValueError, OSError):
        fail(EX_USAGE, "invalid JSON body")


def cmd_put_group(args):
    if not args.id:
        fail(EX_USAGE, "put-group needs a group id")
    body = _read_body(args)
    creds = load_creds()
    allowed = {}
    if "on" in body:
        action = {"on": bool(body["on"])}
        if body.get("bri") is not None:
            action["bri"] = max(1, min(254, int(body["bri"])))
        if body.get("scene"):
            action = {"scene": str(body["scene"])}
        allowed = action
    elif body.get("scene"):
        allowed = {"scene": str(body["scene"])}
    else:
        if body.get("bri") is not None:
            allowed = {"bri": int(max(1, min(254, body["bri"])))}
        else:
            fail(EX_USAGE, "nothing to do")
    payload, st = bridge_request("PUT", "/groups/{}/action".format(args.id),
                                 allowed)
    v1_error(payload, st)
    errors = []
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict) and "error" in entry:
                errors.append(str((entry["error"] or {}).get("description", "error")))
    emit({"ok": True, "errors": errors})
    sys.exit(EX_OK if not errors else EX_BAD_RESPONSE)


def cmd_put_light(args):
    if not args.id:
        fail(EX_USAGE, "missing light id")
    body = _read_body(args)
    state = {}
    if "on" in body:
        state["on"] = bool(body["on"])
    if body.get("bri") is not None:
        state["bri"] = int(max(1, min(254, body["bri"])))
    if body.get("xy"):
        state["xy"] = [round(float(body["xy"][0]), 4), round(float(body["xy"][1]), 4)]
    if body.get("ct") is not None:
        state["ct"] = int(max(153, min(500, body["ct"])))
    if not state:
        fail(EX_USAGE, "nothing to do")
    creds = load_creds()
    payload, st = bridge_request("PUT", "/lights/{}/state".format(args.id),
                                 state)
    v1_error(payload, st)
    errors = []
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict) and "error" in entry:
                errors.append(str((entry["error"] or {}).get("description", "error")))
    emit({"ok": True, "errors": errors})
    sys.exit(EX_OK if not errors else EX_BAD_RESPONSE)


def cmd_probe_v2(_args):
    """The v1 username doubles as the v2 application key — no re-pairing.
    CLIP v2 normalization is deliberately deferred; this only records it."""
    creds = load_creds()
    headers = {"hue-application-key": creds["username"]}
    if TEST_BASE_URL:
        status, payload = _http("GET", TEST_BASE_URL.rstrip("/") + "/clip/v2/resource/bridge",
                                headers=headers)
    else:
        with _BridgeResolver(creds["bridgeId"], creds["bridgeIp"]):
            status, payload = _http(
                "GET", "https://{}/clip/v2/resource/bridge".format(creds["bridgeId"].lower()),
                headers=headers)
    v2 = status == 200 and isinstance(payload, dict) \
        and isinstance(payload.get("data"), list) and not payload.get("errors")
    if v2:
        creds["apiVersion"] = "v2"
        save_creds(creds)
    emit({"ok": True, "v2": bool(v2)})
    sys.exit(EX_OK)


def cmd_v2_scenes(_args):
    """List scenes with CLIP v2 metadata, keyed back to their v1 ids.
    `dynamic` marks scenes with a color palette (animated playback), the
    rest are static. `playing` reflects the bridge's own status so the UI
    can resync after a shell restart."""
    data = v2_data(*v2_request("GET", "/resource/scene"))
    out = []
    for sc in data or []:
        if not isinstance(sc, dict) or not sc.get("id_v1"):
            continue
        v1id = str(sc["id_v1"]).rsplit("/", 1)[-1]
        out.append({
            "id": v1id,
            "v2Id": sc["id"],
            "dynamic": bool(sc.get("palette")),
            "playing": (sc.get("status") or {}).get("active") == "dynamic_palette",
            "speed": sc.get("speed"),
        })
    emit({"ok": True, "scenes": out})
    sys.exit(EX_OK)


def cmd_v2_recall(args):
    """Recall a scene through CLIP v2: "dynamic_palette" starts animated
    playback (the Hue app's dynamic scenes), "active" recalls it
    statically (also stops playback), "inactive" stops playback. Speed
    0..1 scales the animation rate. Options ride either on
    argv (--action/--speed) or in an optional --body JSON, which is how the
    shell's action queue transports every command."""
    raw = getattr(args, "body", None)
    body = {}
    if raw:
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            fail(EX_USAGE, "bad body json")
    action = body.get("action", args.action)
    speed = body.get("speed", args.speed)
    if action not in ("dynamic_palette", "active", "inactive"):
        fail(EX_USAGE, "action must be dynamic_palette, active or inactive")
    out = {"recall": {"action": action}}
    if speed is not None:
        out["speed"] = round(max(0.0, min(1.0, float(speed))), 3)
    v2_error(*v2_request("PUT", "/resource/scene/{}".format(args.id), out))
    emit({"ok": True, "errors": []})
    sys.exit(EX_OK)


def cmd_sync_areas(_args):
    """Entertainment areas from CLIP v2, keyed back to their v1 group ids.
    Each area carries a compact channel map {channel_id: [x, y]} (positions
    normalized -1..1) the streamer uses to map screen regions to channels."""
    data = v2_data(*v2_request("GET",
                               "/resource/entertainment_configuration"))
    creds = load_creds()
    sync_ready = bool(creds.get("syncUsername") and creds.get("syncClientkey"))
    areas = []
    for a in data or []:
        if not isinstance(a, dict) or not a.get("id_v1"):
            continue
        channels = {}
        for ch in a.get("channels") or []:
            pos = ch.get("position") or {}
            channels[str(ch["channel_id"])] = [
                round(float(pos.get("x") or 0.0), 4),
                round(float(pos.get("y") or 0.0), 4)]
        areas.append({
            "id": a["id"],
            "v1Id": str(a["id_v1"]).rsplit("/", 1)[-1],
            "name": sanitize((a.get("metadata") or {}).get("name")
                             or a.get("name") or "Area"),
            "type": a.get("configuration_type"),
            "channels": channels,
        })
    emit({"ok": True, "areas": areas, "syncReady": sync_ready})
    sys.exit(EX_OK)


def cmd_sync_stop(args):
    """Safety valve: force-deactivate a group's streaming (v1 attribute
    PUT, the same endpoint the real streaming session uses)."""
    if not args.id:
        fail(EX_USAGE, "sync-stop needs a group id")
    creds = load_creds()
    payload, st = bridge_request("PUT", "/groups/{}".format(args.id),
                                 {"stream": {"active": False}})
    v1_error(payload, st)
    emit({"ok": True, "errors": []})
    sys.exit(EX_OK)


def cmd_sync_pair(_args):
    """Pair a dedicated entertainment-streaming key: the DTLS identity is a
    (username, clientkey) pair the bridge only hands out during a link-button
    pairing, so this creates a separate credential set from the main one.
    Streamed JSON lines, same shape as `pair`."""
    creds = load_creds()
    if TEST_BASE_URL:
        merged = dict(creds)
        merged["syncUsername"] = "TESTSYNCUSERNAME1234567890AB"
        merged["syncClientkey"] = "00" * 16
        save_creds(merged)
        emit({"ok": True, "event": "paired"})
        sys.exit(EX_OK)

    emit({"event": "discovering"})
    deadline = time.monotonic() + PAIR_SECONDS
    body = {"devicetype": "omarchue#sync", "generateclientkey": True}
    sync_username = None
    clientkey = None
    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        emit({"event": "press-button", "secondsLeft": max(0, remaining)})
        url = "https://{}/api".format(creds["bridgeId"].lower())
        with _BridgeResolver(creds["bridgeId"], creds["bridgeIp"]):
            status, payload = _http("POST", url, body, timeout=5,
                                    ctx=_tls_context())
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict) and "success" in entry:
                    success = entry["success"] or {}
                    sync_username = success.get("username")
                    clientkey = success.get("clientkey")
                    break
                if isinstance(entry, dict) and entry.get("error", {}).get("type") == 101:
                    pass  # link button not pressed yet
        if sync_username and _USERNAME_RE.fullmatch(sync_username) \
                and clientkey and re.fullmatch(r"[0-9a-fA-F]{32}", clientkey):
            break
        time.sleep(PAIR_RETRY_SECS)
    if not sync_username or not clientkey:
        fail(EX_UNPAIRED, "link button was not pressed in time")

    creds["syncUsername"] = sync_username
    creds["syncClientkey"] = clientkey.lower()
    save_creds(creds)
    emit({"event": "paired"})
    sys.exit(EX_OK)


# ------------------------------------------------------- sync streaming ---

SYNC_W = 64
SYNC_H = 36
SYNC_COLS = 5
SYNC_ROWS = 3


def _sample_cell(frame, x, y):
    """Average RGB of the 5x3 grid cell the normalized area position
    (x, y in -1..1, y up) falls in. Frame is SYNC_W x SYNC_H rgb24."""
    col = max(0, min(SYNC_COLS - 1, int((x + 1.0) / 2 * SYNC_COLS)))
    row = max(0, min(SYNC_ROWS - 1, int((1.0 - (y + 1.0) / 2) * SYNC_ROWS)))
    x0 = col * SYNC_W // SYNC_COLS
    x1 = (col + 1) * SYNC_W // SYNC_COLS
    y0 = row * SYNC_H // SYNC_ROWS
    y1 = (row + 1) * SYNC_H // SYNC_ROWS
    r = g = b = n = 0
    for py in range(y0, y1):
        base = (py * SYNC_W + x0) * 3
        for px in range(x0, x1):
            r += frame[base]; g += frame[base + 1]; b += frame[base + 2]
            base += 3
            n += 1
    return r // n, g // n, b // n


def sample_channels(frame, channels, intensity):
    """Frame (rgb24) + area channel positions -> 16-bit LightColorCommands."""
    from hue_entertainment.models import LightColorCommand
    factor = max(0.0, min(1.0, intensity))
    out = []
    for cid, pos in channels.items():
        r, g, b = _sample_cell(frame, pos[0], pos[1])
        out.append(LightColorCommand(
            channel_id=int(cid),
            red=min(65535, int(r * 257 * factor)),
            green=min(65535, int(g * 257 * factor)),
            blue=min(65535, int(b * 257 * factor))))
    return out


def _spawn_capture(output):
    """wf-recorder -> raw rgb24 frames through a FIFO. wf-recorder 0.6 +
    ffmpeg 9 cannot stream to stdout ('-f -' produces nothing) and prompts
    without -y; a FIFO is just a file to it and blocks the writer until we
    open the reader side. Verified empirically: 29.5 fps at 64x36 rgb24.
    The reader opens O_NONBLOCK: if the capture dies before opening its
    side (bad --output name, missing codec...), a blocking open would hang
    the helper forever with the UI stuck in 'starting'."""
    fifo = "/tmp/omarchue-sync-{}.fifo".format(os.getpid())
    errlog = fifo + ".err"
    for path in (fifo, errlog):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    os.mkfifo(fifo)
    cmd = ["wf-recorder", "-y", "--output", output, "--framerate", "30",
           "--codec", "rawvideo", "--muxer", "rawvideo",
           "--pixel-format", "rgb24", "--file", fifo,
           "--filter", "scale={}:{},format=rgb24".format(SYNC_W, SYNC_H),
           "--no-damage"]
    try:
        with open(errlog, "wb") as errf:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=errf)
    except FileNotFoundError:
        for path in (fifo, errlog):
            try:
                os.unlink(path)
            except OSError:
                pass
        fail(EX_USAGE, "wf-recorder is not installed (pacman -S wf-recorder)")
    return proc, fifo, errlog


def cmd_sync_stream(args):
    """Long-running screen sync: activate the area's stream, read downscaled
    screen frames from the capture pipeline, map channel positions to grid
    cells and push HueStream frames over DTLS at capture rate. Cleans up on
    exit: stream deactivated, snapshot restored."""
    creds = load_creds()
    if not creds.get("syncUsername") or not creds.get("syncClientkey"):
        fail(EX_UNPAIRED, "no sync credentials — pair Hue Sync first")
    try:
        if str(Path(__file__).resolve().parent / "vendor") not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
        from hue_entertainment.dtls import HueDtlsStreamer
    except ImportError as e:
        fail(EX_USAGE, "streaming needs the vendored DTLS modules and "
                       "python-cryptography ({})".format(e))

    if not args.id:
        fail(EX_USAGE, "sync-stream needs a group id")
    data = v2_data(*v2_request("GET", "/resource/entertainment_configuration"))
    area = None
    for a in data or []:
        if isinstance(a, dict) and str(a.get("id_v1", "")).rsplit("/", 1)[-1] == str(args.id):
            area = a
            break
    if area is None:
        fail(EX_USAGE, "group {} is not an entertainment area".format(args.id))
    channels = {}
    for ch in area.get("channels") or []:
        pos = ch.get("position") or {}
        channels[str(ch["channel_id"])] = [
            float(pos.get("x") or 0.0), float(pos.get("y") or 0.0)]
    if not channels:
        fail(EX_BAD_RESPONSE, "area has no channels")

    intensity = max(0.0, min(1.0, float(getattr(args, "intensity", 1.0) or 1.0)))
    output = args.output
    if not output:
        fail(EX_USAGE, "sync-stream needs --output (a real monitor name)")

    # Snapshot for restore (streaming overrides everything, so the bridge
    # keeps no history — same as Hue Sync).
    snap, st = bridge_request("GET", "/groups/{}".format(args.id))
    v1_error(snap, st)
    action = (snap.get("action") or {}) if isinstance(snap, dict) else {}
    restore = {}
    for key in ("on", "bri"):
        if action.get(key) is not None:
            restore[key] = action[key]
    for key in ("xy", "ct", "hue", "sat"):
        if action.get(key) is not None:
            restore[key] = action[key]

    import signal as _signal
    stopping = {"now": False}
    _signal.signal(_signal.SIGTERM, lambda *_: stopping.update(now=True))

    proc = None
    fifo = None
    frames = None
    streamer = HueDtlsStreamer()
    try:
        v1_error(*bridge_request("PUT", "/groups/{}".format(args.id),
                                 {"stream": {"active": True}}))
        # Handshake before the capture starts: nothing must hold the frame
        # pipe open while the handshake blocks on the bridge.
        streamer.connect(creds["bridgeIp"], creds["syncUsername"],
                         creds["syncClientkey"], area["id"])
        proc, fifo, errlog = _spawn_capture(output)
        # A bad --output name (or any instant capture failure) used to hang
        # the helper forever: the blocking open() below waits for a writer
        # that is already dead. Give wf-recorder a moment to die, and open
        # the reader non-blocking so EOF arrives instead of an eternal wait.
        deadline = time.monotonic() + 2.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if proc.poll() is not None:
            with open(errlog, "rb") as errf:
                err = errf.read().decode("utf-8", "replace").strip()
            fail(EX_USAGE, "capture failed on output '{}': {}".format(
                output, err.splitlines()[-1] if err else
                "wf-recorder exited with code {}".format(proc.returncode)))
        frames = open(os.open(fifo, os.O_RDONLY | os.O_NONBLOCK), "rb")
        emit({"event": "capturing", "output": output, "channels": len(channels)})
        got_first = False
        frame_size = SYNC_W * SYNC_H * 3
        while not stopping["now"]:
            # Non-blocking fd: None is EAGAIN (writer not up yet, or between
            # frames), b"" is a real EOF (writer closed / died).
            frame = frames.read(frame_size)
            if frame is None:
                if proc.poll() is not None:
                    break  # capture died before producing any frame
                time.sleep(0.005)
                continue
            if not frame or len(frame) < frame_size:
                break  # capture ended (writer closed / died)
            commands = sample_channels(frame, channels, intensity)
            streamer.send_colors(commands)
            if not got_first:
                got_first = True
                emit({"event": "streaming", "area": area["id"],
                      "fps_hint": 30})
    finally:
        if frames is not None:
            try:
                frames.close()
            except OSError:
                pass
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if fifo:
            for path in (fifo, errlog):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        try:
            streamer.disconnect()
        except Exception:
            pass
        try:
            v1_error(*bridge_request("PUT", "/groups/{}".format(args.id),
                                     {"stream": {"active": False}}))
        except SystemExit:
            pass  # bridge may be gone; the 10 s inactivity cutoff is the backstop
        if restore:
            try:
                v1_error(*bridge_request(
                    "PUT", "/groups/{}/action".format(args.id), restore))
            except SystemExit:
                pass
    emit({"event": "stopped"})
    sys.exit(EX_OK)


def cmd_unpair(_args):
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        print("could not remove credentials: {}".format(e), file=sys.stderr)
        fail(EX_NETWORK, "could not remove credentials")
    emit({"ok": True})
    sys.exit(EX_OK)


def main():
    parser = argparse.ArgumentParser(prog="hue_api", description="Omarchue bridge helper")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("discover")
    p_pair = sub.add_parser("pair")
    p_pair.add_argument("--ip")
    p_pair.add_argument("--bridgeid")
    sub.add_parser("get-status")
    sub.add_parser("get-state")
    p_group = sub.add_parser("put-group")
    p_group.add_argument("id")
    p_group.add_argument("--body")
    p_light = sub.add_parser("put-light")
    p_light.add_argument("id")
    p_light.add_argument("--body")
    sub.add_parser("probe-v2")
    sub.add_parser("v2-scenes")
    p_v2recall = sub.add_parser("v2-recall")
    p_v2recall.add_argument("id")
    p_v2recall.add_argument("--action", default="dynamic")
    p_v2recall.add_argument("--speed")
    p_v2recall.add_argument("--body")
    sub.add_parser("sync-areas")
    sub.add_parser("sync-pair")
    p_syncstream = sub.add_parser("sync-stream")
    p_syncstream.add_argument("id")
    p_syncstream.add_argument("--output", default="eDP-2")
    p_syncstream.add_argument("--intensity", default=1.0)
    p_syncstop = sub.add_parser("sync-stop")
    p_syncstop.add_argument("id")
    sub.add_parser("unpair")
    args = parser.parse_args()

    handlers = {
        "discover": cmd_discover,
        "pair": cmd_pair,
        "get-status": cmd_get_status,
        "get-state": cmd_get_state,
        "put-group": cmd_put_group,
        "put-light": cmd_put_light,
        "probe-v2": cmd_probe_v2,
        "v2-scenes": cmd_v2_scenes,
        "v2-recall": cmd_v2_recall,
        "sync-areas": cmd_sync_areas,
        "sync-pair": cmd_sync_pair,
        "sync-stream": cmd_sync_stream,
        "sync-stop": cmd_sync_stop,
        "unpair": cmd_unpair,
    }
    if not args.cmd:
        parser.print_usage(sys.stderr)
        sys.exit(EX_USAGE)
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()