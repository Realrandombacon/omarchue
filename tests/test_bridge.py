"""End-to-end tests: run hue_api.py as a subprocess against the in-process
fake bridge, exactly the way HueService.qml drives it (HUE_BRIDGE_URL env,
JSON on stdin for writes, one JSON object on stdout)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fake_bridge  # noqa: E402

HUE_API = HERE.parent / "hue_api.py"
USER = "TESTUSERNAME1234567890AB"

CREDS = {"bridgeIp": "127.0.0.1", "bridgeId": "001788FFFE123456",
         "username": USER, "apiVersion": "v1"}


class BridgeCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = fake_bridge.FakeBridge()
        cls.bridge.__enter__()
        cls.state_dir = tempfile.mkdtemp()
        settings = Path(cls.state_dir) / "omarchy" / "settings"
        settings.mkdir(parents=True)
        (settings / "hue.json").write_text(json.dumps(CREDS) + "\n")

    @classmethod
    def tearDownClass(cls):
        cls.bridge.__exit__()

    def run_cli(self, *args, stdin=None, creds=True):
        env = dict(os.environ)
        env["HUE_BRIDGE_URL"] = self.bridge.url
        env["XDG_STATE_HOME"] = self.state_dir
        env.pop("XDG_CONFIG_HOME", None)
        if not creds:
            env["XDG_STATE_HOME"] = tempfile.mkdtemp()
        return subprocess.run(
            [sys.executable, str(HUE_API), *args],
            input=stdin, capture_output=True, text=True, env=env, timeout=30)

    def setUp(self):
        # Each test starts from pristine fixtures; the HTTP server reads
        # STATE at request time, so a rebuild takes effect immediately.
        fake_bridge.build_state()

    def get_state(self):
        proc = self.run_cli("get-state")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    # ---- get-state ------------------------------------------------

    def test_get_state_full_snapshot(self):
        out = self.get_state()
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["lights"]), 41)
        self.assertEqual(len(out["groups"]), 4)
        self.assertEqual(len(out["scenes"]), 3)

    def test_get_state_bridge_meta(self):
        out = self.get_state()
        self.assertEqual(out["bridge"]["bridgeid"], "001788FFFE123456")

    def test_get_state_capability_gating(self):
        out = self.get_state()
        self.assertTrue(out["lights"]["1"]["hasColor"])
        self.assertTrue(out["lights"]["25"]["hasCt"])
        self.assertFalse(out["lights"]["25"]["hasColor"])
        self.assertFalse(out["lights"]["32"]["hasCt"])
        self.assertTrue(out["lights"]["32"]["hasBri"])

    def test_get_state_group_bri_from_members(self):
        out = self.get_state()
        living = next(g for g in out["groups"] if g["name"] == "Living Room")
        self.assertEqual(living["bri"], 200)  # not the stale action.bri 254
        self.assertTrue(living["on"])

    def test_get_status_lighter_payload(self):
        proc = self.run_cli("get-status")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["groups"]), 4)
        self.assertEqual(len(out["scenes"]), 3)
        self.assertNotIn("lights", out)

    def test_unauthorized_username(self):
        bad = dict(CREDS, username="WRONGUSERNAME1234567890ABC")
        with tempfile.TemporaryDirectory() as state:
            settings = Path(state) / "omarchy" / "settings"
            settings.mkdir(parents=True)
            (settings / "hue.json").write_text(json.dumps(bad) + "\n")
            env = dict(os.environ, HUE_BRIDGE_URL=self.bridge.url,
                       XDG_STATE_HOME=state)
            proc = subprocess.run([sys.executable, str(HUE_API), "get-state"],
                                  capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 2)  # EX_UNPAIRED
        self.assertEqual(json.loads(proc.stdout)["code"], 2)

    # ---- put-light ------------------------------------------------

    def test_put_light_toggle_and_clamp(self):
        proc = self.run_cli("put-light", "32", stdin='{"on": true, "bri": 300}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["errors"], [])
        out = self.get_state()
        self.assertTrue(out["lights"]["32"]["on"])
        self.assertEqual(out["lights"]["32"]["bri"], 254)  # clamped

    def test_put_light_xy(self):
        proc = self.run_cli("put-light", "1", stdin='{"xy": [0.15, 0.06]}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.get_state()
        self.assertEqual(out["lights"]["1"]["xy"], [0.15, 0.06])
        # sRGB-primary blue should have replaced the warm default.
        r, g, b = (int(out["lights"]["1"]["hex"][i:i + 2], 16)
                   for i in (1, 3, 5))
        self.assertLess(r, 128)
        self.assertLess(g, 128)
        self.assertGreater(b, 128)

    def test_put_light_rejects_empty_body(self):
        proc = self.run_cli("put-light", "1", stdin="{}")
        self.assertEqual(proc.returncode, 4)

    def test_put_light_unknown_light(self):
        proc = self.run_cli("put-light", "999", stdin='{"on": true}')
        self.assertEqual(proc.returncode, 3)

    # ---- put-group ------------------------------------------------

    def test_put_group_all_off(self):
        proc = self.run_cli("put-group", "1", stdin='{"on": false}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.get_state()
        living = next(g for g in out["groups"] if g["name"] == "Living Room")
        self.assertFalse(living["on"])
        self.assertFalse(out["lights"]["5"]["on"])

    def test_put_group_bri(self):
        proc = self.run_cli("put-group", "3", stdin='{"bri": 90}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.get_state()
        self.assertEqual(out["lights"]["25"]["bri"], 90)
        bedroom = next(g for g in out["groups"] if g["name"] == "Bedroom")
        self.assertEqual(bedroom["bri"], 90)

    def test_put_group_bri_skips_unreachable(self):
        # Office contains unreachable light 41; a bri change must reach
        # only reachable members and still succeed.
        proc = self.run_cli("put-group", "4", stdin='{"on": true, "bri": 60}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.get_state()
        self.assertEqual(out["lights"]["32"]["bri"], 60)
        self.assertEqual(out["lights"]["41"]["bri"], 0)

    def test_put_group_scene_recall(self):
        proc = self.run_cli("put-group", "1", stdin='{"scene": "s1"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.get_state()
        self.assertEqual(out["lights"]["1"]["bri"], 144)
        self.assertEqual(out["lights"]["2"]["bri"], 100)
        self.assertTrue(out["lights"]["1"]["on"])

    def test_put_group_scene_then_state_consistent(self):
        self.run_cli("put-group", "1", stdin='{"scene": "s1"}')
        out = self.get_state()
        living = next(g for g in out["groups"] if g["name"] == "Living Room")
        self.assertTrue(living["on"])
        self.assertNotEqual(living["tintHex"], "#1c1c1c")

    def test_put_group_unknown_group(self):
        proc = self.run_cli("put-group", "99", stdin='{"on": false}')
        self.assertEqual(proc.returncode, 3)

    def test_put_group_invalid_json(self):
        proc = self.run_cli("put-group", "1", stdin="not json")
        self.assertEqual(proc.returncode, 4)


if __name__ == "__main__":
    unittest.main()