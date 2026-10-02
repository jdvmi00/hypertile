import QtQuick
import QtQuick.Controls as Controls
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Displays.js" as Displays
import "Readability.js" as Readability
import "Session.js" as Session

// Settings behind the rail's gear: the preferences that belong to no layout,
// scene or display. Saving windows for startup and the desktop text size act
// at once on the system; the rail side and key hints are the overlay's own
// preferences; the menu bar position belongs to the shell, so it is read
// from the shell's live configuration and moved through its API. The bar
// widget's right-click opens this panel on the menu bar position.
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
  // Where the keyboard lands on open: "bar" (the bar widget's right-click)
  // or the first control.
  property string focusOn: "bar"

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

  function openAt(where) {
    focusOn = where === "bar" ? "bar" : "first"
    if (opened) focusInitial()
    else open()
  }

  function focusInitial() {
    if (focusOn === "bar") focusChoice()
    else startupToggle.forceActiveFocus()
  }

  // ---- desktop text size: one setting for every display, applied at once.
  readonly property var textSizeStops: [9, 10, 11, 12, 14, 16, 20]
  property int pendingTextSize: -1
  readonly property real textSize: pendingTextSize >= 0 ? pendingTextSize : Style.font.baseSize
  property string textSizeError: ""
  function setTextSize(index) {
    if (textSizeProcess.running || index < 0 || index >= textSizeStops.length)
      return
    pendingTextSize = textSizeStops[index]
    textSizeProcess.command = ["omarchy", "display", "text", "size", String(pendingTextSize)]
    textSizeProcess.running = true
  }

  readonly property QtObject sliderPalette: QtObject {
    readonly property color foreground: root.overlay.foreground
    readonly property color background: root.overlay.surfaceColor
    readonly property string fontFamily: root.overlay.fontFamily
  }

  width: Math.min(overlay.railWidth, parent ? parent.width : overlay.railWidth)
  padding: overlay.uiPad
  modal: true
  dim: false
  focus: true
  closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutside
  onOpened: { error = ""; textSizeError = ""; focusInitial() }
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
  Process {
    id: textSizeProcess
    stderr: StdioCollector { id: textSizeErrors; waitForEnd: true }
    onExited: function(code) {
      root.pendingTextSize = -1
      root.textSizeError = code !== 0 ? (textSizeErrors.text.trim() || "Could not change the text size.") : ""
    }
  }

  // ---------------------------------------------------------- pieces

  component Heading: Text {
    width: parent ? parent.width : implicitWidth
    textFormat: Text.PlainText
    color: root.overlay.mutedForeground
    font.family: root.overlay.fontFamily
    font.pixelSize: root.overlay.uiCaption
    font.bold: true
  }

  component Note: Text {
    width: parent ? parent.width : implicitWidth
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: root.overlay.mutedForeground
    font.family: root.overlay.fontFamily
    font.pixelSize: root.overlay.uiCaption
  }

  component Switch: Toggle {
    width: parent ? parent.width : implicitWidth
    radius: root.overlay.radiusControl
    rounded: true
    foreground: root.overlay.foreground
    accent: root.overlay.accent
    fontFamily: root.overlay.fontFamily
    titleSize: root.overlay.uiFontSmall
    descriptionSize: root.overlay.uiCaption
    opacity: enabled ? 1 : 0.45
  }

  component Separator: Rectangle {
    width: parent ? parent.width : 0
    height: 1
    color: Util.alpha(root.overlay.foreground, 0.16)
  }

  contentItem: Column {
    spacing: Style.spacing.lg

    Row {
      width: parent.width
      spacing: Style.spacing.sm
      Text {
        width: parent.width - closeButton.width - parent.spacing
        anchors.verticalCenter: parent.verticalCenter
        text: "Settings"
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
        Accessible.name: "Close settings"
        tooltipText: "Close (Esc)"
        onClicked: root.close()
      }
    }

    // ---- Startup
    Heading { text: "STARTUP" }
    Switch {
      id: startupToggle
      label: "Save windows for startup"
      description: "Reopen your windows where they were when you log in"
      checked: !!root.overlay.sessionAvailable && !!root.overlay.sessionStatus && root.overlay.sessionStatus.mode !== "disabled"
      enabled: !!root.overlay.sessionAvailable && !root.overlay.busy
      Accessible.name: "Save windows for startup"
      onClicked: if (enabled) root.overlay.setSessionEnabled(root.overlay.sessionStatus.mode === "disabled")
    }
    Note {
      visible: text !== ""
      text: root.overlay.sessionChecked ? Session.summary(root.overlay.sessionStatus, root.overlay.sessionAvailable, root.overlay.sessionChecked) : ""
    }

    Separator {}

    // ---- The rail
    Heading { text: "RAIL" }
    Item {
      width: parent.width
      implicitHeight: Math.max(sideLabel.implicitHeight, sideChoices.implicitHeight)
      Text {
        id: sideLabel
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: "Side of the screen"
        color: root.overlay.foreground
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFontSmall
      }
      Row {
        id: sideChoices
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.spacing.sm
        Repeater {
          model: [{ left: true, label: "Left" }, { left: false, label: "Right" }]
          Button {
            required property var modelData
            text: modelData.label
            selected: !!root.overlay.dockLeft === modelData.left
            bordered: true
            focusable: true
            foreground: root.overlay.foreground
            accent: root.overlay.accent
            fontFamily: root.overlay.fontFamily
            fontSize: root.overlay.uiFontSmall
            radius: root.overlay.radiusControl
            Accessible.role: Accessible.RadioButton
            Accessible.name: "Rail on the " + modelData.label.toLowerCase()
            Accessible.checkable: true
            Accessible.checked: selected
            onClicked: if (!!root.overlay.dockLeft !== modelData.left) root.overlay.setPref("dockLeft", modelData.left)
          }
        }
      }
    }
    Switch {
      label: "Show the keys"
      description: "List the keyboard shortcuts at the bottom of the rail (?)"
      checked: !!root.overlay.showKeys
      Accessible.name: "Show the keys"
      onClicked: root.overlay.setPref("showKeys", !root.overlay.showKeys)
    }

    Separator {}

    // ---- Menu bar position
    Heading { text: "MENU BAR" }
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

    Separator {}

    // ---- Desktop text size
    Item {
      width: parent.width
      implicitHeight: Math.max(textSizeHeading.implicitHeight, textSizeValue.implicitHeight)
      Heading { id: textSizeHeading; width: implicitWidth; text: "DESKTOP TEXT SIZE"; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter }
      Text {
        id: textSizeValue
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: (textSizeSlider.dragging ? root.textSizeStops[Math.round(textSizeSlider.liveValue)] : root.textSize) + " px"
        color: root.overlay.foreground
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFontSmall
        font.bold: true
      }
    }
    PanelSlider {
      id: textSizeSlider
      width: parent.width
      bar: root.sliderPalette
      minimum: 0
      maximum: root.textSizeStops.length - 1
      step: 1
      integer: true
      tickCount: root.textSizeStops.length
      value: Displays.nearestStop(root.textSizeStops, root.textSize)
      enabled: !textSizeProcess.running
      trackHeight: Math.max(4, Math.round(root.overlay.uiFontSmall * 0.28))
      knobSize: Math.max(14, Math.round(root.overlay.uiFontSmall * 0.85))
      activeFocusOnTab: true
      Accessible.role: Accessible.Slider
      Accessible.name: "Desktop text size"
      onReleased: function(v) { root.setTextSize(Math.round(v)) }
      Keys.onPressed: function(event) {
        var delta = event.key === Qt.Key_Left ? -1 : event.key === Qt.Key_Right ? 1 : 0
        if (delta) {
          root.setTextSize(Math.max(0, Math.min(maximum, value + delta)))
          event.accepted = true
        }
      }
      Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        visible: textSizeSlider.activeFocus
        color: "transparent"
        border.color: root.overlay.accent
        radius: root.overlay.radiusControl
      }
    }
    Note {
      text: root.textSizeError || "Text on every display and in the bar, changed at once."
      color: root.textSizeError ? Readability.textColor(Color.urgent, root.overlay.surfaceColor, 1) : root.overlay.mutedForeground
    }
  }
}
