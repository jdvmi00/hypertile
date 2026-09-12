"""Exercise install/uninstall in isolated homes, with no desktop access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hypertile install ")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / "config"
        self.data = self.home / "data"
        self.state = self.home / "state"
        self.hypr = self.config / "hypr"
        self.hypr.mkdir(parents=True)
        self.main = self.hypr / "hyprland.lua"
        self.main.write_text('require("hypr.bindings")\nrequire("hypr.looknfeel")\n')
        self.bindings = self.hypr / "bindings.lua"
        self.bindings.write_text('-- user bindings\no.bind("SUPER + T", "Terminal", "terminal")\n')
        self.menu = self.config / "omarchy/extensions/omarchy-menu.jsonc"
        self.menu.parent.mkdir(parents=True)
        self.menu.write_text('{\n  "custom": {"action":"keep-me"}\n}\n')
        self.tools = self.home / "tools"
        self.tools.mkdir()
        # A whitelist prevents accidentally calling the real shell/compositor.
        for command in ("bash", "lua", "jq", "python3", "flock", "mkdir", "cp",
                        "basename", "dirname", "find", "rm", "cat", "sha256sum", "cut", "grep", "sed"):
            executable = shutil.which(command)
            self.assertIsNotNone(executable, f"missing test dependency: {command}")
            (self.tools / command).symlink_to(executable)
        # Simulate a watched-file reload at every Lua install, checking that
        # every daemon entry point and Python module is already the new version.
        installer = self.tools / "install"
        installer.write_text('''#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
root = Path(os.environ["TEST_SOURCE"])
destination = Path(sys.argv[-1])
if destination.parent == Path(os.environ["XDG_CONFIG_HOME"]) / "hypr":
    for source in (root / "bin").glob("hypertile-*"):
        target = Path(os.environ["HOME"]) / ".local/bin" / source.name
        assert target.read_bytes() == source.read_bytes(), str(target)
    for service in ("session", "scenes"):
        for source in (root / service).glob("*.py"):
            target = Path(os.environ["XDG_DATA_HOME"]) / "hypertile" / service / source.name
            assert target.read_bytes() == source.read_bytes(), str(target)
sys.exit(subprocess.call([os.environ["TEST_INSTALL"], *sys.argv[1:]]))
''')
        installer.chmod(0o755)
        self.env = {
            "HOME": str(self.home), "PATH": str(self.tools), "LC_ALL": "C.UTF-8",
            "XDG_CONFIG_HOME": str(self.config), "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.state), "XDG_RUNTIME_DIR": str(self.home / "run"),
            "TEST_SOURCE": str(ROOT), "TEST_INSTALL": shutil.which("install"),
        }
        (self.home / "run").mkdir()

    def run_script(self, script, *args, success=True):
        result = subprocess.run([str(ROOT / script), *args], env=self.env, cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def backup(self, path):
        return Path(str(path) + ".hypertile.bak")

    def plugin_checkout(self):
        plugin = self.config / "omarchy/plugins/jmartin.hypertile"
        shutil.copytree(ROOT, plugin, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "docs", "test", "preview.png", "probe.log"))
        (plugin / ".git").mkdir()
        self.env["TEST_SOURCE"] = str(plugin)
        return plugin

    def test_automatic_setup_keeps_shell_placement_and_skips_unchanged_runtime(self):
        plugin = self.plugin_checkout()
        shell = self.config / "omarchy/shell.json"
        shell.write_text('{"bar":{"layout":{"right":[{"id":"jmartin.hypertile"}]}}}\n')
        # Any attempt to manage the shell during automatic setup is a bug.
        for name in ("omarchy", "omarchy-shell", "omarchy-plugin-enable", "omarchy-plugin-disable"):
            command = self.tools / name
            command.write_text('#!/usr/bin/env bash\necho unexpected-shell-call >>"$HOME/shell-calls"\nexit 1\n')
            command.chmod(0o755)
        original = shell.read_bytes()
        self.run_script(plugin / "install.sh", "--automatic")
        self.assertEqual(list((self.hypr / "layouts").iterdir()), [])
        runtime = self.hypr / "hypertile.lua"
        stamp = runtime.stat().st_mtime_ns
        # A no-op must not even query/stop the running services.
        entry = self.home / ".local/bin/hypertile-session"
        entry.write_text('#!/usr/bin/env bash\necho unexpected-service-call >>"$HOME/service-calls"\nexit 1\n')
        self.run_script(plugin / "install.sh", "--automatic")
        self.assertEqual(runtime.stat().st_mtime_ns, stamp)
        self.assertEqual(shell.read_bytes(), original)
        self.assertFalse((self.home / "shell-calls").exists())
        self.assertFalse((self.home / "service-calls").exists())
        self.assertFalse(list(plugin.rglob("__pycache__")))

    def test_automatic_update_preserves_layouts_and_manual_opt_outs(self):
        plugin = self.plugin_checkout()
        originals = {p: p.read_bytes() for p in (self.bindings, self.menu)}
        self.run_script(plugin / "install.sh", "--no-menu", "--no-keybinds")
        self.assertEqual(list((self.hypr / "layouts").iterdir()), [])
        layout = self.hypr / "layouts/quad.lua"
        layout.write_text('-- my layout\n')
        source = plugin / "hypertile.lua"
        source.write_text(source.read_text() + '\n-- updated engine\n')
        self.run_script(plugin / "install.sh", "--automatic")
        self.assertEqual((self.hypr / source.name).read_bytes(), source.read_bytes())
        self.assertEqual(layout.read_text(), '-- my layout\n')
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_automatic_failure_can_retry_and_uninstall_clears_receipt(self):
        receipt = self.state / "hypertile/installed-runtime.sha256"
        command = self.tools / "hyprctl"
        command.write_text('#!/usr/bin/env bash\n[[ "$1" != configerrors ]] || echo "bad config"\n')
        command.chmod(0o755)
        self.run_script("install.sh", "--automatic", success=False)
        self.assertFalse(receipt.exists())
        command.unlink()
        self.run_script("install.sh", "--automatic")
        self.assertTrue(receipt.exists())
        self.run_script("uninstall.sh")
        self.assertFalse(receipt.exists())

    def test_concurrent_automatic_loads_install_once(self):
        command = [str(ROOT / "install.sh"), "--automatic"]
        first = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        outputs = []
        for process in (first, second):
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            outputs.append(stdout)
        self.assertEqual(sum('installed. try:' in output for output in outputs), 1)

    def test_automatic_setup_leaves_development_links_to_dev_apply(self):
        plugin = self.config / "omarchy/plugins/jmartin.hypertile"
        plugin.parent.mkdir(parents=True)
        plugin.symlink_to(ROOT, target_is_directory=True)
        self.run_script("install.sh", "--automatic")
        self.assertFalse((self.hypr / "hypertile.lua").exists())

    @unittest.skipUnless(shutil.which("qs"), "Quickshell is needed for the service integration test")
    def test_enabled_service_installs_runtime_and_reports_failures(self):
        plugin = self.plugin_checkout()
        manifest = json.loads((plugin / "manifest.json").read_text())
        self.assertIn("service", manifest["kinds"])
        service_url = (plugin / manifest["entryPoints"]["service"]).as_uri()
        harness = self.home / "shell.qml"
        harness.write_text('''import QtQuick
import Quickshell
ShellRoot {
  property var service: null
  Component.onCompleted: {
    var component = Qt.createComponent(%s)
    if (component.status !== Component.Ready) throw new Error(component.errorString())
    service = component.createObject(null)
  }
  Timer {
    interval: 50; running: true; repeat: true
    onTriggered: {
      if (service && (service.ready || service.error !== "")) {
        console.log(service.ready ? "SETUP_READY" : "SETUP_FAILED: " + service.error)
        Qt.quit()
      }
    }
  }
}
''' % json.dumps(service_url))
        environment = dict(self.env, QT_QPA_PLATFORM="offscreen")
        # Quickshell must not see the live desktop's D-Bus or Wayland socket.
        environment["XDG_RUNTIME_DIR"] = str(self.home / "run")
        os.chmod(environment["XDG_RUNTIME_DIR"], 0o700)
        def load_service():
            result = subprocess.run([shutil.which("qs"), "--no-color", "-p", str(harness)],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout + result.stderr
        self.assertIn("SETUP_READY", load_service())
        self.assertTrue((self.hypr / "hypertile.lua").exists())
        self.assertTrue((self.home / ".local/bin/hypertile-ctl").is_file())
        self.assertIn('require("hypr.hypertile-layouts")', self.main.read_text())
        self.assertFalse(list(plugin.rglob("__pycache__")))
        stamp = (self.hypr / "hypertile.lua").stat().st_mtime_ns
        self.assertIn("SETUP_READY", load_service())
        self.assertEqual((self.hypr / "hypertile.lua").stat().st_mtime_ns, stamp)
        self.main.unlink()
        self.assertIn("SETUP_FAILED", load_service())
        self.assertIn("hyprland.lua not found", (self.state / "hypertile/install.log").read_text())

    def test_original_backups_survive_repeat_install_and_uninstall(self):
        originals = {path: path.read_bytes() for path in (self.main, self.bindings, self.menu)}
        self.run_script("install.sh")
        installed = {path: path.read_bytes() for path in originals}
        self.run_script("install.sh")
        self.assertEqual(installed, {path: path.read_bytes() for path in originals})
        self.run_script("uninstall.sh")
        self.run_script("uninstall.sh")
        for path, original in originals.items():
            self.assertEqual(self.backup(path).read_bytes(), original)
        self.assertEqual(self.main.read_bytes(), originals[self.main])
        self.assertEqual(self.bindings.read_bytes().rstrip(), originals[self.bindings].rstrip())
        self.assertEqual(json.loads(self.menu.read_text()), json.loads(originals[self.menu]))
        self.assertFalse((self.hypr / "hypertile-navigation.lua").exists())

    def test_marked_blocks_without_original_newline_and_with_internal_blanks(self):
        original = self.bindings.read_text().rstrip()
        self.bindings.write_text(original)
        self.run_script("install.sh")
        text = self.bindings.read_text().replace(
            'require("hypr.hypertile-navigation").bind()',
            '\nrequire("hypr.hypertile-navigation").bind()\n')
        text += 'o.bind("SUPER + U", "User", "keep-me")\n'
        self.bindings.write_text(text)
        self.run_script("uninstall.sh")
        remaining = [line for line in self.bindings.read_text().splitlines() if line]
        self.assertEqual(remaining, original.splitlines() + ['o.bind("SUPER + U", "User", "keep-me")'])
        self.assertEqual(self.backup(self.bindings).read_text(), original)

    def test_reinstall_with_session_recovery_disabled_and_no_daemon(self):
        self.run_script("install.sh")
        config = self.config / "hypertile/session.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"enabled": false}\n')
        self.run_script("install.sh")
        self.assertEqual(json.loads(config.read_text()), {"enabled": False})

    def test_disabled_config_still_requires_stopping_a_live_session(self):
        self.run_script("install.sh")
        config = self.config / "hypertile/session.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"enabled": false}\n')
        entry = self.home / ".local/bin/hypertile-session"
        for mode in ("watching", "disabled"):
            entry.write_text('''#!/usr/bin/env bash
if [[ "$1" == status ]]; then
  echo '{"instance":"test","mode":"%s"}'
else
  echo 'session stop refused' >&2
  exit 1
fi
''' % mode)
            before = entry.read_bytes()
            result = self.run_script("install.sh", success=False)
            self.assertIn("session stop refused", result.stderr)
            self.assertEqual(entry.read_bytes(), before)

    def test_legacy_blocks_with_internal_blanks_keep_adjacent_user_lines(self):
        original = self.bindings.read_text().rstrip()
        self.bindings.write_text(original + '''
-- hypertile: focus and swap across gaps, replacing Omarchy's directional bindings.

require("hypr.hypertile-navigation").bind()
-- hypertile: fullscreen layout overlay (browse with arrows, Enter uses and closes).
o.bind("SUPER + ALT + L", "Layouts overlay", "omarchy-shell shell toggle jmartin.hypertile")
-- hypertile: cycle the workspace through every saved layout, then dwindle.
-- The shell flashes the new layout's name.

hl.unbind("SUPER + L")
o.bind("SUPER + L", "Toggle workspace layout", "hypertile-ctl cycle")
-- hypertile: cycle the other way.
o.bind("SUPER + SHIFT + L", "Toggle workspace layout (back)", "hypertile-ctl cycle --reverse")
-- my own adjacent binding
o.bind("SUPER + U", "User", "keep-me")
''')
        self.run_script("install.sh")
        self.run_script("uninstall.sh")
        self.assertEqual(self.bindings.read_text(), original + '\n-- my own adjacent binding\n'
                         'o.bind("SUPER + U", "User", "keep-me")\n')

    def test_custom_navigation_reference_retains_runtime_until_removed(self):
        self.run_script("install.sh")
        with self.bindings.open("a") as stream:
            stream.write('local navigation = require("hypr.hypertile-navigation")\n')
        result = self.run_script("uninstall.sh", "--purge", success=False)
        self.assertIn("still references hypertile-navigation; runtime files retained", result.stderr)
        for name in ("hypertile-navigation.lua", "hypertile-session.lua", "hypertile.lua"):
            self.assertTrue((self.hypr / name).exists())
        self.assertTrue((self.hypr / "layouts").exists())
        self.bindings.write_text('-- user removed custom navigation binding\n')
        self.run_script("uninstall.sh")
        self.assertFalse((self.hypr / "hypertile-navigation.lua").exists())

    def test_incomplete_marker_keeps_navigation_runtime(self):
        self.run_script("install.sh")
        self.bindings.write_text(self.bindings.read_text().replace('-- hypertile: end\n', '', 1))
        self.run_script("uninstall.sh", success=False)
        self.assertTrue((self.hypr / "hypertile-navigation.lua").exists())

    def test_menu_power_guards_alone_preserve_original_backup_and_custom_action(self):
        self.menu.write_text('''{
  "layouts": {"action":"omarchy-shell shell toggle jmartin.hypertile"},
  "system.logout": {"action":"custom-logout"}
}
''')
        original = self.menu.read_bytes()
        self.run_script("install.sh")
        self.assertEqual(self.backup(self.menu).read_bytes(), original)
        self.assertEqual(json.loads(self.menu.read_text())["system.logout"]["action"], "custom-logout")
        self.run_script("uninstall.sh")
        self.assertEqual(json.loads(self.menu.read_text()), {"system.logout": {"action": "custom-logout"}})

    def test_power_menu_entries_keep_names_and_icons_on_install_and_upgrade(self):
        expected = {
            "logout": ("󰍃", "Logout"),
            "reboot": ("󰜉", "Reboot"),
            "shutdown": ("󰐥", "Shutdown"),
        }
        # Exercise both a fresh install and migration of the old action-only
        # overrides, including whitespace from a manually formatted JSON file.
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                menu = {"custom": {"action": "keep-me"}}
                if legacy:
                    menu.update({"system." + action: {"action": "hypertile-ctl session " + action}
                                 for action in expected})
                self.menu.write_text(json.dumps(menu, indent=2) + '\n')
                self.run_script("install.sh", "--automatic")
                installed = json.loads(self.menu.read_text())
                for action, (icon, label) in expected.items():
                    self.assertEqual(installed["system." + action], {
                        "icon": icon, "label": label, "action": "hypertile-ctl session " + action})
                self.run_script("uninstall.sh")
                self.assertEqual(json.loads(self.menu.read_text()), {"custom": {"action": "keep-me"}})

    def test_power_menu_custom_names_and_icons_survive_install(self):
        custom = {"icon": "custom-icon", "label": "Restart my desktop",
                  "action": "hypertile-ctl session reboot", "description": "My custom entry"}
        self.menu.write_text(json.dumps({"system.reboot": custom}, indent=2) + '\n')
        self.run_script("install.sh")
        self.assertEqual(json.loads(self.menu.read_text())["system.reboot"], custom)

    def test_options_leave_menu_and_bindings_untouched(self):
        originals = {path: path.read_bytes() for path in (self.bindings, self.menu)}
        self.run_script("install.sh", "--no-menu", "--no-keybinds")
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(self.backup(path).exists())

    def test_upgrade_finishes_runtime_before_any_watched_lua_copy(self):
        self.run_script("install.sh")
        for service in ("session", "scenes"):
            for source in (ROOT / service).glob("*.py"):
                (self.data / "hypertile" / service / source.name).write_text("# stale runtime\n")
            executable = self.home / ".local/bin" / ("hypertile-" + service)
            executable.write_text('#!/usr/bin/env bash\necho \'{"instance":"test","mode":"watching"}\'\n')
        self.run_script("install.sh")

    def test_purge_removes_scenes_and_caches_only_when_requested(self):
        self.run_script("install.sh")
        saved = [self.config / "hypertile/scenes.json",
                 self.state / "hypertile/sessions/current.json"]
        caches = [self.data / "hypertile" / service / "__pycache__/old.pyc"
                  for service in ("session", "scenes")]
        unrelated = self.config / "hypertile/session.json"
        for path in [*saved, *caches, unrelated]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}')
        self.run_script("uninstall.sh")
        self.assertTrue(all(path.exists() for path in [*saved, *caches]))
        self.run_script("uninstall.sh", "--purge")
        self.assertTrue(all(not path.exists() for path in [*saved, *caches]))
        self.assertFalse((self.hypr / "layouts").exists())
        self.assertEqual(unrelated.read_text(), '{}')


if __name__ == "__main__":
    unittest.main()
