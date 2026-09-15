import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import "TilePicker.js" as Picker

Item {
  id: root
  property string ctl: ""
  property var request: null
  property bool opened: false
  readonly property bool dragging: !!(root.request && root.request.dragToken)
  property string dragZone: ""
  property bool busy: false
  property string digits: ""
  property string errorText: ""
  readonly property int uiFont: Math.max(16, Math.round(window.height * 0.010))
  signal finished()

  function open(value) {
    root.request = value
    root.digits = ""
    root.errorText = ""
    var screen = null
    for (var i = 0; i < Quickshell.screens.length; i++) {
      if (Quickshell.screens[i].name === value.monitor) screen = Quickshell.screens[i]
    }
    if (!screen) { root.finished(); return }
    window.screen = screen
    root.opened = true
    if (root.dragging) dragFile.reload()
    else Qt.callLater(function() { keys.forceActiveFocus() })
  }

  function readDrag(text) {
    var value
    try { value = JSON.parse(text) } catch (e) { return }
    if (!root.dragging || value.token !== root.request.dragToken) return
    root.dragZone = value.zone || ""
    if (!value.active) root.finished()
  }

  FileView {
    id: dragFile
    path: root.dragging ? (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/hypertile-tile-drag.json" : ""
    watchChanges: root.dragging
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.readDrag(text())
  }

  function close() { root.opened = false }

  function choose(slot) {
    if (!slot || root.busy || !root.opened) return
    if (slot.zone === root.request.source) { root.finished(); return }
    var value = Object.assign({}, root.request, { zone: slot.zone })
    // Geometry is presentation-only and need not make the round trip.
    delete value.slots
    root.busy = true
    root.errorText = ""
    moveProc.command = [root.ctl, "tile-move", JSON.stringify(value)]
    moveProc.running = true
    startCheck.restart()
  }

  function chooseNumber(number) {
    var result = Picker.match(root.request ? root.request.slots : [], number)
    if (result.exact) root.choose(result.exact)
    else root.errorText = "No available tile numbered " + number
  }

  function handleKey(event) {
    if (event.isAutoRepeat || root.busy) return
    if (event.key === Qt.Key_Escape) { root.finished(); return }
    if (event.key === Qt.Key_Backspace) { root.digits = root.digits.slice(0, -1); root.errorText = ""; return }
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      if (root.digits !== "") root.chooseNumber(root.digits)
      return
    }
    if (event.key < Qt.Key_0 || event.key > Qt.Key_9) return
    var digits = root.digits + String(event.key - Qt.Key_0)
    var result = Picker.match(root.request.slots, digits)
    root.errorText = ""
    if (!result.found) {
      root.errorText = "No available tile numbered " + digits
      root.digits = ""
      return
    }
    root.digits = digits
    if (result.exact && !result.longer) root.choose(result.exact)
  }

  Process {
    id: moveProc
    stderr: StdioCollector { id: moveErrors; waitForEnd: true }
    onExited: function(code, status) {
      root.busy = false
      if (code === 0 && status === 0) root.finished()
      else root.errorText = moveErrors.text.trim() || "Could not move the window. Close and reopen the tile picker."
    }
  }

  Timer {
    id: startCheck
    interval: 1000
    onTriggered: {
      if (root.busy && !moveProc.running) {
        root.busy = false
        root.errorText = "Could not run Hypertile. Close and reopen the tile picker."
      }
    }
  }

  PanelWindow {
    id: window
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "hypertile-move"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.dragging ? WlrKeyboardFocus.None : WlrKeyboardFocus.Exclusive
    mask: Region { item: root.dragging ? null : keys }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.25) }
    MouseArea { anchors.fill: parent; onClicked: if (!root.busy) root.finished() }
    Item {
      id: keys
      anchors.fill: parent
      focus: true
      Keys.onPressed: function(event) { root.handleKey(event); event.accepted = true }
      Keys.onReleased: function(event) { event.accepted = true }
    }
    Repeater {
      model: root.request ? root.request.slots : []
      delegate: Rectangle {
        required property var modelData
        readonly property bool hovered: root.dragging ? root.dragZone === modelData.zone : mouse.containsMouse
        readonly property bool source: modelData.zone === root.request.source
        x: modelData.x + 4
        y: modelData.y + 4
        width: Math.max(1, modelData.w - 8)
        height: Math.max(1, modelData.h - 8)
        color: source || hovered ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.18) : "transparent"
        border.width: source || hovered ? 3 : 1
        border.color: source || hovered ? Color.accent : "#b3ffffff"
        radius: 10
        MouseArea {
          id: mouse
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: root.choose(modelData)
        }
        Rectangle {
          anchors.centerIn: parent
          width: label.width + root.uiFont * 2
          height: label.height + root.uiFont
          radius: 12
          color: "#ee16191f"
          border.color: source ? Color.accent : "#88ffffff"
          Column {
            id: label
            anchors.centerIn: parent
            spacing: 4
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: modelData.numbers.length ? modelData.numbers.join(" / ") : modelData.zone
              font.family: Style.font.menuFamily
              font.pixelSize: Math.round(root.uiFont * 2.5)
              font.bold: true
              color: "white"
            }
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: source ? "Current tile" : (modelData.occupied ? "Swap" : "Move here")
              font.family: Style.font.menuFamily
              font.pixelSize: root.uiFont
              color: "#dddddd"
            }
          }
        }
      }
    }
    Rectangle {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 28
      width: Math.min(parent.width - 40, hint.implicitWidth + 40)
      height: hint.implicitHeight + 24
      radius: 12
      color: "#f016191f"
      Text {
        id: hint
        anchors.centerIn: parent
        width: Math.min(implicitWidth, window.width - 80)
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        text: root.errorText || (root.busy ? "Moving window…" :
          (root.dragging ? "Drag window to a tile · Release mouse to drop" : root.digits ? "Tile " + root.digits + " · Continue typing or press Enter · Backspace to correct · Esc to cancel" :
            "Move window to tile · Release modifiers, then type a number or click · Esc to cancel"))
        font.family: Style.font.menuFamily
        font.pixelSize: root.uiFont
        color: "white"
      }
    }
  }
}
