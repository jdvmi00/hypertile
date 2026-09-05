"""Managed layout previews exercise real scene/stream state transitions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("scene_fixtures", Path(__file__).with_name("scenes.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class BrowseTests(unittest.TestCase):
    setUp = fixtures.SceneTests.setUp
    controller = fixtures.SceneTests.controller
    tick = fixtures.SceneTests.tick
    command = fixtures.SceneTests.command
    save = fixtures.SceneTests.save
    apply = fixtures.SceneTests.apply
    ready = fixtures.SceneTests.ready

    def start(self, token="overlay", name="other"):
        if len(self.layouts.entries) == 1:
            self.layouts.entries.append({"name": "other", "spec": {"columns": [{"name": "one"}, {"name": "two"}]}})
        return self.command("browse", name=name, browse_token=token)

    def test_preview_and_cancel_keep_stream_scene_and_saved_files(self):
        self.ready()
        before = copy.deepcopy(self.ctl.records["laptop"])
        scene = self.command("current")
        saved = (self.root / "scenes/work.json").read_bytes()
        self.start()
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:other")
        self.comp.invalid = True  # Preview zones do not contain the assigned leaf.
        self.tick(4)
        self.assertEqual(self.ctl.records["laptop"], before)
        self.assertEqual(self.command("current"), scene)
        self.command("browse-end", browse_token="overlay")
        self.comp.invalid = False
        self.tick()
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:quad")
        self.assertEqual(self.command("current"), scene)
        self.assertEqual(self.ctl.records["laptop"]["assignment"], before["assignment"])
        self.assertEqual(self.ctl.records["laptop"]["window"], before["window"])
        self.assertEqual(self.proc.count["laptop"], 1)
        self.assertEqual((self.root / "scenes/work.json").read_bytes(), saved)

    def test_close_before_start_and_late_old_owner_cannot_move_windows(self):
        self.ready()
        self.command("browse-end", browse_token="old")
        self.assertFalse(self.start("old")["preview"])
        self.start("new")
        self.command("browse-end", browse_token="old")
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:other")
        self.assertFalse(self.start("old")["preview"])
        self.assertEqual(self.ctl.browser.active["1"]["token"], "new")

    def test_lease_heartbeat_expiry_and_controller_restart_restore(self):
        self.ready()
        self.ctl.browser.clock = lambda: self.now
        self.start()
        self.now += 8
        self.command("catalog", browse_token="overlay")
        self.now += 8
        self.tick()
        self.assertIn("1", self.ctl.browser.active)
        self.now += 11
        self.tick()
        self.assertFalse(self.ctl.browser.active)
        self.start("restart")
        self.ctl = self.controller()
        self.tick()
        self.assertFalse(self.ctl.browser.active)
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:quad")
        self.assertEqual(self.proc.count["laptop"], 1)

    def test_new_scene_restores_base_before_capturing_and_retains_client(self):
        self.ready()
        self.save("move", zone="left")
        self.start()
        self.apply("move")
        self.tick(4)
        self.assertFalse(self.ctl.browser.active)
        self.assertEqual(self.command("current")["phase"], "ready")
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "left")
        self.assertEqual(self.proc.count["laptop"], 1)
        self.command("browse-end", browse_token="overlay")
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "left")

    def test_disconnect_is_not_blocked_by_preview(self):
        self.ready()
        self.start()
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(5)
        self.assertFalse(self.ctl.browser.active)
        self.assertFalse(self.ctl.records["laptop"]["desired"])
        self.assertFalse(self.proc.alive)

    def test_session_capture_keeps_last_checkpoint_during_preview(self):
        self.ready()
        self.start()
        directory = self.root / "hypertile/streams"
        directory.mkdir(parents=True)
        (directory / "state.json").write_text(json.dumps(self.ctl.state))
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)}):
            with self.assertRaisesRegex(ValueError, "layout preview is active"):
                fixtures.fixtures.integration.capture(self.comp.snapshot())

    def test_preview_rejects_inflight_stream_and_failed_restore_stays_blocked(self):
        self.save()
        self.apply()
        with self.assertRaisesRegex(ValueError, "Wait for the scene"):
            self.start()
        self.tick(6)
        self.start()
        self.comp.fail_layout = True
        with self.assertRaises(RuntimeError):
            self.command("browse-end", browse_token="overlay")
        self.assertIn("1", self.ctl.browser.active)
        self.assertEqual(self.ctl.records["laptop"]["observed"], "window-ready")
        self.comp.fail_layout = False
        self.tick()
        self.assertFalse(self.ctl.browser.active)

    def test_late_close_does_not_override_unrelated_external_layout(self):
        self.ready()
        self.start()
        self.comp.desktop["workspaces"][0]["layout"] = "dwindle"
        self.command("browse-end", browse_token="overlay")
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "dwindle")


if __name__ == "__main__":
    unittest.main()
