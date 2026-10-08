import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Geometry.js" as Geometry
import "Editor.js" as Editor
import "Content.js" as Content
import "Session.js" as Session

// The inspector rail: the name and actions of what is being looked at on
// top, then the sections for the current mode. The Layouts tab shows the
// layout list and, collapsed, the workspaces to put the layout on; the
// rarer layout actions sit in its ⋯ menu. The Scenes tab (ContentPane)
// shows what each zone of the workspace holds and the saved scenes. Edit
// mode shows the selected zone's name, size and what it holds, then
// (collapsed by default) its other options, the apps pinned to it, and the
// layout's appearance and behaviour. Preferences live behind the gear
// (SettingsPanel); the keys are shown on request (?).
Card {
  id: rail
  property real maxHeight: 100000
  readonly property string nameText: nameField.text
  // The Scenes tab's picker: what is typed into its search, and the keys
  // that drive it from the overlay and its IPC.
  readonly property string searchText: contentPane.query
  readonly property int matchCount: contentPane.matchCount
  function handleSceneKey(event) { return contentPane.handleSceneKey(event) }
  function focusSearch() { contentPane.focusSearch() }
  function setSearch(text) { contentPane.setQuery(text) }
  function typeSearch(text) { contentPane.typeSearch(text) }
  function pickMatch() { contentPane.pickMatch() }
  function hoverMatch(index) { contentPane.hoverMatch(index) }

  function revealItem(item) {
    var top = item.mapToItem(column, 0, 0).y
    var bottom = top + item.height
    if (top < scroller.contentY) scroller.contentY = top
    else if (bottom > scroller.contentY + scroller.height) scroller.contentY = bottom - scroller.height
  }
  Connections {
    target: rail.overlay
    function onPendingSwitchChanged() {
      if (rail.overlay.pendingSwitch) Qt.callLater(function() { rail.revealItem(switchPrompt) })
    }
  }

  // Put the cursor in the layout-name field, preloaded with `initial`.
  function focusName(initial) {
    nameField.text = initial
    Qt.callLater(function() { nameField.forceActiveFocus(); nameField.selectAll() })
  }

  // "Paused since 5:17 PM" today, with the date once it is older.
  function sinceText(seconds) {
    var d = new Date(Number(seconds) * 1000)
    var now = new Date()
    var sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
    var when = Qt.formatTime(d, "HH:mm")
    if (!sameDay) when = Qt.formatDate(d, Locale.ShortFormat) + " " + when
    return "Paused since " + when
  }

  function focusWidth() {
    Qt.callLater(function() { widthField.field.field.forceActiveFocus(); widthField.field.field.selectAll() })
  }

  readonly property color fg: overlay.foreground
  readonly property color accent: overlay.accent
  readonly property string family: overlay.fontFamily
  readonly property int pad: overlay.uiPad
  readonly property var sel: overlay.selectedZone
  readonly property var draft: overlay.draft
  readonly property real cap: (draft && draft.capacity && overlay.selected !== "" && draft.capacity[overlay.selected]) ? draft.capacity[overlay.selected] : 0
  readonly property var gaps: (draft && draft.gaps) ? draft.gaps : ({})
  readonly property int globalIn: overlay.current ? overlay.current.gaps_in : 0
  readonly property int globalOut: (overlay.current && overlay.current.gaps_out) ? overlay.current.gaps_out.top : 0
  readonly property int globalBorder: overlay.current ? overlay.current.border_size : 0
  readonly property int innerGap: gaps.inner !== undefined ? gaps.inner : globalIn
  readonly property int outerGap: gaps.outer !== undefined ? gaps.outer : globalOut
  readonly property bool borderSet: draft && draft.border !== undefined
  readonly property int borderPx: borderSet ? draft.border : globalBorder
  readonly property bool inspecting: overlay.editing && !overlay.numbering
  // The Scenes tab's header: the workspace's scene, if the catalog is in.
  readonly property var scene: (overlay.contentCatalog && overlay.contentCatalog.current) ? overlay.contentCatalog.current : null
  readonly property bool sceneNamed: !!(scene && scene.document && scene.document.name && ["none", "restored"].indexOf(scene.phase) === -1)
  readonly property bool sceneModified: Content.sceneModified(scene)
  readonly property bool contentReady: overlay.contentCatalog !== null && !overlay.catalogFailed && overlay.viewedIsActive && !overlay.viewedIsBuiltin
  readonly property bool scenesTab: overlay.contentMode && !overlay.editing
  readonly property string widthTarget: (sel && draft) ? Editor.extentTarget(draft, sel.name, "w") : ""
  readonly property string heightTarget: (sel && draft) ? Editor.extentTarget(draft, sel.name, "h") : ""
  // What the selected zone holds: "windows", "one" (never split) or "nothing" (a spacer).
  readonly property string selHolds: !sel ? "windows" : (sel.spacer ? "nothing" : (sel.neverSplit ? "one" : "windows"))
  readonly property bool roundingSet: !!draft && draft.rounding !== undefined
  readonly property int roundingPx: roundingSet ? draft.rounding : (overlay.current ? (overlay.current.rounding || 0) : 0)
  // The collapsed sections say what they hold that is not the default.
  readonly property string moreSummary: {
    if (!sel) return ""
    var bits = []
    if (!sel.neverSplit && sel.stack === "h") bits.push("side by side")
    if (!sel.neverSplit && cap > 0) bits.push("up to " + cap)
    if (sel.aspect) bits.push(overlay.aspectLabel(sel.aspect))
    if (sel.scale) bits.push(Math.round(sel.scale * 100) + "%")
    return bits.length ? bits.join("  ·  ") : "stack, capacity, aspect, scale"
  }
  readonly property string behaviourSummary: {
    if (!draft) return ""
    var bits = []
    if (draft.empty === "keep") bits.push("keeps empty zones")
    if (draft.single === "slot") bits.push("lone window stays")
    return bits.length ? bits.join("  ·  ") : "empty zones, a lone window"
  }

  // PanelSlider colors itself from a bar; hand it the rail's palette.
  readonly property QtObject palette: QtObject {
    readonly property color foreground: rail.fg
    readonly property color background: Commons.Color.menu.background
    readonly property string fontFamily: rail.family
  }

  readonly property var keyHints: {
    if (overlay.naming || overlay.namingScene) return [["Enter", "save"], ["Esc", "cancel"]]
    if (overlay.renaming) return [["Enter", "rename"], ["Esc", "cancel"]]
    if (overlay.contentMode) return [["↑ ↓ (no zone)", "select scene"], ["Enter / Delete", "use / delete selected scene"], ["click / ← →", "select zone"], ["Tab", "next zone (keep search)"], ["1 – 9 (outside search)", "zone by number"], ["type", "search apps"], ["↑ ↓ (search)", "pick a match"], ["Enter (search)", "assign match"], ["Esc", "clear the search, else close"], ["?", "hide keys"]]
    if (overlay.numbering) return [["click", "next in order"], ["click again", "stack"], ["Backspace", "undo"], ["Enter", "done"]]
    if (overlay.editing) return [["click / ← → ↑ ↓", "select zone"], ["Shift + arrows", "resize 1%"], ["Tab", "next zone"], ["drag", "resize"], ["c", "split columns"], ["r", "split rows"], ["x / right-click", "delete"], ["s", "holds nothing (spacer)"], ["f", "fill order"], ["u", "undo"], ["Space", "hold to peek"], ["w / Ctrl+S", "save"], ["Esc", "done"], ["?", "hide keys"]]
    return [["← → ↑ ↓ / hjkl", "browse layouts"], ["Super+L / Shift+Super+L", "next / previous layout"], ["Enter", "use and close"], ["Space", "hold to peek"], ["e", "edit"], ["n", "new"], ["F2", "rename"], ["d", "delete"], ["r", "refresh"], ["Esc", "close"], ["?", "hide keys"]]
  }

  // How windows fill the viewed layout, for the header.
  readonly property string fillText: {
    if (overlay.editing || overlay.contentMode || !overlay.viewed || !overlay.viewed.spec) return ""
    var spec = overlay.viewed.spec
    var count = Array.isArray(spec.fill) ? spec.fill.length : overlay.zones.length
    if (count === 1) return "Every window shares zone 1"
    var s = "Windows fill zones 1 to " + count + " in order"
    var c = Geometry.cycleSummary(spec)
    if (c !== "") s += ", " + c
    return s
  }

  // Workspaces the viewed layout is on, for the APPLY TO header.
  readonly property string usedOnText: {
    if (!overlay.viewed) return ""
    var ids = []
    for (var i = 0; i < overlay.workspaces.length; i++) {
      var w = overlay.workspaces[i]
      if (String(w.effective_layout || w.layout) === overlay.layoutTarget(overlay.viewed)) ids.push(w.id)
    }
    if (ids.length === 0) return "not in use"
    return (ids.length === 1 ? "workspace " : "workspaces ") + ids.join(", ")
  }

  readonly property string metaText: {
    if (overlay.naming || overlay.renaming || overlay.namingScene) return "Letters, digits, _ and - only"
    if (overlay.numbering) return "Click zones in the order windows should fill them"
    if (overlay.contentMode) {
      if (overlay.catalogFailed || overlay.contentCatalog === null) return ""
      if (!overlay.viewedIsActive) return (overlay.current && overlay.current.workspace) ? "Workspace " + overlay.workspaceId + " uses " + String(overlay.current.workspace.layout).replace(/^lua:/, "") : ""
      return Content.sceneMeta(rail.scene, overlay.viewed ? overlay.viewed.name : "", overlay.workspaceId)
    }
    if (overlay.editing) {
      if (overlay.managedContent) return "Preview off: assigned content stays put" + (overlay.draftIsNew ? " · save, then choose Use" : " · saving applies")
      var s = overlay.workspaceId !== "" ? "Previewing on workspace " + overlay.workspaceId : "Previewing"
      if (overlay.draftIsNew) s += "  ·  new layout"
      return s
    }
    if (!overlay.viewed) return "No layouts in ~/.config/hypr/layouts yet"
    var m = ""
    if (overlay.workspaceId !== "") {
      if (overlay.liveLayout !== "" && overlay.liveLayout !== overlay.committedLayout)
        m = "Previewing on workspace " + overlay.workspaceId + " · Enter keeps it, Esc puts " + overlay.committedLayout.replace(/^lua:/, "") + " back"
      else if (overlay.viewedIsActive) m = "In use on workspace " + overlay.workspaceId
      else m = "Workspace " + overlay.workspaceId + " uses " + overlay.committedLayout.replace(/^lua:/, "")
    }
    if (overlay.viewedIsDefault) m += (m !== "" ? "  ·  " : "") + "default layout"
    if (!overlay.viewedInCycle) m += (m !== "" ? "  ·  " : "") + "not in the SUPER+L cycle"
    return m
  }

  width: overlay.railWidth
  height: Math.min(maxHeight, column.implicitHeight + pad * 2)
  accented: overlay.editing
  Behavior on height { NumberAnimation { duration: overlay.motion; easing.type: Easing.OutCubic } }

  // ---------------------------------------------------------- pieces

  component Label: Text {
    textFormat: Text.PlainText
    color: rail.overlay.mutedForeground
    font.family: rail.family
    font.pixelSize: overlay.uiCaption
    font.bold: true
  }

  component Muted: Text {
    textFormat: Text.PlainText
    width: column.width
    wrapMode: Text.WordWrap
    color: rail.overlay.mutedForeground
    font.family: rail.family
    font.pixelSize: overlay.uiCaption
  }

  component Body: Text {
    textFormat: Text.PlainText
    width: column.width
    wrapMode: Text.WordWrap
    color: rail.fg
    font.family: rail.family
    font.pixelSize: overlay.uiFontSmall
  }

  // The overlay's button (KitButton): `primary` marks the one main action.
  component Action: KitButton {
    overlay: rail.overlay
    foreground: rail.fg
    accent: rail.accent
    fontFamily: rail.family
  }

  // One line of the ⋯ menu: a verb on the left, its key on the right.
  component MenuRow: Button {
    id: menuRow
    property string keyText: ""
    property bool danger: false
    width: parent ? parent.width : implicitWidth
    leftAlign: true
    bordered: false
    radius: overlay.radiusControl
    foreground: danger ? Commons.Color.urgent : rail.fg
    accent: rail.accent
    fontFamily: rail.family
    fontSize: overlay.uiFontSmall
    opacity: enabled ? 1 : 0.45
    Text {
      visible: menuRow.keyText !== ""
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.lg
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: menuRow.keyText
      color: rail.overlay.mutedForeground
      font.family: rail.family
      font.pixelSize: overlay.uiCaption
    }
  }

  // A section header; collapsible ones show a chevron and toggle on click.
  // An action ("+ New") sits on the right in place of the detail.
  component SectionHeader: Item {
    id: sh
    property string text: ""
    property string detail: ""
    property bool collapsible: false
    property bool open: true
    property string actionText: ""
    property string actionHint: ""
    property bool actionEnabled: true
    property bool actionSelected: false
    signal toggled()
    signal actionClicked()
    width: column.width
    implicitHeight: Math.max(shTitle.implicitHeight, shDetail.implicitHeight, shAction.visible ? shAction.implicitHeight : 0)
    Row {
      id: shLead
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.sm
      Text {
        visible: sh.collapsible
        textFormat: Text.PlainText
        text: sh.open ? "▾" : "▸"
        color: rail.overlay.mutedForeground
        font.family: rail.family
        font.pixelSize: overlay.uiCaption
        anchors.verticalCenter: parent.verticalCenter
      }
      PanelSectionHeader {
        id: shTitle
        text: sh.text
        foreground: rail.fg
        fontFamily: rail.family
        fontSize: overlay.uiCaption
        anchors.verticalCenter: parent.verticalCenter
      }
    }
    Text {
      id: shDetail
      visible: sh.actionText === ""
      textFormat: Text.PlainText
      text: sh.detail
      color: rail.overlay.mutedForeground
      font.family: rail.family
      font.pixelSize: overlay.uiCaption
      elide: Text.ElideRight
      width: Math.max(0, Math.min(implicitWidth, parent.width - shLead.implicitWidth - Style.spacing.lg * 2))
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea {
      anchors.fill: parent
      enabled: sh.collapsible
      cursorShape: Qt.PointingHandCursor
      onClicked: sh.toggled()
    }
    Action {
      id: shAction
      visible: sh.actionText !== ""
      text: sh.actionText
      tooltipText: sh.actionHint
      enabled: sh.actionEnabled
      selected: sh.actionSelected
      bordered: false
      fontSize: overlay.uiCaption
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      onClicked: sh.actionClicked()
    }
  }

  component Section: Column {
    id: section
    property alias title: header.text
    property alias detail: header.detail
    property alias actionText: header.actionText
    property alias actionHint: header.actionHint
    property alias actionEnabled: header.actionEnabled
    property alias actionSelected: header.actionSelected
    property bool collapsible: false
    property bool open: true
    signal toggled()
    signal actionClicked()
    width: column.width
    spacing: Style.spacing.lg
    PanelSeparator { foreground: rail.fg; width: column.width }
    SectionHeader { id: header; collapsible: section.collapsible; open: section.open; onToggled: section.toggled(); onActionClicked: section.actionClicked() }
  }

  // A caption above a control.
  component Field: Column {
    id: field
    property string label: ""
    default property alias content: holder.data
    width: column.width
    spacing: Style.spacing.labelGap
    Label { text: field.label }
    Item {
      id: holder
      width: parent.width
      implicitHeight: childrenRect.height
      height: implicitHeight
    }
  }

  // A labelled slider with its value and an optional reset on the right.
  component SliderField: Column {
    id: sf
    property string label: ""
    property string valueText: ""
    property bool overridden: false
    property string resetLabel: "Reset"
    property string resetHint: "Back to the global value"
    property real minimum: 0
    property real maximum: 1
    property real step: 0.05
    property bool integer: false
    property real value: 0
    property bool undoStarted: false
    function changeValue(value, released) {
      if (!undoStarted) { undoStarted = true; dragStarted() }
      changed(value)
      if (released) undoStarted = false
    }
    signal dragStarted()
    signal changed(real value)   // every step of a drag, and its end
    signal reset()
    width: column.width
    spacing: Style.spacing.xs
    Item {
      width: parent.width
      implicitHeight: Math.max(sfLabel.implicitHeight, sfRow.implicitHeight)
      Label { id: sfLabel; text: sf.label; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter }
      Row {
        id: sfRow
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.spacing.sm
        Text {
          textFormat: Text.PlainText
          text: sf.valueText
          color: rail.fg
          font.family: rail.family
          font.pixelSize: overlay.uiFontSmall
          font.bold: true
          anchors.verticalCenter: parent.verticalCenter
        }
        Action { visible: sf.overridden; text: sf.resetLabel; tooltipText: sf.resetHint; fontSize: overlay.uiCaption; onClicked: sf.reset() }
      }
    }
    PanelSlider {
      width: parent.width
      bar: rail.palette
      minimum: sf.minimum
      maximum: sf.maximum
      step: sf.step
      integer: sf.integer
      value: sf.value
      trackHeight: Math.max(4, Math.round(overlay.uiFontSmall * 0.28))
      knobSize: Math.max(14, Math.round(overlay.uiFontSmall * 0.85))
      onDraggingChanged: if (dragging) sf.undoStarted = false
      onMoved: function(v) { sf.changeValue(v, false) }
      onReleased: function(v) { sf.changeValue(v, true) }
    }
  }

  component Switch: Toggle {
    width: column.width
    radius: overlay.radiusControl
    rounded: true
    foreground: rail.fg
    accent: rail.accent
    fontFamily: rail.family
    titleSize: overlay.uiFontSmall
    descriptionSize: overlay.uiCaption
  }

  // A row of exclusive choices; the selected one reads as pressed. Wraps
  // when the options outgrow the rail (the aspect presets do).
  component Choice: Flow {
    id: choice
    property var options: []
    property string value: ""
    signal changed(string value)
    width: column.width
    spacing: Style.spacing.md
    Repeater {
      model: choice.options
      Action {
        required property var modelData
        horizontalPadding: Style.spacing.lg
        text: modelData.label
        selected: String(modelData.value) === choice.value
        onClicked: choice.changed(String(modelData.value))
      }
    }
  }

  component KeyHint: Item {
    id: hint
    property string keys: ""
    property string label: ""
    width: column.width
    implicitHeight: Math.max(keyBox.height, hintText.implicitHeight)
    Rectangle {
      id: keyBox
      width: Math.min(keyText.implicitWidth + Style.space(10), hint.width * 0.62)
      height: keyText.implicitHeight + Style.space(4)
      radius: overlay.radiusControl
      color: Util.alpha(rail.fg, 0.08)
      border.width: 1
      border.color: Util.alpha(rail.fg, 0.28)
      anchors.verticalCenter: parent.verticalCenter
      Text {
        id: keyText
        anchors.centerIn: parent
        width: parent.width - Style.space(10)
        textFormat: Text.PlainText
        text: hint.keys
        color: rail.fg
        font.family: rail.family
        font.pixelSize: overlay.uiCaption
        font.bold: true
        wrapMode: Text.WordWrap
      }
    }
    Text {
      id: hintText
      anchors.left: keyBox.right
      anchors.leftMargin: Style.spacing.md
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: hint.label
      color: rail.overlay.mutedForeground
      font.family: rail.family
      font.pixelSize: overlay.uiCaption
      wrapMode: Text.WordWrap
    }
  }

  // A tinted card for a question: delete, discard, new.
  component Prompt: Rectangle {
    id: prompt
    property bool warning: false
    default property alias content: promptColumn.data
    width: column.width
    implicitHeight: promptColumn.implicitHeight + Style.spacing.xl * 2
    height: implicitHeight
    radius: overlay.radiusControl
    color: Util.alpha(warning ? Commons.Color.urgent : rail.accent, 0.08)
    border.width: 1
    border.color: Util.alpha(warning ? Commons.Color.urgent : rail.accent, 0.6)
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
    color: rail.fg
    font.family: rail.family
    font.pixelSize: overlay.uiFontSmall
    font.bold: true
  }

  // A percentage field for the selected zone's size on one axis.
  component PercentField: Row {
    id: pf
    property string label: ""
    property int value: 0
    property string target: ""      // "zone", "column", "row", "group", or "" (not resizable)
    property alias field: pfNumber
    signal committed(int value)
    spacing: Style.spacing.md
    Label { text: pf.label; width: overlay.uiFont * 3; anchors.verticalCenter: parent.verticalCenter }
    NumberField {
      id: pfNumber
      value: pf.value
      from: 1
      to: 100
      enabled: pf.target !== ""
      opacity: enabled ? 1 : 0.45
      foreground: rail.fg
      accent: rail.accent
      fontFamily: rail.family
      fontSize: overlay.uiFontSmall
      fieldWidth: overlay.uiFont * 4.5
      Component.onCompleted: field.background.radius = overlay.radiusControl
      onModified: function(v) { pf.committed(v) }
      anchors.verticalCenter: parent.verticalCenter
    }
    Muted {
      width: column.width - overlay.uiFont * 7.5 - Style.spacing.md * 2
      text: pf.target === "" ? "% · set by the layout" : (pf.target === "zone" ? "% of the screen" : "% · sizes its " + pf.target)
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  // ---------------------------------------------------------- content

  Flickable {
    id: scroller
    anchors.fill: parent
    anchors.margins: rail.pad
    contentWidth: width
    contentHeight: column.implicitHeight
    clip: true
    interactive: contentHeight > height
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: column
      width: scroller.width
      spacing: Style.spacing.xl

      // ---- Header: tabs or mode, name, meta, actions.
      Column {
        width: column.width
        spacing: Style.spacing.sm

        Item {
          width: parent.width
          implicitHeight: Math.max(eyebrow.implicitHeight, tabs.implicitHeight, headerTools.implicitHeight)
          Label {
            id: eyebrow
            visible: !tabs.visible
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: overlay.naming ? "SAVE AS"
              : overlay.renaming ? "RENAME"
              : overlay.namingScene ? "SAVE SCENE AS"
              : overlay.numbering ? "FILL ORDER"
              : overlay.editing ? (overlay.draftIsNew ? "NEW LAYOUT" : "EDITING")
              : "HYPERTILE"
          }
          // The three things the overlay can be about: the layouts (browsed
          // with the arrows, the windows follow), the scenes (what each zone
          // of the workspace holds) and the displays.
          Row {
            id: tabs
            visible: !overlay.editing && !overlay.naming && !overlay.renaming && !overlay.namingScene
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            Action { text: "Layouts"; horizontalPadding: 4; bordered: false; selected: !overlay.contentMode; tooltipText: "Browse and edit the layouts"; onClicked: overlay.showContent(false) }
            Action { text: "Scenes"; horizontalPadding: 4; bordered: false; selected: overlay.contentMode; tooltipText: "What each zone holds: any window, a remote desktop, an app; saved as scenes"; onClicked: overlay.showContent(true) }
            Action { text: "Displays"; horizontalPadding: 4; bordered: false; tooltipText: "Arrange displays, their wallpaper and where workspaces live"; onClicked: overlay.showDisplays() }
          }
          Row {
            id: headerTools
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm
            Action {
              text: "\u{F0493}"
              bordered: false
              horizontalPadding: 4
              focusable: true
              selected: overlay.barSettingsOpen
              Accessible.name: "Settings"
              tooltipText: "Settings: startup, rail side, keys, menu bar, text size"
              onClicked: overlay.showSettings()
              anchors.verticalCenter: parent.verticalCenter
            }
            Action {
              text: "?"
              horizontalPadding: 4
              selected: overlay.showKeys
              bordered: false
              fontSize: overlay.uiFontSmall
              tooltipText: overlay.showKeys ? "Hide the keys (?)" : "Show the keys (?)"
              onClicked: overlay.setPref("showKeys", !overlay.showKeys)
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        Item {
          visible: !overlay.naming && !overlay.renaming && !overlay.namingScene
          width: parent.width
          implicitHeight: Math.max(titleText.implicitHeight, titleStatus.implicitHeight)
          Text {
            id: titleText
            anchors.left: parent.left
            anchors.right: titleStatus.left
            anchors.rightMargin: Style.spacing.sm
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: overlay.editing ? overlay.draftName
              : overlay.contentMode ? ((overlay.catalogFailed || overlay.contentCatalog === null) ? "Scenes" : Content.sceneTitle(rail.scene, overlay.workspaceId))
              : (overlay.viewed ? overlay.viewed.name : "No layouts")
            color: rail.accent
            font.family: rail.family
            font.pixelSize: overlay.uiTitle
            font.bold: true
            elide: Text.ElideRight
          }
          Row {
            id: titleStatus
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm
            Label {
              visible: !overlay.editing && !overlay.contentMode && overlay.layouts.length > 0
              text: (overlay.viewIndex + 1) + " / " + overlay.layouts.length
              anchors.verticalCenter: parent.verticalCenter
            }
            Chip {
              visible: (overlay.editing && overlay.dirty) || (rail.scenesTab && rail.sceneModified)
              text: overlay.editing ? "unsaved" : "modified"
              foreground: rail.fg
              fontFamily: rail.family
              fontSize: overlay.uiCaption
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        TextField {
          id: nameField
          visible: overlay.naming || overlay.renaming || overlay.namingScene
          width: parent.width
          foreground: rail.fg
          accent: rail.accent
          font.family: rail.family
          font.pixelSize: overlay.uiFont
          placeholderText: overlay.namingScene ? "scene name" : "layout name"
          Component.onCompleted: background.radius = overlay.radiusControl
          Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { overlay.renaming ? overlay.confirmRename() : overlay.namingScene ? overlay.confirmSceneName() : overlay.confirmName(); event.accepted = true }
            else if (event.key === Qt.Key_Escape) { overlay.naming = false; overlay.renaming = false; overlay.namingScene = false; overlay.errorText = ""; overlay.focusKeys(); event.accepted = true }
          }
        }

        Muted { text: rail.metaText; visible: text !== "" }
        Muted { visible: rail.fillText !== "" && !overlay.renaming; text: rail.fillText }
        Muted { visible: !overlay.editing && !overlay.contentMode && overlay.viewedIsBuiltin; text: "Dwindle automatically splits space as windows open. Its layout is managed by Hyprland." }
        Muted { visible: rail.scenesTab && rail.scene !== null && !!rail.scene.error; text: rail.scene ? (rail.scene.error || "") : ""; color: Commons.Color.urgent }
        Muted { visible: rail.scenesTab && rail.scene !== null && (rail.scene.phase === "partial" || rail.scene.phase === "needs-attention"); text: Content.retrySummary(rail.scene) }

        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          topPadding: Style.spacing.xs

          // the Layouts tab: the main verbs, the rest in the ⋯ menu
          Action { visible: !overlay.editing && !overlay.renaming && !overlay.contentMode && !overlay.viewedIsActive; text: "Use"; primary: true; tooltipText: "Use on this workspace and close (Enter)"; enabled: overlay.viewed !== null && !overlay.busy; onClicked: overlay.applyViewed(true) }
          Action { visible: !overlay.editing && !overlay.renaming && !overlay.contentMode; text: "Edit"; tooltipText: overlay.viewedIsBuiltin ? "Dwindle is Hyprland's own; start a new layout instead (n)" : "Edit this layout (e)"; enabled: overlay.viewed !== null && !overlay.viewedIsBuiltin; onClicked: overlay.startEdit(false) }
          Action {
            visible: !overlay.editing && !overlay.renaming && !overlay.contentMode
            text: "⋯"
            selected: overlay.showingMore
            Accessible.name: "More layout actions"
            tooltipText: "Rename, duplicate, export, the SUPER+L cycle, delete"
            enabled: overlay.viewed !== null
            onClicked: { overlay.confirmingDelete = false; overlay.choosingNew = false; overlay.showingMore = !overlay.showingMore }
          }
          // the Scenes tab
          Action { visible: rail.scenesTab && !overlay.namingScene && rail.sceneNamed; text: "Save"; primary: rail.sceneModified; tooltipText: rail.sceneModified ? "Save the changes to " + rail.scene.document.name : "Saved"; enabled: rail.sceneModified && !overlay.busy; onClicked: overlay.saveScene(rail.scene.document.name) }
          Action { visible: rail.scenesTab && !overlay.namingScene && rail.contentReady; text: rail.sceneNamed ? "Save as…" : "Save as scene…"; tooltipText: "Save this workspace's layout and content under a name"; enabled: !overlay.busy; onClicked: overlay.startSceneSave() }
          Action { visible: rail.scenesTab && !overlay.namingScene && rail.scene !== null && rail.scene.can_restore === true && ["restored", "none"].indexOf(rail.scene.phase) === -1; text: "Restore previous"; tooltipText: "Put back the layout and content the workspace had before the scene"; enabled: !overlay.busy; onClicked: overlay.sceneAction("restore") }
          Action { visible: rail.scenesTab && !overlay.namingScene && rail.scene !== null && (rail.scene.phase === "partial" || rail.scene.phase === "needs-attention"); text: "Retry"; tooltipText: Content.retrySummary(rail.scene); enabled: !overlay.busy; onClicked: overlay.sceneAction("retry") }
          Action { visible: rail.scenesTab && !overlay.namingScene && rail.scene !== null && rail.scene.can_dismiss === true; text: "Dismiss"; tooltipText: "Forget this scene and release its zone assignments; keep the layout and open apps"; enabled: !overlay.busy; onClicked: overlay.sceneAction("dismiss") }
          // naming a scene
          Action { visible: overlay.namingScene; text: "Save"; primary: true; onClicked: overlay.confirmSceneName() }
          Action { visible: overlay.namingScene; text: "Cancel"; onClicked: { overlay.namingScene = false; overlay.errorText = ""; overlay.focusKeys() } }
          // edit mode
          Action { visible: overlay.editing && !overlay.naming; text: "Save"; primary: true; tooltipText: "Save to ~/.config/hypr/layouts (w)"; enabled: !overlay.busy; onClicked: overlay.requestSave() }
          Action { visible: overlay.editing && !overlay.naming; text: "Undo"; tooltipText: "Undo (u)"; enabled: overlay.undoStack.length > 0; onClicked: overlay.undo() }
          Action { visible: overlay.editing && !overlay.naming; text: overlay.numbering ? "Done numbering" : "Fill order"; selected: overlay.numbering; tooltipText: "Click zones in the order windows fill them (f)"; onClicked: overlay.numbering ? overlay.finishNumbering() : overlay.startNumbering() }
          Action { visible: overlay.editing && !overlay.naming && !overlay.confirmingDiscard; text: overlay.dirty ? "Discard" : "Done"; accent: overlay.dirty ? Commons.Color.urgent : rail.accent; tooltipText: overlay.dirty ? "Drop the changes (Esc)" : "Back to browsing (Esc)"; enabled: !overlay.busy; onClicked: overlay.dirty ? (overlay.confirmingDiscard = true) : overlay.leaveEdit("") }
          // naming
          Action { visible: overlay.naming; text: "Save as"; primary: true; onClicked: overlay.confirmName() }
          Action { visible: overlay.naming; text: "Cancel"; onClicked: { overlay.naming = false; overlay.focusKeys() } }
          // renaming
          Action { visible: overlay.renaming; text: "Rename"; primary: true; onClicked: overlay.confirmRename() }
          Action { visible: overlay.renaming; text: "Cancel"; onClicked: { overlay.renaming = false; overlay.errorText = ""; overlay.focusKeys() } }
        }
      }

      // ---- View mode: the viewed layout's rarer actions (⋯).
      Rectangle {
        id: moreMenu
        visible: !overlay.editing && !overlay.contentMode && !overlay.renaming && overlay.showingMore && overlay.viewed !== null
        width: column.width
        implicitHeight: moreColumn.implicitHeight + Style.spacing.sm * 2
        height: implicitHeight
        radius: overlay.radiusControl
        color: Util.alpha(rail.fg, 0.04)
        border.width: 1
        border.color: Util.alpha(rail.fg, 0.22)
        Column {
          id: moreColumn
          x: Style.spacing.sm
          y: Style.spacing.sm
          width: parent.width - Style.spacing.sm * 2
          spacing: Style.spacing.xxs
          MenuRow {
            text: "Rename…"
            keyText: "F2"
            enabled: overlay.viewed !== null && !overlay.viewedIsBuiltin && !overlay.busy
            onClicked: overlay.startRename()
          }
          MenuRow {
            text: "Duplicate"
            keyText: "n, c"
            tooltipText: "Start a new layout from a copy of this one"
            enabled: overlay.viewed !== null && !overlay.viewedIsBuiltin && overlay.current !== null
            onClicked: overlay.startEdit(true, false)
          }
          MenuRow {
            text: "Export…"
            tooltipText: "Save this layout to a JSON file to share it"
            enabled: overlay.viewed !== null && !overlay.viewedIsBuiltin && !overlay.busy && !overlay.transferDialogOpen
            onClicked: overlay.chooseExport()
          }
          MenuRow {
            id: cycleRow
            text: "In the SUPER+L cycle"
            tooltipText: overlay.viewedInCycle ? "SUPER+L reaches this layout; switch off to skip it" : "SUPER+L skips this layout; the overlay still lists it"
            enabled: overlay.viewed !== null && !overlay.viewedIsBuiltin && !overlay.busy
            onClicked: overlay.setInCycle(!overlay.viewedInCycle)
            ToggleSwitch {
              checked: overlay.viewedInCycle
              interactive: false
              rounded: true
              foreground: rail.fg
              accent: rail.accent
              anchors.right: parent.right
              anchors.rightMargin: Style.spacing.lg
              anchors.verticalCenter: parent.verticalCenter
            }
          }
          PanelSeparator { foreground: rail.fg; width: parent.width }
          MenuRow {
            text: "Delete…"
            keyText: "d"
            danger: true
            tooltipText: overlay.viewedIsDefault ? "The default layout cannot be deleted; make another the default first (Apply to)" : "Delete this layout's file"
            enabled: overlay.viewed !== null && !overlay.viewedIsBuiltin && !overlay.viewedIsDefault && !overlay.busy
            onClicked: { overlay.showingMore = false; overlay.choosingNew = false; overlay.confirmingDelete = true }
          }
        }
      }

      // ---- View mode: confirm a delete.
      Prompt {
        visible: !overlay.editing && !overlay.contentMode && overlay.confirmingDelete && overlay.viewed !== null
        warning: true
        PromptTitle { text: "Delete " + (overlay.viewed ? overlay.viewed.name : "") + "?" }
        Muted {
          width: parent.width
          text: {
            var using = []
            for (var i = 0; i < overlay.workspaces.length; i++)
              if (overlay.viewed && overlay.workspaces[i].layout === overlay.layoutTarget(overlay.viewed)) using.push(overlay.workspaces[i].id)
            var s = "The file in ~/.config/hypr/layouts is removed and Hyprland reloads."
            if (using.length > 0) s += " Workspace " + using.join(", ") + " falls back to the default layout."
            else s += " Any workspace rule that points at it falls back to the default layout."
            return s
          }
        }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { text: "Delete"; accent: Commons.Color.urgent; selected: true; enabled: !overlay.busy; onClicked: overlay.deleteViewed() }
          Action { text: "Cancel"; tooltipText: "Esc"; onClicked: overlay.confirmingDelete = false }
        }
      }

      // ---- First run: what the overlay is for, once.
      Prompt {
        visible: !overlay.coachDismissed && !overlay.editing && !overlay.contentMode && !overlay.renaming && overlay.layouts.length > 0
        PromptTitle { text: "Getting started" }
        Body { width: parent.width; text: "Pick a layout below, or press ← →. Your windows move into it as a preview." }
        Body { width: parent.width; text: "Enter keeps it on this workspace; Esc puts the old one back." }
        Body { width: parent.width; text: "Edit draws your own. Scenes puts apps in zones." }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { text: "Got it"; primary: true; onClicked: overlay.setPref("coachDismissed", true) }
          Action { text: "Show the keys"; visible: !overlay.showKeys; onClicked: overlay.setPref("showKeys", true) }
        }
      }

      // ---- Confirm replacing assigned content or a modified scene.
      Prompt {
        id: switchPrompt
        visible: !overlay.editing && overlay.pendingSwitch !== null
        warning: true
        PromptTitle { text: "Use " + (overlay.pendingSwitch ? (overlay.pendingSwitch.sceneName || overlay.pendingSwitch.layoutName.replace(/^lua:/, "")) : "") + " anyway?" }
        Muted { width: parent.width; text: overlay.switchSummary() }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { text: "Use " + (overlay.pendingSwitch ? (overlay.pendingSwitch.sceneName || overlay.pendingSwitch.layoutName.replace(/^lua:/, "")) : ""); accent: Commons.Color.urgent; selected: true; tooltipText: "Enter"; enabled: !overlay.busy; onClicked: overlay.confirmSwitch() }
          Action { text: "Cancel"; tooltipText: "Esc"; onClicked: overlay.pendingSwitch = null }
        }
      }

      // ---- Session saving, when it needs attention: a notice with its actions.
      Prompt {
        id: sessionNotice
        readonly property bool attention: Session.attention(overlay.sessionStatus, overlay.sessionAvailable, overlay.sessionChecked)
        readonly property var unmatched: (overlay.sessionStatus && overlay.sessionStatus.unmatched) || []
        visible: attention || unmatched.length > 0
        warning: attention
        PromptTitle { text: Session.summary(overlay.sessionStatus, overlay.sessionAvailable, overlay.sessionChecked) }
        Muted {
          width: parent.width
          visible: !!(overlay.sessionStatus && overlay.sessionStatus.saving && overlay.sessionStatus.saving.since)
          text: visible ? rail.sinceText(overlay.sessionStatus.saving.since) : ""
        }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { visible: Session.canResume(overlay.sessionStatus); text: "Resume saving"; primary: true; tooltipText: "Accept the current desktop and resume saving; pending scene delivery keeps retrying"; enabled: !overlay.busy; onClicked: overlay.resumeSession() }
          Action { visible: sessionNotice.unmatched.length > 0; text: overlay.showSessionDetails ? "Hide unmatched" : "Show unmatched"; onClicked: overlay.showSessionDetails = !overlay.showSessionDetails }
        }
        Column {
          width: parent.width
          visible: overlay.showSessionDetails
          spacing: Style.spacing.xs
          Repeater {
            model: overlay.showSessionDetails ? ((overlay.sessionStatus && overlay.sessionStatus.unmatched) || []) : []
            Muted { required property var modelData; width: parent.width; text: modelData.class + (modelData.title ? " — " + modelData.title : "") + ": " + modelData.reason }
          }
        }
      }

      // ---- The Scenes tab: saved scenes, what each zone holds, the selected zone.
      ContentPane {
        id: contentPane
        visible: rail.scenesTab
        width: column.width
        overlay: rail.overlay
        onRevealItem: function(item) { rail.revealItem(item) }
      }

      // ---- Edit mode: unsaved changes.
      Prompt {
        visible: overlay.editing && overlay.confirmingDiscard
        warning: true
        PromptTitle { text: "Unsaved changes to " + overlay.draftName }
        Muted { width: parent.width; text: overlay.draftIsNew ? "Discarding puts the workspace back on the layout it had." : "Discarding puts the saved layout back on the workspace. Nothing reloads." }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { text: "Discard"; accent: Commons.Color.urgent; selected: true; tooltipText: "d"; enabled: !overlay.busy; onClicked: overlay.discard() }
          Action { text: "Save"; primary: true; tooltipText: "w"; enabled: !overlay.busy; onClicked: overlay.requestSave() }
          Action { text: "Keep editing"; tooltipText: "Esc"; onClicked: overlay.confirmingDiscard = false }
        }
      }

      // ---- View mode: every layout on disk, with a picture of each, and
      // the New prompt (blank, a copy, an import).
      Section {
        visible: !overlay.editing && !overlay.contentMode
        title: "LAYOUTS"
        actionText: "+ New"
        actionHint: "New layout: blank, a copy, or an import (n)"
        actionEnabled: overlay.current !== null && !overlay.renaming
        actionSelected: overlay.choosingNew
        onActionClicked: { overlay.confirmingDelete = false; overlay.showingMore = false; overlay.choosingNew = !overlay.choosingNew }

        Prompt {
          visible: overlay.choosingNew
          PromptTitle { text: "Start a new layout from" }
          Flow {
            width: parent.width
            spacing: Style.spacing.sm
            Action { text: "Blank"; primary: true; tooltipText: "One zone filling the screen (b)"; onClicked: overlay.startEdit(true, true) }
            Action { visible: overlay.viewed !== null && !overlay.viewedIsBuiltin; text: "A copy of " + (overlay.viewed ? overlay.viewed.name : ""); tooltipText: "c"; onClicked: overlay.startEdit(true, false) }
            Action { text: "Import…"; tooltipText: "A layout exported to a JSON file, added as a new copy"; enabled: !overlay.busy && !overlay.transferDialogOpen; onClicked: overlay.chooseImport() }
            Action { text: "Cancel"; tooltipText: "Esc"; onClicked: overlay.choosingNew = false }
          }
        }

        Column {
          width: column.width
          spacing: Style.spacing.xs
          Repeater {
            model: overlay.layouts
            Rectangle {
              id: layoutRow
              required property var modelData
              required property int index
              // The Repeater hands delegates a converted copy of the entry; the
              // original object (plain JS arrays inside) is what the helpers expect.
              readonly property var entry: overlay.layouts[index] || modelData
              readonly property bool viewing: index === overlay.viewIndex
              readonly property bool inUse: overlay.committedLayout === overlay.layoutTarget(entry)
              readonly property bool isDefault: overlay.defaultLayout === overlay.layoutTarget(entry)
              readonly property bool inCycle: !(entry.spec && entry.spec.in_cycle === false)
              width: column.width
              implicitHeight: rowContent.implicitHeight + Style.spacing.sm * 2
              height: implicitHeight
              radius: overlay.radiusControl
              color: viewing ? Util.alpha(rail.accent, 0.14) : (rowHover.containsMouse ? Util.alpha(rail.fg, 0.06) : "transparent")
              border.width: viewing ? 1 : 0
              border.color: Util.alpha(rail.accent, 0.6)
              Behavior on color { ColorAnimation { duration: overlay.motionFast } }

              Row {
                id: rowContent
                x: Style.spacing.sm
                y: Style.spacing.sm
                width: parent.width - Style.spacing.sm * 2
                spacing: Style.spacing.lg
                Thumb {
                  overlay: rail.overlay
                  spec: layoutRow.entry.spec
                  current: layoutRow.viewing
                  width: overlay.uiFont * 5
                  anchors.verticalCenter: parent.verticalCenter
                }
                Column {
                  width: parent.width - overlay.uiFont * 5 - Style.spacing.lg
                  spacing: Style.spacing.xxs
                  anchors.verticalCenter: parent.verticalCenter
                  Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: layoutRow.modelData.name
                    color: layoutRow.viewing ? rail.accent : rail.fg
                    font.family: rail.family
                    font.pixelSize: overlay.uiFontSmall
                    font.bold: layoutRow.viewing || layoutRow.inUse
                    elide: Text.ElideRight
                  }
                  Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    visible: text !== ""
                    text: {
                      var bits = []
                      if (layoutRow.inUse) bits.push("in use")
                      if (layoutRow.isDefault) bits.push("default")
                      if (!layoutRow.inCycle) bits.push("not in cycle")
                      var spec = layoutRow.entry.spec
                      if (layoutRow.entry.builtin) { bits.push("built-in"); return bits.join("  ·  ") }
                      var n = Editor.fillableNames(spec).length
                      bits.push(n + (n === 1 ? " zone" : " zones"))
                      return bits.join("  ·  ")
                    }
                    color: rail.overlay.mutedForeground
                    font.family: rail.family
                    font.pixelSize: overlay.uiCaption
                    elide: Text.ElideRight
                  }
                }
              }
              MouseArea {
                id: rowHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: overlay.viewAt(layoutRow.index)
                onDoubleClicked: { overlay.viewAt(layoutRow.index); overlay.applyViewed(true) }
              }
            }
          }
        }
      }

      // ---- View mode: where else the layout can go (collapsed by default).
      Section {
        visible: !overlay.editing && !overlay.contentMode && overlay.viewed !== null && overlay.workspaces.length > 0
        title: "APPLY TO"
        detail: rail.usedOnText
        collapsible: true
        open: overlay.applySectionOpen
        onToggled: overlay.setPref("applySectionOpen", !overlay.applySectionOpen)

        Column {
          visible: overlay.applySectionOpen
          width: column.width
          spacing: Style.spacing.sm

          Repeater {
            model: overlay.workspaces
            Item {
              id: wsRow
              required property var modelData
              readonly property bool uses: overlay.viewed !== null && String(modelData.effective_layout || modelData.layout) === overlay.layoutTarget(overlay.viewed)
              width: column.width
              implicitHeight: Math.max(wsText.implicitHeight, wsControl.implicitHeight)

              Column {
                id: wsText
                anchors.left: parent.left
                anchors.right: wsControl.left
                anchors.rightMargin: Style.spacing.lg
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.xxs
                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  text: "Workspace " + wsRow.modelData.id
                  color: wsRow.uses ? rail.accent : rail.fg
                  font.family: rail.family
                  font.pixelSize: overlay.uiFontSmall
                  font.bold: wsRow.uses
                  elide: Text.ElideRight
                }
                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  id: wsMeta
                  readonly property string compactText: String(wsRow.modelData.windows || 0) + " win  ·  " + String(wsRow.modelData.effective_layout || wsRow.modelData.layout).replace(/^lua:/, "")
                  // Drop the display before sacrificing the window count.
                  text: wsMeasure.advanceWidth <= width ? wsMeasure.text : compactText
                  TextMetrics {
                    id: wsMeasure
                    font: wsMeta.font
                    text: wsMeta.compactText + "  ·  " + wsRow.modelData.monitor
                  }
                  color: rail.overlay.mutedForeground
                  font.family: rail.family
                  font.pixelSize: overlay.uiCaption
                  elide: Text.ElideRight
                }
                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  text: wsRow.modelData.layout_source === "monitor" ? "Follows its display's default"
                    : wsRow.modelData.layout_source === "global" ? "Follows the default layout"
                    : wsRow.modelData.layout_source === "scene" ? "Set by its scene" : "Chosen for this workspace"
                  color: rail.overlay.mutedForeground
                  font.family: rail.family
                  font.pixelSize: overlay.uiCaption
                }
              }
              Item {
                id: wsControl
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: wsRow.uses ? wsStatus.implicitWidth : wsButton.implicitWidth
                implicitHeight: wsRow.uses ? wsStatus.implicitHeight : wsButton.implicitHeight
                Chip {
                  id: wsStatus
                  visible: wsRow.uses
                  text: "In use"
                  foreground: rail.accent
                  fontFamily: rail.family
                  fontSize: overlay.uiCaption
                }
                Action {
                  id: wsButton
                  visible: !wsRow.uses
                  text: "Use"
                  fontSize: overlay.uiCaption
                  tooltipText: "Use " + (overlay.viewed ? overlay.viewed.name : "") + " on workspace " + wsRow.modelData.id + "; the overlay stays open"
                  enabled: !wsRow.uses && !overlay.busy
                  opacity: 1
                  onClicked: overlay.applyTo(wsRow.modelData.id)
                }
              }
            }
          }
        }

        Flow {
          visible: overlay.applySectionOpen
          width: column.width
          spacing: Style.spacing.sm
          Repeater {
            model: overlay.monitors
            Action {
              required property var modelData
              text: monitorLabel.elidedText
              TextMetrics {
                id: monitorLabel
                text: "Every workspace on " + modelData
                font.family: rail.family
                font.pixelSize: overlay.uiCaption
                elide: Qt.ElideRight
                elideWidth: Math.max(0, column.width - overlay.uiFont * 3)
              }
              fontSize: overlay.uiCaption
              tooltipText: "Use it on every workspace now on display " + modelData
              enabled: !overlay.busy
              onClicked: overlay.applyMonitor(modelData)
            }
          }
          Action {
            text: overlay.viewedIsDefault ? "The default layout" : "Make it the default"
            selected: overlay.viewedIsDefault
            fontSize: overlay.uiCaption
            tooltipText: "The default layout is for workspaces with no layout of their own and no display default (general.layout in looknfeel.lua)"
            enabled: !overlay.busy && !overlay.viewedIsDefault
            opacity: 1
            onClicked: overlay.setDefault()
          }
        }
        // The current workspace can drop its own layout choice and follow
        // its display's default. Offered only while it has a choice to drop.
        Column {
          id: inherit
          readonly property var here: {
            for (var i = 0; i < overlay.workspaces.length; i++)
              if (String(overlay.workspaces[i].id) === overlay.workspaceId) return overlay.workspaces[i]
            return null
          }
          readonly property bool inherits: here !== null && ["monitor", "global"].indexOf(here.layout_source) !== -1
          readonly property bool sceneOwned: overlay.contentWorkspace(overlay.workspaceId)
          readonly property string why: sceneOwned ? "Workspace " + overlay.workspaceId + "'s scene owns its layout; replace or restore the scene first."
            : inherits ? "Workspace " + overlay.workspaceId + " already follows its display's default."
            : "Drops the layout chosen for workspace " + overlay.workspaceId + "; it follows its display's default instead."
          visible: overlay.applySectionOpen && overlay.workspaceId !== ""
          width: column.width
          spacing: Style.spacing.xs
          Action {
            text: "Follow the display default"
            width: column.width
            enabled: !overlay.busy && !inherit.sceneOwned && !inherit.inherits
            tooltipText: inherit.why
            onClicked: overlay.applyTo(overlay.workspaceId, "monitor-default")
          }
          Muted { text: inherit.why }
        }
      }

      // ---- Edit mode: renumbering.
      Section {
        visible: overlay.editing && overlay.numbering
        title: "FILL ORDER"
        Body { text: "Click zones in the order windows should fill them. Click a zone again to stack another window there. Zones you skip follow at the end." }
        Flow {
          width: column.width
          spacing: Style.spacing.xs
          Repeater {
            model: overlay.numberingFill
            Chip {
              required property var modelData
              required property int index
              text: (index + 1) + "  " + modelData
              foreground: rail.fg
              fontFamily: rail.family
              fontSize: overlay.uiCaption
            }
          }
          Muted { visible: overlay.numberingFill.length === 0; width: implicitWidth; text: "nothing yet" }
        }
        Flow {
          width: column.width
          spacing: Style.spacing.sm
          Action { text: "Undo click"; tooltipText: "Backspace"; enabled: overlay.numberingFill.length > 0; onClicked: { var next = overlay.numberingFill.slice(); next.pop(); overlay.numberingFill = next } }
          Action { text: "Done"; primary: true; tooltipText: "Enter"; onClicked: overlay.finishNumbering() }
        }
      }

      // ---- Edit mode: the selected zone.
      Section {
        visible: rail.inspecting
        title: "ZONE"
        detail: rail.sel ? rail.sel.name : ""

        Muted { visible: rail.sel === null; text: "Click a zone, or use the arrows, to inspect it." }

        // The zone's card carries these when it has room; a small card does not.
        Flow {
          visible: rail.sel !== null && !overlay.zoneRoomy(rail.sel)
          width: column.width
          spacing: Style.spacing.sm
          Action { text: "Split columns"; tooltipText: "c"; onClicked: overlay.splitSelected("columns") }
          Action { text: "Split rows"; tooltipText: "r"; onClicked: overlay.splitSelected("rows") }
          Action { text: "Delete"; accent: Commons.Color.urgent; tooltipText: "Remove this zone; its neighbours take the room (x, or right-click the zone)"; onClicked: overlay.deleteZone(overlay.selected) }
        }

        Field {
          visible: rail.sel !== null
          label: "Name"
          TextField {
            id: zoneNameField
            width: column.width
            foreground: rail.fg
            accent: rail.accent
            font.family: rail.family
            font.pixelSize: overlay.uiFontSmall
            placeholderText: "zone name"
            text: rail.sel ? rail.sel.name : ""
            Component.onCompleted: background.radius = overlay.radiusControl
            function commit() {
              if (!rail.sel) return
              if (overlay.renameSelected(text)) overlay.focusKeys()
            }
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { commit(); event.accepted = true }
              else if (event.key === Qt.Key_Escape) { text = rail.sel ? rail.sel.name : ""; overlay.focusKeys(); event.accepted = true }
            }
            onEditingFinished: if (rail.sel && text !== rail.sel.name) commit()
          }
        }

        Column {
          visible: rail.sel !== null
          width: column.width
          spacing: Style.spacing.xs
          Label { text: "Size" }
          PercentField {
            id: widthField
            label: "Width"
            value: rail.sel ? rail.sel.pctW : 0
            target: rail.widthTarget
            onCommitted: function(v) { overlay.setSelectedExtent("w", v / 100); overlay.focusKeys() }
          }
          PercentField {
            label: "Height"
            value: rail.sel ? rail.sel.pctH : 0
            target: rail.heightTarget
            onCommitted: function(v) { overlay.setSelectedExtent("h", v / 100); overlay.focusKeys() }
          }
        }

        Field {
          visible: rail.sel !== null
          label: "Holds"
          Column {
            width: column.width
            spacing: Style.spacing.xs
            Choice {
              options: [{ label: "Windows", value: "windows" }, { label: "One window", value: "one" }, { label: "Nothing", value: "nothing" }]
              value: rail.selHolds
              onChanged: function(v) { overlay.zoneHolds(v) }
            }
            Muted {
              text: rail.selHolds === "nothing" ? "An empty gap that never takes windows (s)"
                : rail.selHolds === "one" ? "One window; more overlap it at full size"
                : "More windows split the zone"
            }
          }
        }
      }

      // ---- Edit mode: how windows sit in the selected zone (collapsed by default).
      Section {
        visible: rail.inspecting && rail.sel !== null && !rail.sel.spacer
        title: "MORE OPTIONS"
        detail: overlay.zoneMoreOpen ? "" : rail.moreSummary
        collapsible: true
        open: overlay.zoneMoreOpen
        onToggled: overlay.setPref("zoneMoreOpen", !overlay.zoneMoreOpen)

        Field {
          visible: overlay.zoneMoreOpen && rail.sel !== null && !rail.sel.neverSplit
          label: "Stack"
          Choice {
            options: [{ label: "Vertical", value: "v" }, { label: "Horizontal", value: "h" }]
            value: rail.sel ? rail.sel.stack : "v"
            onChanged: function(v) { overlay.zoneProp("stack", v === ((rail.draft && rail.draft.stack) || "v") ? null : v) }
          }
        }

        Field {
          visible: overlay.zoneMoreOpen && rail.sel !== null && !rail.sel.neverSplit
          label: "Capacity"
          Row {
            spacing: Style.spacing.lg
            NumberField {
              value: rail.cap
              from: 0
              to: 24
              foreground: rail.fg
              accent: rail.accent
              fontFamily: rail.family
              fontSize: overlay.uiFontSmall
              fieldWidth: overlay.uiFont * 5
              Component.onCompleted: field.background.radius = overlay.radiusControl
              onModified: function(v) { overlay.zoneCapacity(v); overlay.focusKeys() }
              anchors.verticalCenter: parent.verticalCenter
            }
            Muted {
              width: column.width - overlay.uiFont * 5 - Style.spacing.lg
              text: rail.cap > 0 ? "windows, then the next zone takes over" : "No limit"
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        Field {
          visible: overlay.zoneMoreOpen && rail.sel !== null
          label: "Aspect"
          Choice {
            options: overlay.aspectPresets.map(function(p) { return { label: p.label, value: p.value === null ? "" : String(p.value) } })
            value: (rail.sel && rail.sel.aspect) ? String(overlay.aspectKey(rail.sel.aspect)) : ""
            onChanged: function(v) { overlay.zoneProp("aspect", v === "" ? null : Math.round(Number(v) * 1000) / 1000) }
          }
        }

        SliderField {
          visible: overlay.zoneMoreOpen && rail.sel !== null
          label: "Scale"
          valueText: Math.round(((rail.sel && rail.sel.scale) || 1) * 100) + "%"
          overridden: rail.sel !== null && rail.sel.scale !== undefined
          resetHint: "Back to 100%"
          minimum: 0.1
          maximum: 1
          step: 0.05
          value: (rail.sel && rail.sel.scale) || 1
          onDragStarted: overlay.pushUndo()
          onChanged: function(v) { overlay.liveZoneProp("scale", v >= 1 ? null : Math.round(v * 100) / 100) }
          onReset: overlay.zoneProp("scale", null)
        }
      }

      // ---- Edit mode: apps routed to the selected zone (collapsed by default).
      Section {
        visible: rail.inspecting && rail.sel !== null && !rail.sel.spacer
        title: "OPENS HERE"
        detail: overlay.selectedRules.length > 0 ? overlay.selectedRules.length + (overlay.selectedRules.length === 1 ? " app" : " apps") : ""
        collapsible: true
        open: overlay.rulesSectionOpen
        onToggled: overlay.setPref("rulesSectionOpen", !overlay.rulesSectionOpen)

        Muted { visible: overlay.rulesSectionOpen && overlay.selectedRules.length === 0; text: "No apps pinned. Windows land here by fill order." }

        Flow {
          visible: overlay.rulesSectionOpen
          width: column.width
          spacing: Style.spacing.xs
          Repeater {
            model: overlay.selectedRules
            Action {
              required property var modelData
              readonly property var rule: modelData.rule
              text: (rule.class ? rule.class : (rule.title ? "title " + rule.title : "tag " + rule.tag)) + "   ✕"
              fontSize: overlay.uiCaption
              tooltipText: "Remove this rule"
              onClicked: overlay.removeRule(modelData.index)
            }
          }
        }

        Action {
          visible: overlay.rulesSectionOpen
          text: overlay.pickerOpen ? "Pick an open window" : "Add an open window"
          selected: overlay.pickerOpen
          fontSize: overlay.uiCaption
          onClicked: overlay.togglePicker()
        }

        Column {
          visible: overlay.rulesSectionOpen && overlay.pickerOpen
          width: column.width
          spacing: Style.spacing.xxs
          Repeater {
            model: overlay.windowClasses
            Action {
              required property var modelData
              width: column.width
              leftAlign: true
              bordered: false
              text: modelData
              fontSize: overlay.uiFontSmall
              onClicked: overlay.addClassRule(modelData)
            }
          }
          Muted { visible: overlay.windowClasses.length === 0; text: "No windows open" }
        }
      }

      // ---- Edit mode: the layout's gutters, border and corners (collapsed by default).
      Section {
        visible: rail.inspecting
        title: "APPEARANCE"
        detail: overlay.appearanceSectionOpen ? "" : ("gaps " + rail.innerGap + "·" + rail.outerGap + "  border " + rail.borderPx + "  corners " + rail.roundingPx)
        collapsible: true
        open: overlay.appearanceSectionOpen
        onToggled: overlay.setPref("appearanceSectionOpen", !overlay.appearanceSectionOpen)

        SliderField {
          visible: overlay.appearanceSectionOpen
          label: "Gutter"
          valueText: rail.innerGap + " px" + (rail.gaps.inner === undefined ? "  ·  global" : "")
          overridden: rail.gaps.inner !== undefined
          minimum: 0; maximum: 40; step: 1; integer: true
          value: rail.innerGap
          onDragStarted: overlay.pushUndo()
          onChanged: function(v) { overlay.liveGap("inner", v) }
          onReset: overlay.gap("inner", null)
        }

        SliderField {
          visible: overlay.appearanceSectionOpen
          label: "Edge gap"
          valueText: rail.outerGap + " px" + (rail.gaps.outer === undefined ? "  ·  global" : "")
          overridden: rail.gaps.outer !== undefined
          minimum: 0; maximum: 40; step: 1; integer: true
          value: rail.outerGap
          onDragStarted: overlay.pushUndo()
          onChanged: function(v) { overlay.liveGap("outer", v) }
          onReset: overlay.gap("outer", null)
        }

        SliderField {
          visible: overlay.appearanceSectionOpen
          label: "Border"
          valueText: rail.borderPx + " px" + (rail.borderSet ? "" : "  ·  global")
          overridden: rail.borderSet
          minimum: 0; maximum: 12; step: 1; integer: true
          value: rail.borderPx
          onDragStarted: overlay.pushUndo()
          onChanged: function(v) { overlay.liveLayoutProp("border", v) }
          onReset: overlay.layoutProp("border", null)
        }

        SliderField {
          visible: overlay.appearanceSectionOpen
          label: "Window corners"
          valueText: rail.roundingPx + " px" + (rail.roundingSet ? "" : "  ·  global")
          overridden: rail.roundingSet
          minimum: 0; maximum: 20; step: 1; integer: true
          value: rail.roundingPx
          onDragStarted: overlay.pushUndo()
          onChanged: function(v) { overlay.liveLayoutProp("rounding", v) }
          onReset: overlay.layoutProp("rounding", null)
        }
      }

      // ---- Edit mode: what the layout does with empty zones and a lone window.
      Section {
        visible: rail.inspecting
        title: "BEHAVIOUR"
        detail: overlay.behaviourSectionOpen ? "" : rail.behaviourSummary
        collapsible: true
        open: overlay.behaviourSectionOpen
        onToggled: overlay.setPref("behaviourSectionOpen", !overlay.behaviourSectionOpen)

        Field {
          visible: overlay.behaviourSectionOpen
          label: "Empty zones"
          Choice {
            options: [{ label: "Collapse", value: "collapse" }, { label: "Keep their place", value: "keep" }]
            value: rail.draft ? (rail.draft.empty || "collapse") : "collapse"
            onChanged: function(v) { overlay.layoutProp("empty", v) }
          }
        }

        Field {
          visible: overlay.behaviourSectionOpen
          label: "A lone window"
          Choice {
            options: [{ label: "Fills the area", value: "collapse" }, { label: "Stays in its zone", value: "slot" }]
            value: rail.draft ? (rail.draft.single || "collapse") : "collapse"
            onChanged: function(v) { overlay.layoutProp("single", v) }
          }
        }
      }

      // ---- Keys, on request.
      Section {
        visible: overlay.showKeys
        title: "KEYS"
        Column {
          width: column.width
          spacing: Style.spacing.xs
          Repeater {
            model: rail.keyHints
            KeyHint {
              required property var modelData
              keys: modelData[0]
              label: modelData[1]
            }
          }
        }
      }

      Muted {
        visible: !overlay.showKeys && !overlay.naming && !overlay.renaming && !overlay.namingScene
        text: "Hold Space to peek  ·  ? for the keys"
      }
    }
  }

  // Where the scroll is, when the rail is taller than the screen.
  Rectangle {
    visible: scroller.interactive
    width: Math.max(3, Math.round(rail.pad * 0.22))
    radius: width / 2
    x: rail.width - Math.round((rail.pad + width) / 2)
    y: scroller.y + scroller.visibleArea.yPosition * scroller.height
    height: Math.max(rail.pad, scroller.visibleArea.heightRatio * scroller.height)
    color: Util.alpha(rail.fg, 0.35)
  }
}
