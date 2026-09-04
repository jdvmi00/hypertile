"""Regression checks for data loss and duplicate/incorrect restoration."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "session"))
from service import Recovery, Service, Store, match_windows


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

    def test_power_action_proceeds_and_warns_when_the_service_is_down(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        for tool in ("omarchy", "notify-send"):
            script = fake_bin / tool
            script.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" >> "$HYPERTILE_TEST_LOG.' + tool + '"\n')
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                   XDG_RUNTIME_DIR=str(self.root), XDG_STATE_HOME=str(self.root), XDG_CONFIG_HOME=str(self.root),
                   HYPERTILE_TEST_LOG=str(self.root / "log"))
        service = Path(__file__).resolve().parents[1] / "session" / "service.py"
        result = subprocess.run([sys.executable, str(service), "logout"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "log.omarchy").read_text().split(), ["system", "logout"])
        self.assertIn("not saved", (self.root / "log.notify-send").read_text())

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


if __name__ == "__main__":
    unittest.main()
