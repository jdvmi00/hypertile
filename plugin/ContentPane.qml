import QtQuick
import qs.Commons
import qs.Ui
import "Content.js" as Content

Column {
  id: pane
  required property var overlay
  readonly property var catalog: overlay.contentCatalog || ({})
  readonly property var scene: catalog.current || ({})
  readonly property var source: overlay.contentFor(overlay.selected)
  readonly property var runtime: source && source.runtime ? source.runtime : ({})
  property bool details: false
  spacing: Style.spacing.lg

  component Caption: Text {
    width: pane.width
    textFormat: Text.PlainText
    color: pane.overlay.foreground
    font.family: pane.overlay.fontFamily
    font.pixelSize: pane.overlay.uiFontSmall
    wrapMode: Text.WordWrap
  }
  component Small: Caption {
    font.pixelSize: pane.overlay.uiCaption
    color: Util.alpha(pane.overlay.foreground, 0.65)
  }
  component Action: Button {
    bordered: true
    radius: pane.overlay.radiusControl
    foreground: pane.overlay.foreground
    accent: pane.overlay.accent
    fontFamily: pane.overlay.fontFamily
    fontSize: pane.overlay.uiFontSmall
    enabled: !pane.overlay.busy
    opacity: enabled ? 1 : 0.45
  }

  PanelSectionHeader { text: "SCENES"; foreground: overlay.foreground; fontFamily: overlay.fontFamily; fontSize: overlay.uiCaption }
  Caption { text: (pane.scene.document ? (pane.scene.document.name || "Unsaved scene") + (pane.scene.modified ? " · modified" : "") + "\n" : "") + Content.status(pane.scene.phase) }
  Small { visible: !!pane.scene.error; text: pane.scene.error || "" }
  Flow {
    width: parent.width
    spacing: Style.spacing.sm
    Action { text: "Restore previous"; enabled: !overlay.busy && !!pane.scene.can_restore && pane.scene.phase !== "restored"; onClicked: overlay.sceneAction("restore") }
    Action { text: "Retry"; visible: pane.scene.phase === "partial" || pane.scene.phase === "needs-attention"; onClicked: overlay.sceneAction("retry") }
  }
  Column {
    width: parent.width
    spacing: Style.spacing.sm
    Repeater {
      model: pane.catalog.scenes || []
      Column {
        required property var modelData
        width: pane.width
        Action { width: parent.width; text: modelData.name; enabled: !overlay.busy && modelData.valid; onClicked: overlay.sceneAction("apply", modelData.name) }
        Small { visible: !modelData.valid; text: modelData.error || "" }
      }
    }
  }
  TextField {
    id: sceneName
    width: parent.width
    placeholderText: "Scene name"
    foreground: overlay.foreground
    accent: overlay.accent
    font.family: overlay.fontFamily
    font.pixelSize: overlay.uiFontSmall
    Keys.onReturnPressed: overlay.saveScene(text)
  }
  Action { text: "Save current scene"; enabled: !overlay.busy && sceneName.text.trim() !== ""; onClicked: overlay.saveScene(sceneName.text) }
  Small { text: "Save this workspace’s layout, computers and profiles as one scene." }
  Action {
    visible: !overlay.viewedIsActive && overlay.viewed !== null
    width: parent.width
    text: "Start scene with this layout"
    onClicked: overlay.sceneAction("layout", overlay.viewed.name)
  }
  Small { visible: !overlay.viewedIsActive; text: "Starting a scene with this layout removes the current remote assignments. Local apps stay open." }

  PanelSeparator { width: parent.width; foreground: overlay.foreground }
  PanelSectionHeader { text: "CONTENT"; foreground: overlay.foreground; fontFamily: overlay.fontFamily; fontSize: overlay.uiCaption }
  Caption { text: overlay.selected ? overlay.selected + "\n" + Content.label(pane.source) : "Select a zone in the layout" }
  Small { visible: !!pane.source && !!pane.source.error; text: pane.source ? pane.source.error || "" : "" }
  Column {
    visible: overlay.selected !== "" && overlay.viewedIsActive
    width: parent.width
    spacing: Style.spacing.lg
    Flow {
      width: parent.width
      spacing: Style.spacing.sm
      Action { text: "Local windows"; onClicked: overlay.assignContent("local") }
      Action { text: "Empty"; onClicked: overlay.assignContent("empty") }
    }
    Column {
      visible: pane.source !== null && pane.source.type === "stream"
      width: parent.width
      spacing: Style.spacing.sm
      Flow {
        width: parent.width
        spacing: Style.spacing.sm
        Action { text: "Focus"; enabled: !overlay.busy && !!pane.runtime.window; onClicked: overlay.streamAction("focus", pane.source.computer, true) }
        Action { text: "Disconnect"; onClicked: overlay.streamAction("disconnect", pane.source.computer) }
        Action { text: "Retry"; visible: !pane.runtime.window && pane.runtime.desired === true; onClicked: overlay.streamAction("retry", pane.source.computer) }
        Action { text: "Restore display"; visible: !!pane.runtime.journal && pane.runtime.desired !== true; onClicked: overlay.streamAction("restore", pane.source.computer) }
      }
      Small { text: Content.audio((pane.runtime.requested || {}).audio) }
      Small { visible: !!pane.runtime.audio_health && !!pane.runtime.audio_health.error; text: pane.runtime.audio_health ? pane.runtime.audio_health.error || "" : "" }
      Flow {
        width: parent.width
        spacing: Style.spacing.sm
        Action { text: "Type clipboard"; enabled: !overlay.busy && !!pane.runtime.window && (pane.runtime.clipboard || {}).state !== "unsupported"; tooltipText: "Type your local clipboard into the focused app on this computer"; onClicked: overlay.streamAction("clipboard", pane.source.computer, true) }
        Action { text: "Toggle capture"; enabled: !overlay.busy && !!pane.runtime.window; onClicked: overlay.streamAction("input-release", pane.source.computer, true) }
        Action { text: "Statistics"; enabled: !overlay.busy && !!pane.runtime.window; onClicked: overlay.streamAction("stats", pane.source.computer, true) }
      }
      Small { visible: !!(pane.runtime.clipboard || {}).reason; text: (pane.runtime.clipboard || {}).reason || "" }
      Small { text: (pane.runtime.requested || {}).system_keys === "always" ? "System keys go to this computer while captured. Toggle capture to use local shortcuts." : "System keys stay local. Command/Windows shortcuts require a keyboard-capture profile." }
      Small { text: "Ctrl+Alt+Shift+Z toggles capture. Camera, microphone and meeting playback need a separate call check." }
      Action { text: pane.details ? "Hide details" : "Details"; onClicked: pane.details = !pane.details }
      Small { visible: pane.details; text: JSON.stringify(pane.runtime, null, 2) }
    }
    Repeater {
      model: pane.catalog.computers || []
      Column {
        id: computer
        required property var modelData
        width: pane.width
        spacing: Style.spacing.sm
        Caption { text: computer.modelData.computer }
        Repeater {
          model: computer.modelData.profiles
          Column {
            required property var modelData
            width: pane.width
            Action { width: parent.width; text: modelData.name; onClicked: overlay.assignContent("stream", computer.modelData.computer, modelData.name) }
            Small { text: Content.audio(modelData.audio) + (modelData.input === "relative" ? " · captured pointer" : "") + (modelData.system_keys === "always" ? " · system keys captured" : "") }
          }
        }
      }
    }
    Small { visible: (pane.catalog.computers || []).length === 0; text: "No computers configured yet. Add paired computers in Hypertile’s computers.json." }
    PanelSectionHeader { text: "OPEN LOCAL APPS"; foreground: overlay.foreground; fontFamily: overlay.fontFamily; fontSize: overlay.uiCaption }
    Repeater {
      model: overlay.contentWindowClasses
      Action { required property string modelData; width: pane.width; text: modelData; onClicked: overlay.assignContent("local", "", "", modelData) }
    }
    Small { text: "An app assignment uses one matching window on this workspace. Missing or ambiguous matches remain pending." }
  }
}
