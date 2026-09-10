import QtQuick
import Quickshell.Io
import "Session.js" as Session

// Read the running writer, so an old status file cannot imply saving is active.
Item {
  id: root
  required property string ctl
  property bool polling: true
  property var data: null
  property bool available: false
  property bool checked: false
  property bool stalled: false
  visible: false

  function refresh() {
    if (polling && !query.running) query.running = true
  }
  Component.onCompleted: refresh()
  onPollingChanged: if (polling) refresh()
  Timer { interval: 5000; repeat: true; running: root.polling; onTriggered: root.refresh() }
  Process {
    id: query
    command: [root.ctl, "session", "status"]
    stdout: StdioCollector { id: output; waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
    onStarted: { root.stalled = false; timeout.restart() }
    onExited: function(code, status) {
      timeout.stop()
      if (root.stalled) return
      var value = Session.parse(output.text)
      root.available = code === 0 && status === 0 && value !== null
      root.data = root.available ? value : null
      root.checked = true
    }
  }
  Timer {
    id: timeout
    interval: 4000
    onTriggered: { root.stalled = true; query.running = false; root.available = false; root.data = null; root.checked = true }
  }
}
