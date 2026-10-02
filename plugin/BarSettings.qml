import QtQuick
import QtQuick.Controls as Controls
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Readability.js" as Readability

// Placement belongs to the shell, not to an overlay preference or a layout.
// Read its live configuration and move the existing entry through its API.
Controls.Popup {
  id: root
  required property var overlay
  readonly property var barConfig: overlay.shell ? overlay.shell.barConfig : null
  readonly property bool vertical: barConfig && ["left", "right"].indexOf(barConfig.position) !== -1
  readonly property var options: [
    { section: "left", label: vertical ? "Top" : "Left" },
    { section: "center", label: "Middle" },
    { section: "right", label: vertical ? "Bottom" : "Right" }
  ]
  readonly property string section: currentSection(barConfig)
  readonly property bool busy: moveProcess.running
  property string error: ""
  property string requested: ""
  property bool timedOut: false

  function currentSection(config) {
    if (!config || !config.layout) return ""
    var found = []
    for (var i = 0; i < options.length; i++) {
      var key = options[i].section
      var entries = config.layout[key] || []
      for (var j = 0; j < entries.length; j++) {
        var id = typeof entries[j] === "string" ? entries[j] : entries[j] && entries[j].id
        if (id === "jmartin.hypertile") found.push(key)
      }
    }
    return found.length === 1 ? found[0] : ""
  }

  function choose(section) {
    if (busy || !root.section || section === root.section) return
    if (["left", "center", "right"].indexOf(section) === -1) return
    error = ""
    requested = section
    timedOut = false
    moveProcess.command = ["omarchy-shell", "shell", "moveBarWidget", "jmartin.hypertile", JSON.stringify({section: section})]
    moveProcess.running = true
    timeout.restart()
  }

  function focusChoice() {
    if (!section) { closeButton.forceActiveFocus(); return }
    var index = Math.max(0, ["left", "center", "right"].indexOf(section))
    choices.itemAt(index).forceActiveFocus()
  }

  width: Math.min(overlay.railWidth, parent ? parent.width : overlay.railWidth)
  padding: overlay.uiPad
  modal: true
  dim: false
  focus: true
  closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutside
  onOpened: { error = ""; focusChoice() }
  onClosed: overlay.focusKeys()

  background: BorderSurface {
    color: root.overlay.surfaceColor
    radius: root.overlay.radiusCard
    borderSpec: Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(1)))
  }

  Process {
    id: moveProcess
    stdout: StdioCollector { id: output; waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code, status) {
      timeout.stop()
      if (root.timedOut) return
      if (code !== 0 || status !== 0 || output.text.trim() !== "ok")
        root.error = "Couldn’t move Hypertile. Try again."
      // The selection follows the live configuration, never the request.
      else if (root.section !== root.requested)
        root.error = "The bar hasn’t confirmed this position. Try again."
    }
  }
  Timer {
    id: timeout
    interval: 5000
    onTriggered: {
      root.timedOut = true
      moveProcess.running = false
      root.error = "The bar didn’t respond. Try again."
    }
  }

  contentItem: Column {
    spacing: Style.spacing.lg

    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Text {
        width: parent.width - closeButton.width - parent.spacing
        anchors.verticalCenter: parent.verticalCenter
        text: "Menu bar"
        color: root.overlay.foreground
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFont
        font.bold: true
      }
      Button {
        id: closeButton
        text: "×"
        foreground: root.overlay.foreground
        accent: root.overlay.accent
        fontFamily: root.overlay.fontFamily
        fontSize: root.overlay.uiFont
        radius: root.overlay.radiusControl
        focusable: true
        Accessible.name: "Close menu bar settings"
        tooltipText: "Close (Esc)"
        onClicked: root.close()
      }
    }

    Text {
      width: parent.width
      text: "Where should Hypertile appear?"
      color: root.overlay.foreground
      font.family: root.overlay.fontFamily
      font.pixelSize: root.overlay.uiFontSmall
      wrapMode: Text.WordWrap
    }

    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Repeater {
        id: choices
        model: root.options
        Button {
          id: choice
          required property var modelData
          required property int index
          width: (parent.width - parent.spacing * 2) / 3
          implicitHeight: preview.implicitHeight + caption.implicitHeight + Style.spacing.lg * 3
          selected: root.section === modelData.section
          enabled: root.section !== ""
          opacity: enabled ? 1 : 0.45
          bordered: true
          focusable: true
          foreground: root.overlay.foreground
          accent: root.overlay.accent
          radius: root.overlay.radiusControl
          Accessible.role: Accessible.RadioButton
          Accessible.name: modelData.label
          Accessible.checkable: true
          Accessible.checked: selected
          Accessible.description: "Hypertile menu bar position"
          onClicked: root.choose(modelData.section)
          Keys.onLeftPressed: choices.itemAt((index + 2) % 3).forceActiveFocus()
          Keys.onRightPressed: choices.itemAt((index + 1) % 3).forceActiveFocus()
          Keys.onUpPressed: choices.itemAt((index + 2) % 3).forceActiveFocus()
          Keys.onDownPressed: choices.itemAt((index + 1) % 3).forceActiveFocus()

          // A miniature screen makes each target legible before choosing it.
          Rectangle {
            id: preview
            width: parent.width - Style.spacing.lg * 2
            implicitHeight: root.overlay.uiFont * 2.5
            height: implicitHeight
            x: Style.spacing.lg
            y: Style.spacing.lg
            radius: Math.min(4, root.overlay.radiusControl)
            color: "transparent"
            border.width: 1
            border.color: Util.alpha(root.overlay.foreground, 0.3)
            Rectangle {
              id: bar
              x: root.vertical && root.barConfig.position === "right" ? parent.width - width - 4 : 4
              y: !root.vertical && root.barConfig && root.barConfig.position === "bottom" ? parent.height - height - 4 : 4
              width: root.vertical ? 5 : parent.width - 8
              height: root.vertical ? parent.height - 8 : 5
              radius: 1
              color: Util.alpha(root.overlay.foreground, 0.12)
              Rectangle {
                width: root.vertical ? parent.width : parent.width * 0.26
                height: root.vertical ? parent.height * 0.26 : parent.height
                x: root.vertical ? 0 : (parent.width - width) * choice.index / 2
                y: root.vertical ? (parent.height - height) * choice.index / 2 : 0
                radius: 1
                color: choice.selected ? root.overlay.accent : root.overlay.foreground
              }
            }
          }
          Text {
            id: caption
            anchors.horizontalCenter: parent.horizontalCenter
            y: preview.y + preview.height + Style.spacing.lg
            text: (choice.selected ? "✓ " : "") + choice.modelData.label
            color: choice.selected ? root.overlay.accent : root.overlay.foreground
            font.family: root.overlay.fontFamily
            font.pixelSize: root.overlay.uiFontSmall
            font.bold: choice.selected
          }
        }
      }
    }

    Text {
      width: parent.width
      text: root.error || (!root.section ? "Hypertile’s bar position is unavailable." : root.busy ? "Moving Hypertile…" : "Applies immediately on every screen.")
      color: root.error ? Readability.textColor(Color.urgent, root.overlay.surfaceColor, 1) : root.overlay.mutedForeground
      font.family: root.overlay.fontFamily
      font.pixelSize: root.overlay.uiCaption
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      Accessible.role: Accessible.StaticText
    }
  }
}
