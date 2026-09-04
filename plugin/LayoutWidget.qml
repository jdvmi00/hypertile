import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.Commons
import qs.Ui

// The layout on this monitor's active workspace, in the bar. Click opens
// the overlay; the wheel and middle-click cycle through the layouts. The label follows
// the focus and the config, and hypertile-ctl pokes it after a switch
// (omarchy-shell hypertile-bar refresh), since a workspace rule write
// raises no compositor event of its own.
BarWidget {
  id: root
  moduleName: "jmartin.hypertile"

  readonly property string home: Quickshell.env("HOME")
  readonly property string ctl: home + "/.local/bin/hypertile-ctl"
  readonly property string icon: "\u{F1CAC}"

  property string layout: ""         // as the compositor names it: lua:columns, dwindle
  property int workspaceId: 0
  readonly property string label: displayName(layout)

  // A bar is built per monitor, so each instance describes the workspace
  // active on its own screen rather than the one holding keyboard focus.
  readonly property string screenName: root.QsWindow.window && root.QsWindow.window.screen
    ? String(root.QsWindow.window.screen.name || "") : ""

  // A read already in flight started before the event that asked for this
  // one, so it may report the layout the switch replaced. Run again when it
  // lands rather than dropping the request.
  property bool refreshPending: false
  // Set when the CLI cannot be started (the plugin was added but install.sh
  // has not been run); the tooltip then says what to do.
  property bool ctlMissing: false
  property bool stalled: false     // the last read was cut short by stallTimer

  function displayName(raw) {
    var s = String(raw || "")
    var m = s.match(/^lua:(.+)$/)
    if (m) return m[1]
    if (s === "") return ""
    return s.charAt(0).toUpperCase() + s.slice(1)
  }

  function refresh() {
    if (queryProc.running) {
      refreshPending = true
      return
    }
    refreshPending = false
    queryProc.running = true
  }

  function openOverlay() {
    if (root.bar) root.bar.run("omarchy-shell shell toggle jmartin.hypertile")
  }

  function cycle(reverse) {
    if (root.bar) root.bar.run(Util.shellQuote(root.ctl) + " cycle" + (reverse ? " --reverse" : "") + (root.workspaceId > 0 ? " --workspace " + root.workspaceId : ""))
  }

  // One switch per wheel notch; a fast flick is still one step at a time.
  property int wheelAccum: 0
  function wheel(delta) {
    wheelAccum += delta
    if (wheelAccum >= 120) { wheelAccum = 0; cycle(true) }
    else if (wheelAccum <= -120) { wheelAccum = 0; cycle(false) }
  }

  Component.onCompleted: refresh()
  onScreenNameChanged: refresh()

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event || !event.name) return
      var name = String(event.name)
      // Focus moved (workspace, focusedmon), a workspace moved between
      // monitors, or a reload changed the default layout or the rules.
      if (name === "workspace" || name === "focusedmon" || name === "configreloaded" || name.indexOf("moveworkspace") === 0) debounce.restart()
    }
  }

  Timer {
    id: debounce
    interval: 80
    onTriggered: root.refresh()
  }

  Process {
    id: queryProc
    command: [root.ctl, "workspaces", "--json"]
    onRunningChanged: {
      if (running) {
        root.stalled = false
        stallTimer.restart()
        return
      }
      stallTimer.stop()
      if (root.refreshPending) root.refresh()
    }
    onExited: function(code, status) {
      if (!root.stalled) root.ctlMissing = (status !== 0 || code < 0 || code >= 126)
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var list
        try {
          list = JSON.parse(text || "{}").workspaces
        } catch (e) {
          return
        }
        if (!Array.isArray(list)) return
        var pick = null
        for (var i = 0; i < list.length; i++) {
          var ws = list[i]
          if (!ws || !ws.active) continue
          if (root.screenName === "" || String(ws.monitor || "") === root.screenName) { pick = ws; break }
        }
        if (!pick) return
        root.layout = String(pick.layout || "")
        root.workspaceId = Number(pick.id) || 0
      }
    }
  }

  // A read that never returns would pin the label until the shell restarts,
  // since a running Process cannot be re-run. Give up on one that overstays.
  Timer {
    id: stallTimer
    interval: 5000
    onTriggered: { root.stalled = true; queryProc.running = false; debounce.restart() }
  }

  IpcHandler {
    target: "hypertile-bar"
    function refresh(): void { root.broadcast("refresh") }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.vertical || root.label === "" ? root.icon : root.icon + "  " + root.label
    fontSize: Style.font.caption
    horizontalMargin: 6
    tooltipText: root.ctlMissing
      ? "hypertile-ctl is not installed: run install.sh in ~/.config/omarchy/plugins/jmartin.hypertile"
      : (root.label !== "" ? root.label + " on workspace " + root.workspaceId + "\n" : "")
        + "Click: layouts overlay · Scroll or middle-click: next layout"
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.MiddleButton) root.cycle(false)
      else root.openOverlay()
    }
    onWheelMoved: function(delta) { root.wheel(delta) }
  }
}
