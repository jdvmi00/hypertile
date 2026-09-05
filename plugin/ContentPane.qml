import QtQuick
import qs.Commons
import qs.Ui
import "Content.js" as Content
import "Editor.js" as Editor

// The body of the rail's Scenes tab: the saved scenes, what each zone of
// the workspace's layout holds, and the selected zone with the choices
// for it. The header above it (the scene's name and state, Save and
// Restore) is the rail's own. Every change goes through hypertile-ctl
// scene/stream; the catalog is re-read every couple of seconds while the
// overlay is open, so the states here follow the controller.
Column {
  id: pane
  required property var overlay
  readonly property var catalog: overlay.contentCatalog || ({})
  readonly property var scene: catalog.current || ({})
  readonly property var scenes: catalog.scenes || []
  readonly property var computers: catalog.computers || []
  readonly property bool ready: overlay.contentCatalog !== null && !overlay.catalogFailed
  readonly property bool usable: ready && overlay.viewedIsActive
  // The zones in fill order, as the numerals on the screen read them.
  readonly property var zoneRows: {
    if (!usable) return []
    var rows = []
    for (var i = 0; i < overlay.zones.length; i++) {
      var z = overlay.zones[i]
      rows.push({ name: z.name, first: z.numbers.length > 0 ? z.numbers[0] : 999, badge: z.spacer ? "∅" : (z.numbers.length > 0 ? z.numbers.join(" · ") : "—"), spacer: z.spacer === true })
    }
    rows.sort(function(a, b) { return a.first - b.first || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) })
    return rows
  }
  readonly property var sel: overlay.selectedZone
  readonly property var source: overlay.contentFor(overlay.selected)
  readonly property var runtime: (source && source.runtime) ? source.runtime : ({})
  readonly property var controls: Content.streamControls(runtime)
  readonly property bool isStream: source !== null && source.type === "stream"
  readonly property var quality: runtime.quality || ({})
  readonly property var measurement: (quality.current || {}).measurement || ({})
  readonly property string appliedScene: (scene.document && scene.document.name && ["none", "restored"].indexOf(scene.phase) === -1) ? scene.document.name : ""
  readonly property color fg: overlay.foreground
  readonly property color accent: overlay.accent
  readonly property string family: overlay.fontFamily
  property bool details: false
  property string deleting: ""      // the saved scene a delete is being confirmed for

  spacing: Style.spacing.xl

  // Another zone: back to the short view of it.
  Connections {
    target: pane.overlay
    function onSelectedChanged() { pane.details = false; pane.overlay.contentMore = false; pane.overlay.performanceOpen = false }
  }

  // ---------------------------------------------------------- pieces

  component Label: Text {
    textFormat: Text.PlainText
    color: Util.alpha(pane.fg, 0.7)
    font.family: pane.family
    font.pixelSize: pane.overlay.uiCaption
    font.bold: true
  }

  component Muted: Text {
    property bool urgent: false
    textFormat: Text.PlainText
    width: pane.width
    wrapMode: Text.WordWrap
    color: urgent ? Color.urgent : Util.alpha(pane.fg, 0.62)
    font.family: pane.family
    font.pixelSize: pane.overlay.uiCaption
  }

  component Body: Text {
    textFormat: Text.PlainText
    width: pane.width
    wrapMode: Text.WordWrap
    color: pane.fg
    font.family: pane.family
    font.pixelSize: pane.overlay.uiFontSmall
  }

  component Action: Button {
    bordered: true
    radius: pane.overlay.radiusControl
    foreground: pane.fg
    accent: pane.accent
    fontFamily: pane.family
    fontSize: pane.overlay.uiFontSmall
    enabled: !pane.overlay.busy
    opacity: enabled ? 1 : 0.45
  }

  component Section: Column {
    id: section
    property string title: ""
    property string detail: ""
    width: pane.width
    spacing: Style.spacing.lg
    PanelSeparator { foreground: pane.fg; width: pane.width }
    Item {
      width: pane.width
      implicitHeight: Math.max(sectionTitle.implicitHeight, sectionDetail.implicitHeight)
      PanelSectionHeader {
        id: sectionTitle
        text: section.title
        foreground: pane.fg
        fontFamily: pane.family
        fontSize: pane.overlay.uiCaption
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        id: sectionDetail
        textFormat: Text.PlainText
        text: section.detail
        color: pane.accent
        font.family: pane.family
        font.pixelSize: pane.overlay.uiFontSmall
        font.bold: true
        elide: Text.ElideRight
        width: Math.min(implicitWidth, parent.width - sectionTitle.implicitWidth - Style.spacing.lg * 2)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
      }
    }
  }

  // A small collapsible group inside a section, headed like the rail's
  // collapsible sections.
  component Disclosure: Item {
    id: disclosure
    property string text: ""
    property bool open: false
    signal toggled()
    width: pane.width
    implicitHeight: disclosureRow.implicitHeight
    Row {
      id: disclosureRow
      spacing: Style.spacing.sm
      Text {
        textFormat: Text.PlainText
        text: disclosure.open ? "▾" : "▸"
        color: Util.alpha(pane.fg, 0.7)
        font.family: pane.family
        font.pixelSize: pane.overlay.uiCaption
        anchors.verticalCenter: parent.verticalCenter
      }
      PanelSectionHeader {
        text: disclosure.text
        foreground: pane.fg
        fontFamily: pane.family
        fontSize: pane.overlay.uiCaption
        anchors.verticalCenter: parent.verticalCenter
      }
    }
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: disclosure.toggled()
    }
  }

  // One line in a list: a name, a quieter phrase next to it, and a state
  // on the right. The current one reads like the viewed layout in the
  // LAYOUTS list.
  component ListRow: Rectangle {
    id: row
    property string badge: ""      // the fill number, as on the zone card
    property bool badgeStrong: true
    property string text: ""
    property string sub: ""
    property string trait: ""
    property bool current: false
    property bool urgent: false
    signal clicked()
    width: pane.width
    implicitHeight: rowMain.implicitHeight + Style.spacing.sm * 2
    height: implicitHeight
    radius: pane.overlay.radiusControl
    color: current ? Util.alpha(pane.accent, 0.14) : (rowHover.containsMouse ? Util.alpha(pane.fg, 0.06) : "transparent")
    border.width: current ? 1 : 0
    border.color: Util.alpha(pane.accent, 0.6)
    Behavior on color { ColorAnimation { duration: pane.overlay.motionFast } }
    Chip {
      id: rowBadge
      visible: row.badge !== ""
      x: Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
      text: row.badge
      strong: row.badgeStrong
      foreground: pane.fg
      fontFamily: pane.family
      fontSize: pane.overlay.uiCaption
    }
    Text {
      id: rowMain
      x: rowBadge.visible ? rowBadge.x + rowBadge.width + Style.spacing.md : Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - x - Style.spacing.md - (rowTrait.visible ? rowTrait.implicitWidth + Style.spacing.lg : 0)
      textFormat: Text.PlainText
      text: row.text
      color: row.current ? pane.accent : pane.fg
      font.family: pane.family
      font.pixelSize: pane.overlay.uiFontSmall
      font.bold: row.current
      elide: Text.ElideRight
      Text {
        // The quieter phrase sits after the name on the same line.
        visible: row.sub !== ""
        x: parent.contentWidth + Style.spacing.lg
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, parent.width - x)
        textFormat: Text.PlainText
        text: row.sub
        color: Util.alpha(pane.fg, 0.7)
        font.family: pane.family
        font.pixelSize: pane.overlay.uiFontSmall
        elide: Text.ElideRight
      }
    }
    Text {
      id: rowTrait
      visible: row.trait !== ""
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: row.trait
      color: row.urgent ? Color.urgent : Util.alpha(pane.fg, 0.62)
      font.family: pane.family
      font.pixelSize: pane.overlay.uiCaption
    }
    MouseArea {
      id: rowHover
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: row.clicked()
    }
  }

  component Prompt: Rectangle {
    id: prompt
    property bool warning: false
    default property alias content: promptColumn.data
    width: pane.width
    implicitHeight: promptColumn.implicitHeight + Style.spacing.xl * 2
    height: implicitHeight
    radius: pane.overlay.radiusControl
    color: Util.alpha(warning ? Color.urgent : pane.accent, 0.08)
    border.width: 1
    border.color: Util.alpha(warning ? Color.urgent : pane.accent, 0.6)
    Column {
      id: promptColumn
      x: Style.spacing.xl
      y: Style.spacing.xl
      width: parent.width - Style.spacing.xl * 2
      spacing: Style.spacing.md
    }
  }

  component PromptTitle: Text {
    textFormat: Text.PlainText
    width: parent.width
    wrapMode: Text.WordWrap
    color: pane.fg
    font.family: pane.family
    font.pixelSize: pane.overlay.uiFontSmall
    font.bold: true
  }

  // ------------------------------------------------- when nothing works

  Muted {
    visible: pane.overlay.catalogFailed
    text: "Scenes need Hypertile's stream controller, which is not installed. Run install.sh from the plugin directory, then open the overlay again."
  }
  Muted {
    visible: !pane.overlay.catalogFailed && pane.overlay.contentCatalog === null
    text: "Reading the workspace…"
  }
  Muted {
    visible: pane.ready && !pane.overlay.viewedIsActive
    text: "Workspace " + pane.overlay.workspaceId + " is not on a Hypertile layout. Pick one under Layouts first; then its zones can hold content."
  }

  // ------------------------------------------------------ saved scenes

  Section {
    visible: pane.ready && pane.scenes.length > 0
    title: "SAVED SCENES"

    Column {
      width: pane.width
      spacing: Style.spacing.sm
      Repeater {
        model: pane.scenes
        Item {
          id: sceneRow
          required property var modelData
          readonly property bool applied: pane.appliedScene === modelData.name
          readonly property bool valid: modelData.valid === true
          width: pane.width
          implicitHeight: Math.max(sceneText.implicitHeight, sceneTools.implicitHeight)
          height: implicitHeight

          Column {
            id: sceneText
            anchors.left: parent.left
            anchors.right: sceneTools.left
            anchors.rightMargin: Style.spacing.lg
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.xxs
            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: sceneRow.modelData.name
              color: sceneRow.applied ? pane.accent : pane.fg
              font.family: pane.family
              font.pixelSize: pane.overlay.uiFontSmall
              font.bold: sceneRow.applied
              elide: Text.ElideRight
            }
            Text {
              textFormat: Text.PlainText
              width: parent.width
              text: sceneRow.valid ? String(sceneRow.modelData.layout || "")
                : (sceneRow.modelData.error || "This scene cannot be applied")
              color: sceneRow.valid ? Util.alpha(pane.fg, 0.62) : Color.urgent
              font.family: pane.family
              font.pixelSize: pane.overlay.uiCaption
              wrapMode: sceneRow.valid ? Text.NoWrap : Text.WordWrap
              elide: sceneRow.valid ? Text.ElideRight : Text.ElideNone
            }
          }
          Row {
            id: sceneTools
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.xs
            Action {
              text: sceneRow.applied && !pane.scene.modified ? "Applied" : "Apply"
              selected: sceneRow.applied && !pane.scene.modified
              fontSize: pane.overlay.uiCaption
              tooltipText: sceneRow.applied && pane.scene.modified ? "Put the saved definition back" : "Use this layout and content on workspace " + pane.overlay.workspaceId
              enabled: !pane.overlay.busy && sceneRow.valid && !(sceneRow.applied && !pane.scene.modified)
              opacity: 1
              onClicked: pane.overlay.sceneAction("apply", sceneRow.modelData.name)
            }
            Action {
              text: "✕"
              bordered: false
              fontSize: pane.overlay.uiCaption
              tooltipText: "Delete this scene"
              onClicked: pane.deleting = sceneRow.modelData.name
            }
          }
        }
      }
    }

    Prompt {
      visible: pane.deleting !== ""
      warning: true
      PromptTitle { text: "Delete scene " + pane.deleting + "?" }
      Muted { width: parent.width; text: "Its file is removed. Nothing on the workspace changes and nothing disconnects." }
      Flow {
        width: parent.width
        spacing: Style.spacing.sm
        Action { text: "Delete"; accent: Color.urgent; selected: true; onClicked: { pane.overlay.deleteScene(pane.deleting); pane.deleting = "" } }
        Action { text: "Cancel"; onClicked: pane.deleting = "" }
      }
    }
  }

  // ---------------------------------------------------- what is where

  Section {
    visible: pane.usable
    title: "CONTENT"
    detail: pane.overlay.viewed ? pane.overlay.viewed.name : ""

    Column {
      width: pane.width
      spacing: Style.spacing.xxs
      Repeater {
        model: pane.zoneRows
        ListRow {
          required property var modelData
          readonly property var zoneSource: pane.overlay.contentFor(modelData.name)
          readonly property var zoneState: Content.state(zoneSource)
          badge: modelData.badge
          badgeStrong: !modelData.spacer
          text: modelData.name
          sub: modelData.spacer ? "Spacer" : Content.label(zoneSource)
          trait: zoneState.text
          urgent: zoneState.urgent
          current: pane.overlay.selected === modelData.name
          onClicked: pane.overlay.selected = modelData.name
        }
      }
    }
  }

  // ------------------------------------------------- the selected zone

  Section {
    visible: pane.usable
    title: "ZONE"
    detail: pane.overlay.selected

    Muted {
      visible: pane.sel === null
      text: "Click a zone above or on the screen to change what it holds. Tab and the arrows move between zones."
    }

    Column {
      visible: pane.sel !== null
      width: pane.width
      spacing: Style.spacing.lg

      Column {
        width: pane.width
        spacing: Style.spacing.xxs
        Body { text: Content.label(pane.source); font.bold: true }
        Muted { text: Content.detail(pane.source); urgent: Content.state(pane.source).urgent && !pane.isStream }
        Muted { visible: pane.isStream && !!pane.source.error; text: pane.isStream ? (pane.source.error || "") : ""; urgent: true }
      }

      // ---- a stream: what to do with it
      Flow {
        visible: pane.isStream
        width: pane.width
        spacing: Style.spacing.sm
        Action { text: "Focus"; tooltipText: "Focus the remote desktop and close"; enabled: !pane.overlay.busy && pane.controls.focus; onClicked: pane.overlay.streamAction("focus", pane.source.computer, true) }
        Action { text: "Disconnect"; visible: pane.controls.disconnect; tooltipText: "Close the view; the zone goes back to local windows"; onClicked: pane.overlay.streamAction("disconnect", pane.source.computer) }
        Action {
          text: "Reconnect"
          tooltipText: "Open the remote desktop in this zone"
          enabled: !pane.overlay.busy && pane.controls.reconnect !== ""
          onClicked: {
            if (pane.controls.reconnect === "connect")
              pane.overlay.assignContent("stream", pane.source.computer, pane.source.profile)
            else pane.overlay.streamAction("reconnect", pane.source.computer)
          }
        }
        Action { text: "Retry"; visible: pane.controls.retry; onClicked: pane.overlay.streamAction("retry", pane.source.computer) }
        Action { text: "Restore display"; visible: pane.controls.restore; tooltipText: "Put the host's display settings back"; onClicked: pane.overlay.streamAction("restore", pane.source.computer) }
      }

      Disclosure {
        visible: pane.isStream
        text: "MORE CONTROLS"
        open: pane.overlay.contentMore
        onToggled: pane.overlay.contentMore = !pane.overlay.contentMore
      }

      Column {
        visible: pane.isStream && pane.overlay.contentMore
        width: pane.width
        spacing: Style.spacing.md

        Flow {
          width: pane.width
          spacing: Style.spacing.sm
          Action { text: "Toggle capture"; tooltipText: "Ctrl+Alt+Shift+Z in the stream"; enabled: !pane.overlay.busy && !!pane.runtime.window; onClicked: pane.overlay.streamAction("input-release", pane.source.computer, true) }
          Action { text: "Type clipboard"; tooltipText: "Type your local clipboard into the app focused on this computer"; enabled: !pane.overlay.busy && !!pane.runtime.window && (pane.runtime.clipboard || {}).state !== "unsupported"; onClicked: pane.overlay.streamAction("clipboard", pane.source.computer, true) }
          Action { text: "Statistics"; tooltipText: "Moonlight's on-screen statistics"; enabled: !pane.overlay.busy && !!pane.runtime.window; onClicked: pane.overlay.streamAction("stats", pane.source.computer, true) }
          Action { text: "Focus a local window"; tooltipText: "Leave the remote desktop for a local window on this workspace"; enabled: !pane.overlay.busy && !!pane.runtime.window; onClicked: pane.overlay.streamAction("local", pane.source.computer, true) }
        }
        Muted {
          text: (pane.runtime.requested || {}).system_keys === "always"
            ? "Command and Windows keys go to this computer while captured; toggle capture to use local shortcuts."
            : "Command and Windows keys stay local; a profile with system keys sends them to this computer."
        }
        Muted { visible: !!(pane.runtime.clipboard || {}).reason; text: (pane.runtime.clipboard || {}).reason || "" }

        Flow {
          width: pane.width
          spacing: Style.spacing.sm
          Action { text: "Performance"; selected: pane.overlay.performanceOpen; onClicked: pane.overlay.performanceOpen = !pane.overlay.performanceOpen }
          Action { text: "Raw status"; selected: pane.details; onClicked: pane.details = !pane.details }
        }

        Column {
          visible: pane.overlay.performanceOpen
          width: pane.width
          spacing: Style.spacing.sm
          Muted { text: Content.performance(pane.quality) }
          Action {
            text: pane.measurement.status === "recording" ? "Measuring; reconnects in 30 s" : "Measure in 30 s"
            tooltipText: "Reconnects the view after 30 seconds to read Moonlight's decoder summary; host apps stay open"
            enabled: !pane.overlay.busy && !!pane.runtime.window && !!(pane.quality.current || {}).quality_parser && pane.measurement.status !== "recording"
            onClicked: pane.overlay.streamAction("measure", pane.source.computer)
          }
          Muted { visible: !!pane.quality.collection_reason; text: pane.quality.collection_reason || "" }
          Label { text: "How does text look at this size?" }
          Flow {
            width: pane.width
            spacing: Style.spacing.sm
            Repeater {
              model: [{ label: "Readable", value: "readable" }, { label: "Too small", value: "too-small" }, { label: "Blurry", value: "blurry" }]
              Action {
                required property var modelData
                text: modelData.label
                selected: pane.quality.readability === modelData.value
                enabled: !pane.overlay.busy && !!pane.runtime.window
                onClicked: pane.overlay.rateReadability(pane.source.computer, modelData.value)
              }
            }
          }
          Muted { text: "Timing measures when the window is ready, not its first frame; end-to-end latency is not available." }
        }

        Muted { visible: pane.details; text: JSON.stringify(pane.runtime, null, 2) }
      }

      Muted { visible: pane.sel !== null && pane.sel.spacer === true; text: "A spacer never holds windows." }
    }
  }

  // ------------------------------------------- what else it could hold

  Section {
    visible: pane.usable && pane.sel !== null && pane.sel.spacer !== true
    title: "CHANGE TO"

    Column {
      width: pane.width
      spacing: Style.spacing.sm

      Column {
        width: pane.width
        spacing: Style.spacing.xxs
        ListRow {
          text: "Local windows"
          trait: "by fill order"
          current: pane.source === null || (pane.source.type === "local" && !pane.source.app_class)
          onClicked: pane.overlay.assignContent("local")
        }
        ListRow {
          text: "Empty"
          trait: "nothing opens here"
          current: pane.source !== null && pane.source.type === "empty"
          onClicked: pane.overlay.assignContent("empty")
        }
      }

      Repeater {
        model: pane.computers
        Column {
          id: computer
          required property var modelData
          width: pane.width
          spacing: Style.spacing.xxs
          Label { text: computer.modelData.computer; topPadding: Style.spacing.xs; bottomPadding: Style.spacing.xxs }
          Repeater {
            model: computer.modelData.profiles
            ListRow {
              required property var modelData
              text: modelData.name
              trait: Content.traits(modelData)
              current: pane.isStream && pane.source.computer === computer.modelData.computer && pane.source.profile === modelData.name
              onClicked: pane.overlay.assignContent("stream", computer.modelData.computer, modelData.name)
            }
          }
        }
      }
      Muted {
        visible: pane.computers.length === 0
        text: "No computers configured. Pair one in Moonlight and add it to ~/.config/hypertile/computers.json."
      }

      Column {
        visible: pane.overlay.contentWindowClasses.length > 0
        width: pane.width
        spacing: Style.spacing.xxs
        Label { text: "Open apps"; topPadding: Style.spacing.xs; bottomPadding: Style.spacing.xxs }
        Repeater {
          model: pane.overlay.contentWindowClasses
          ListRow {
            required property string modelData
            text: modelData
            trait: "one window"
            current: pane.source !== null && pane.source.type === "local" && pane.source.app_class === modelData
            onClicked: pane.overlay.assignContent("local", "", "", modelData)
          }
        }
      }
    }
  }
}
