"""Regression checks for data loss and duplicate/incorrect restoration."""
import copy
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "session"))
from service import Recovery, Service, Store, match_windows, read_config, request


def window(address, title="", cls="terminal"):
    return dict(address=address, stable_id=int(address), pid=100 + int(address),
                title=title, initial_title=title, initial_class=cls, **{"class": cls},
                workspace="1", at={"x": 0, "y": 0}, size={"x": 100, "y": 100},
                launch={"argv": ["terminal"], "per_window": True})


def record(*windows, instance="old"):
    return dict(version=1, instance=instance, saved_at=1,
                desktop=dict(windows=list(windows), workspaces=[], monitors=[], layouts={}))


class FakeCompositor:
    instance = "new"

    def __init__(self, desktop):
        self.desktop = copy.deepcopy(desktop)
        self.calls = []

    def snapshot(self):
        return copy.deepcopy(self.desktop)

    def call(self, method, value):
        self.calls.append((method, value))
        return True


class Launchers:
    apps = {}

    def recipe(self, window):
        return None

    def capture(self, desktop):
        return desktop


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = Store(self.root)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root), XDG_RUNTIME_DIR=str(self.root))
        env.start()
        self.addCleanup(env.stop)
        notification = patch("service.notify")
        notification.start()
        self.addCleanup(notification.stop)

    def test_interrupted_publish_and_corrupt_latest_preserve_previous(self):
        first, second = record(window("1")), record(window("2"))
        self.store.checkpoint(first)
        original_replace = __import__("os").replace
        def fail_latest(source, destination):
            if Path(destination).name == "latest.json":
                raise OSError("simulated interrupted write")
            original_replace(source, destination)
        with patch("service.os.replace", side_effect=fail_latest):
            with self.assertRaises(OSError):
                self.store.checkpoint(second)
        self.assertEqual(self.store.load(), first)
        self.store.checkpoint(second)
        (self.root / "latest.json").write_text('{"version":')
        self.assertEqual(self.store.load(), first)
        self.assertEqual(list(self.root.glob(".write-*")), [])

    def test_freeze_survives_empty_desktop_and_service_restart(self):
        comp = FakeCompositor(record(window("1"))["desktop"])
        daemon = Service(self.store, comp, Launchers())
        daemon.startup()
        daemon.command({"command": "freeze"})
        saved = self.store.load()
        comp.desktop["windows"] = []
        daemon.checkpoint()
        restarted = Service(self.store, comp, Launchers())
        restarted.startup()
        self.assertEqual(restarted.mode, "frozen")
        self.assertEqual(self.store.load(), saved)
        restarted.command({"command": "resume"})
        self.assertEqual(self.store.load()["desktop"]["windows"], [])

    def test_disabling_stops_capture_and_survives_a_new_compositor(self):
        config = self.root / "session.json"
        settings = {"replay": ["herdr"], "apps": {"terminal": False}, "custom": 42}
        config.write_text(json.dumps(settings))
        comp = FakeCompositor(record(window("1"))["desktop"])
        daemon = Service(self.store, comp, Launchers(), config)
        daemon.startup()
        saved = self.store.load()
        status = daemon.command({"command": "disable"})
        self.assertEqual(read_config(config), dict(settings, enabled=False))
        self.assertEqual(status["mode"], "disabled")
        self.assertIsNone(status["saving"]["since"])
        self.assertFalse(status["saving"]["can_resume"])
        comp.instance = "rebooted"
        restarted = Service(self.store, comp, Launchers(), config, enabled=read_config(config)["enabled"])
        with patch.object(comp, "snapshot", side_effect=AssertionError("disabled capture")):
            daemon.dirty(1)
            daemon.checkpoint()
            restarted.startup()
            self.assertEqual(restarted.command({"command": "freeze"})["mode"], "disabled")
            for command in ("save", "restore", "resume"):
                with self.assertRaisesRegex(ValueError, "session saving is disabled"):
                    restarted.command({"command": command, "name": "work"})
        self.assertEqual(comp.calls, [])
        self.assertEqual(self.store.load(), saved)

    def test_enabling_after_cancelled_recovery_saves_only_the_current_desktop(self):
        config = self.root / "session.json"
        saved = record(window("1"))
        saved["desktop"]["scenes"] = [{"workspace": "1", "document": {"sources": {}}}]
        self.store.checkpoint(saved)
        comp = FakeCompositor(record()["desktop"])
        daemon = Service(self.store, comp, Launchers(), config)
        with patch("service.scene_recovery.deliver", side_effect=OSError("offline")):
            daemon.startup()
        self.assertEqual(daemon.mode, "restoring")
        self.assertTrue(daemon.scene_delivery.pending)
        with patch("service.subprocess.Popen") as launch:
            daemon.command({"command": "disable"})
            self.assertIsNone(daemon.recovery)
            self.assertTrue(daemon.scene_delivery.paused)
            comp.calls.clear()
            comp.desktop = record(window("2"))["desktop"]
            daemon.command({"command": "enable"})
            self.assertEqual(read_config(config), {"enabled": True})
            self.assertEqual(daemon.mode, "watching")
            self.assertEqual(daemon.scene_delivery.pending, [])
            self.assertFalse(daemon.scene_delivery.paused)
            self.assertEqual(self.store.load()["desktop"]["windows"], [window("2")])
            daemon = Service(self.store, comp, Launchers(), config)
            daemon.startup()
            self.assertEqual(daemon.mode, "watching")
            self.assertEqual(comp.calls, [])
            launch.assert_not_called()
        self.assertEqual(json.loads((self.root / "recovery.json").read_text()), saved)

    def test_enable_is_idempotent_and_does_not_resume_a_frozen_session(self):
        config = self.root / "session.json"
        daemon = Service(self.store, FakeCompositor(record()["desktop"]), Launchers(), config)
        daemon.startup()
        daemon.command({"command": "freeze"})
        self.assertEqual(daemon.command({"command": "enable"})["mode"], "frozen")

    def test_setting_write_failure_does_not_disable_the_running_writer(self):
        config = self.root / "session.json"
        config.write_text('{"enabled":true}')
        daemon = Service(self.store, FakeCompositor(record()["desktop"]), Launchers(), config)
        with patch("service.atomic_json", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                daemon.command({"command": "disable"})
        self.assertEqual(daemon.mode, "watching")
        self.assertEqual(read_config(config), {"enabled": True})
        config.write_text("[]")
        with self.assertRaisesRegex(ValueError, "configuration must be an object"):
            daemon.command({"command": "disable"})
        self.assertEqual(config.read_text(), "[]")

    def test_enable_capture_failure_does_not_restore_stale_windows_on_restart(self):
        config = self.root / "session.json"
        self.store.checkpoint(record(window("1")))
        comp = FakeCompositor(record(window("2"))["desktop"])
        daemon = Service(self.store, comp, Launchers(), config, enabled=False)
        daemon.startup()
        with patch.object(comp, "snapshot", side_effect=ValueError("preview active")):
            with self.assertRaisesRegex(ValueError, "preview active"):
                daemon.command({"command": "enable"})
        restarted = Service(self.store, comp, Launchers(), config)
        restarted.startup()
        self.assertEqual(restarted.mode, "watching")
        self.assertEqual(comp.calls, [])
        self.assertEqual(self.store.load()["desktop"]["windows"], [window("2")])

    def test_restart_after_enabling_was_persisted_accepts_the_current_desktop(self):
        config = self.root / "session.json"
        self.store.checkpoint(record(window("1")))
        comp = FakeCompositor(record(window("2"))["desktop"])
        Service(self.store, comp, Launchers(), config, enabled=False).startup()
        # Simulate interruption between persisting enabled=true and capture.
        config.write_text('{"enabled":true}')
        restarted = Service(self.store, comp, Launchers(), config, enabled=read_config(config)["enabled"])
        restarted.startup()
        self.assertEqual(restarted.mode, "watching")
        self.assertEqual(comp.calls, [])
        self.assertEqual(self.store.load()["desktop"]["windows"], [window("2")])

    def test_cli_starts_an_idle_writer_and_toggles_it_over_ipc(self):
        # Real CLI/daemon processes and sockets, with an isolated compositor.
        # The fake hyprctl supplies snapshots but refuses any recovery mutation.
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        scripts = {
            "systemd-inhibit": "#!/bin/sh\nexit 1\n",
            "hyprctl": "#!/usr/bin/env python3\nimport json, pathlib, re, sys\n"
                        "code = sys.argv[-1]\nassert '.snapshot(v)' in code, code\n"
                        "answer = re.search(r'io.open\\(\"([^\"]+\\.answer)\"', code)[1]\n"
                        f"pathlib.Path(answer).write_text({json.dumps(json.dumps(record()['desktop']))})\n",
        }
        for tool, body in scripts.items():
            path = fake_bin / tool
            path.write_text(body)
            path.chmod(0o700)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
                   XDG_CONFIG_HOME=str(self.root), XDG_DATA_HOME=str(self.root), XDG_DATA_DIRS=str(self.root),
                   HYPRLAND_INSTANCE_SIGNATURE="test-toggle")
        event_path = self.root / "hypr/test-toggle/.socket2.sock"
        event_path.parent.mkdir(parents=True)
        runtime = self.root / "hypertile-session"
        state = self.root / "hypertile/sessions"
        Store(state).checkpoint(record(window("1")))
        config = self.root / "hypertile/session.json"
        config.write_text('{"enabled":false,"replay":["herdr"]}')
        entry = Path(__file__).resolve().parents[1] / "session/service.py"
        def cli(command):
            result = subprocess.run([sys.executable, str(entry), command], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        with socket.socket(socket.AF_UNIX) as events:
            events.bind(str(event_path))
            events.listen(1)
            try:
                self.assertEqual(cli("disable")["mode"], "disabled")
                self.assertEqual(Store(state).load()["desktop"]["windows"], [window("1")])
                self.assertEqual(cli("enable")["mode"], "watching")
                self.assertEqual(Store(state).load()["desktop"]["windows"], [])
                self.assertEqual(cli("disable")["mode"], "disabled")
                self.assertEqual(cli("status")["mode"], "disabled")
                self.assertEqual(read_config(config), {"enabled": False, "replay": ["herdr"]})
            finally:
                try:
                    request(runtime, "stop")
                except OSError:
                    pass
                # Wait for the daemon to close its event stream before removing
                # its isolated state (and surface a stuck daemon as a failure).
                events.settimeout(5)
                with events.accept()[0] as connection:
                    connection.settimeout(5)
                    self.assertEqual(connection.recv(1), b"")

    def test_partial_restore_keeps_source_and_launch_intent_across_restart(self):
        saved = record(window("1"))
        self.store.checkpoint(saved)
        comp = FakeCompositor(record()["desktop"])
        daemon = Service(self.store, comp, Launchers())
        with patch("service.time.monotonic", return_value=0):
            daemon.startup()
        with patch("service.subprocess.Popen") as launch:
            daemon.recovery.tick(4)
            self.assertEqual(launch.call_count, 1)
            restarted = Service(self.store, comp, Launchers())
            with patch("service.time.monotonic", return_value=5):
                restarted.startup()
            restarted.recovery.tick(10)
            self.assertEqual(launch.call_count, 1)
        restarted.command({"command": "freeze"})
        self.assertEqual(restarted.mode, "partial")
        restarted.checkpoint()
        self.assertEqual(self.store.load(), saved)
        self.assertEqual(json.loads((self.root / "recovery.json").read_text()), saved)

    def test_matching_never_reuses_old_addresses_or_guesses_between_peers(self):
        old = [window("1", "project A"), window("2", "project B")]
        # Address 1 has been reused by a different window after restart.
        live = [window("1", "project B"), window("3", "project A")]
        self.assertEqual(match_windows(old, live, {}), {"1": "3", "2": "1"})
        ambiguous = [window("4"), window("5")]
        self.assertEqual(match_windows([window("1"), window("2")], ambiguous, {}), {})

    def test_sequential_launch_matches_identical_terminal_titles_without_duplicates(self):
        saved = record(window("1"), window("2"))
        comp = FakeCompositor(record()["desktop"])
        recovery = Recovery(saved, comp, Launchers(), 0, lambda value: None)
        with patch("service.subprocess.Popen") as launch:
            recovery.tick(4)
            self.assertEqual(launch.call_count, 1)
            comp.desktop["windows"] = [window("3")]
            recovery.tick(5)
            self.assertEqual(recovery.matches, {"1": "3"})
            recovery.tick(7)
            self.assertEqual(launch.call_count, 2)
            comp.desktop["windows"].append(window("4"))
            recovery.tick(8)
            self.assertEqual(recovery.tick(11), "complete")
            self.assertEqual(recovery.matches, {"1": "3", "2": "4"})
            self.assertEqual(launch.call_count, 2)

    def test_generations_are_time_spaced(self):
        def at(stamp, address):
            return dict(record(window(address)), saved_at=stamp)
        def generations():
            return [self.store.load(name)["saved_at"] if (self.root / (name[1:] + ".json")).exists() else None
                    for name in ("@previous-1", "@previous-2", "@previous-3")]
        self.store.checkpoint(at(0, "1"))
        self.store.checkpoint(at(30, "2"))  # nothing to lose yet: promote
        self.assertEqual(generations(), [0, None, None])
        self.store.checkpoint(at(200, "3"))  # outgoing latest (30) is too close to previous-1
        self.assertEqual(generations(), [0, None, None])
        self.store.checkpoint(at(205, "4"))  # outgoing latest (200) is far enough: promote
        self.assertEqual(generations(), [200, 0, None])
        self.store.checkpoint(at(206, "5"))  # a close-all storm within seconds cannot flush it
        self.store.checkpoint(at(207, "6"))
        self.assertEqual(generations(), [200, 0, None])
        self.assertEqual(self.store.load()["saved_at"], 207)
        self.store.checkpoint(at(400, "7"))
        self.store.checkpoint(at(401, "8"))
        self.assertEqual(generations(), [400, 200, 0])

    def test_startup_survives_corrupt_status_and_missing_recovery_source(self):
        comp = FakeCompositor(record(window("1"))["desktop"])
        (self.root / "status.json").write_text("{bad")
        daemon = Service(self.store, comp, Launchers())
        daemon.startup()
        self.assertEqual(daemon.mode, "watching")
        self.assertIsNotNone(self.store.load())
        (self.root / "status.json").write_text(json.dumps({"mode": "partial", "instance": "old"}))
        restarted = Service(self.store, comp, Launchers())
        restarted.startup()
        self.assertEqual(restarted.mode, "watching")
        self.assertIn("recovery source unavailable", restarted.error)

    def test_failed_restore_keeps_serving_and_retries_from_protected_source(self):
        self.store.checkpoint(record(window("1")))
        comp = FakeCompositor(record()["desktop"])
        calls = comp.call
        def failing(method, value):
            if method == "prepare":
                raise RuntimeError("compositor query failed")
            return calls(method, value)
        comp.call = failing
        daemon = Service(self.store, comp, Launchers())
        daemon.startup()
        self.assertEqual(daemon.mode, "partial")
        self.assertIn("compositor query failed", daemon.error)
        self.assertEqual(daemon.command({"command": "freeze"})["saved"], False)
        comp.call = calls
        daemon.command({"command": "restore"})
        self.assertEqual(daemon.mode, "restoring")
        self.assertEqual(daemon.recovery.record, self.store.load())

    def test_finish_warnings_reach_the_report(self):
        saved = record(window("1"))
        comp = FakeCompositor(saved["desktop"])
        def call(method, value):
            comp.calls.append((method, value))
            return {"warnings": ["workspace 1: window order not restored"]} if method == "finish" else True
        comp.call = call
        recovery = Recovery(saved, comp, Launchers(), 0, lambda value: None)
        self.assertEqual(recovery.tick(3), "restoring")
        self.assertEqual(recovery.tick(5), "complete")
        self.assertIn("workspace 1: window order not restored", recovery.report()["limitations"])

    def power_action(self, command="logout"):
        fake_bin = self.root / "bin"
        fake_bin.mkdir(exist_ok=True)
        for tool in ("omarchy", "notify-send"):
            script = fake_bin / tool
            script.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" >> "$HYPERTILE_TEST_LOG.' + tool + '"\n')
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                   XDG_RUNTIME_DIR=str(self.root), XDG_STATE_HOME=str(self.root), XDG_CONFIG_HOME=str(self.root),
                   HYPERTILE_TEST_LOG=str(self.root / "log"))
        service = Path(__file__).resolve().parents[1] / "session" / "service.py"
        return subprocess.run([sys.executable, str(service), command], env=env, capture_output=True, text=True)

    def test_power_action_proceeds_and_warns_when_the_service_is_down(self):
        result = self.power_action()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "log.omarchy").read_text().split(), ["system", "logout"])
        self.assertIn("not saved", (self.root / "log.notify-send").read_text())

    def test_power_action_proceeds_when_the_config_is_malformed(self):
        config = self.root / "hypertile" / "session.json"
        config.parent.mkdir(parents=True)
        for body in ("{", "[]", '{"enabled": false'):
            config.write_text(body)
            (self.root / "log.omarchy").unlink(missing_ok=True)
            result = self.power_action("reboot")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.root / "log.omarchy").read_text().split(), ["system", "reboot"], body)

    def test_disabled_power_actions_do_not_warn_or_save(self):
        config = self.root / "hypertile/session.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"enabled":false}')
        for command in ("logout", "reboot", "shutdown"):
            (self.root / "log.omarchy").unlink(missing_ok=True)
            result = self.power_action(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.root / "log.omarchy").read_text().split(), ["system", command])
            self.assertFalse((self.root / "log.notify-send").exists())

    def test_chromium_app_windows_get_a_web_app_recipe(self):
        from service import Launchers as RealLaunchers
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root), "XDG_DATA_DIRS": str(self.root)}):
            launchers = RealLaunchers({})
        with patch("service.shutil.which", return_value="/usr/bin/omarchy-launch-webapp"):
            recipe = launchers.recipe(window("1", "Home / X", "chrome-x.com__-Default"))
            self.assertEqual(recipe, {"argv": ["omarchy-launch-webapp", "https://x.com/", "--profile-directory=Default"], "per_window": True})
            slack = launchers.recipe(window("2", "Slack", "chrome-app.slack.com__client-Profile 2"))
            self.assertEqual(slack["argv"][1:], ["https://app.slack.com/client", "--profile-directory=Profile 2"])
            self.assertIsNone(launchers.recipe(window("3", "odd", "chrome-bad host__-Default")))
        with patch("service.shutil.which", return_value=None):
            with patch("service.Path.read_bytes", return_value=b"/opt/google/chrome/chrome\0--type=main\0"):
                recipe = launchers.recipe(window("4", "Home / X", "chrome-x.com__-Default"))
            self.assertEqual(recipe["argv"], ["/opt/google/chrome/chrome", "--app=https://x.com/", "--profile-directory=Default"])

    def test_invalid_app_configuration_fails_before_capture_with_a_clear_error(self):
        from service import Launchers as RealLaunchers
        for apps in ([], "terminal", 1, None):
            with self.assertRaisesRegex(ValueError, "apps must be an object"):
                RealLaunchers({"apps": apps})
        for recipe in ([], "terminal", True, {}, {"argv": []}, {"argv": [1]},
                       {"argv": [""]}, {"argv": ["bad\0command"]}, {"argv": ["terminal"], "per_window": "yes"}):
            with self.assertRaisesRegex(ValueError, "apps.terminal"):
                RealLaunchers({"apps": {"terminal": recipe}})
        with patch.dict(os.environ, XDG_DATA_HOME=str(self.root), XDG_DATA_DIRS=str(self.root)):
            disabled = RealLaunchers({"apps": {"terminal": False}})
            self.assertIsNone(disabled.recipe(window("1")))
            explicit = RealLaunchers({"apps": {"terminal": {"argv": ["terminal", ""]}}})
            self.assertEqual(explicit.recipe(window("1"))["argv"], ["terminal", ""])

    def test_bad_session_config_daemon_exits_cleanly_and_preserves_checkpoints(self):
        config = self.root / "hypertile/session.json"
        config.parent.mkdir(exist_ok=True)
        for body, message in (("[]", "configuration must be an object"),
                              ('{"apps":[]}', "apps must be an object")):
            config.write_text(body)
            env = dict(os.environ, XDG_CONFIG_HOME=str(self.root), HYPRLAND_INSTANCE_SIGNATURE="test-bad-config")
            entry = Path(__file__).resolve().parents[1] / "session/service.py"
            result = subprocess.run([sys.executable, str(entry), "daemon"], env=env, capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 1)
            self.assertIn(message, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((self.root / "hypertile/sessions/latest.json").exists())

    def test_retry_uses_a_builtin_recipe_the_snapshot_lacked(self):
        saved = record(dict(window("1", "Home / X", "chrome-x.com__-Default"), launch=None))
        comp = FakeCompositor(record()["desktop"])
        class Rescuing(Launchers):
            def recipe(self, window):
                return {"argv": ["omarchy-launch-webapp", "https://x.com/"], "per_window": True}
        recovery = Recovery(saved, comp, Rescuing(), 0, lambda value: None)
        with patch("service.subprocess.Popen") as launch:
            recovery.tick(4)
            self.assertEqual(launch.call_args[0][0], ["omarchy-launch-webapp", "https://x.com/"])

    def test_self_restoring_apps_launch_together_and_missing_recipes_do_not_wait_for_the_deadline(self):
        saved = record(window("1", "a", "chrome"), window("2", "b", "cursor"), window("3", "Home / X", "chrome-x.com__-Default"))
        for w in saved["desktop"]["windows"][:2]:
            w["launch"] = {"argv": [w["class"]], "per_window": False}
        saved["desktop"]["windows"][2]["launch"] = None
        comp = FakeCompositor(record()["desktop"])
        recovery = Recovery(saved, comp, Launchers(), 0, lambda value: None)
        with patch("service.subprocess.Popen") as launch:
            self.assertEqual(recovery.tick(0.5), "restoring")
            self.assertEqual(launch.call_count, 0)  # grace period
            self.assertEqual(recovery.tick(1), "restoring")
            self.assertEqual([c[0][0] for c in launch.call_args_list], [["chrome"], ["cursor"]])
            comp.desktop["windows"] = [window("4", "a", "chrome"), window("5", "b", "cursor")]
            self.assertEqual(recovery.tick(2), "restoring")
            # Settled: the rest has no recipe, which no retry could change, so
            # the restore is complete and saving resumes.
            self.assertEqual(recovery.tick(4), "complete")
            self.assertLess(4, recovery.deadline)
        report = recovery.report()
        self.assertEqual(report["matched"], 2)
        self.assertEqual(report["unmatched"], [{"class": "chrome-x.com__-Default", "title": "Home / X", "reason": "no launch recipe"}])

    def test_a_failed_launch_still_ends_partial(self):
        saved = record(window("1", "a", "chrome"), window("2", "b", "cursor"))
        saved["desktop"]["windows"][0]["launch"] = {"argv": ["chrome"], "per_window": False}
        saved["desktop"]["windows"][1]["launch"] = {"argv": ["cursor"], "per_window": False}
        comp = FakeCompositor(record()["desktop"])
        recovery = Recovery(saved, comp, Launchers(), 0, lambda value: None)
        with patch("service.subprocess.Popen", side_effect=[OSError("cursor: not found"), None]) as launch:
            self.assertEqual(recovery.tick(1), "restoring")
            self.assertEqual(launch.call_count, 2)
            comp.desktop["windows"] = [window("4", "b", "cursor")]
            self.assertEqual(recovery.tick(2), "restoring")
            self.assertEqual(recovery.tick(4), "partial")  # a retry can still launch chrome
        report = recovery.report()
        self.assertEqual([w["reason"] for w in report["unmatched"]], ["launch failed"])

    def test_terminal_recipes_read_threaded_children_and_replay_only_listed_jobs(self):
        from service import Launchers as RealLaunchers
        proc = self.root / "proc"
        def process(pid, argv, cwd, threads=(), children="", tpgid=None):
            base = proc / str(pid)
            tids = threads or (pid,)
            for tid in tids:
                (base / "task" / str(tid)).mkdir(parents=True)
                (base / "task" / str(tid) / "children").write_text(children if tid == tids[-1] else "")
            (base / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
            (base / "cwd").symlink_to(cwd)
            (base / "stat").write_text(f"{pid} ({argv[0]} x) S 1 {pid} {pid} 0 {tpgid or pid} 0 0\n")
        process(100, ["ghostty"], "/home", threads=(100, 101, 102), children="200")
        process(200, ["/usr/bin/bash", "--posix"], "/home/me/project", tpgid=300)
        process(300, ["herdr", "--session", "work"], "/home/me/project")
        process(110, ["foot"], "/home", children="210")
        process(210, ["bash"], "/tmp/build", tpgid=310)
        process(310, ["make", "all"], "/tmp/build")
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root), "XDG_DATA_DIRS": str(self.root)}):
            plain = RealLaunchers({}, proc=proc)
            replaying = RealLaunchers({"replay": ["herdr"]}, proc=proc)
            making = RealLaunchers({"replay": ["make"]}, proc=proc)
            with self.assertRaises(ValueError):
                RealLaunchers({"replay": "herdr"}, proc=proc)
        ghostty = dict(window("1", "~", "com.mitchellh.ghostty"), pid=100)
        self.assertEqual(plain.recipe(ghostty)["argv"], ["ghostty", "--working-directory=/home/me/project"])
        self.assertEqual(replaying.recipe(ghostty)["argv"],
                         ["ghostty", "--working-directory=/home/me/project", "-e", "herdr", "--session", "work"])
        foot = dict(window("2", "make", "foot"), pid=110)
        self.assertEqual(replaying.recipe(foot)["argv"], ["foot", "--working-directory=/tmp/build"])
        self.assertEqual(making.recipe(foot)["argv"], ["foot", "--working-directory=/tmp/build", "make", "all"])


if __name__ == "__main__":
    unittest.main()
