"""Tests for the Hue Sync (entertainment streaming) helper commands:
area discovery (CLIP v2) and stream activation/deactivation (v1)."""

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


class SyncCliTest(unittest.TestCase):
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

    def run_cli(self, *args):
        env = dict(os.environ)
        env["HUE_BRIDGE_URL"] = self.bridge.url
        env["XDG_STATE_HOME"] = self.state_dir
        return subprocess.run(
            [sys.executable, str(HUE_API), *args],
            input="", capture_output=True, text=True, env=env, timeout=30)

    def setUp(self):
        fake_bridge.build_state()

    def test_sync_areas_lists_areas_with_channel_map(self):
        proc = self.run_cli("sync-areas")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["areas"]), 1)
        area = out["areas"][0]
        self.assertEqual(area["v1Id"], "11")
        self.assertEqual(area["name"], "Gaming Den")
        self.assertEqual(area["type"], "screen")
        self.assertEqual(area["channels"], {
            "0": [-1.0, 0.8],
            "1": [0.0, 0.8],
            "2": [1.0, 0.8],
        })

    def test_sync_areas_unauthorized(self):
        bad_state = tempfile.mkdtemp()
        Path(bad_state, "omarchy", "settings").mkdir(parents=True)
        Path(bad_state, "omarchy", "settings", "hue.json").write_text(
            json.dumps(dict(CREDS, username="WRONGUSER1234567890ABCDEF")) + "\n")
        env = dict(os.environ, HUE_BRIDGE_URL=self.bridge.url,
                   XDG_STATE_HOME=bad_state)
        proc = subprocess.run([sys.executable, str(HUE_API), "sync-areas"],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 2)  # EX_UNPAIRED

    def test_sync_stop_deactivates_stream(self):
        fake_bridge.STATE["groups"]["11"]["stream"]["active"] = True
        proc = self.run_cli("sync-stop", "11")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertFalse(fake_bridge.STATE["groups"]["11"]["stream"]["active"])

    def test_sync_stop_unknown_group(self):
        proc = self.run_cli("sync-stop", "99")
        self.assertEqual(proc.returncode, 3)  # EX_BAD_RESPONSE

    # No missing-id test: argparse exits 2 before our exit codes apply.

    # ---- sync-pair / sync-stream --------------------------------------------

    def test_sync_pair_testmode_saves_credentials(self):
        proc = self.run_cli("sync-pair")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        creds = json.loads(Path(self.state_dir, "omarchy", "settings",
                                "hue.json").read_text())
        self.assertTrue(creds.get("syncUsername"))
        self.assertEqual(len(creds.get("syncClientkey") or ""), 32)

    def test_sync_stream_requires_sync_credentials(self):
        # Rebuild creds without the sync pair.
        Path(self.state_dir, "omarchy", "settings", "hue.json").write_text(
            json.dumps(CREDS) + "\n")
        proc = self.run_cli("sync-stream", "11")
        self.assertEqual(proc.returncode, 2)  # EX_UNPAIRED
        out = json.loads(proc.stdout)
        self.assertIn("sync credentials", out["error"])
        self.assertFalse(fake_bridge.STATE["groups"]["11"]["stream"]["active"])


if __name__ == "__main__":
    unittest.main()