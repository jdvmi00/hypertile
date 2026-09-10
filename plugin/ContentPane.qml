import QtQuick
import qs.Commons
import qs.Ui
import "Content.js" as Content

// The body of the rail's Scenes tab: the saved scenes as cards, what each
// zone of the workspace's layout holds, and a picker for the selected zone
// that filters as you type. The header above it (the scene's name and
// state, Save and Restore) is the rail's own. Every change goes through
// hypertile-ctl scene; the catalog is re-read every couple of seconds while
// the overlay is open, so the states here follow the controller.
Column {
  id: pane
  required property var overlay
  readonly property var catalog: overlay.contentCatalog || ({})
  readonly property var scene: catalog.current || ({})
  // The catalog is re-read every couple of seconds; these keep their
  // identity until their content changes, so the rows (and what the
  // pointer is over) survive a poll.
  property var scenes: []
  property var apps: []
  property string selectedScene: ""
  signal revealItem(var item)
  onCatalogChanged: syncLists()
  Component.onCompleted: syncLists()
  function syncLists() {
    syncOpenRows()
    var nextScenes = catalog.scenes || []
    if (JSON.stringify(nextScenes) !== JSON.stringify(scenes)) scenes = nextScenes
    if (!scenes.some(function(s) { return s.name === selectedScene })) selectedScene = ""
    var nextApps = catalog.apps || []
    if (JSON.stringify(nextApps) !== JSON.stringify(apps)) apps = nextApps
  }
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
  readonly property string appliedScene: (scene.document && scene.document.name && ["none", "restored"].indexOf(scene.phase) === -1) ? scene.document.name : ""
  readonly property color fg: overlay.foreground
  readonly property color accent: overlay.accent
  readonly property string family: overlay.fontFamily
  readonly property int iconSize: Math.round(overlay.uiFontSmall * 1.4)
  property string deleting: ""      // the saved scene a delete is being confirmed for
  onDeletingChanged: if (deleting !== "") Qt.callLater(function() { pane.revealItem(deletePrompt) })

  // ---- the picker: what is typed, and the rows that match it, in the
  // order they are listed (Enter takes the hot one).
  readonly property string query: searchField.text
  readonly property bool searching: query.trim() !== ""
  property int hot: 0
  onQueryChanged: hot = 0
  property var openRows: []
  Connections {
    target: pane.overlay
    function onWindowsChanged() { pane.syncOpenRows() }
    function onWorkspaceIdChanged() { pane.syncOpenRows() }
  }
  function syncOpenRows() {
    var next = Content.openApps(overlay.windows, overlay.workspaceId)
    if (JSON.stringify(next) !== JSON.stringify(openRows)) openRows = next
  }
  readonly property var builtinMatches: {
    if (!searching) return []
    var out = []
    if (Content.matches(query, ["Local windows", "fill order"])) out.push({ kind: "local", name: "Local windows", trait: "by fill order", icon: "" })
    if (Content.matches(query, ["Empty", "nothing opens here"])) out.push({ kind: "empty", name: "Empty", trait: "nothing opens here", icon: "" })
    return out
  }
  readonly property var openMatches: {
    var out = []
    for (var i = 0; i < openRows.length; i++) {
      var r = openRows[i]
      var name = overlay.nameForClass(r.app_class, apps)
      if (!Content.matches(query, [name, r.app_class, r.title])) continue
      out.push({ kind: "open", name: name, app_class: r.app_class, trait: r.count === 1 ? r.title : r.count + " windows", icon: overlay.iconForClass(r.app_class, apps) })
    }
    return out
  }
  readonly property var remoteMatches: pane.appRows(pane.query, pane.apps, true)
  readonly property var appMatches: pane.appRows(pane.query, pane.apps, false)
  readonly property var matches: builtinMatches.concat(openMatches, remoteMatches, appMatches)
  readonly property int matchCount: matches.length

  function appRows(query, apps, remote) {
    var out = []
    for (var i = 0; i < apps.length; i++) {
      var a = apps[i]
      if (Content.isRemoteDesktop(a) !== remote) continue
      var name = remote ? Content.displayName(a.name) : a.name
      if (!Content.matches(query, [name, a.app_class, a.desktop_id])) continue
      out.push({ kind: "app", name: name, desktop_id: a.desktop_id, app: a, trait: "", icon: pane.overlay.resolveIcon(a.icon) })
    }
    return out
  }

  function moveScene(delta) {
    if (!ready || !scenes.length) return
    var index = scenes.findIndex(function(s) { return s.name === selectedScene })
    index = index < 0 ? (delta > 0 ? 0 : scenes.length - 1) : (index + delta + scenes.length) % scenes.length
    selectedScene = scenes[index].name
    deleting = ""
    var item = sceneCards.itemAt(index)
    if (item) pane.revealItem(item)
  }
  function pickScene() {
    var entry = scenes.find(function(s) { return s.name === selectedScene })
    if (!entry || !ready || overlay.busy) return
    if (!entry.valid) { overlay.errorText = entry.error || "This scene cannot be used"; return }
    if (appliedScene === entry.name && !scene.modified) { overlay.statusText = "Already using " + entry.name; return }
    overlay.sceneAction("apply", entry.name)
  }
  function handleSceneKey(event) {
    if (deleting !== "") {
      if (event.key === Qt.Key_Escape) deleting = ""
      else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !overlay.busy) {
        overlay.deleteScene(deleting)
        deleting = ""
      }
      return true
    }
    if (ready && scenes.length && (event.key === Qt.Key_Up || event.key === Qt.Key_Down)) { moveScene(event.key === Qt.Key_Down ? 1 : -1); return true }
    if (selectedScene !== "" && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) { pickScene(); return true }
    if (event.key === Qt.Key_Delete && selectedScene !== "" && ready && !overlay.busy) { deleting = selectedScene; return true }
    return false
  }
  function handleSearchKey(event) {
    var k = event.key
    if (k === Qt.Key_Question || (k === Qt.Key_Slash && (event.modifiers & Qt.ShiftModifier))) return overlay.handleKey(event)
    if (k === Qt.Key_Escape && query !== "") { searchField.text = ""; return true }
    if ((k === Qt.Key_Return || k === Qt.Key_Enter) && searching) { pickMatch(); return true }
    if (k === Qt.Key_Down && searching) { hot = Math.min(hot + 1, Math.max(0, matches.length - 1)); return true }
    if (k === Qt.Key_Up && searching) { hot = Math.max(hot - 1, 0); return true }
    if ((k === Qt.Key_Left || k === Qt.Key_Right) && query !== "") return false
    if ([Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right].indexOf(k) !== -1) return overlay.handleKey(event)
    return false
  }
  function focusSearch() {
    Qt.callLater(function() { if (searchField.visible) { searchField.forceActiveFocus(); searchField.cursorPosition = searchField.text.length } })
  }
  function setQuery(text) { searchField.text = String(text || ""); pane.focusSearch() }
  // A key typed while the overlay's key handler had the focus: the search
  // takes it and the ones after it.
  function typeSearch(text) {
    searchField.text = searchField.text + String(text || "")
    Qt.callLater(function() { if (searchField.visible) { searchField.forceActiveFocus(); searchField.cursorPosition = searchField.text.length } })
  }
  function pickMatch() {
    if (!pane.searching || pane.matches.length === 0) return
    pane.choose(pane.matches[Math.max(0, Math.min(pane.hot, pane.matches.length - 1))])
  }
  function choose(m) {
    pane.overlay.hoverMatch = null
    if (m.kind === "local") pane.overlay.assignContent("local")
    else if (m.kind === "empty") pane.overlay.assignContent("empty")
    else if (m.kind === "open") pane.overlay.assignContent("local", m.app_class)
    else pane.overlay.assignApp(m.app)
    searchField.text = ""
  }
  // Preview a match by its place in the list (-1 clears), as hovering does.
  function hoverMatch(index) {
    if (index < 0 || index >= pane.matches.length) { pane.overlay.hoverMatch = null; return }
    pane.overlay.ghost(pane.ghostFor(pane.matches[index]))
  }
  function ghostFor(m) {
    var key = m.kind + ":" + (m.desktop_id || m.app_class || m.kind)
    return { key: key, kind: m.kind, name: m.name || (m.kind === "empty" ? "Empty" : "Local windows"), icon: m.icon || "" }
  }
  function isCurrent(m) {
    var s = pane.source
    if (m.kind === "local") return s === null || (s.type === "local" && !s.app_class)
    if (m.kind === "empty") return s !== null && s.type === "empty"
    if (m.kind === "open") return s !== null && s.type === "local" && s.app_class === m.app_class
    return s !== null && s.type === "app" && s.desktop_id === m.desktop_id
  }

  spacing: Style.spacing.xl

  // Keep the query when moving between zones; deselection starts a new search.
  Connections {
    target: pane.overlay
    function onSelectedChanged() {
      if (pane.overlay.selected === "") { searchField.text = ""; if (pane.overlay.contentMode) pane.overlay.focusKeys() }
      pane.overlay.hoverMatch = null
      if (pane.overlay.contentMode && pane.overlay.selected !== "" && pane.usable) pane.focusSearch()
    }
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
      visible: section.title !== ""
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

  // A group inside the picker: a small heading over its rows.
  component Group: Column {
    property string title: ""
    property string caption: ""
    width: pane.width
    spacing: Style.spacing.xxs
    Label { text: parent.title; topPadding: Style.spacing.xs; bottomPadding: Style.spacing.xxs }
    Muted { visible: parent.caption !== ""; text: parent.caption; bottomPadding: Style.spacing.xs }
  }

  // One line in a list: an optional badge and icon, a name, a quieter
  // phrase next to it, and a state on the right. The current one reads
  // like the viewed layout in the LAYOUTS list; the hot one is what Enter
  // takes while a search is typed.
  component ListRow: Rectangle {
    id: row
    property string badge: ""      // the fill number, as on the zone card
    property bool badgeStrong: true
    property string icon: ""
    property string text: ""
    property string sub: ""
    property string trait: ""
    property bool current: false
    property bool hot: false
    property bool urgent: false
    signal clicked()
    signal hovered(bool on)
    width: pane.width
    implicitHeight: Math.max(rowMain.implicitHeight, rowIcon.visible ? rowIcon.height : 0, rowBadge.visible ? rowBadge.implicitHeight : 0) + Style.spacing.sm * 2
    height: implicitHeight
    radius: pane.overlay.radiusControl
    color: current ? Util.alpha(pane.accent, 0.14) : (hot ? Util.alpha(pane.accent, 0.08) : (rowHover.containsMouse ? Util.alpha(pane.fg, 0.06) : "transparent"))
    border.width: (current || hot) ? 1 : 0
    border.color: Util.alpha(pane.accent, current ? 0.6 : 0.35)
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
    Image {
      id: rowIcon
      visible: row.icon !== ""
      x: rowBadge.visible ? rowBadge.x + rowBadge.width + Style.spacing.md : Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
      width: pane.iconSize
      height: pane.iconSize
      sourceSize.width: pane.iconSize
      sourceSize.height: pane.iconSize
      source: row.icon
      smooth: true
      mipmap: true
      asynchronous: true
    }
    Text {
      id: rowMain
      x: rowIcon.visible ? rowIcon.x + rowIcon.width + Style.spacing.md
        : (rowBadge.visible ? rowBadge.x + rowBadge.width + Style.spacing.md : Style.spacing.md)
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - x - Style.spacing.md - (rowTrait.visible ? rowTrait.width + Style.spacing.lg : 0)
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
      width: Math.min(implicitWidth, row.width * 0.45)
      textFormat: Text.PlainText
      text: row.trait
      color: row.urgent ? Color.urgent : Util.alpha(pane.fg, 0.62)
      font.family: pane.family
      font.pixelSize: pane.overlay.uiCaption
      elide: Text.ElideRight
    }
    MouseArea {
      id: rowHover
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: row.clicked()
      onEntered: row.hovered(true)
      onExited: row.hovered(false)
    }
  }

  // A picker row for one match, by its place in the flat list of matches.
  component MatchRow: ListRow {
    required property var modelData
    required property int index
    property int offset: 0
    readonly property var match: pane.matches[offset + index] || modelData
    icon: modelData.icon
    text: modelData.name
    trait: modelData.trait
    current: pane.isCurrent(match)
    hot: pane.searching && pane.hot === offset + index
    onClicked: pane.choose(match)
    // Hovering previews the match in the selected zone's card.
    onHovered: function(on) { on ? pane.overlay.ghost(pane.ghostFor(match)) : pane.overlay.unghost(pane.ghostFor(match).key) }
  }

  // A saved scene, drawn like a layout in the LAYOUTS list: a picture of
  // its layout with the apps it places, its name, and what it holds.
  // Click or Enter uses it; the selected card exposes Delete.
  component SceneCard: Rectangle {
    id: card
    required property var modelData
    required property int index
    // The Repeater hands delegates a converted copy; the original entry
    // keeps its plain arrays for the thumbnail.
    readonly property var entry: pane.scenes[index] || modelData
    readonly property bool highlighted: pane.overlay.selected === "" && pane.selectedScene === entry.name
    readonly property bool applied: pane.appliedScene === entry.name
    readonly property bool valid: entry.valid === true
    readonly property bool modified: applied && pane.scene.modified === true
    readonly property var spec: valid ? pane.overlay.layoutSpec(entry.layout) : null
    readonly property var sources: entry.sources || []
    readonly property bool canApply: valid && !(applied && !modified) && !pane.overlay.busy
    readonly property string meta: {
      if (!valid) return entry.error || "This scene cannot be used"
      var bits = []
      if (applied) bits.push(modified ? "in use  ·  modified" : "in use")
      var names = Content.summary(Content.appNames(sources), 2)
      bits.push(names !== "" ? names : "local windows")
      bits.push(String(entry.layout || ""))
      return bits.join("  ·  ")
    }
    width: pane.width
    implicitHeight: cardRow.implicitHeight + Style.spacing.sm * 2
    height: implicitHeight
    radius: pane.overlay.radiusControl
    color: applied ? Util.alpha(pane.accent, 0.14) : ((highlighted || cardHover.containsMouse) ? Util.alpha(pane.fg, 0.06) : "transparent")
    border.width: (applied || highlighted) ? 1 : 0
    border.color: Util.alpha(pane.accent, 0.6)
    Behavior on color { ColorAnimation { duration: pane.overlay.motionFast } }

    MouseArea {
      id: cardHover
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: card.canApply ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: { pane.selectedScene = card.entry.name; pane.overlay.selected = ""; pane.overlay.focusKeys(); if (card.canApply) pane.pickScene() }
    }
    Row {
      id: cardRow
      x: Style.spacing.sm
      y: Style.spacing.sm
      width: parent.width - Style.spacing.sm * 2 - deleteButton.width - Style.spacing.sm
      spacing: Style.spacing.lg
      Thumb {
        overlay: pane.overlay
        spec: card.spec
        sources: card.sources
        current: card.applied
        width: pane.overlay.uiFont * 5
        anchors.verticalCenter: parent.verticalCenter
      }
      Column {
        width: parent.width - pane.overlay.uiFont * 5 - Style.spacing.lg
        spacing: Style.spacing.xxs
        anchors.verticalCenter: parent.verticalCenter
        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: card.entry.name
          color: card.applied ? pane.accent : pane.fg
          font.family: pane.family
          font.pixelSize: pane.overlay.uiFontSmall
          font.bold: card.applied
          elide: Text.ElideRight
        }
        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: card.meta
          color: card.valid ? Util.alpha(pane.fg, 0.62) : Color.urgent
          font.family: pane.family
          font.pixelSize: pane.overlay.uiCaption
          wrapMode: card.valid ? Text.NoWrap : Text.WordWrap
          elide: card.valid ? Text.ElideRight : Text.ElideNone
        }
      }
    }
    Action {
      id: deleteButton
      text: "✕"
      bordered: false
      fontSize: pane.overlay.uiCaption
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.xs
      anchors.verticalCenter: parent.verticalCenter
      opacity: (card.highlighted || cardHover.containsMouse || hot || pane.deleting === card.entry.name) ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: pane.overlay.motionFast } }
      tooltipText: "Delete this scene"
      onClicked: { pane.selectedScene = card.entry.name; pane.overlay.selected = ""; pane.overlay.focusKeys(); pane.deleting = card.entry.name }
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
    text: pane.overlay.catalogError || "The workspace catalog is unavailable. Try again."
    urgent: true
  }
  Action {
    visible: pane.overlay.catalogFailed
    text: "Retry"
    onClicked: pane.overlay.retryCatalog()
  }
  Muted {
    visible: !pane.overlay.catalogFailed && pane.overlay.contentCatalog === null
    text: "Reading the workspace…"
  }
  Muted {
    visible: pane.ready && !pane.overlay.viewedIsActive
    text: pane.overlay.committedLayout.indexOf("lua:") === 0
      ? "Showing another layout. Select " + pane.overlay.committedLayout.slice(4) + " under Layouts to edit this workspace's content."
      : "Workspace " + pane.overlay.workspaceId + " is not on a Hypertile layout. Pick one under Layouts first; then its zones can hold content."
  }

  // ------------------------------------------------------ saved scenes

  Section {
    visible: pane.ready && pane.scenes.length > 0
    title: "SCENES"

    Column {
      width: pane.width
      spacing: Style.spacing.xs
      Repeater {
        id: sceneCards
        model: pane.scenes
        SceneCard {}
      }
    }

    Prompt {
      id: deletePrompt
      visible: pane.deleting !== ""
      warning: true
      PromptTitle { text: "Delete scene " + pane.deleting + "?" }
      Muted { width: parent.width; text: "Its file is removed. Nothing on the workspace changes and nothing closes." }
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
    title: "ZONES"
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
          icon: modelData.spacer ? "" : pane.overlay.iconFor(zoneSource)
          text: modelData.spacer ? "Spacer" : pane.overlay.contentName(zoneSource)
          sub: pane.overlay.zoneLabel(modelData.name)
          trait: zoneState.text
          urgent: zoneState.urgent
          current: pane.overlay.selected === modelData.name
          onClicked: pane.overlay.selected = modelData.name
        }
      }
    }

    Muted {
      visible: pane.sel === null
      text: "Click a zone on the screen, or in this list, to choose what opens there."
    }
    Muted { visible: pane.sel !== null && pane.sel.spacer === true; text: "A spacer never holds windows." }
  }

  // ------------------------------------------- what the zone could hold

  Section {
    visible: pane.usable && pane.sel !== null && pane.sel.spacer !== true

    Item {
      width: pane.width
      implicitHeight: Math.max(pickBadge.implicitHeight, pickName.implicitHeight, pickCurrent.implicitHeight)
      Chip {
        id: pickBadge
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: pane.sel ? (pane.sel.numbers.length > 0 ? pane.sel.numbers.join(" · ") : "—") : ""
        strong: true
        foreground: pane.fg
        fontFamily: pane.family
        fontSize: pane.overlay.uiCaption
      }
      Text {
        id: pickName
        anchors.left: pickBadge.right
        anchors.leftMargin: Style.spacing.md
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, Math.min(implicitWidth, parent.width - pickBadge.width - pickCurrent.width - Style.spacing.md * 2))
        textFormat: Text.PlainText
        text: pane.sel ? pane.overlay.zoneLabel(pane.sel.name) : ""
        color: pane.fg
        font.family: pane.family
        font.pixelSize: pane.overlay.uiFontSmall
        font.bold: true
        elide: Text.ElideRight
        Text {
          // The layout's own name for the zone, when the position stands in for it.
          visible: pane.sel !== null && pane.overlay.zoneLabel(pane.sel.name) !== pane.sel.name
          x: parent.contentWidth + Style.spacing.md
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: pane.sel ? pane.sel.name : ""
          color: Util.alpha(pane.fg, 0.62)
          font.family: pane.family
          font.pixelSize: pane.overlay.uiCaption
        }
      }
      Text {
        id: pickCurrent
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, parent.width * 0.55)
        textFormat: Text.PlainText
        text: pane.overlay.contentName(pane.source)
        color: pane.accent
        font.family: pane.family
        font.pixelSize: pane.overlay.uiFontSmall
        font.bold: true
        elide: Text.ElideRight
      }
    }
    Muted { text: Content.detail(pane.source); urgent: Content.state(pane.source).urgent }

    TextField {
      id: searchField
      width: pane.width
      foreground: pane.fg
      accent: pane.accent
      font.family: pane.family
      font.pixelSize: pane.overlay.uiFontSmall
      placeholderText: "Search apps…"
      Component.onCompleted: background.radius = pane.overlay.radiusControl
      // Esc clears, Enter takes the hot match, ↑ ↓ move it; everything
      // else the overlay would do with these keys still happens.
      Keys.onPressed: function(event) {
        if (pane.handleSearchKey(event)) event.accepted = true
      }
    }

    Row {
      visible: !pane.searching
      spacing: Style.spacing.sm
      Action {
        text: "Local windows"
        selected: pane.isCurrent({ kind: "local" })
        tooltipText: "Windows open here in fill order"
        onClicked: pane.choose({ kind: "local" })
        onHotChanged: hot ? pane.overlay.ghost(pane.ghostFor({ kind: "local" })) : pane.overlay.unghost("local:local")
      }
      Action {
        text: "Empty"
        selected: pane.isCurrent({ kind: "empty" })
        tooltipText: "Nothing opens here; the zone stays empty"
        onClicked: pane.choose({ kind: "empty" })
        onHotChanged: hot ? pane.overlay.ghost(pane.ghostFor({ kind: "empty" })) : pane.overlay.unghost("empty:empty")
      }
    }

    Column {
      visible: pane.builtinMatches.length > 0
      width: pane.width
      spacing: Style.spacing.xxs
      Repeater {
        model: pane.builtinMatches
        MatchRow { offset: 0 }
      }
    }

    Group {
      visible: pane.openMatches.length > 0
      title: "OPEN HERE"
      Repeater {
        model: pane.openMatches
        MatchRow { offset: pane.builtinMatches.length }
      }
    }

    Group {
      visible: pane.remoteMatches.length > 0
      title: "REMOTE DESKTOPS"
      Repeater {
        model: pane.remoteMatches
        MatchRow { offset: pane.builtinMatches.length + pane.openMatches.length }
      }
    }

    Group {
      visible: pane.appMatches.length > 0
      title: "APPS"
      caption: pane.searching ? "" : "Launches the app, or reuses its open window"
      Repeater {
        model: pane.appMatches
        MatchRow { offset: pane.builtinMatches.length + pane.openMatches.length + pane.remoteMatches.length }
      }
    }

    Muted {
      visible: pane.searching && pane.matches.length === 0
      text: "Nothing matches “" + pane.query.trim() + "”"
    }
    Muted {
      visible: !pane.searching && pane.apps.length === 0
      text: "Apps with a known window identity appear here. Open an installed app to help identify it."
    }
  }
}
