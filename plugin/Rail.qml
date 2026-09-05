import QtQuick
import qs.Commons
import qs.Ui
import "Geometry.js" as Geometry
import "Editor.js" as Editor

// The inspector rail: the layout's name and actions on top, then the
// sections for the current mode. View mode shows the layout list, the
// fill order, the workspaces to put the layout on, and the cycle switch.
// Edit mode shows the selected zone, then (collapsed by default) the apps
// pinned to it and the layout's gutters and policies. The keys are shown
// on request (?). The rail docks on either side.
Card {
  id: rail
  property real maxHeight: 100000
  readonly property string nameText: nameField.text

  // Put the cursor in the layout-name field, preloaded with `initial`.
  function focusName(initial) {
    nameField.text = initial
    Qt.callLater(function() { nameField.forceActiveFocus(); nameField.selectAll() })
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
  readonly property string widthTarget: (sel && draft) ? Editor.extentTarget(draft, sel.name, "w") : ""
  readonly property string heightTarget: (sel && draft) ? Editor.extentTarget(draft, sel.name, "h") : ""

  // PanelSlider colors itself from a bar; hand it the rail's palette.
  readonly property QtObject palette: QtObject {
    readonly property color foreground: rail.fg
    readonly property color background: Color.menu.background
    readonly property string fontFamily: rail.family
  }

  readonly property var keyHints: {
    if (overlay.naming) return [["Enter", "save"], ["Esc", "cancel"]]
    if (overlay.renaming) return [["Enter", "rename"], ["Esc", "cancel"]]
    if (overlay.numbering) return [["click", "next in order"], ["click again", "stack"], ["Backspace", "undo"], ["Enter", "done"]]
    if (overlay.editing) return [["click / ← → ↑ ↓", "select zone"], ["Shift + arrows", "resize 1%"], ["Tab", "next zone"], ["drag", "resize"], ["c", "split columns"], ["r", "split rows"], ["x", "delete"], ["s", "spacer"], ["f", "renumber"], ["u", "undo"], ["Space", "hold to peek"], ["w", "save"], ["Esc", "leave"], ["?", "hide keys"]]
    return [["← →", "browse (the windows follow)"], ["Enter", "use and close"], ["Space", "hold to peek"], ["e", "edit"], ["n", "new"], ["F2", "rename"], ["d", "delete"], ["r", "refresh"], ["Esc", "close"], ["?", "hide keys"]]
  }

  readonly property string metaText: {
    if (overlay.naming || overlay.renaming) return "Letters, digits, _ and - only"
    if (overlay.numbering) return "Click zones in the order windows should fill them"
    if (overlay.editing) {
      var s = overlay.workspaceId !== "" ? "Previewing on workspace " + overlay.workspaceId : "Previewing"
      if (overlay.draftIsNew) s += "  ·  new layout"
      return s
    }
    if (!overlay.viewed) return "No layouts in ~/.config/hypr/layouts yet"
    var m = ""
    if (overlay.viewedIsActive) m = "In use on workspace " + overlay.current.workspace.id
    else if (overlay.current && overlay.current.workspace) m = "Workspace " + overlay.current.workspace.id + " uses " + String(overlay.current.workspace.layout).replace(/^lua:/, "")
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
    color: Util.alpha(rail.fg, 0.7)
    font.family: rail.family
    font.pixelSize: overlay.uiCaption
    font.bold: true
  }

  component Muted: Text {
    textFormat: Text.PlainText
    width: column.width
    wrapMode: Text.WordWrap
    color: Util.alpha(rail.fg, 0.62)
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

  component Action: Button {
    bordered: true
    radius: overlay.radiusControl
    foreground: rail.fg
    accent: rail.accent
    fontFamily: rail.family
    fontSize: overlay.uiFontSmall
    opacity: enabled ? 1 : 0.45
  }

  // A section header; collapsible ones show a chevron and toggle on click.
  component SectionHeader: Item {
    id: sh
    property string text: ""
    property string detail: ""
    property bool collapsible: false
    property bool open: true
    signal toggled()
    width: column.width
    implicitHeight: Math.max(shTitle.implicitHeight, shDetail.implicitHeight)
    Row {
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.sm
      Text {
        visible: sh.collapsible
        textFormat: Text.PlainText
        text: sh.open ? "▾" : "▸"
        color: Util.alpha(rail.fg, 0.7)
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
      textFormat: Text.PlainText
      text: sh.detail
      color: rail.accent
      font.family: rail.family
      font.pixelSize: overlay.uiFontSmall
      font.bold: true
      elide: Text.ElideRight
      width: Math.min(implicitWidth, parent.width - shTitle.implicitWidth - Style.spacing.lg * 2)
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea {
      anchors.fill: parent
      enabled: sh.collapsible
      cursorShape: Qt.PointingHandCursor
      onClicked: sh.toggled()
    }
  }

  component Section: Column {
    id: section
    property alias title: header.text
    property alias detail: header.detail
    property bool collapsible: false
    property bool open: true
    signal toggled()
    width: column.width
    spacing: Style.spacing.lg
    PanelSeparator { foreground: rail.fg; width: column.width }
    SectionHeader { id: header; collapsible: section.collapsible; open: section.open; onToggled: section.toggled() }
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
    property string resetLabel: "global"
    property real minimum: 0
    property real maximum: 1
    property real step: 0.05
    property bool integer: false
    property real value: 0
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
        Action { visible: sf.overridden; text: sf.resetLabel; tooltipText: "Back to the default"; fontSize: overlay.uiCaption; onClicked: sf.reset() }
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
      onDraggingChanged: if (dragging) sf.dragStarted()
      onMoved: function(v) { sf.changed(v) }
      onReleased: function(v) { sf.changed(v) }
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

  // A row of exclusive choices; the selected one reads as pressed.
  component Choice: Row {
    id: choice
    property var options: []
    property string value: ""
    signal changed(string value)
    spacing: Style.spacing.md
    Repeater {
      model: choice.options
      Action {
        required property var modelData
        text: modelData.label
        selected: String(modelData.value) === choice.value
        onClicked: choice.changed(String(modelData.value))
      }
    }
  }

  component KeyHint: Row {
    id: hint
    property string keys: ""
    property string label: ""
    spacing: Style.spacing.sm
    Rectangle {
      width: keyText.implicitWidth + Style.space(10)
      height: keyText.implicitHeight + Style.space(4)
      radius: overlay.radiusControl
      color: Util.alpha(rail.fg, 0.08)
      border.width: 1
      border.color: Util.alpha(rail.fg, 0.28)
      anchors.verticalCenter: parent.verticalCenter
      Text {
        id: keyText
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: hint.keys
        color: rail.fg
        font.family: rail.family
        font.pixelSize: overlay.uiCaption
        font.bold: true
      }
    }
    Text {
      textFormat: Text.PlainText
      text: hint.label
      color: Util.alpha(rail.fg, 0.7)
      font.family: rail.family
      font.pixelSize: overlay.uiCaption
      anchors.verticalCenter: parent.verticalCenter
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
    color: Util.alpha(warning ? Color.urgent : rail.accent, 0.08)
    border.width: 1
    border.color: Util.alpha(warning ? Color.urgent : rail.accent, 0.6)
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

      Flow {
        visible: !overlay.editing
        width: parent.width
        spacing: Style.spacing.sm
        Action { text: "Layouts"; selected: !overlay.contentMode; onClicked: overlay.showContent(false) }
        Action { text: "Scenes & content"; selected: overlay.contentMode; onClicked: overlay.showContent(true) }
      }

      ContentPane { visible: overlay.contentMode && !overlay.editing; width: parent.width; overlay: rail.overlay }

      // ---- Header: mode, name, meta, actions.
      Column {
        width: column.width
        spacing: Style.spacing.sm

        Item {
          width: parent.width
          implicitHeight: Math.max(eyebrow.implicitHeight, headerTools.implicitHeight)
          Label {
            id: eyebrow
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: overlay.naming ? "SAVE AS"
              : overlay.renaming ? "RENAME"
              : overlay.numbering ? "RENUMBERING"
              : overlay.editing ? (overlay.draftIsNew ? "NEW LAYOUT" : "EDITING")
              : "HYPERTILE" + (overlay.layouts.length > 0 ? "   " + (overlay.viewIndex + 1) + " / " + overlay.layouts.length : "")
          }
          Row {
            id: headerTools
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm
            Chip {
              visible: overlay.editing && overlay.dirty
              text: "unsaved"
              foreground: rail.fg
              fontFamily: rail.family
              fontSize: overlay.uiCaption
              anchors.verticalCenter: parent.verticalCenter
            }
            Action {
              text: "?"
              selected: overlay.showKeys
              bordered: false
              fontSize: overlay.uiCaption
              tooltipText: overlay.showKeys ? "Hide the keys (?)" : "Show the keys (?)"
              onClicked: overlay.setPref("showKeys", !overlay.showKeys)
              anchors.verticalCenter: parent.verticalCenter
            }
            Action {
              text: overlay.dockLeft ? "⇥" : "⇤"
              bordered: false
              fontSize: overlay.uiCaption
              tooltipText: overlay.dockLeft ? "Dock the rail on the right" : "Dock the rail on the left"
              onClicked: overlay.setPref("dockLeft", !overlay.dockLeft)
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        Text {
          visible: !overlay.naming && !overlay.renaming
          width: parent.width
          textFormat: Text.PlainText
          text: overlay.editing ? overlay.draftName : (overlay.viewed ? overlay.viewed.name : "No layouts")
          color: rail.accent
          font.family: rail.family
          font.pixelSize: overlay.uiTitle
          font.bold: true
          elide: Text.ElideRight
        }

        TextField {
          id: nameField
          visible: overlay.naming || overlay.renaming
          width: parent.width
          foreground: rail.fg
          accent: rail.accent
          font.family: rail.family
          font.pixelSize: overlay.uiFont
          placeholderText: "layout name"
          Component.onCompleted: background.radius = overlay.radiusControl
          Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { overlay.renaming ? overlay.confirmRename() : overlay.confirmName(); event.accepted = true }
            else if (event.key === Qt.Key_Escape) { overlay.naming = false; overlay.renaming = false; overlay.errorText = ""; overlay.focusKeys(); event.accepted = true }
          }
        }

        Muted { text: rail.metaText; visible: text !== "" }

        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          topPadding: Style.spacing.xs

          // view mode
          Action { visible: !overlay.editing && !overlay.renaming; text: overlay.viewedIsActive ? "In use" : "Use"; selected: overlay.viewedIsActive; tooltipText: "Use on this workspace and close (Enter)"; enabled: overlay.viewed !== null && !overlay.viewedIsActive && !overlay.busy; onClicked: overlay.applyViewed(true) }
          Action { visible: !overlay.editing && !overlay.renaming; text: "Edit"; tooltipText: "Edit this layout (e)"; enabled: overlay.viewed !== null; onClicked: overlay.startEdit(false) }
          Action { visible: !overlay.editing && !overlay.renaming; text: "New"; selected: overlay.choosingNew; tooltipText: "New layout: blank, or a copy of this one (n)"; enabled: overlay.current !== null; onClicked: { overlay.confirmingDelete = false; overlay.choosingNew = !overlay.choosingNew } }
          Action { visible: !overlay.editing && !overlay.renaming; text: "Rename"; tooltipText: "Rename this layout (F2)"; enabled: overlay.viewed !== null && !overlay.busy; onClicked: overlay.startRename() }
          Action { visible: !overlay.editing && !overlay.renaming && !overlay.confirmingDelete; text: "Delete"; accent: Color.urgent; tooltipText: overlay.viewedIsDefault ? "The default layout cannot be deleted; make another the default first" : "Delete this layout's file (d)"; enabled: overlay.viewed !== null && !overlay.viewedIsDefault && !overlay.busy; onClicked: { overlay.choosingNew = false; overlay.confirmingDelete = true } }
          // edit mode
          Action { visible: overlay.editing && !overlay.naming; text: overlay.numbering ? "Done numbering" : "Renumber"; selected: overlay.numbering; tooltipText: "Click zones in fill order (f)"; onClicked: overlay.numbering ? overlay.finishNumbering() : overlay.startNumbering() }
          Action { visible: overlay.editing && !overlay.naming; text: "Undo"; tooltipText: "Undo (u)"; enabled: overlay.undoStack.length > 0; onClicked: overlay.undo() }
          Action { visible: overlay.editing && !overlay.naming; text: "Save"; tooltipText: "Save to ~/.config/hypr/layouts (w)"; enabled: !overlay.busy; onClicked: overlay.requestSave() }
          Action { visible: overlay.editing && !overlay.naming && !overlay.confirmingDiscard; text: overlay.dirty ? "Discard" : "Leave"; accent: Color.urgent; tooltipText: overlay.dirty ? "Drop the changes (Esc)" : "Back to browsing (Esc)"; enabled: !overlay.busy; onClicked: overlay.dirty ? (overlay.confirmingDiscard = true) : overlay.leaveEdit("") }
          // naming
          Action { visible: overlay.naming; text: "Save as"; onClicked: overlay.confirmName() }
          Action { visible: overlay.naming; text: "Cancel"; onClicked: { overlay.naming = false; overlay.focusKeys() } }
          // renaming
          Action { visible: overlay.renaming; text: "Rename"; onClicked: overlay.confirmRename() }
          Action { visible: overlay.renaming; text: "Cancel"; onClicked: { overlay.renaming = false; overlay.errorText = ""; overlay.focusKeys() } }
        }
      }

      // ---- View mode: new layout, blank or a copy.
      Prompt {
        visible: !overlay.editing && overlay.choosingNew
        PromptTitle { text: "Start a new layout from" }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { text: "Blank"; tooltipText: "One zone filling the screen (b)"; selected: true; onClicked: overlay.startEdit(true, true) }
          Action { visible: overlay.viewed !== null; text: "A copy of " + (overlay.viewed ? overlay.viewed.name : ""); tooltipText: "c"; onClicked: overlay.startEdit(true, false) }
          Action { text: "Cancel"; onClicked: overlay.choosingNew = false }
        }
      }

      // ---- View mode: confirm a delete.
      Prompt {
        visible: !overlay.editing && overlay.confirmingDelete && overlay.viewed !== null
        warning: true
        PromptTitle { text: "Delete " + (overlay.viewed ? overlay.viewed.name : "") + "?" }
        Muted {
          width: parent.width
          text: {
            var using = []
            for (var i = 0; i < overlay.workspaces.length; i++)
              if (overlay.viewed && overlay.workspaces[i].layout === "lua:" + overlay.viewed.name) using.push(overlay.workspaces[i].id)
            var s = "The file in ~/.config/hypr/layouts is removed and Hyprland reloads."
            if (using.length > 0) s += " Workspace " + using.join(", ") + " falls back to the default layout."
            else s += " Any workspace rule that points at it falls back to the default layout."
            return s
          }
        }
        Flow {
          width: parent.width
          spacing: Style.spacing.sm
          Action { text: "Delete"; accent: Color.urgent; selected: true; enabled: !overlay.busy; onClicked: overlay.deleteViewed() }
          Action { text: "Cancel"; onClicked: overlay.confirmingDelete = false }
        }
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
          Action { text: "Discard"; accent: Color.urgent; selected: true; tooltipText: "d"; enabled: !overlay.busy; onClicked: overlay.discard() }
          Action { text: "Save"; tooltipText: "w"; enabled: !overlay.busy; onClicked: overlay.requestSave() }
          Action { text: "Keep editing"; tooltipText: "Esc"; onClicked: overlay.confirmingDiscard = false }
        }
      }

      // ---- View mode: every layout on disk, with a picture of each.
      Section {
        visible: !overlay.editing && overlay.layouts.length > 1
        title: "LAYOUTS"

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
              readonly property bool inUse: overlay.committedLayout === "lua:" + modelData.name
              readonly property bool isDefault: overlay.defaultLayout === "lua:" + modelData.name
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
                      var n = Array.isArray(spec.fill) ? spec.fill.length : Editor.leafNames(spec).length
                      bits.push(n + (n === 1 ? " slot" : " slots"))
                      return bits.join("  ·  ")
                    }
                    color: Util.alpha(rail.fg, 0.62)
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

      // ---- View mode: fill order.
      Section {
        visible: !overlay.editing && overlay.viewed !== null && overlay.viewed.spec !== undefined
        title: "FILL ORDER"
        Body {
          text: {
            if (!overlay.viewed || !overlay.viewed.spec) return ""
            var spec = overlay.viewed.spec
            var count = Array.isArray(spec.fill) ? spec.fill.length : overlay.zones.length
            var s = "Windows take slots 1 to " + count + " in order"
            var c = Geometry.cycleSummary(spec)
            if (c !== "") s += ", " + c
            return s
          }
        }
      }

      // ---- View mode: workspaces.
      Section {
        visible: !overlay.editing && overlay.viewed !== null && overlay.workspaces.length > 0
        title: "WORKSPACES"

        Column {
          width: column.width
          spacing: Style.spacing.sm

          Repeater {
            model: overlay.workspaces
            Item {
              id: wsRow
              required property var modelData
              readonly property bool uses: overlay.viewed !== null && modelData.layout === "lua:" + overlay.viewed.name
              width: column.width
              implicitHeight: Math.max(wsText.implicitHeight, wsButton.implicitHeight)

              Column {
                id: wsText
                anchors.left: parent.left
                anchors.right: wsButton.left
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
                  text: wsRow.modelData.monitor + "  ·  " + String(wsRow.modelData.layout).replace(/^lua:/, "") + (wsRow.modelData.windows > 0 ? "  ·  " + wsRow.modelData.windows + (wsRow.modelData.windows === 1 ? " window" : " windows") : "")
                  color: Util.alpha(rail.fg, 0.62)
                  font.family: rail.family
                  font.pixelSize: overlay.uiCaption
                  elide: Text.ElideRight
                }
              }
              Action {
                id: wsButton
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: wsRow.uses ? "In use" : "Use"
                selected: wsRow.uses
                fontSize: overlay.uiCaption
                tooltipText: "Use " + (overlay.viewed ? overlay.viewed.name : "") + " on workspace " + wsRow.modelData.id + "; the overlay stays open"
                enabled: !wsRow.uses && !overlay.busy
                opacity: 1
                onClicked: overlay.applyTo(wsRow.modelData.id)
              }
            }
          }
        }

        Flow {
          width: column.width
          spacing: Style.spacing.sm
          Repeater {
            model: overlay.monitors
            Action {
              required property var modelData
              text: "Use on all of " + modelData
              fontSize: overlay.uiCaption
              tooltipText: "Every workspace currently on " + modelData
              enabled: !overlay.busy
              onClicked: overlay.applyMonitor(modelData)
            }
          }
          Action {
            text: overlay.viewedIsDefault ? "Default" : "Use as default"
            selected: overlay.viewedIsDefault
            fontSize: overlay.uiCaption
            tooltipText: "Default for workspaces without their own layout (general.layout in looknfeel.lua)"
            enabled: !overlay.busy && !overlay.viewedIsDefault
            opacity: 1
            onClicked: overlay.setDefault()
          }
        }
      }

      // ---- View mode: the SUPER+L cycle.
      Section {
        visible: !overlay.editing && overlay.viewed !== null
        title: "CYCLE"
        Switch {
          label: "In the SUPER+L cycle"
          description: overlay.viewedInCycle ? "SUPER+L reaches this layout" : "SUPER+L skips it; the overlay still shows it"
          checked: overlay.viewedInCycle
          enabled: !overlay.busy
          onClicked: overlay.setInCycle(!overlay.viewedInCycle)
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
          Action { text: "Undo click"; enabled: overlay.numberingFill.length > 0; onClicked: { var next = overlay.numberingFill.slice(); next.pop(); overlay.numberingFill = next } }
          Action { text: "Done"; onClicked: overlay.finishNumbering() }
        }
      }

      // ---- Edit mode: the selected zone.
      Section {
        visible: rail.inspecting
        title: "ZONE"
        detail: rail.sel ? rail.sel.name : ""

        Muted { visible: rail.sel === null; text: "Click a zone, or use the arrows, to inspect it." }

        Flow {
          visible: rail.sel !== null
          width: column.width
          spacing: Style.spacing.sm
          Action { text: "Split columns"; tooltipText: "c"; onClicked: overlay.splitSelected("columns") }
          Action { text: "Split rows"; tooltipText: "r"; onClicked: overlay.splitSelected("rows") }
          Action { text: "Delete"; accent: Color.urgent; tooltipText: "x, or right-click the zone"; onClicked: overlay.deleteZone(overlay.selected) }
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

        Switch {
          visible: rail.sel !== null
          label: "Spacer"
          description: "An empty hole that never takes windows"
          checked: rail.sel ? rail.sel.spacer === true : false
          onClicked: overlay.zoneProp("spacer", !(rail.sel && rail.sel.spacer))
        }

        Switch {
          visible: rail.sel !== null && !rail.sel.spacer
          label: "Never split"
          description: "One window; more overlap it at full size instead of splitting it"
          checked: rail.sel ? rail.sel.neverSplit === true : false
          onClicked: overlay.zoneProp("never_split", (rail.sel && rail.sel.neverSplit) ? null : true)
        }

        Field {
          visible: rail.sel !== null && !rail.sel.spacer && !rail.sel.neverSplit
          label: "Stack"
          Choice {
            options: [{ label: "Vertical", value: "v" }, { label: "Horizontal", value: "h" }]
            value: rail.sel ? rail.sel.stack : "v"
            onChanged: function(v) { overlay.zoneProp("stack", v === ((rail.draft && rail.draft.stack) || "v") ? null : v) }
          }
        }

        Field {
          visible: rail.sel !== null && !rail.sel.spacer && !rail.sel.neverSplit
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
              text: rail.cap > 0 ? "windows, then the next zone takes over" : "unlimited; 1 or more spills over"
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }

        Field {
          visible: rail.sel !== null && !rail.sel.spacer
          label: "Aspect"
          Choice {
            options: overlay.aspectPresets.map(function(p) { return { label: p.label, value: p.value === null ? "" : String(p.value) } })
            value: (rail.sel && rail.sel.aspect) ? String(overlay.aspectKey(rail.sel.aspect)) : ""
            onChanged: function(v) { overlay.zoneProp("aspect", v === "" ? null : Math.round(Number(v) * 1000) / 1000) }
          }
        }

        SliderField {
          visible: rail.sel !== null && !rail.sel.spacer
          label: "Scale"
          valueText: Math.round(((rail.sel && rail.sel.scale) || 1) * 100) + "%"
          overridden: rail.sel !== null && rail.sel.scale !== undefined
          resetLabel: "100%"
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

      // ---- Edit mode: the layout's gutters and policies (collapsed by default).
      Section {
        visible: rail.inspecting
        title: "LAYOUT"
        detail: overlay.layoutSectionOpen ? "" : ("gaps " + rail.innerGap + "·" + rail.outerGap + "  border " + rail.borderPx)
        collapsible: true
        open: overlay.layoutSectionOpen
        onToggled: overlay.setPref("layoutSectionOpen", !overlay.layoutSectionOpen)

        SliderField {
          visible: overlay.layoutSectionOpen
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
          visible: overlay.layoutSectionOpen
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
          visible: overlay.layoutSectionOpen
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
          visible: overlay.layoutSectionOpen
          readonly property bool set: rail.draft && rail.draft.rounding !== undefined
          readonly property int globalRounding: overlay.current ? (overlay.current.rounding || 0) : 0
          label: "Window corners"
          valueText: (set ? rail.draft.rounding : globalRounding) + " px" + (set ? "" : "  ·  global")
          overridden: set
          minimum: 0; maximum: 20; step: 1; integer: true
          value: set ? rail.draft.rounding : globalRounding
          onDragStarted: overlay.pushUndo()
          onChanged: function(v) { overlay.liveLayoutProp("rounding", v) }
          onReset: overlay.layoutProp("rounding", null)
        }

        Field {
          visible: overlay.layoutSectionOpen
          label: "Empty zones"
          Choice {
            options: [{ label: "Collapse", value: "collapse" }, { label: "Keep their place", value: "keep" }]
            value: rail.draft ? (rail.draft.empty || "collapse") : "collapse"
            onChanged: function(v) { overlay.layoutProp("empty", v) }
          }
        }

        Field {
          visible: overlay.layoutSectionOpen
          label: "A lone window"
          Choice {
            options: [{ label: "Fills the area", value: "collapse" }, { label: "Stays in its zone", value: "slot" }]
            value: rail.draft ? (rail.draft.single || "collapse") : "collapse"
            onChanged: function(v) { overlay.layoutProp("single", v) }
          }
        }

        Switch {
          visible: overlay.layoutSectionOpen
          label: "In the SUPER+L cycle"
          description: "Off: SUPER+L skips this layout"
          checked: !(rail.draft && rail.draft.in_cycle === false)
          onClicked: overlay.layoutProp("in_cycle", (rail.draft && rail.draft.in_cycle === false) ? null : false)
        }
      }

      // ---- Keys, on request.
      Section {
        visible: overlay.showKeys
        title: "KEYS"
        Grid {
          width: column.width
          columns: 2
          columnSpacing: Style.spacing.xl
          rowSpacing: Style.spacing.xs
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
        visible: !overlay.showKeys && !overlay.naming && !overlay.renaming
        text: overlay.editing ? "Hold Space to peek at the windows  ·  ? for the keys" : "Hold Space to peek  ·  ? for the keys"
      }
    }
  }
}
