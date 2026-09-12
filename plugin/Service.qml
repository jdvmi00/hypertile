import QtQuick
import Quickshell
import Quickshell.Io

// Omarchy mounts one service per enabled plugin, including overlay-only use.
// Keep setup out of per-monitor widgets and let Omarchy own plugin placement
// and reloads. install.sh serializes runs and skips an unchanged runtime.
Item {
  id: root
  visible: false

  property bool ready: false
  property string error: ""
  readonly property bool installing: !ready && error === ""
  readonly property string logPath: (Quickshell.env("XDG_STATE_HOME")
    || Quickshell.env("HOME") + "/.local/state") + "/hypertile/install.log"
  readonly property string statusText: error || (installing ? "Setting up Hypertile…" : "")
  readonly property string installer: decodeURIComponent(String(Qt.resolvedUrl("../install.sh")).replace(/^file:\/\//, ""))

  Component.onCompleted: setup.running = true

  Process {
    id: setup
    // A standalone ./install.sh copies only the shell files. That copy has
    // already been set up, so it has no installer to run here.
    command: ["bash", "-c",
      'if [[ -f "$1" ]]; then mkdir -p "${2%/*}" && exec bash "$1" --automatic >"$2" 2>&1; fi',
      "hypertile-setup", root.installer, root.logPath]
    onExited: function(code, status) {
      root.ready = code === 0 && status === 0
      root.error = root.ready ? "" : "Hypertile setup failed. See " + root.logPath
      if (!root.ready) console.warn(root.error)
    }
  }
}
