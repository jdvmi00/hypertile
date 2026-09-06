"""Generic app scenes: launch ownership, exact identity, recovery and user moves."""
import copy
import fcntl
import importlib.util
import json
import multiprocessing
import time
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("scene_fixtures", Path(__file__).with_name("scenes.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
from apps import DesktopApps
from scene_service import SceneController
from service import Launchers, match_windows
from ipc import daemon, request
import scene_recovery


class Desktop(DesktopApps):
    def __init__(self, ctl):
        super().__init__()
        self.ctl, self.launched, self.error = ctl, [], None

    def launch(self, source):
        state = json.loads((self.ctl.root / "state.json").read_text())
        assert source["desktop_id"] in state["app_launches"], "launch intent must precede process creation"
        self.launched.append(source["desktop_id"])

    def failure(self, desktop_id):
        return self.error


class Compositor(f.Compositor):
    def call(self, method, args):
        if method == "scene_layout":
            for ws in self.desktop["workspaces"]:
                if ws["selector"] == args["workspace"]:
                    ws["layout"] = args["layout"]
            self.desktop["layouts"][args["layout"].removeprefix("lua:")] = {"spec": args.get("spec", {})}
            self.calls.append((method, copy.deepcopy(args)))
            return "scene rule"
        if method == "scene_app_place":
            self.calls.append((method, copy.deepcopy(args)))
            window = next(w for w in self.desktop["windows"] if w["address"] == args["address"])
            pin = {k: window[k] for k in ("address", "stable_id", "pid")}
            pin.update(zone=args["zone"], before=window.get("pin"))
            window.update(workspace=args["workspace"], pin=args["zone"], pin_exclusive=True, floating=False)
            return pin
        return super().call(method, args)


class AppTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        self.apps_dir = self.data / "applications"
        self.apps_dir.mkdir(parents=True)
        env = patch.dict(os.environ, XDG_DATA_HOME=str(self.data), XDG_DATA_DIRS=str(self.root / "system"),
                         XDG_STATE_HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / "config"))
        env.start()
        self.addCleanup(env.stop)
        self.desktop_file = self.apps_dir / "remote-desktops-macbook.desktop"
        self.desktop_file.write_text('[Desktop Entry]\nType=Application\nName=MacBook\nExec=remote-desktops open macbook\n'
            'X-RemoteDesktops-WindowClass=com.moonlight_stream.Moonlight\nX-RemoteDesktops-WindowTitle=MacBook - Moonlight\n')
        self.layouts = f.Layouts()
        self.comp = Compositor(self.layouts)
        self.now = 100
        self.ctl = self.controller()
        self.desktop = Desktop(self.ctl)
        self.ctl.scenes.apps.desktop = self.desktop

    def controller(self):
        ctl = SceneController(self.root / "hypertile/scenes", self.root / "config/hypertile/scenes.json", self.comp, now=lambda: self.now)
        ctl.scenes.layouts = self.layouts
        return ctl

    def command(self, action, **kw):
        return self.ctl.command({"command": "scene", "action": action, "workspace": "1", **kw})

    def save(self):
        return self.command("save", name="work", document={"version": 1, "layout": "quad", "sources": {
            "right": {"type": "app", "desktop_id": self.desktop_file.name}}})

    def start(self):
        self.save()
        self.command("apply", name="work")
        self.tick()

    def tick(self, n=1):
        for _ in range(n):
            self.ctl.tick()
            self.now += 1

    def window(self, title="MacBook - Moonlight", address="macbook", workspace="2"):
        window = {"address": address, "pid": 7, "stable_id": 22, "class": "com.moonlight_stream.Moonlight",
                  "initial_class": "com.moonlight_stream.Moonlight", "title": title, "workspace": workspace,
                  "floating": False}
        self.comp.desktop["windows"].append(window)
        return window

    def placements(self):
        return [v for k, v in self.comp.calls if k == "scene_app_place"]

    def test_installed_entry_supplies_exact_identity(self):
        source = self.save()["document"]["sources"]["z-right"]
        self.assertEqual(source["app_title"], "MacBook - Moonlight")
        self.assertEqual(source["app_class"], "com.moonlight_stream.Moonlight")
        self.assertEqual(self.command("catalog")["apps"][0]["name"], "MacBook")
        self.assertNotIn("computers", self.command("catalog"))
        (self.apps_dir / "placeholder.desktop").write_text('[Desktop Entry]\nType=Application\nName=Placeholder\nExec=placeholder\nStartupWMClass=@@startup_wm_class\n')
        self.ctl.scenes.apps.desktop.next_scan = 0
        self.assertNotIn("Placeholder", [a["name"] for a in self.command("catalog")["apps"]])
        self.assertFalse(self.desktop.launched)

    def test_standalone_service_does_not_take_stream_lock_or_read_computers(self):
        legacy = self.root / "hypertile/streams"
        legacy.mkdir()
        (legacy / "state.json").write_text("not a scene journal")
        with (legacy / "writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ctl = self.controller()
            self.assertFalse(ctl.scenes.records)
            ctl.tick()
        self.assertEqual((legacy / "state.json").read_text(), "not a scene journal")

    def test_launch_once_wait_for_final_title_and_reuse_exact_window(self):
        other = self.window("Work Laptop - Moonlight", "work")
        startup = self.window("Moonlight", "startup")
        self.start()
        self.tick(5)
        self.assertEqual(self.desktop.launched, [self.desktop_file.name])
        self.assertFalse(self.placements())
        startup["title"] = "MacBook - Moonlight"
        self.tick(3)
        self.assertEqual(len(self.placements()), 1)
        self.assertEqual(other["workspace"], "2")
        self.assertEqual(startup["workspace"], "1")
        self.assertEqual(self.command("current")["phase"], "ready")
        self.command("apply", name="work")
        self.tick()
        self.assertEqual(len(self.placements()), 1)

    def test_existing_window_reused_and_manual_move_survives_restart(self):
        window = self.window()
        self.start()
        self.assertFalse(self.desktop.launched)
        window.update(workspace="2", pin=None, floating=True)
        self.tick(3)
        self.ctl = self.controller()
        self.ctl.scenes.apps.desktop = self.desktop
        self.tick(3)
        self.assertEqual(len(self.placements()), 1)
        self.assertEqual(self.command("current")["sources"][0]["status"], "moved")
        self.command("apply", name="work")
        self.tick()
        self.assertEqual(len(self.placements()), 2)
        self.assertEqual(window["workspace"], "1")

    def test_close_does_not_relaunch_until_explicit_apply(self):
        self.window()
        self.start()
        self.comp.desktop["windows"].clear()
        self.tick(4)
        self.assertFalse(self.desktop.launched)
        self.assertEqual(self.command("current")["sources"][0]["status"], "closed")
        self.command("apply", name="work")
        self.tick()
        self.assertEqual(len(self.desktop.launched), 1)

    def test_ambiguous_match_neither_launches_nor_places(self):
        self.window()
        self.window(address="duplicate")
        self.start()
        self.assertFalse(self.desktop.launched)
        self.assertFalse(self.placements())
        self.assertEqual(self.command("current")["phase"], "partial")

    def test_uncertain_launch_survives_restart_timeout_and_explicit_retry(self):
        self.start()
        self.ctl = self.controller()
        self.ctl.scenes.apps.desktop = self.desktop
        self.tick(3)
        self.assertEqual(len(self.desktop.launched), 1)
        self.now += 46
        self.tick()
        self.assertEqual(self.command("current")["phase"], "partial")
        self.command("retry")
        self.tick()
        self.assertEqual(len(self.desktop.launched), 2)

    def test_new_scene_does_not_duplicate_pending_launch_or_place_late_app_after_cancel(self):
        self.start()
        self.command("content", type="app", desktop_id=self.desktop_file.name, zone="left")
        self.tick()
        self.assertEqual(len(self.desktop.launched), 1)
        self.command("cancel")
        self.tick()
        window = self.window()
        self.tick(5)
        self.assertFalse(self.placements())
        self.assertEqual(window["workspace"], "2")

    def test_lost_placement_reply_does_not_retry_after_manual_move(self):
        window = self.window()
        original = self.comp.call
        def fail(method, args):
            value = original(method, args)
            if method == "scene_app_place":
                raise RuntimeError("reply lost")
            return value
        with patch.object(self.comp, "call", side_effect=fail):
            self.start()
        window["workspace"] = "2"
        self.ctl = self.controller()
        self.tick(4)
        self.assertEqual(len(self.placements()), 1)
        self.assertEqual(window["workspace"], "2")

    def test_session_checkpoint_uses_one_launcher_and_preserves_manual_departure(self):
        window = self.window()
        self.start()
        captured = scene_recovery.capture(self.comp.snapshot())
        self.assertNotIn("macbook", [w["address"] for w in captured["windows"]])
        self.assertEqual(captured["scenes"][0]["document"]["sources"]["z-right"]["desktop_id"], self.desktop_file.name)
        window.update(workspace="2", pin=None)
        captured = scene_recovery.capture(self.comp.snapshot())
        self.assertIn("macbook", [w["address"] for w in captured["windows"]])
        self.assertEqual(captured["scenes"][0]["document"]["sources"], {})
        recipe = Launchers({}).recipe(window)
        self.assertEqual(recipe["argv"], ["gio", "launch", str(self.desktop_file)])
        self.comp.instance = "next-compositor"
        self.ctl = self.controller()
        self.tick()
        self.assertEqual(self.command("current")["phase"], "waiting-session")
        self.ctl.command({"command": "session-restore", "scenes": captured["scenes"]})
        self.tick(3)
        self.assertEqual(self.command("current")["document"]["sources"], {})

    def test_scene_preview_pauses_capture_without_any_stream_journal(self):
        self.start()
        self.ctl.state["browse"]["active"]["1"] = {"token": "preview"}
        self.ctl.persist()
        with self.assertRaisesRegex(ValueError, "layout preview"):
            scene_recovery.capture(self.comp.snapshot())

    def test_missing_empty_workspace_can_return_with_the_app(self):
        self.start()
        self.comp.desktop["workspaces"].clear()
        window = self.window()
        self.tick()
        self.assertEqual(len(self.placements()), 1)
        self.assertEqual(window["workspace"], "1")

    def test_new_assignment_supersedes_pending_placement_on_another_workspace(self):
        self.start()
        self.comp.desktop["workspaces"].append({"selector": "2", "layout": "dwindle"})
        self.ctl.command({"command": "scene", "action": "apply", "name": "work", "workspace": "2"})
        self.assertEqual(self.ctl.scenes.records["1"]["apps"]["z-right"]["status"], "moved")
        self.window()
        # The first workspace may observe this late window, but has relinquished placement.
        self.ctl.scenes.apps.step(self.ctl.scenes.records["1"], self.comp.snapshot())
        self.assertFalse(self.placements())

    def test_current_observes_manual_move_before_idle_tick(self):
        window = self.window()
        self.start()
        self.assertEqual(self.ctl.tick_interval(), 30)
        window["workspace"] = "2"
        self.assertEqual(self.command("current")["sources"][0]["status"], "moved")
        self.assertEqual(len(self.placements()), 1)

    def test_recovery_never_matches_other_computer_by_shared_class(self):
        saved = self.window()
        saved["launch"] = Launchers({}).recipe(saved)
        other = {**saved, "address": "other", "title": "Work Laptop - Moonlight"}
        matched = {}
        match_windows([saved], [other], matched)
        self.assertEqual(matched, {})
        final = {**saved, "address": "new"}
        match_windows([saved], [other, final], matched)
        self.assertEqual(matched, {saved["address"]: "new"})

    def test_extra_matching_windows_remain_in_normal_checkpoint(self):
        self.window()
        self.start()
        self.window(address="extra")
        captured = scene_recovery.capture(self.comp.snapshot())
        self.assertEqual([w["address"] for w in captured["windows"]], ["extra"])
        self.assertIn("z-right", captured["scenes"][0]["document"]["sources"])

    def test_normal_recovery_does_not_claim_the_window_already_placed_by_scenes(self):
        saved = self.window()
        current = {**saved, "address": "scene-owned", "scene_app": True}
        matches = {}
        match_windows([saved], [current], matches)
        self.assertEqual(matches, {})

    def test_app_only_scene_recovery_does_not_wait_for_another_app_to_create_workspace(self):
        doc = self.save()["document"]
        self.comp.desktop["workspaces"].clear()
        self.ctl.command({"command": "session-restore", "scenes": [{"workspace": "1", "document": doc}]})
        self.tick(3)
        self.assertEqual(self.desktop.launched, [self.desktop_file.name])
        self.window()
        self.tick()
        self.assertEqual(len(self.placements()), 1)

    def test_daemon_has_independent_socket_and_writer_lock(self):
        root, runtime = self.root / "ipc/scenes", self.root / "ipc/runtime"
        legacy = self.root / "ipc/streams"
        legacy.mkdir(parents=True)
        with (legacy / "writer.lock").open("a") as lock, patch.dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE="fake-scenes"):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            proc = multiprocessing.get_context("fork").Process(target=daemon, args=(root, runtime, self.ctl.config, SceneController))
            proc.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        status = request(runtime, {"command": "status"}, timeout=.2)
                        break
                    except (OSError, ValueError):
                        time.sleep(.02)
                else:
                    self.fail("scene daemon did not start")
                self.assertEqual(status["instance"], "fake-scenes")
                self.assertEqual((runtime / "control.sock").stat().st_mode & 0o777, 0o600)
                with (root / "writer.lock").open("a") as competing:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                request(runtime, {"command": "stop"}, timeout=1)
                proc.join(3)
                self.assertEqual(proc.exitcode, 0)
            finally:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(3)

    def test_launcher_validation_and_xdg_precedence(self):
        with self.assertRaisesRegex(ValueError, "not a path"):
            self.desktop.resolve({"desktop_id": "../evil.desktop"})
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self.desktop.resolve({"desktop_id": self.desktop_file.name, "app_title": "Work Laptop - Moonlight"})
        system = self.root / "system/applications"
        system.mkdir(parents=True)
        (system / self.desktop_file.name).write_text(self.desktop_file.read_text())
        self.desktop_file.write_text("[Desktop Entry]\nType=Application\nHidden=true\n")
        self.desktop.next_scan = 0
        with self.assertRaisesRegex(ValueError, "Install the app"):
            self.desktop.resolve({"desktop_id": self.desktop_file.name})

    def test_launch_uses_desktop_file_without_shell(self):
        source = self.save()["document"]["sources"]["z-right"]
        with patch("apps.subprocess.Popen") as launch:
            DesktopApps().launch(source)
        self.assertEqual(launch.call_args.args[0], ["gio", "launch", str(self.desktop_file)])
        self.assertNotIn("shell", launch.call_args.kwargs)



if __name__ == "__main__":
    unittest.main()
