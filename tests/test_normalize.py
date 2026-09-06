"""Unit tests for hue_api.py normalization and color math (pure functions,
no network). Fixtures come from fake_bridge.build_state()."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("XDG_STATE_HOME", tempfile.mkdtemp())  # before import
import hue_api  # noqa: E402

import fake_bridge  # noqa: E402

STATE = fake_bridge.build_state()


class LightCapabilityTests(unittest.TestCase):
    def setUp(self):
        # test_bridge mutates STATE through the in-process HTTP server;
        # every test here starts from pristine fixtures.
        global STATE
        STATE = fake_bridge.build_state()

    def test_rgb_light_flags(self):
        light = hue_api.normalize_light("1", STATE["lights"]["1"])
        self.assertTrue(light["hasBri"])
        self.assertTrue(light["hasCt"])
        self.assertTrue(light["hasColor"])
        self.assertEqual(light["ctMin"], 153)
        self.assertEqual(light["ctMax"], 500)
        self.assertTrue(light["on"])
        self.assertEqual(light["bri"], 200)

    def test_white_ambiance_flags(self):
        light = hue_api.normalize_light("25", STATE["lights"]["25"])
        self.assertTrue(light["hasBri"])
        self.assertTrue(light["hasCt"])
        self.assertFalse(light["hasColor"])

    def test_white_only_flags(self):
        light = hue_api.normalize_light("32", STATE["lights"]["32"])
        self.assertTrue(light["hasBri"])
        self.assertFalse(light["hasCt"])
        self.assertFalse(light["hasColor"])

    def test_unreachable_light(self):
        light = hue_api.normalize_light("41", STATE["lights"]["41"])
        self.assertFalse(light["reachable"])
        self.assertFalse(light["on"])

    def test_hex_present_for_on_light(self):
        light = hue_api.normalize_light("1", STATE["lights"]["1"])
        self.assertRegex(light["hex"], r"^#[0-9a-f]{6}$")

    def test_hex_off_is_dark(self):
        STATE["lights"]["32"]["state"]["on"] = False
        light = hue_api.normalize_light("32", STATE["lights"]["32"])
        self.assertEqual(light["hex"], "#1c1c1c")

    def test_name_sanitized(self):
        data = dict(STATE["lights"]["1"])
        data["name"] = "Liv‮ing room​"  # bidi + zero-width
        light = hue_api.normalize_light("1", data)
        self.assertEqual(light["name"], "Living room")

    def test_missing_bri_is_none(self):
        data = {"state": {"on": True}, "name": "X", "type": "Dimmable light"}
        light = hue_api.normalize_light("9", data)
        self.assertIsNone(light["bri"])
        self.assertTrue(light["on"])


class GroupNormalizationTests(unittest.TestCase):
    def setUp(self):
        global STATE
        STATE = fake_bridge.build_state()
        fake_bridge.refresh_group_states()
        self.lights = {lid: hue_api.normalize_light(lid, data)
                       for lid, data in STATE["lights"].items()}
        # normalize_light has no _raw; group_tint uses it for HS fallback —
        # simulate what cmd_get_state does.
        for lid, data in STATE["lights"].items():
            self.lights[lid]["_raw"] = data["state"]

    def normalize(self, gid):
        group = hue_api.normalize_group(gid, STATE["groups"][gid],
                                        self.lights)
        return group

    def test_avg_bri_derived_from_members(self):
        # action.bri is a deliberately stale 254; all 15 living-room bulbs
        # sit at 200, so avgBri must come from members, not the action.
        group = self.normalize("1")
        self.assertEqual(group["bri"], 200)
        self.assertNotEqual(group["bri"], 254)

    def test_avg_bri_ignores_off_members(self):
        # Kitchen: only even-numbered bulbs on, all at 180.
        group = self.normalize("2")
        self.assertEqual(group["bri"], 180)

    def test_avg_bri_none_when_all_off(self):
        # Office: bulbs 32-40 off, 41 unreachable.
        group = self.normalize("4")
        self.assertIsNone(group["bri"])

    def test_any_on_semantics(self):
        self.assertTrue(self.normalize("1")["on"])
        self.assertFalse(self.normalize("4")["on"])

    def test_tint_from_lit_members(self):
        group = self.normalize("1")
        self.assertRegex(group["tintHex"], r"^#[0-9a-f]{6}$")
        self.assertNotEqual(group["tintHex"], "#1c1c1c")

    def test_tint_falls_back_when_all_off(self):
        group = self.normalize("4")
        self.assertRegex(group["tintHex"], r"^#[0-9a-f]{6}$")

    def test_scene_ids_populated(self):
        group = self.normalize("1")
        self.assertEqual(sorted(group["sceneIds"]), ["s1", "s2"])
        self.assertEqual(self.normalize("3")["sceneIds"], [])

    def test_light_ids_are_strings(self):
        group = self.normalize("4")
        self.assertIn("41", group["lightIds"])
        self.assertTrue(all(isinstance(x, str) for x in group["lightIds"]))


class ColorMathTests(unittest.TestCase):
    def test_warm_white_xy(self):
        rgb = hue_api.xy_to_rgb(0.4573, 0.4053)
        self.assertIsNotNone(rgb)
        r, g, b = rgb
        self.assertGreater(r, g)
        self.assertGreater(g, b)

    def test_invalid_xy(self):
        self.assertIsNone(hue_api.xy_to_rgb(0.5, 0))
        self.assertIsNone(hue_api.xy_to_rgb(-0.1, 0.5))
        self.assertIsNone(hue_api.xy_to_rgb(None, 0.5))

    def test_ct_warm_vs_cool(self):
        cool = hue_api.ct_to_rgb(153)   # 6500K
        warm = hue_api.ct_to_rgb(500)   # 2000K
        self.assertGreater(cool[2], warm[2])   # blue channel
        self.assertGreater(cool[1], warm[1])   # green channel (cool is brighter)

    def test_ct_out_of_range_clamped(self):
        self.assertIsNotNone(hue_api.ct_to_rgb(1))
        self.assertIsNone(hue_api.ct_to_rgb(0))

    def test_hs_roundtrip(self):
        rgb = hue_api.hs_to_rgb(0, 254)   # pure red at display value 0.75
        self.assertAlmostEqual(rgb[0], 0.75)
        self.assertAlmostEqual(rgb[1], 0.0)
        self.assertAlmostEqual(rgb[2], 0.0)

    def test_to_hex(self):
        self.assertEqual(hue_api.to_hex([1.0, 0.0, 0.0]), "#ff0000")
        self.assertEqual(hue_api.to_hex(None), "#1c1c1c")

    def test_light_hex_prefers_xy(self):
        state = {"xy": [0.4573, 0.4053], "hue": 0, "sat": 254}
        self.assertEqual(hue_api.light_hex(state),
                         hue_api.to_hex(hue_api.xy_to_rgb(0.4573, 0.4053)))


if __name__ == "__main__":
    unittest.main()