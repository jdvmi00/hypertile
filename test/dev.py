"""Developer deployment boundaries: preserve checkouts, reload selectively, fail safely."""
import fcntl
from contextlib import redirect_stdout
import importlib.machinery
import importlib.util
import json
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("hypertile_dev", str(REPO / "dev"))
spec = importlib.util.spec_from_loader(loader.name, loader)
dev = importlib.util.module_from_spec(spec)
loader.exec_module(dev)


class DevTests(unittest.TestCase):
    def setUp(self):
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        temporary = tempfile.TemporaryDirectory(prefix="hypertile dev ")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root, self.config, self.state = base / "source", base / "config", base / "state"
        self.root.mkdir()
        for directory in ("bin", "plugin", "session", "layouts"):
            (self.root / directory).mkdir()
        for name, content in {
            "hypertile.lua": "return {}\n", "bin/hypertile-ctl": "return true\n",
            "bin/hypertile-session": "pass\n", "session/service.py": "pass\n",
            "plugin/Overlay.qml": "import QtQuick\nItem {}\n",
            "manifest.json": '{"schemaVersion":1}',
        }.items():
            (self.root / name).write_text(content)
        shutil.copy2(REPO / "dev", self.root / "dev")
        self.plugin = self.config / "omarchy/plugins/jmartin.hypertile"
        self.plugin.parent.mkdir(parents=True)
        hypr = self.config / "hypr"
        hypr.mkdir()
        (hypr / "hyprland.lua").write_text('require("hypr.hypertile-layouts")\n')
        env = dict(dev.ENV, HYPRLAND_INSTANCE_SIGNATURE="test-instance")
        constants = patch.multiple(dev, ROOT=self.root, CONFIG=self.config, STATE=self.state,
                                   DATA=base / "data", PLUGIN=self.plugin, BIN=base / "bin", ENV=env)
        constants.start()
        self.addCleanup(constants.stop)
        self.commands, self.errors, self.running = [], "", False
        writer = self.state / "sessions/writer.lock"
        writer.parent.mkdir(parents=True)
        self.writer = writer.open("a")
        self.addCleanup(self.writer.close)
        original_run = dev.run
        def run(*argv, **kwargs):
            words = [str(a) for a in argv]
            self.commands.append(words)
            output, code = "", 0
            if words[0] == "lua" or words[0].endswith("qmlformat"):
                return original_run(*argv, **kwargs)
            if words[0].endswith("hypertile-session"):
                if words[1] == "status":
                    output = json.dumps({"mode": "watching", "instance": "test-instance"})
                    code = 0 if self.running else 1
                elif words[1] == "stop":
                    fcntl.flock(self.writer, fcntl.LOCK_UN)
                    self.running = False
            if words[:2] == ["hyprctl", "getoption"]:
                output = '{"bool":false}'
            if words[:2] == ["hyprctl", "configerrors"]:
                output = self.errors
            if words[:2] == ["hyprctl", "eval"] and "hl.exec_cmd" in words[2]:
                # This fails if dev tries to start before releasing its lock.
                fcntl.flock(self.writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.running = True
            return subprocess.CompletedProcess(words, code, output, "")
        runner = patch.object(dev, "run", side_effect=run)
        runner.start()
        self.addCleanup(runner.stop)

    def test_link_preserves_dirty_checkout_and_is_idempotent(self):
        (self.plugin / ".git").mkdir(parents=True)
        (self.plugin / ".git/HEAD").write_text("original HEAD")
        (self.plugin / "untracked.txt").write_text("local work")
        dev.link()
        backups = list((self.state / "dev/backups").glob("plugin-*/jmartin.hypertile"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "untracked.txt").read_text(), "local work")
        self.assertEqual((backups[0] / ".git/HEAD").read_text(), "original HEAD")
        self.assertEqual(self.plugin.resolve(), self.root)
        dev.link()
        self.assertEqual(len(list((self.state / "dev/backups").iterdir())), 1)

    def test_incremental_apply_restarts_only_affected_components(self):
        self.plugin.symlink_to(self.root)
        self.running = True
        fcntl.flock(self.writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        dev.apply(False)
        self.assertTrue(any(c[-1:] == ["stop"] for c in self.commands))
        self.assertTrue(self.running)
        self.commands.clear()
        dev.apply(False)
        self.assertNotIn(["hyprctl", "reload"], self.commands)
        self.assertNotIn(["omarchy", "restart", "shell"], self.commands)
        (self.root / "bin/hypertile-ctl").write_text("-- edited CLI\nreturn true\n")
        dev.apply(False)
        self.assertEqual((dev.BIN / "hypertile-ctl").read_text(), "-- edited CLI\nreturn true\n")
        self.assertFalse(any(c[-1:] == ["stop"] or c[:2] == ["hyprctl", "reload"] for c in self.commands))
        self.commands.clear()
        (self.root / "plugin/Overlay.qml").write_text("import QtQuick\nItem { width: 100 }\n")
        dev.apply(False)
        self.assertIn(["omarchy", "restart", "shell"], self.commands)
        self.assertNotIn(["hyprctl", "reload"], self.commands)
        self.commands.clear()
        (self.root / "session/service.py").write_text("# new service\npass\n")
        dev.apply(False)
        self.assertTrue(any(c[-1:] == ["stop"] for c in self.commands))
        self.assertTrue(self.running)
        self.assertNotIn(["hyprctl", "reload"], self.commands)
        self.assertNotIn(["omarchy", "restart", "shell"], self.commands)

    def test_invalid_source_and_failed_reload_never_record_success(self):
        self.plugin.symlink_to(self.root)
        dev.apply(False)
        before = dev.receipt()
        original = (dev.DATA / "hypertile/session/service.py").read_bytes()
        (self.root / "session/service.py").write_text("def broken(\n")
        self.commands.clear()
        with self.assertRaises(SyntaxError):
            dev.apply(False)
        self.assertEqual(dev.receipt(), before)
        self.assertEqual((dev.DATA / "hypertile/session/service.py").read_bytes(), original)
        self.assertFalse(any(c[-1:] == ["stop"] for c in self.commands))
        (self.root / "session/service.py").write_bytes(original)
        (self.root / "hypertile.lua").write_text("-- runtime error fixture\nreturn {}\n")
        self.errors = "bad config"
        with self.assertRaisesRegex(RuntimeError, "bad config"):
            dev.apply(False)
        self.assertEqual(dev.receipt(), before)
        self.assertEqual(self.commands[-1], ["hyprctl", "eval", "hl.config({misc={disable_autoreload=false}})"])
        self.assertIn("lua", dev.pending(dev.groups(), dev.fingerprints(dev.groups())))
        saved = list((self.state / "dev/backups").glob("runtime-*/hypertile.lua"))
        self.assertTrue(any(path.read_text() == "return {}\n" for path in saved))


if __name__ == "__main__":
    unittest.main()
