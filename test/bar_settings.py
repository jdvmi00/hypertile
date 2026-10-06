"""Exercise the real settings popup (menu bar placement) and Omarchy registry in an isolated shell.

Requires an installed Omarchy shell and Quickshell. No desktop configuration
is changed. Run with --screenshots DIRECTORY to retain rendered popup images.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--screenshots", type=Path)
args = parser.parse_args()
shell = Path("/usr/share/omarchy/shell")
if not shell.is_dir() or not shutil.which("qs"):
    raise SystemExit("This UI integration check requires Omarchy and Quickshell.")
images = args.screenshots.resolve() if args.screenshots else None
if images:
    images.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix="hypertile-bar-settings-") as directory:
    root = Path(directory)
    for name in ("Commons", "Ui", "services"):
        (root / name).symlink_to(shell / name, target_is_directory=True)
    (root / "plugin").symlink_to(ROOT / "plugin", target_is_directory=True)
    (root / "bin").mkdir()
    (root / "run").mkdir(mode=0o700)
    # Send the production popup's command to this isolated registry.
    command = root / "bin/omarchy-shell"
    command.write_text("#!/bin/sh\nexec qs -p " + str(root) + ' ipc call -- "$@"\n')
    command.chmod(0o755)
    config = dict(version=1, unrelated={"keep": True}, bar=dict(position="top", layout=dict(
        left=[{"id": "omarchy.workspaces"}, {"id": "jmartin.hypertile", "custom": {"keep": 42}}, {"id": "left-neighbor"}],
        center=[{"id": "omarchy.clock"}, {"id": "omarchy.weather"}],
        right=[{"id": "omarchy.tray"}, {"id": "right-neighbor"}])))
    qml = '''import QtQuick
import QtTest
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "services" as Services
import "plugin" as Hypertile
ShellRoot {
  id: harness
  property var config: CONFIG
  property string failure: ""
  property int moves: 0
  function focused(item) {
    if (item.activeFocus && item.Accessible.name) return item.Accessible.name
    for (var i = 0; i < item.children.length; i++) {
      var found = focused(item.children[i]); if (found) return found
    }
    return ""
  }
  function find(item, name) {
    if (item.Accessible.name === name) return item
    for (var i = 0; i < item.children.length; i++) {
      var found = find(item.children[i], name); if (found) return found
    }
    return null
  }
  Services.PluginRegistry {
    id: registry
    shellConfigProvider: function() { return harness.config }
    shellConfigMutator: function(mutate) {
      var next = JSON.parse(JSON.stringify(harness.config)); mutate(next); harness.config = next
      saved.setText(JSON.stringify(next))
    }
  }
  FileView { id: saved; path: CONFIG_PATH }
  QtObject {
    id: shellApi
    readonly property var barConfig: harness.config.bar
  }
  QtObject {
    id: overlay
    property var shell: shellApi
    property var manifest: MANIFEST
    property color foreground: "#f5d2b7"
    property color mutedForeground: "#bba695"
    property color accent: "#ffcba4"
    property color surfaceColor: "#141821"
    property string fontFamily: "JetBrainsMono Nerd Font"
    property int uiFont: 18
    property int uiFontSmall: 14
    property int uiCaption: 12
    property int uiPad: 16
    property int railWidth: 360
    property int radiusCard: 12
    property int radiusControl: 7
    property bool busy: false
    property bool dockLeft: true
    property bool showKeys: false
    property var sessionStatus: ({mode: "watching"})
    property bool sessionAvailable: true
    property bool sessionChecked: true
    property var prefs: []
    function setPref(key, value) { this[key] = value; prefs = prefs.concat([key]) }
    function setSessionEnabled(enabled) { sessionStatus = {mode: enabled ? "watching" : "disabled"} }
    function focusKeys() { backdrop.forceActiveFocus() }
  }
  FloatingWindow {
    id: window
    visible: true
    implicitWidth: 440
    implicitHeight: 900
    color: "#090c12"
    Item { id: backdrop; anchors.fill: parent }
    TestCase { id: input; when: false }
    Hypertile.SettingsPanel { id: popup; overlay: overlay; x: 40; y: 40 }
    BorderSurface {
      id: captureSurface
      visible: false
      width: popup.width; height: popup.height
      color: overlay.surfaceColor
      radius: overlay.radiusCard
      borderSpec: Border.flat(overlay.mutedForeground, 1)
    }
    Component.onCompleted: popup.open()
  }
  IpcHandler {
    target: "shell"
    function moveBarWidget(id: string, placement: string): string {
      harness.moves++
      if (harness.failure) return harness.failure
      var error = registry.moveBarWidget(id, JSON.parse(placement))
      return error || "ok"
    }
  }
  IpcHandler {
    target: "test"
    function state(): string { return JSON.stringify({section:popup.section, busy:popup.busy, error:popup.error, config:harness.config, moves:harness.moves, visible:popup.visible, focus:harness.focused(popup.contentItem), dockLeft:overlay.dockLeft, showKeys:overlay.showKeys, session:overlay.sessionStatus.mode}) }
    function openAt(where: string): void { popup.openAt(where) }
    function choose(section: string): void { popup.choose(section) }
    function key(key: int): void { input.keyClick(key) }
    function click(name: string): void {
      var button = harness.find(popup.contentItem, name)
      input.mouseClick(button, button.width / 2, button.height / 2)
    }
    function outside(): void { input.mouseClick(backdrop, 2, 2) }
    function fail(message: string): void { harness.failure = message }
    function configure(value: string): void { harness.config = JSON.parse(value) }
    function open(): void { popup.open() }
    function close(): void { popup.close() }
    function size(value: int): void { overlay.railWidth = value }
    function capture(path: string): void {
      // Capture the real content over an opaque copy of the popup surface;
      // the C++ popup item itself has no QML engine for grabToImage.
      var content = popup.contentItem, original = content.parent
      content.parent = captureSurface
      captureSurface.visible = true
      captureSurface.grabToImage(function(image) {
        content.parent = original
        captureSurface.visible = false
        popup.focusChoice()
        image.saveToFile(path)
      })
    }
  }
}
'''.replace("CONFIG_PATH", json.dumps(str(root / "saved.json"))).replace("CONFIG", json.dumps(config)).replace("MANIFEST", (ROOT / "manifest.json").read_text())
    (root / "shell.qml").write_text(qml)
    env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / ".config"),
               XDG_STATE_HOME=str(root / ".state"), XDG_RUNTIME_DIR=str(root / "run"),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QPA_PLATFORMTHEME="", QT_STYLE_OVERRIDE="Fusion",
               PATH=str(root / "bin") + os.pathsep + os.environ["PATH"])
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
    with (root / "log").open("w") as log:
        process = subprocess.Popen(["qs", "--no-color", "-p", str(root)], env=env, stdout=log, stderr=log)
        try:
            def ipc(*arguments):
                result = subprocess.run(["qs", "-p", str(root), "ipc", "call", "test", *arguments],
                                        env=env, capture_output=True, text=True, timeout=5)
                if result.returncode:
                    raise RuntimeError(result.stderr or result.stdout)
                return result.stdout

            def wait_for(predicate):
                deadline = time.monotonic() + 8
                state = None
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        state = json.loads(ipc("state"))
                        if predicate(state):
                            return state
                    except (RuntimeError, json.JSONDecodeError):
                        pass
                    time.sleep(.05)
                raise AssertionError(str(state) + "\n" + (root / "log").read_text())

            def capture(name):
                if images:
                    path = images / (name + ".png")
                    path.unlink(missing_ok=True)
                    ipc("capture", str(path))
                    deadline = time.monotonic() + 3
                    while not path.exists() and time.monotonic() < deadline:
                        time.sleep(.05)
                    assert path.exists(), "Screenshot did not render"

            state = wait_for(lambda s: s["visible"] and s["focus"] == "Left")
            assert state["section"] == "left", state
            capture("left")
            # Keyboard focus moves among choices; activation applies, Escape
            # dismisses only the popup and leaves the overlay's focus intact.
            ipc("key", str(0x01000014))  # Right
            wait_for(lambda s: s["focus"] == "Middle")
            ipc("key", str(0x01000005))  # Enter
            wait_for(lambda s: s["section"] == "center" and not s["busy"])
            ipc("key", str(0x01000000))  # Escape
            wait_for(lambda s: not s["visible"])
            ipc("open")
            wait_for(lambda s: s["visible"] and s["focus"] == "Middle")
            ipc("click", "Right")
            wait_for(lambda s: s["section"] == "right" and not s["busy"])
            ipc("outside")
            wait_for(lambda s: not s["visible"])
            ipc("open")
            wait_for(lambda s: s["visible"] and s["focus"] == "Right")
            for section in ("center", "right", "left"):
                ipc("choose", section)
                state = wait_for(lambda s: not s["busy"] and s["section"] == section)
                assert not state["error"], state
                original_others = {key: [v for v in values if v["id"] != "jmartin.hypertile"]
                                   for key, values in config["bar"]["layout"].items()}
                current = state["config"]["bar"]["layout"]
                actual_others = {key: [v for v in values if v["id"] != "jmartin.hypertile"]
                                 for key, values in current.items()}
                assert original_others == actual_others
                entries = [v for values in current.values() for v in values if v["id"] == "jmartin.hypertile"]
                assert entries == [config["bar"]["layout"]["left"][1]]
                assert state["config"]["unrelated"] == config["unrelated"]
                assert json.loads((root / "saved.json").read_text()) == state["config"]
                capture(section)
            moves = state["moves"]
            ipc("choose", "left")
            ipc("choose", "invalid")
            assert json.loads(ipc("state"))["moves"] == moves
            ipc("fail", "could not find widget jmartin.hypertile")
            ipc("choose", "right")
            state = wait_for(lambda s: not s["busy"] and bool(s["error"]))
            assert state["section"] == "left", state
            capture("error")
            ipc("fail", "")
            ipc("choose", "right")
            wait_for(lambda s: not s["busy"] and s["section"] == "right" and not s["error"])
            ipc("close")
            ipc("open")
            wait_for(lambda s: s["visible"] and s["focus"] == "Right")
            ipc("size", "280")
            capture("compact")
            # Follow external moves and vertical bars without a shadow preference.
            vertical = json.loads(json.dumps(config))
            vertical["bar"]["position"] = "right"
            ipc("configure", json.dumps(vertical))
            state = wait_for(lambda s: s["section"] == "left")
            capture("vertical")
            vertical["bar"]["layout"]["left"] = []
            ipc("configure", json.dumps(vertical))
            wait_for(lambda s: s["section"] == "")
            capture("unavailable")
            ipc("choose", "right")
            assert json.loads(ipc("state"))["moves"] == moves + 2
            # The gear opens the panel at the top; the other settings act on the overlay.
            ipc("configure", json.dumps(config))
            wait_for(lambda s: s["section"] != "")
            ipc("close")
            ipc("openAt", "")
            wait_for(lambda s: s["visible"] and s["focus"] == "Save windows for startup")
            ipc("click", "Rail on the right")
            wait_for(lambda s: s["dockLeft"] is False)
            ipc("click", "Rail on the left")
            wait_for(lambda s: s["dockLeft"] is True)
            ipc("click", "Show the keys")
            wait_for(lambda s: s["showKeys"] is True)
            ipc("click", "Save windows for startup")
            wait_for(lambda s: s["session"] == "disabled")
            ipc("click", "Save windows for startup")
            wait_for(lambda s: s["session"] == "watching")
            capture("settings")
            ipc("openAt", "bar")
            wait_for(lambda s: s["visible"] and s["focus"] == {"left": "Left", "center": "Middle", "right": "Right"}[s["section"]])
            print("PASS: real popup and registry; all positions, persistence, neighbors, errors, retry, keyboard, mouse, focus, dismissal, external changes, missing widget")
            print("PASS: settings panel; rail side, key hints and startup saving reach the overlay; gear and bar entry points focus their sections")
        except Exception:
            print((root / "log").read_text())
            raise
        finally:
            process.terminate()
            process.wait(timeout=5)
