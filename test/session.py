"""Regression checks for data loss and duplicate/incorrect restoration."""
import copy
import json
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
