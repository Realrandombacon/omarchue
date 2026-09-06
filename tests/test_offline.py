"""Offline/failure-path tests: dead bridge, missing credentials, unpair.
The contract under test: a network failure exits 1, never looks like
"no lights" (exit 0 with empty lists), and never writes state."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUE_API = HERE.parent / "hue_api.py"

CREDS = {"bridgeIp": "127.0.0.1", "bridgeId": "001788FFFE123456",
         "username": "TESTUSERNAME1234567890AB", "apiVersion": "v1"}

DEAD_URL = "http://127.0.0.1:1"  # nothing listens on port 1


def run_cli(state_dir, *args, bridge_url=DEAD_URL, stdin=None):
    env = dict(os.environ, HUE_STATE_DIR_FOR_TEST=state_dir,
               XDG_STATE_HOME=state_dir, HUE_BRIDGE_URL=bridge_url)
    return subprocess.run([sys.executable, str(HUE_API), *args],
                          input=stdin, capture_output=True, text=True,
                          env=env, timeout=30)


def state_with_creds():
    state = tempfile.mkdtemp()
    settings = Path(state) / "omarchy" / "settings"
    settings.mkdir(parents=True)
    (settings / "hue.json").write_text(json.dumps(CREDS) + "\n")
    return state


class OfflineTests(unittest.TestCase):
    def test_dead_bridge_is_network_error(self):
        state = state_with_creds()
        proc = run_cli(state, "get-state")
        self.assertEqual(proc.returncode, 1)  # EX_NETWORK, never 0
        out = json.loads(proc.stdout)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], 1)

    def test_dead_bridge_status_also_network_error(self):
        state = state_with_creds()
        proc = run_cli(state, "get-status")
        self.assertEqual(proc.returncode, 1)

    def test_dead_bridge_write_fails_cleanly(self):
        state = state_with_creds()
        proc = run_cli(state, "put-group", "1", stdin='{"on": false}')
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["code"], 1)

    def test_no_credentials(self):
        state = tempfile.mkdtemp()  # empty state dir, no hue.json
        proc = run_cli(state, "get-state", bridge_url="http://127.0.0.1:1")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["error"], "not paired")
        self.assertFalse(
            (Path(state) / "omarchy" / "settings" / "hue.json").exists())

    def test_corrupt_credentials(self):
        state = tempfile.mkdtemp()
        settings = Path(state) / "omarchy" / "settings"
        settings.mkdir(parents=True)
        (settings / "hue.json").write_text("{broken")
        proc = run_cli(state, "get-state")
        self.assertEqual(proc.returncode, 2)

    def test_incomplete_credentials(self):
        state = tempfile.mkdtemp()
        settings = Path(state) / "omarchy" / "settings"
        settings.mkdir(parents=True)
        (settings / "hue.json").write_text(json.dumps({"username": "x"}) + "\n")
        proc = run_cli(state, "get-state")
        self.assertEqual(proc.returncode, 2)

    def test_unpair_removes_creds(self):
        state = state_with_creds()
        proc = run_cli(state, "unpair", bridge_url="http://127.0.0.1:1")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(
            (Path(state) / "omarchy" / "settings" / "hue.json").exists())
        # Second unpair is idempotent.
        proc = run_cli(state, "unpair")
        self.assertEqual(proc.returncode, 0)

    def test_pair_test_mode_writes_creds(self):
        state = tempfile.mkdtemp()
        proc = run_cli(state, "pair")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["event"], "paired")
        creds = json.loads(
            (Path(state) / "omarchy" / "settings" / "hue.json").read_text())
        self.assertTrue(creds["username"])
        # Credentials file must not be world-readable.
        mode = (Path(state) / "omarchy" / "settings" / "hue.json") \
            .stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_usage_error(self):
        proc = run_cli(tempfile.mkdtemp())
        self.assertEqual(proc.returncode, 4)


if __name__ == "__main__":
    unittest.main()