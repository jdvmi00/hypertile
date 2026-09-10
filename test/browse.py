"""Managed layout previews exercise real scene state transitions."""
import copy
import importlib.util
import json
import fcntl
import multiprocessing
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("scene_fixtures", Path(__file__).with_name("scenes.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from ipc import daemon, request


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

    def test_preview_and_cancel_keep_scene_and_saved_files(self):
        self.ready()
        scene = self.command("current")
        saved = (self.root / "scenes/work.json").read_bytes()
        self.start()
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:other")
        self.tick(4)
        self.assertEqual(self.command("current"), scene)
        self.command("browse-end", browse_token="overlay")
        self.tick()
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:quad")
        self.assertEqual(self.command("current"), scene)
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
        durable = json.loads((self.ctl.root / "state.json").read_text())
        self.assertEqual(durable["browse"]["active"]["1"]["deadline"], self.now + 10)
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

    def test_new_scene_restores_base_before_capturing_and_retains_client(self):
        self.ready()
        self.save("move", zone="left")
        self.start()
        self.apply("move")
        self.tick(4)
        self.assertFalse(self.ctl.browser.active)
        self.assertEqual(self.command("current")["phase"], "ready")
        self.command("browse-end", browse_token="overlay")

    def test_session_capture_keeps_last_checkpoint_during_preview(self):
        self.ready()
        self.start()
        directory = self.root / "hypertile/scenes"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "state.json").write_text(json.dumps(self.ctl.state))
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)}):
            with self.assertRaisesRegex(ValueError, "layout preview is active"):
                fixtures.scene_recovery.capture(self.comp.snapshot())

    def test_preview_rejects_inflight_scene_and_failed_restore_stays_blocked(self):
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
        self.comp.fail_layout = False
        self.tick()
        self.assertFalse(self.ctl.browser.active)

    def test_late_close_does_not_override_unrelated_external_layout(self):
        self.ready()
        self.start()
        self.comp.desktop["workspaces"][0]["layout"] = "dwindle"
        self.command("browse-end", browse_token="overlay")
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "dwindle")

    def test_waiting_session_does_not_block_a_managed_preview(self):
        self.ready()
        self.ctl.scenes.records["1"]["phase"] = "waiting-session"
        self.assertTrue(self.start()["preview"])
        self.command("browse-end", browse_token="overlay")
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:quad")

    def test_shutdown_attempts_all_leases_even_when_the_compositor_is_gone(self):
        self.ready()
        self.start()
        self.ctl.browser.active["2"] = copy.deepcopy(self.ctl.browser.active["1"])
        with patch.object(self.comp, "snapshot", side_effect=RuntimeError("compositor gone")) as snap:
            result = self.ctl.command({"command": "stop"})
        self.assertTrue(result["stopping"])
        self.assertFalse(self.ctl.running)
        self.assertEqual(snap.call_count, 2)
        self.assertIn("compositor gone", result["error"])
        saved = json.loads((self.ctl.root / "state.json").read_text())
        self.assertTrue(all(r["ending"] for r in saved["browse"]["active"].values()))

    def test_stop_and_sigterm_release_socket_and_writer_lock_with_active_lease(self):
        self.ready()
        self.start()
        original = copy.deepcopy(self.ctl.state)
        scene_root = self.ctl.root
        runtime = self.root / "runtime"
        comp = self.comp
        # Keep the lease live until shutdown; don't let a startup tick recover
        # the prior writer's lease before the test can send its stop signal.
        class QuietController(fixtures.SceneController):
            def tick(self):
                pass
        for sigterm in (False, True):
            for failing in (False, True):
                with self.subTest(sigterm=sigterm, failing=failing):
                    (scene_root / "state.json").write_text(json.dumps(original))
                    def factory(root, config, compositor):
                        ctl = QuietController(root, config, comp)
                        if failing:
                            def unavailable():
                                raise RuntimeError("compositor gone")
                            comp.snapshot = unavailable
                        return ctl
                    with patch.dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE="one"):
                        proc = multiprocessing.get_context("fork").Process(target=daemon, args=(scene_root, runtime, self.ctl.config, factory))
                        proc.start()
                    try:
                        until = time.monotonic() + 5
                        while time.monotonic() < until:
                            try:
                                request(runtime, {"command": "status"}, timeout=.2)
                                break
                            except (OSError, ValueError):
                                time.sleep(.02)
                        else:
                            self.fail("daemon did not start")
                        if sigterm:
                            proc.terminate()
                        else:
                            self.assertTrue(request(runtime, {"command": "stop"}, timeout=2)["stopping"])
                        proc.join(3)
                        self.assertEqual(proc.exitcode, 0)
                        self.assertFalse((runtime / "control.sock").exists())
                        with (scene_root / "writer.lock").open("a") as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        active = json.loads((scene_root / "state.json").read_text())["browse"]["active"]
                        if failing:
                            self.assertTrue(active["1"]["ending"])
                        else:
                            self.assertFalse(active)
                    finally:
                        if proc.is_alive():
                            proc.kill()
                            proc.join(3)


if __name__ == "__main__":
    unittest.main()
