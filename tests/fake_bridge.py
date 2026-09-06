"""In-memory Hue bridge fixture: 41 lights across 4 rooms, plus a tiny
HTTP server standing in for the bridge (driven via HUE_BRIDGE_URL).

Lights (matching the plan's fixture spec):
  1-20   LCT007  Extended color (bri + ct + hue/sat)   — Bacon's RGB bulbs
  21-31  LTA001  White ambiance (bri + ct)
  32-40  LWB010  White (bri only)
  41     LCT007  present but unreachable (simulated dead bulb)

Rooms: Living Room (1-15), Kitchen (16-24), Bedroom (25-35), Office (36-41).
One scene per room (2 for the living room), each with stored light states.
"""

STATE = {
    "lights": {},
    "groups": {},
    "scenes": {},
    "v2scenes": {},
    "config": {"bridgeid": "001788FFFE123456", "name": "Bacon's Bridge",
               "apiversion": "1.62.0"},
    # Bookkeeping for tests: every request the helper made.
    "requests": [],
}

_USER = "TESTUSERNAME1234567890AB"


def build_state():
    """(Re)build the fixture state from scratch. Returns the STATE dict."""
    lights = {}
    for lid in range(1, 16):
        lights[str(lid)] = _light("LCT007", "Extended color light",
                                  on=True, bri=200, ct=300,
                                  hue=8000, sat=180,
                                  xy=[0.4573, 0.4053], reachable=True)
    for lid in range(16, 25):
        lights[str(lid)] = _light("LTA001", "Color temperature light",
                                  on=(lid % 2 == 0), bri=180, ct=350,
                                  reachable=True)
    for lid in range(32, 41):
        lights[str(lid)] = _light("LWB010", "Dimmable light",
                                  on=False, bri=120, reachable=True)
    lights["41"] = _light("LCT007", "Extended color light",
                          on=False, bri=0, ct=300, hue=0, sat=0,
                          xy=[0.3, 0.3], reachable=False)
    # Lights 25-31 belong to the Bedroom (white ambiance, all on).
    for lid in range(25, 32):
        lights[str(lid)] = _light("LTA001", "Color temperature light",
                                  on=True, bri=160, ct=250, reachable=True)

    scenes = {
        "s1": _scene("s1", "Relax", "1", "LivingRoom",
                     {"1": {"on": True, "bri": 144, "xy": [0.5, 0.4]},
                      "2": {"on": True, "bri": 100, "xy": [0.55, 0.38]}}),
        "s2": _scene("s2", "Bright", "1", "LivingRoom",
                     {"1": {"on": True, "bri": 254, "xy": [0.32, 0.33]},
                      "2": {"on": True, "bri": 254, "xy": [0.32, 0.33]}}),
        "s3": _scene("s3", "Nightlight", "4", "Office",
                     {"32": {"on": True, "bri": 40, "xy": [0.6, 0.35]}}),
    }
    groups = {
        "1": _group("1", "Living Room", "Living room",
                    [str(i) for i in range(1, 16)]),
        "2": _group("2", "Kitchen", "Kitchen",
                    [str(i) for i in range(16, 25)]),
        "3": _group("3", "Bedroom", "Bedroom",
                    [str(i) for i in range(25, 32)]),
        "4": _group("4", "Office", "Office",
                    [str(i) for i in list(range(32, 41)) + ["41"]]),
    }
    STATE.update({"lights": lights, "groups": groups, "scenes": scenes,
                  "v2scenes": {}, "requests": []})
    # CLIP v2 mirror of the scenes. s1 carries a palette (dynamic-capable);
    # the others are static. status.active mirrors real bridge values
    # ("inactive" / "static" / "dynamic").
    for i, (sid, sc) in enumerate(sorted(scenes.items())):
        STATE["v2scenes"]["v2-{}".format(sid)] = {
            "id": "v2-{}".format(sid),
            "id_v1": "/scenes/{}".format(sid),
            "type": "scene",
            "metadata": {"name": sc["name"]},
            "group": {"rid": "g{}".format(sc["group"]), "rtype": "room"},
            "palette": {"color": [{"color": {"xy": {"x": 0.5, "y": 0.4}},
                                   "dimming": {"brightness": 80.0}}]}
            if sid == "s1" else None,
            "speed": 0.6031746,
            "recall": {},
            "status": {"active": "inactive"},
            "actions": [],
        }
    return STATE


def _light(model, ltype, on, bri, reachable, ct=None, hue=None, sat=None,
           xy=None):
    state = {"on": on, "reachable": reachable, "alert": "none", "mode": "homeautomation"}
    if bri is not None:
        state["bri"] = bri
    if ct is not None:
        state["ct"] = ct
    if hue is not None:
        state["hue"] = hue
        state["sat"] = sat
    if xy is not None:
        state["xy"] = xy
    caps = {"control": {}}
    if bri is not None:
        caps["control"]["mindim"] = 0
    if ct is not None:
        caps["control"]["ct"] = {"min": 153, "max": 500}
    if hue is not None:
        caps["control"]["colorgamut"] = [[0.36, 0.38], [0.68, 0.31], [0.14, 0.04]]
        caps["control"]["ct"] = {"min": 153, "max": 500}
    return {"state": state, "name": "Light {}".format(model),
            "type": ltype, "modelid": model,
            "capabilities": caps, "swversion": "1.88.1"}


def _group(gid, name, gclass, light_ids, action_bri=254):
    return {
        "name": name, "type": "Room", "class": gclass,
        "lights": light_ids,
        "state": {"all_on": False, "any_on": False},  # refreshed on GET
        # Deliberately stale: the documented trap — action.bri does not
        # track member lights, so normalization must derive avgBri itself.
        "action": {"on": True, "bri": action_bri,
                   "xy": [0.4573, 0.4053]},
        "scenes": [sid for sid, s in STATE["scenes"].items()
                   if s["group"] == gid] if STATE.get("scenes") else [],
    }


def _scene(sid, name, group, gclass, lightstates):
    return {"name": name, "type": "GroupScene", "group": group,
            "class": gclass, "owner": _USER, "recycle": False,
            "lightstates": lightstates}


def refresh_group_states():
    """Recompute any_on/all_on so GETs never serve stale group state."""
    for group in STATE["groups"].values():
        ons = [STATE["lights"][l]["state"]["on"] for l in group["lights"]
               if l in STATE["lights"]]
        group["state"] = {"any_on": any(ons), "all_on": all(ons)}


def apply_group_action(gid, body):
    group = STATE["groups"][gid]
    action = group["action"]
    if "scene" in body:
        scene = STATE["scenes"][body["scene"]]
        for lid, ls in scene["lightstates"].items():
            if lid in STATE["lights"]:
                STATE["lights"][lid]["state"].update(ls)
        refresh_group_states()
        return
    for key in ("on", "bri", "xy", "ct", "hue", "sat"):
        if key in body:
            action[key] = body[key]
    for lid in group["lights"]:
        if lid in STATE["lights"] and STATE["lights"][lid]["state"]["reachable"]:
            for key in ("on", "bri", "xy", "ct", "hue", "sat"):
                if key in body:
                    STATE["lights"][lid]["state"][key] = body[key]
    refresh_group_states()


# ------------------------------------------------------------ server ----

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402


class FakeBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep test output clean
        pass

    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        STATE["requests"].append(("GET", self.path, None))
        path = self.path.split("?")[0]
        if path == "/config":
            return self._send(200, STATE["config"])
        if path == "/clip/v2/resource/scene":
            if not self._v2_authorized():
                return self._send(403, {"errors": [{"description":
                                                    "unauthorized"}]})
            return self._v2(200, list(STATE["v2scenes"].values()))
        # Any authenticated path under the wrong username is a 401-style
        # v1 error, like the real bridge.
        if path.startswith("/api/") and _USER not in path.split("/"):
            return self._send(403, [{"error": {"type": 1,
                                               "description": "unauthorized"}}])
        if path == "/api" or path == "/api/":
            return self._send(403, [{"error": {"type": 1,
                                               "description": "unauthorized"}}])
        if path == "/api/{}".format(_USER):
            refresh_group_states()
            return self._send(200, {"lights": STATE["lights"],
                                    "groups": STATE["groups"],
                                    "scenes": STATE["scenes"],
                                    "config": STATE["config"]})
        if path == "/api/{}/groups".format(_USER):
            refresh_group_states()
            return self._send(200, STATE["groups"])
        if path == "/api/{}/scenes".format(_USER):
            return self._send(200, STATE["scenes"])
        self._send(404, {"error": "not found"})

    def _v2(self, code, data):
        return self._send(code, {"data": data, "errors": []})

    def _v2_authorized(self):
        return self.headers.get("hue-application-key") == _USER

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode())
        except ValueError:
            return self._send(400, {"error": "bad json"})
        STATE["requests"].append(("PUT", self.path, body))
        parts = self.path.split("?")[0].strip("/").split("/")
        # clip/v2/resource/scene/<v2id> — dynamic scene playback control.
        if len(parts) == 5 and parts[:4] == ["clip", "v2", "resource",
                                             "scene"] \
                and parts[4] in STATE["v2scenes"]:
            if not self._v2_authorized():
                return self._send(403, {"errors": [{"description":
                                                    "unauthorized"}]})
            sc = STATE["v2scenes"][parts[4]]
            recall = body.get("recall") or {}
            action = recall.get("action")
            if action == "dynamic_palette":
                sc["status"]["active"] = "dynamic_palette"
            elif action == "active":
                sc["status"]["active"] = "static"
            elif action == "inactive":
                sc["status"]["active"] = "inactive"
            if "speed" in body:
                sc["speed"] = body["speed"]
            return self._v2(200, [{"id": sc["id"], "status": sc["status"]}])
        # api/<user>/groups/<gid>/action | api/<user>/lights/<lid>/state
        if len(parts) == 5 and parts[0] == "api" and parts[1] == _USER:
            if parts[2] == "groups" and parts[4] == "action" \
                    and parts[3] in STATE["groups"]:
                apply_group_action(parts[3], body)
                return self._send(200, [{"success": {"/groups/{}/{}".format(
                    parts[3], k): v} for k, v in body.items()}])
            if parts[2] == "lights" and parts[4] == "state" \
                    and parts[3] in STATE["lights"]:
                STATE["lights"][parts[3]]["state"].update(body)
                return self._send(200, [{"success": {"/lights/{}/{}".format(
                    parts[3], k): v} for k, v in body.items()}])
        return self._send(404, [{"error": {"type": 3,
                                           "description": "not found"}}])


class FakeBridge:
    """Context manager running the fake bridge on an ephemeral port."""

    def __init__(self):
        build_state()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBridgeHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)

    @property
    def url(self):
        return "http://127.0.0.1:{}".format(self.port)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        return False


if __name__ == "__main__":  # manual poke: python3 tests/fake_bridge.py
    import os
    import signal

    build_state()
    port = int(os.environ.get("FAKE_PORT", "8188"))
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeBridgeHandler)
    signal.signal(signal.SIGTERM, lambda *_: server.shutdown())
    print("fake bridge on :{} (user {})".format(port, _USER), flush=True)
    server.serve_forever()