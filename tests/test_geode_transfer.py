import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geode_transfer as gt  # noqa: E402


DEVICES = {
    "devices": [
        {
            "identifier": "AAAA-1",
            "hardwareProperties": {"deviceType": "iPad", "marketingName": "iPad Pro", "udid": "UDID-IPAD"},
            "deviceProperties": {"name": "My iPad", "osVersionNumber": "27.2"},
            "connectionProperties": {"transportType": "wired", "pairingState": "paired"},
        },
        {
            "identifier": "BBBB-2",
            "hardwareProperties": {"deviceType": "iPhone", "marketingName": "iPhone 15 Pro Max", "udid": "UDID-PHONE"},
            "deviceProperties": {"name": "Alex’s iPhone (2)", "osVersionNumber": "27.2"},
            "connectionProperties": {"transportType": "localNetwork", "pairingState": "paired"},
        },
        {
            "identifier": "CCCC-3",
            "hardwareProperties": {"deviceType": "appleWatch", "marketingName": "Apple Watch", "udid": "UDID-WATCH"},
            "deviceProperties": {"name": "Watch", "osVersionNumber": "27.2"},
            "connectionProperties": {},
        },
    ]
}

APPS = {
    "apps": [
        {"bundleIdentifier": "com.apple.mobilesafari", "name": "Safari", "version": "1"},
        {"bundleIdentifier": "com.geode.launcher.TEAM", "name": "Geode", "version": "1.5.5", "containerAccessible": True,
         "url": "file:///private/var/containers/Bundle/Application/X/Geode.app/"},
        {"bundleIdentifier": "com.robtop.geometryjump", "name": "Geometry Dash", "version": "2.2", "containerAccessible": False},
    ]
}

ROOT = "Documents/Data/Application/GeometryDash"
LISTING = {
    "Documents": 0,
    "Documents/Data": 0,
    "Documents/Data/Application": 0,
    ROOT: 0,
    f"{ROOT}/Documents": 0,
    f"{ROOT}/Documents/CCGameManager.dat": 100,
    f"{ROOT}/Documents/CCLocalLevels.dat": 300,
    f"{ROOT}/Documents/12345.ogg": 1000,
    f"{ROOT}/Documents/67890.mp3": 2000,
    f"{ROOT}/Documents/notes.txt": 5,
    f"{ROOT}/Documents/game": 0,
    f"{ROOT}/Documents/game/geode": 0,
    f"{ROOT}/Documents/game/geode/mods": 0,
    f"{ROOT}/Documents/game/geode/mods/a.geode": 50,
    f"{ROOT}/Documents/game/geode/mods/b.geode": 60,
    f"{ROOT}/Documents/game/geode/config": 0,
    f"{ROOT}/Documents/game/geode/config/a": 0,
    f"{ROOT}/Documents/game/geode/config/a/cache.bin": 700,
    f"{ROOT}/Documents/game/geode/unzipped": 0,
    f"{ROOT}/Documents/game/geode/unzipped/a/x.dll": 999,
    f"{ROOT}/Documents/game/geode/logs/today.log": 10,
    f"{ROOT}/Documents/save": 0,
    f"{ROOT}/Documents/save/geode": 0,
    f"{ROOT}/Documents/save/geode/bindings.json": 4,
    f"{ROOT}/Documents/save/geode/mods/a/saved.json": 8,
    "Documents/Applications/com.robtop.geometryjump.app/Info.plist": 3,
    "Documents/Tweaks/TweakLoader.dylib": 3,
}


class Categories(unittest.TestCase):
    def test_categorize(self):
        c = gt.categorize
        self.assertEqual(c("Documents/CCGameManager.dat"), "saves")
        self.assertEqual(c("Documents/CCLocalLevels2.dat"), "saves")
        self.assertEqual(c("Documents/game/geode/mods/a.geode"), "mods")
        self.assertEqual(c("Documents/save/geode/bindings.json"), "mod-data")
        self.assertEqual(c("Documents/game/geode/config/a/cache.bin"), "mod-config")
        self.assertEqual(c("Documents/123.ogg"), "songs")
        self.assertEqual(c("Documents/456.mp3"), "songs")

    def test_regenerated_or_local_files_are_never_copied(self):
        for rel in (
            "Documents/game/geode/unzipped/a/x.dll",
            "Documents/game/geode/resources/r.png",
            "Documents/game/geode/logs/today.log",
            "Documents/game/geode/ModInfo.plist",
            "Documents/Applications/com.robtop.geometryjump.app/Info.plist",
            "Documents/Tweaks/TweakLoader.dylib",
            "Library/Caches/x",
            "tmp/x",
            "Documents/notes.txt",
            "Documents/sub/song.ogg",
        ):
            self.assertIsNone(gt.categorize(rel), rel)

    def test_selection(self):
        self.assertEqual(gt.resolve_categories(None, None), list(gt.CATEGORIES))
        self.assertEqual(gt.resolve_categories("saves,mods", None), ["saves", "mods"])
        self.assertNotIn("songs", gt.resolve_categories(None, "songs"))
        self.assertEqual(gt.resolve_categories("saves,mods", "mods"), ["saves"])

    def test_selection_rejects_unknown_and_empty(self):
        with self.assertRaises(gt.TransferError):
            gt.resolve_categories("saves,bogus", None)
        with self.assertRaises(gt.TransferError):
            gt.resolve_categories("saves", "saves")


class Preferences(unittest.TestCase):
    PREFS = {
        "CompletedSetup": True,
        "JITLESS": True,
        "LCCertificateData": b"secret",
        "LCCertificatePassword": "pw",
        "LCCertificateImported": True,
        "PATCH_CHECKSUM": "abc",
        "CURRENT_TWEAK_HASH": "def",
        "GDVerified": True,
        "LAUNCH_COUNT": 117,
        "FIX_ROTATION": True,
        "CURRENT_ICON": "Gay",
    }

    def test_certificate_is_left_out_by_default(self):
        cleaned = gt.clean_prefs(self.PREFS, include_certificate=False)
        for key in ("LCCertificateData", "LCCertificatePassword", "LCCertificateImported", "CompletedSetup", "JITLESS"):
            self.assertNotIn(key, cleaned)
        self.assertEqual(cleaned["FIX_ROTATION"], True)
        self.assertEqual(cleaned["CURRENT_ICON"], "Gay")

    def test_derived_state_is_always_removed(self):
        for include in (False, True):
            cleaned = gt.clean_prefs(self.PREFS, include_certificate=include)
            for key in ("PATCH_CHECKSUM", "CURRENT_TWEAK_HASH", "GDVerified", "LAUNCH_COUNT"):
                self.assertNotIn(key, cleaned)

    def test_certificate_kept_when_asked(self):
        cleaned = gt.clean_prefs(self.PREFS, include_certificate=True)
        self.assertEqual(cleaned["LCCertificateData"], b"secret")
        self.assertEqual(cleaned["LCCertificatePassword"], "pw")
        self.assertTrue(cleaned["CompletedSetup"])

    def test_input_is_not_modified(self):
        original = dict(self.PREFS)
        gt.clean_prefs(self.PREFS, include_certificate=False)
        self.assertEqual(self.PREFS, original)


class Devices(unittest.TestCase):
    def test_parse_keeps_only_phones_and_tablets(self):
        devices = gt.parse_devices(DEVICES)
        self.assertEqual([d.kind for d in devices], ["iPad", "iPhone"])
        self.assertEqual(devices[1].udid, "UDID-PHONE")

    def test_connection_tells_a_cable_from_wifi(self):
        devices = gt.parse_devices(DEVICES)
        self.assertEqual([d.connection for d in devices], ["usb", "wifi"])
        devices[0].transport = "?"
        self.assertEqual(devices[0].connection, "unknown")

    def test_pick_by_name_ignores_curly_quotes_and_nbsp(self):
        devices = gt.parse_devices(DEVICES)
        self.assertEqual(gt.pick_device(devices, "my ipad").id, "AAAA-1")
        self.assertEqual(gt.pick_device(devices, "alex's iphone (2)").id, "BBBB-2")

    def test_pick_by_id_and_udid(self):
        devices = gt.parse_devices(DEVICES)
        self.assertEqual(gt.pick_device(devices, "BBBB-2").name, "Alex’s iPhone (2)")
        self.assertEqual(gt.pick_device(devices, "UDID-IPAD").id, "AAAA-1")

    def test_pick_errors(self):
        devices = gt.parse_devices(DEVICES)
        with self.assertRaises(gt.TransferError):
            gt.pick_device(devices, "android")
        with self.assertRaises(gt.TransferError):
            gt.pick_device(devices, None)  # two devices, none chosen
        with self.assertRaises(gt.TransferError):
            gt.pick_device([], None)
        self.assertEqual(gt.pick_device(devices[:1], None).id, "AAAA-1")

    def test_ambiguous_name(self):
        devices = gt.parse_devices(DEVICES)
        devices[0].name = "iPhone A"
        with self.assertRaises(gt.TransferError) as ctx:
            gt.pick_device(devices, "iphone")
        self.assertIn("be more specific", str(ctx.exception))

    def test_cable_transfer_accepts_two_wired_devices(self):
        devices = gt.parse_devices(DEVICES)
        second = dataclasses.replace(devices[1], transport="wired")
        gt.require_cable(devices[0], second)

    def test_cable_transfer_rejects_wifi_device(self):
        devices = gt.parse_devices(DEVICES)
        with self.assertRaises(gt.TransferError) as ctx:
            gt.require_cable(*devices)
        self.assertIn("USB", str(ctx.exception))
        self.assertIn("Alex’s iPhone (2)", str(ctx.exception))

    def test_transfer_parser_accepts_cable_aliases(self):
        parser = gt.build_parser()
        via_cable = parser.parse_args(["transfer", "--from", "source", "--to", "target", "--via-cable"])
        alias = parser.parse_args(["transfer", "--from", "source", "--to", "target", "--cable"])
        self.assertTrue(via_cable.via_cable)
        self.assertTrue(alias.via_cable)


class Apps(unittest.TestCase):
    def test_only_geode_apps_are_found(self):
        apps = gt.parse_apps(APPS)
        self.assertEqual([a.bundle_id for a in apps], ["com.geode.launcher.TEAM"])
        self.assertTrue(apps[0].accessible)


class Container(unittest.TestCase):
    def test_find_and_pick(self):
        self.assertEqual(gt.find_containers(LISTING), ["GeometryDash"])
        self.assertEqual(gt.pick_container(LISTING, None), "GeometryDash")
        with self.assertRaises(gt.TransferError):
            gt.pick_container(LISTING, "Other")

    def test_several_containers_need_a_choice(self):
        files = dict(LISTING)
        files["Documents/Data/Application/Second/Documents"] = 0
        with self.assertRaises(gt.TransferError):
            gt.pick_container(files, None)
        self.assertEqual(gt.pick_container(files, "Second"), "Second")
        self.assertEqual(gt.pick_container(files, None, preferred="Second"), "Second")

    def test_empty_container_gives_a_useful_error(self):
        with self.assertRaises(gt.TransferError) as ctx:
            gt.pick_container({"Documents": 0}, None)
        self.assertIn("Open it once", str(ctx.exception))


class Planning(unittest.TestCase):
    def test_counts_and_sizes_ignore_directories_and_excluded_files(self):
        plan = gt.build_plan(LISTING, "GeometryDash", list(gt.CATEGORIES))
        self.assertEqual(plan.counts["saves"], 2)
        self.assertEqual(plan.sizes["saves"], 400)
        self.assertEqual(plan.counts["songs"], 2)
        self.assertEqual(plan.counts["mods"], 2)
        self.assertEqual(plan.counts["mod-config"], 1)
        self.assertEqual(plan.counts["mod-data"], 2)
        self.assertNotIn("Documents/game/geode/unzipped/a/x.dll", plan.entries)
        self.assertNotIn("Documents/notes.txt", plan.entries)

    def test_selection_limits_the_plan(self):
        plan = gt.build_plan(LISTING, "GeometryDash", ["saves"])
        self.assertEqual(set(plan.entries), {"Documents/CCGameManager.dat", "Documents/CCLocalLevels.dat"})


class Manifest(unittest.TestCase):
    def test_read_manifest_rejects_foreign_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(gt.TransferError):
                gt.read_manifest(Path(tmp))
            (Path(tmp) / gt.MANIFEST).write_text(json.dumps({"tool": "other"}))
            with self.assertRaises(gt.TransferError):
                gt.read_manifest(Path(tmp))
            (Path(tmp) / gt.MANIFEST).write_text(json.dumps({"tool": "geode-transfer", "categories": []}))
            self.assertEqual(gt.read_manifest(Path(tmp))["tool"], "geode-transfer")


class Verification(unittest.TestCase):
    def run_verify(self, device_files, expected):
        with mock.patch.object(gt, "list_files", return_value=device_files), mock.patch.object(gt, "say"):
            return gt.verify(mock.Mock(), mock.Mock(bundle_id="b"), ROOT, expected)

    def test_ok_when_everything_matches(self):
        self.assertTrue(self.run_verify(LISTING, {"Documents/CCGameManager.dat": 100}))

    def test_missing_and_size_mismatch_fail(self):
        self.assertFalse(self.run_verify(LISTING, {"Documents/missing.dat": 1}))
        self.assertFalse(self.run_verify(LISTING, {"Documents/CCGameManager.dat": 999}))


class Hints(unittest.TestCase):
    def test_known_errors_get_a_hint(self):
        self.assertIn("unlock", gt.hint_for("The device was locked").lower())
        self.assertIn("cable", gt.hint_for("No devices matched the specifier"))
        self.assertIn("development", gt.hint_for("app is not debuggable"))
        self.assertIsNone(gt.hint_for("something unrelated"))


class Formatting(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(gt.fmt_bytes(0), "0 B")
        self.assertEqual(gt.fmt_bytes(1500), "1.5 KB")
        self.assertEqual(gt.fmt_bytes(2_600_000_000), "2.6 GB")

    def test_time(self):
        self.assertEqual(gt.fmt_time(75), "01:15")


if __name__ == "__main__":
    unittest.main()
