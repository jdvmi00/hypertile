import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Geometry.js" as Geometry
import "Editor.js" as Editor
import "Content.js" as Content

// Hypertile overlay: view and edit tiling layouts at true scale. The keys
// are listed in README.md and in the rail (?).
//
// Pieces: ZoneItem (a zone), Divider (a boundary), Rail (the inspector),
// Thumb (a layout picture), Card and Chip (surfaces). Zone math is
// Geometry.js, edits are pure functions in Editor.js.
//
// Everything goes through hypertile-ctl (JSON in, JSON out): preview
// hot-swaps the layout in the compositor without touching disk, save
// writes ~/.config/hypr/layouts/<name>.lua and reloads. Discarding an edit
// previews the saved spec back; nothing reloads. The shell unloads this
// item when the overlay hides, so a fresh instance starts every open.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string home: Quickshell.env("HOME")
  readonly property string ctl: home + "/.local/bin/hypertile-ctl"
  readonly property string missingCtlText: "hypertile-ctl is not installed: run install.sh in the plugin directory (~/.config/omarchy/plugins/jmartin.hypertile)"
  readonly property string runtimeDir: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/hypertile"
  readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || (home + "/.local/state")) + "/hypertile"

  // Motion durations shared by every piece of the overlay.
  readonly property int motionFast: 120
  readonly property int motion: 160
  readonly property int motionSlow: 220

  readonly property var aspectPresets: [
    { label: "Free", value: null }, { label: "1:1", value: 1 }, { label: "4:3", value: 4 / 3 },
    { label: "3:2", value: 1.5 }, { label: "16:9", value: 16 / 9 }, { label: "21:9", value: 21 / 9 },
  ]

  property bool opened: false
  property var current: null       // hypertile-ctl current --json
  property var layouts: []         // hypertile-ctl list --json .layouts
  property var workspaces: []      // hypertile-ctl workspaces --json .workspaces
  property var windows: []         // hypertile-ctl windows --json .windows
  property string defaultLayout: ""
  property bool contentMode: false
  property var contentCatalog: null
  readonly property bool managedContent: {
    if (!contentCatalog) return false
    var streams = contentCatalog.streams || []
    for (var i = 0; i < streams.length; i++) if (streams[i].desired && streams[i].assignment.workspace === workspaceId) return true
    return contentCatalog.current && ["none", "restored"].indexOf(contentCatalog.current.phase) === -1
  }
  property int viewIndex: 0
  property string errorText: ""
  property string statusText: ""
  property bool statusSticky: false   // a status that stays until replaced
  onStatusTextChanged: statusSticky = false

  // ---- editing state
  property bool editing: false
  property var draft: null
  property string draftName: ""
  property bool draftIsNew: false
  property bool dirty: false
  property var undoStack: []
  property string selected: ""
  property bool numbering: false
  property var numberingFill: []
  property bool naming: false
  property bool confirmingDiscard: false
  property bool previewPending: false
  property bool leaveAfterPreview: false
  property bool busy: false
  property bool pickerOpen: false
  property bool confirmingDelete: false
  property bool renaming: false
  property bool choosingNew: false
  property bool peeking: false
  property bool nudging: false        // a run of Shift+arrow presses shares one undo entry
  property string pendingView: ""     // layout to view once the list is re-read

  // ---- preferences (persisted in ~/.local/state/hypertile/overlay.json)
  property bool dockLeft: false
  property bool showKeys: false
  property bool layoutSectionOpen: false
  property bool rulesSectionOpen: false

  // ---- drag state (one MouseArea does all hit-testing, so nothing is
  // destroyed under the pointer while the model changes)
  property var hoverDivider: null
  property var dragDivider: null
  property string hoverZone: ""

  readonly property var viewed: (layouts.length > 0 && viewIndex >= 0 && viewIndex < layouts.length) ? layouts[viewIndex] : null
  readonly property var activeSpec: editing ? draft : (viewed ? viewed.spec : null)
  // The area this layout gets: the layout's own outer gap wins over the global.
  readonly property var area: Geometry.areaFor(current, activeSpec)
  readonly property var zones: (activeSpec && area) ? Geometry.zones(activeSpec, area, numbering ? numberingFill : undefined) : []
  // Zones by name, plus a list model of names that is updated in place, so
  // the zone items persist across edits and can animate to their new boxes.
  readonly property var zoneMap: {
    var m = ({})
    for (var i = 0; i < zones.length; i++) m[zones[i].name] = zones[i]
    return m
  }
  readonly property var noZone: ({ name: "", x: 0, y: 0, w: 1, h: 1, fit: { x: 0, y: 0, w: 1, h: 1 }, fitted: false, numbers: [], stack: "v", spacer: false, neverSplit: false, pctW: 0, pctH: 0 })
  onZonesChanged: syncZoneModel()

  function syncZoneModel() {
    var want = {}
    for (var i = 0; i < zones.length; i++) want[zones[i].name] = true
    for (var j = zoneModel.count - 1; j >= 0; j--) if (!want[zoneModel.get(j).name]) zoneModel.remove(j)
    var have = {}
    for (var k = 0; k < zoneModel.count; k++) have[zoneModel.get(k).name] = true
    for (var z = 0; z < zones.length; z++) if (!have[zones[z].name]) zoneModel.append({ name: zones[z].name })
  }

  ListModel { id: zoneModel }

  readonly property var dividers: (editing && activeSpec && area) ? Editor.dividers(activeSpec, area) : []
  // "In use" means the layout the workspace is persisted on, not whatever
  // browsing has it showing at the moment.
  readonly property bool viewedIsActive: viewed !== null && committedLayout !== "" && ("lua:" + viewed.name) === committedLayout
  readonly property string workspaceId: (current && current.workspace) ? String(current.workspace.id) : ""
  readonly property var selectedZone: {
    if ((!editing && !contentMode) || selected === "") return null
    for (var i = 0; i < zones.length; i++) if (zones[i].name === selected) return zones[i]
    return null
  }
  readonly property var selectedRules: (editing && draft && selected !== "") ? Editor.rulesFor(draft, selected) : []
  readonly property var windowClasses: {
    var seen = {}, out = []
    for (var i = 0; i < windows.length; i++) {
      var c = windows[i].class
      if (c && !seen[c]) { seen[c] = true; out.push(c) }
    }
    out.sort()
    return out
  }
  readonly property var contentWindowClasses: {
    var seen = {}, out = []
    for (var i = 0; i < windows.length; i++) {
      var w = windows[i]
      if (String(w.workspace) === workspaceId && w.class && w.class !== "com.moonlight_stream.Moonlight" && !seen[w.class]) {
        seen[w.class] = true; out.push(w.class)
      }
    }
    return out.sort()
  }
  readonly property var monitors: {
    var seen = {}, out = []
    for (var i = 0; i < workspaces.length; i++) {
      var m = workspaces[i].monitor
      if (m && !seen[m]) { seen[m] = true; out.push(m) }
    }
    return out
  }

  property color foreground: Color.menu.text
  property color accent: Color.accent
  property color scrim: Color.menu.scrim
  property string fontFamily: Style.font.menuFamily

  // Type scale for the chrome. The shell's tokens are bar-sized, so on a
  // large display everything grows with the screen height instead.
  readonly property int uiFont: Math.max(Style.font.subtitle, Math.round(window.height * 0.010))
  readonly property int uiFontSmall: Math.max(Style.font.body, Math.round(uiFont * 0.82))
  readonly property int uiCaption: Math.max(Style.font.caption, Math.round(uiFont * 0.66))
  readonly property int uiTitle: Math.round(uiFont * 1.4)
  readonly property int uiPad: Math.max(Style.spacing.panelPadding, Math.round(uiFont * 0.75))
  readonly property int railWidth: uiFont * 20

  // Rounding. The shell's token mirrors Hyprland's decoration:rounding,
  // which is often 0; the overlay rounds regardless, and follows the theme
  // when it rounds more.
  readonly property int radiusCard: Math.max(Style.cornerRadius, Style.space(12))
  readonly property int radiusControl: Math.max(Style.cornerRadius, Style.space(7))

  function focusKeys() { keys.forceActiveFocus() }

  function contentFor(zone) { return Content.source(contentCatalog, workspaceId, zone, viewedIsActive) }
  function contentLabel(zone) { return Content.label(contentFor(zone)) }
  function showContent(on) {
    if (editing) return
    contentMode = on
    browseTimer.stop()
    revertBrowse()
    selectActive()
    selected = ""
    if (!catalogProc.running) catalogProc.running = true
  }
  function sceneAction(action, name) {
    var args = ["scene", action]
    if (name) args.push(name)
    args.push("--workspace", workspaceId, "--json")
    if (runCtl(args, "Updating scene…", "Scene request accepted")) {
      browseTimer.stop()
      commitOnRefresh = true
    }
  }
  function saveScene(name) {
    name = String(name || "").trim()
    if (!Editor.validName(name)) { errorText = "Scene name: letters, digits, _ and - only"; return }
    sceneAction("save", name)
  }
  function assignContent(type, computer, profile, app) {
    if (!selected || !viewedIsActive) { errorText = "Select a zone in the current layout"; return }
    var args = ["scene", "content", "--workspace", workspaceId, "--zone", selected, "--type", type, "--json"]
    if (computer) args.push("--computer", computer)
    if (profile) args.push("--profile", profile)
    if (app) args.push("--app-class", app)
    runCtl(args, "Updating content…", "Content request accepted")
  }
  function streamAction(action, computer, closeOverlay) {
    if (closeOverlay) {
      Quickshell.execDetached([ctl, "stream", action, computer])
      dismiss()
    } else runCtl(["stream", action, computer, "--json"], "Updating " + computer + "…", "Request accepted")
  }

  // ------------------------------------------------------------ preferences

  FileView {
    id: prefsFile
    path: root.stateDir + "/overlay.json"
    watchChanges: false
    printErrors: false
    atomicWrites: true
    onLoaded: root.readPrefs(text())
  }

  function readPrefs(text) {
    var doc = null
    try { doc = JSON.parse(String(text || "")) } catch (e) { doc = null }
    if (!doc) return
    if (doc.dockLeft !== undefined) root.dockLeft = doc.dockLeft === true
    if (doc.showKeys !== undefined) root.showKeys = doc.showKeys === true
    if (doc.layoutSectionOpen !== undefined) root.layoutSectionOpen = doc.layoutSectionOpen === true
    if (doc.rulesSectionOpen !== undefined) root.rulesSectionOpen = doc.rulesSectionOpen === true
  }

  function savePrefs() {
    prefsFile.setText(JSON.stringify({ dockLeft: root.dockLeft, showKeys: root.showKeys, layoutSectionOpen: root.layoutSectionOpen, rulesSectionOpen: root.rulesSectionOpen }))
  }

  function setPref(key, value) {
    root[key] = value
    savePrefs()
  }

  // ------------------------------------------------------------- lifecycle

  function open(payloadJson) {
    root.opened = true
    root.errorText = ""
    root.statusText = ""
    root.committedLayout = ""
    root.liveLayout = ""
    root.browseTarget = ""
    root.browseLaunched = ""
    root.commitOnRefresh = false
    root.dismissAfterApply = false
    root.choosingNew = false
    root.peeking = false
    prefsFile.reload()
    refresh()
    Qt.callLater(function() { keys.forceActiveFocus() })
  }

  function close() {
    revertBrowse()
    root.opened = false
    root.editing = false
    root.numbering = false
    root.naming = false
    root.pickerOpen = false
    root.choosingNew = false
    root.confirmingDiscard = false
    root.peeking = false
  }

  function dismiss() {
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "jmartin.hypertile")
    else close()
  }

  // --------------------------------------------------------------- data

  function refresh() {
    currentProc.running = true
    workspacesProc.running = true
    windowsProc.running = true
    defaultProc.running = true
    if (!catalogProc.running) catalogProc.running = true
  }

  function parseJson(text, what) {
    try { return JSON.parse(String(text || "")) }
    catch (e) { root.errorText = "Could not parse " + what + ": " + e; return null }
  }

  function selectActive() {
    if (!root.current || !root.current.workspace) return
    var want = root.current.workspace.layout
    for (var i = 0; i < root.layouts.length; i++)
      if ("lua:" + root.layouts[i].name === want) { root.viewIndex = i; return }
    if (root.viewIndex >= root.layouts.length) root.viewIndex = 0
  }

  function step(delta) {
    if (root.editing || root.layouts.length === 0) return
    viewAt((root.viewIndex + delta + root.layouts.length) % root.layouts.length)
  }

  // Browse to the layout at `index` in the list (arrows, or a click in the
  // rail's layout list).
  function viewAt(index) {
    if (root.editing || index < 0 || index >= root.layouts.length) return
    root.viewIndex = index
    root.statusText = ""
    root.confirmingDelete = false
    root.choosingNew = false
    browseTimer.restart()
  }

  // ------------------------------------------------------------ browsing
  //
  // The workspace follows the viewed layout while browsing, so the real
  // windows move under the overlay. Each switch is a compositor-only apply
  // (nothing persisted) debounced behind the keys, so holding an arrow
  // across five layouts switches once, to the one landed on. Enter
  // persists and closes; closing any other way puts the committed layout back.
  property string committedLayout: ""   // what the workspace's rule file says
  property string liveLayout: ""        // what the compositor is showing
  property string browseTarget: ""      // what browsing wants it to show
  property string browseLaunched: ""    // what the running switch is going to
  property bool commitOnRefresh: false
  property bool dismissAfterApply: false

  function browseTo(layout) {
    if (layout === "" || root.workspaceId === "") return
    if (root.contentMode || root.managedContent || root.contentCatalog === null) return
    root.browseTarget = layout
    root.liveLayout = layout
    runBrowse()
  }

  // A compositor-only switch of this workspace; nothing is persisted.
  function browseArgs(layout) {
    return [root.ctl, "apply", layout, "--workspace", root.workspaceId, "--no-persist", "--quiet"]
  }

  function runBrowse() {
    if (browseProc.running || root.browseTarget === "" || root.browseTarget === root.browseLaunched) return
    root.browseLaunched = root.browseTarget
    browseProc.command = browseArgs(root.browseTarget)
    browseProc.running = true
  }

  // Runs while the overlay is being torn down (the shell unloads it on
  // hide), so the switch is detached rather than a child that would be
  // killed with the overlay.
  function revertBrowse() {
    browseTimer.stop()
    if (root.committedLayout === "" || root.liveLayout === "" || root.liveLayout === root.committedLayout || root.workspaceId === "") return
    root.liveLayout = root.committedLayout
    root.browseTarget = root.committedLayout
    root.browseLaunched = root.committedLayout
    Quickshell.execDetached(browseArgs(root.committedLayout))
  }

  Timer {
    id: browseTimer
    interval: 200
    onTriggered: if (!root.editing && root.viewed) root.browseTo("lua:" + root.viewed.name)
  }

  // A hypertile-ctl run whose stderr, if any, becomes the toast's error.
  component CtlProcess: Process {
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.reportCtlError(text)
    }
  }

  function reportCtlError(text) {
    var t = String(text || "").trim()
    if (t !== "") root.errorText = t.replace(/^hypertile-ctl: /, "")
  }

  CtlProcess {
    id: browseProc
    onExited: Qt.callLater(root.runBrowse)
  }

  readonly property bool viewedIsDefault: viewed !== null && defaultLayout === "lua:" + viewed.name
  readonly property bool viewedInCycle: viewed !== null && !(viewed.spec && viewed.spec.in_cycle === false)
  // Window corner radius this layout gives its tiled windows; the zone
  // cards use the same radius so the picture matches the workspace.
  readonly property int effectiveRounding: (activeSpec && activeSpec.rounding !== undefined) ? activeSpec.rounding : (current ? (current.rounding || 0) : 0)

  // Rename the viewed layout: its file, every workspace rule that points
  // at it, and the default follow the new name.
  function startRename() {
    if (!root.viewed || root.editing || root.busy) return
    root.confirmingDelete = false
    root.choosingNew = false
    root.renaming = true
    root.errorText = ""
    rail.focusName(root.viewed.name)
  }

  // False when the name is refused; the error says why.
  function renameViewed(name) {
    if (!root.viewed || root.editing) return false
    name = String(name || "").trim()
    if (name === root.viewed.name) return true
    if (!Editor.validName(name)) { root.errorText = "Name: letters, digits, _ and - only"; return false }
    if (layoutNameTaken(name)) { root.errorText = "A layout called " + name + " already exists"; return false }
    root.errorText = ""
    root.pendingView = name
    return runCtl(["rename", root.viewed.name, name], "Renaming to " + name + "…", "Renamed to " + name)
  }

  function confirmRename() {
    if (!root.viewed || renameViewed(rail.nameText)) { root.renaming = false; focusKeys() }
  }

  // Delete the viewed layout's file. Workspaces whose rule points at it
  // fall back to the default; the default itself cannot be deleted.
  function deleteViewed() {
    if (!root.viewed || root.editing || root.viewedIsDefault) return
    root.confirmingDelete = false
    runCtl(["remove", root.viewed.name, "--force"], "Deleting " + root.viewed.name + "…", "Deleted " + root.viewed.name)
  }

  // Take the viewed layout out of (or put it back into) the SUPER+L cycle.
  // Saved straight to its file; the cycle reads the files, so no reload.
  function setInCycle(on) {
    if (!root.viewed || root.editing || root.busy) return
    var spec = Editor.clone(root.viewed.spec)
    if (on) delete spec.in_cycle
    else spec.in_cycle = false
    var doc = Editor.toDoc(root.viewed.name, spec)
    doc.stamp = Date.now()
    root.busy = true
    root.statusText = "Updating " + root.viewed.name + "…"
    cycleFile.setText(JSON.stringify(doc))
  }

  FileView {
    id: cycleFile
    path: root.runtimeDir + "/cycle.json"
    atomicWrites: true
    printErrors: false
    onSaved: { root.busy = false; root.runCtl(["save", path, "--no-reload"], "Updating…", "") }
    onSaveFailed: { root.busy = false; root.errorText = "Could not write " + path }
  }

  // One hypertile-ctl call at a time; false when one is already running.
  property string ctlDone: ""
  function runCtl(args, status, done) {
    if (root.busy) return false
    root.busy = true
    root.statusText = status
    root.ctlDone = done === undefined ? "" : done
    ctlProc.command = [root.ctl].concat(args)
    ctlProc.running = true
    return true
  }

  // Enter: persist the viewed layout on this workspace and close. The
  // overlay's toast is the feedback while it is open (--quiet); the shell's
  // OSD is for switches made without it.
  function applyViewed(andClose) {
    if (!root.viewed) return
    if (root.managedContent && !root.viewedIsActive) {
      root.errorText = "This workspace has assigned content. Open Scenes and choose Start scene with this layout to replace it."
      return
    }
    browseTimer.stop()
    if (!runCtl(["apply", root.viewed.name, "--quiet"], "Using " + root.viewed.name + "…", "Now using " + root.viewed.name)) return
    root.commitOnRefresh = true
    root.dismissAfterApply = andClose === true
  }

  function applyTo(workspace) {
    if (!root.viewed) return
    if (contentWorkspace(String(workspace))) {
      root.applyQueue = []
      root.errorText = "Workspace " + workspace + " has assigned content. Open its Scenes view to change the layout."
      return
    }
    runCtl(["apply", root.viewed.name, "--workspace", String(workspace), "--quiet"], "Using " + root.viewed.name + " on workspace " + workspace + "…", "Workspace " + workspace + " uses " + root.viewed.name)
  }

  function contentWorkspace(workspace) {
    if (!root.contentCatalog) return true
    if ((root.contentCatalog.active_workspaces || []).indexOf(workspace) !== -1) return true
    return (root.contentCatalog.streams || []).some(function(s) { return s.desired && s.assignment.workspace === workspace })
  }

  // Every existing workspace on a monitor, one apply per workspace.
  property var applyQueue: []
  function applyMonitor(monitor) {
    if (!root.viewed) return
    var ids = []
    for (var i = 0; i < root.workspaces.length; i++) if (root.workspaces[i].monitor === monitor) ids.push(root.workspaces[i].id)
    if (ids.length === 0) return
    for (var j = 0; j < ids.length; j++) if (contentWorkspace(String(ids[j]))) {
      root.errorText = "This monitor has a workspace with assigned content. Change its layout from Scenes."
      return
    }
    root.applyQueue = ids.slice(1)
    applyTo(ids[0])
  }

  function setDefault() {
    if (!root.viewed) return
    runCtl(["default", root.viewed.name], "Making " + root.viewed.name + " the default…", root.viewed.name + " is the default")
  }

  function layoutNameTaken(name) {
    for (var i = 0; i < root.layouts.length; i++) if (root.layouts[i].name === name) return true
    return false
  }

  function uniqueLayoutName(base) {
    if (!layoutNameTaken(base)) return base
    for (var n = 2; n < 1000; n++) if (!layoutNameTaken(base + "-" + n)) return base + "-" + n
    return base + "-" + Date.now()
  }

  // ------------------------------------------------------------ editing

  // asNew: the draft is a new layout (named on save). blank: start from one
  // zone instead of a copy of the viewed layout.
  function startEdit(asNew, blank) {
    if (!root.current) return
    var fromBlank = blank === true || !root.viewed || !root.viewed.spec
    if (!asNew && fromBlank) return
    root.draft = Editor.identify(fromBlank ? ({ name: "main", fill: ["main"] }) : root.viewed.spec, asNew === true)
    root.draftIsNew = asNew === true
    root.draftName = !root.draftIsNew ? root.viewed.name : (fromBlank ? uniqueLayoutName("new-layout") : uniqueLayoutName(root.viewed.name + "-copy"))
    root.undoStack = []
    root.dirty = false
    root.selected = fromBlank ? "main" : ""
    root.numbering = false
    root.naming = false
    root.pickerOpen = false
    root.confirmingDelete = false
    root.confirmingDiscard = false
    root.choosingNew = false
    root.nudging = false
    root.errorText = ""
    root.statusText = ""
    root.editing = true
    windowsProc.running = true
    // A new layout is a new name: preview it so this workspace shows it right away.
    if (root.draftIsNew) { root.dirty = true; schedulePreview() }
  }

  function pushUndo() {
    var next = root.undoStack.slice()
    next.push(JSON.stringify(root.draft))
    if (next.length > 100) next.shift()
    root.undoStack = next
  }

  function commit(spec) {
    root.draft = spec
    root.dirty = true
    root.confirmingDiscard = false
    schedulePreview()
  }

  // pushUndo + commit in one step for the property panels.
  function edit(spec) { root.nudging = false; pushUndo(); commit(spec) }

  function undo() {
    if (root.undoStack.length === 0) { root.statusText = "Nothing to undo"; return }
    var next = root.undoStack.slice()
    var last = next.pop()
    root.undoStack = next
    root.nudging = false
    root.draft = JSON.parse(last)
    root.dirty = true
    if (Editor.leafNames(root.draft).indexOf(root.selected) === -1) root.selected = ""
    schedulePreview()
  }

  function splitSelected(kind) {
    if (!root.editing || root.selected === "") { root.statusText = "Select a zone first"; return }
    edit(Editor.splitZone(root.draft, root.selected, kind))
  }

  function deleteZone(name) {
    if (!root.editing || name === "") return
    if (Editor.leafNames(root.draft).length <= 1) { root.statusText = "A layout needs at least one zone"; return }
    edit(Editor.deleteZone(root.draft, name))
    if (root.selected === name) root.selected = ""
  }

  function renameSelected(name) {
    if (!root.editing || root.selected === "") return false
    name = String(name || "").trim()
    if (name === root.selected) return true
    if (!Editor.validName(name)) { root.errorText = "Zone name: letters, digits, _ and - only"; return false }
    if (Editor.leafNames(root.draft).indexOf(name) !== -1) { root.errorText = "A zone called " + name + " already exists"; return false }
    root.errorText = ""
    var was = root.selected
    edit(Editor.renameZone(root.draft, was, name))
    root.selected = name
    return true
  }

  // Move the selection to the zone beside the selected one.
  function selectNeighbor(dir) {
    if (!root.editing || !root.draft) return
    var names = Editor.leafNames(root.draft)
    if (names.length === 0) return
    if (root.selected === "") { root.selected = names[0]; return }
    var next = Editor.neighbor(root.draft, root.area, root.selected, dir)
    if (next !== "") root.selected = next
  }

  // Shift+arrow: move the selected zone's edge by 1% of the area. A run of
  // presses is one undo step.
  function nudgeSelected(axis, delta) {
    if (!root.editing || root.selected === "") { root.statusText = "Select a zone first"; return }
    var next = Editor.nudge(root.draft, root.area, root.selected, axis, delta)
    if (next === root.draft) { root.statusText = "That edge is the screen's"; return }
    if (!root.nudging) { pushUndo(); root.nudging = true }
    commit(next)
  }

  // The size chip on a zone: select it and jump to the rail's width field.
  function editSize(name) {
    if (!root.editing) return
    root.selected = name
    root.pickerOpen = false
    rail.focusWidth()
  }

  // Exact size from the rail: `fraction` of the layout area on `axis`.
  function setSelectedExtent(axis, fraction) {
    if (!root.editing || root.selected === "") return
    var next = Editor.setZoneExtent(root.draft, root.area, root.selected, axis, fraction)
    if (next === root.draft) return
    edit(next)
  }

  function zoneProp(key, value) {
    if (!root.editing || root.selected === "") return
    var after = Editor.setZoneProp(root.draft, root.selected, key, value)
    if (after === root.draft) {
      if (key === "spacer") root.statusText = "At least one zone must take windows"
      return
    }
    edit(after)
  }

  function zoneCapacity(value) {
    if (!root.editing || root.selected === "") return
    edit(Editor.setCapacity(root.draft, root.selected, value))
  }

  function layoutProp(key, value) {
    if (!root.editing) return
    edit(Editor.setLayoutProp(root.draft, key, value))
  }

  function gap(which, value) {
    if (!root.editing) return
    edit(Editor.setGap(root.draft, which, value))
  }

  // Slider drags: the slider pushes one undo entry when the drag starts,
  // then every step updates the draft without another.
  function liveZoneProp(key, value) {
    if (!root.editing || root.selected === "") return
    commit(Editor.setZoneProp(root.draft, root.selected, key, value))
  }

  function liveGap(which, value) {
    if (!root.editing) return
    commit(Editor.setGap(root.draft, which, value))
  }

  function liveLayoutProp(key, value) {
    if (!root.editing) return
    commit(Editor.setLayoutProp(root.draft, key, value))
  }

  function togglePicker() {
    if (!root.pickerOpen) windowsProc.running = true
    root.pickerOpen = !root.pickerOpen
  }

  function addClassRule(cls) {
    if (!root.editing || root.selected === "") return
    root.pickerOpen = false
    edit(Editor.addRule(root.draft, { class: Editor.exactPattern(cls), slot: root.selected }))
  }

  function removeRule(index) {
    if (!root.editing) return
    edit(Editor.removeRule(root.draft, index))
  }

  function startNumbering() {
    if (!root.editing) return
    root.numbering = true
    root.numberingFill = []
    root.selected = ""
    root.pickerOpen = false
    root.statusText = ""
  }

  function numberZone(name) {
    if (Editor.fillableNames(root.draft).indexOf(name) === -1) { root.statusText = name + " is a spacer"; return }
    var leaf = Editor.findLeaf(root.draft, name)
    if (leaf && leaf.node.never_split === true && root.numberingFill.indexOf(name) !== -1) { root.statusText = name + " never splits: one window only"; return }
    var next = root.numberingFill.slice()
    next.push(name)
    root.numberingFill = next
  }

  // Zones that were not clicked follow the clicked ones in tree order, so
  // every zone keeps receiving windows; the toast says how many were added.
  function finishNumbering() {
    root.numbering = false
    if (root.numberingFill.length === 0) { root.statusText = "Numbering unchanged"; return }
    var clicked = root.numberingFill.slice()
    var fillable = Editor.fillableNames(root.draft)
    var added = 0
    for (var i = 0; i < fillable.length; i++) if (clicked.indexOf(fillable[i]) === -1) { clicked.push(fillable[i]); added++ }
    edit(Editor.setFill(root.draft, clicked))
    var n = root.numberingFill.length
    root.statusText = "Numbered " + n + (n === 1 ? " zone" : " zones") + (added > 0 ? "; " + added + " you did not click " + (added === 1 ? "follows" : "follow") + " as " + (n + 1) + (added > 1 ? "–" + (n + added) : "") : "")
  }

  function resizeDivider(d, px, py) {
    var pos = d.kind === "columns" ? px : py
    var ratio = (pos - d.start) / Math.max(1, d.span)
    root.draft = Editor.resizeSiblings(root.draft, d.path, d.index, ratio)
    root.dirty = true
    root.confirmingDiscard = false
    schedulePreview()
  }

  // ------------------------------------------------------------ preview

  // FileView skips a write whose text matches the file, and preview and
  // save wait for that write; a stamp keeps every document distinct (the
  // bridge ignores it).
  function docJson() {
    var doc = Editor.toDoc(root.draftName, root.draft)
    doc.stamp = Date.now()
    return JSON.stringify(doc)
  }

  function schedulePreview() { previewTimer.restart() }

  function doPreview() {
    if (!root.editing || !root.draft || root.workspaceId === "") return
    if (root.managedContent) { root.statusText = "Assigned content stays in place while editing. Changes take effect when saved."; return }
    if (previewProc.running) { root.previewPending = true; return }
    editFile.setText(docJson())
  }

  Timer {
    id: previewTimer
    interval: 120
    onTriggered: root.doPreview()
  }

  FileView {
    id: editFile
    path: root.runtimeDir + "/edit.json"
    atomicWrites: true
    printErrors: false
    onSaved: previewProc.running = true
    onSaveFailed: root.errorText = "Could not write " + path
  }

  CtlProcess {
    id: previewProc
    command: [root.ctl, "preview", editFile.path, "--workspace", root.workspaceId]
    onExited: function(code) {
      // A preview that goes through clears the error a bad edit left behind.
      if (code === 0) root.errorText = ""
      if (root.previewPending) {
        root.previewPending = false
        Qt.callLater(root.doPreview)
        return
      }
      if (root.leaveAfterPreview) {
        root.leaveAfterPreview = false
        root.leaveEdit("Changes discarded")
      }
    }
  }

  // --------------------------------------------------------------- save

  function requestSave() {
    if (!root.editing || root.busy) return
    if (root.numbering) finishNumbering()
    root.confirmingDiscard = false
    if (root.draftIsNew || root.naming) {
      root.naming = true
      rail.focusName(root.draftName)
      return
    }
    save()
  }

  function confirmName() { saveAs(rail.nameText) }

  // Save the draft under `name`; refused (with the error set) when the name
  // is invalid or belongs to another layout.
  function saveAs(name) {
    if (!root.editing || root.busy) return
    name = String(name || "").trim()
    if (!Editor.validName(name)) { root.errorText = "Name: letters, digits, _ and - only"; return }
    if ((!root.viewed || name !== root.viewed.name) && layoutNameTaken(name)) { root.errorText = "A layout called " + name + " already exists"; return }
    root.errorText = ""
    root.draftName = name
    root.naming = false
    keys.forceActiveFocus()
    save()
  }

  function save() {
    root.busy = true
    root.statusText = "Saving " + root.draftName + "…"
    saveFile.setText(docJson())
  }

  FileView {
    id: saveFile
    path: root.runtimeDir + "/save.json"
    atomicWrites: true
    printErrors: false
    onSaved: saveProc.running = true
    onSaveFailed: { root.busy = false; root.errorText = "Could not write " + path }
  }

  CtlProcess {
    id: saveProc
    command: [root.ctl, "save", saveFile.path]
    onExited: function(code) {
      root.busy = false
      if (code !== 0) { root.statusText = ""; return }
      root.editing = false
      root.numbering = false
      root.naming = false
      root.pickerOpen = false
      root.confirmingDiscard = false
      root.dirty = false
      root.pendingView = root.draftName
      // The reload dropped the preview rule; put this workspace on the saved layout.
      root.commitOnRefresh = true
      runCtl(["apply", root.draftName, "--quiet"], "Saved " + root.draftName, "Saved " + root.draftName)
    }
  }

  // Drop the draft. An existing layout previews its saved spec back (one
  // hot swap, nothing reloads); a new one puts the workspace back on the
  // layout it had.
  function discard() {
    if (!root.editing) return
    previewTimer.stop()
    root.confirmingDiscard = false
    root.numbering = false
    root.naming = false
    root.pickerOpen = false
    if (!root.dirty) { leaveEdit(""); return }
    if (root.draftIsNew || !root.viewed || !root.viewed.spec) {
      var back = root.committedLayout !== "" ? root.committedLayout : (root.viewed ? "lua:" + root.viewed.name : "")
      if (back === "" || root.workspaceId === "") { leaveEdit("Changes discarded"); return }
      root.liveLayout = back
      root.browseTarget = back
      root.browseLaunched = back
      root.busy = true
      root.statusText = "Discarding…"
      revertProc.command = browseArgs(back)
      revertProc.running = true
      return
    }
    root.draft = Editor.clone(root.viewed.spec)
    root.draftName = root.viewed.name
    root.busy = true
    root.statusText = "Discarding…"
    root.leaveAfterPreview = true
    root.previewPending = false
    if (previewProc.running) { root.previewPending = true; return }
    editFile.setText(docJson())
  }

  function leaveEdit(status) {
    previewTimer.stop()
    root.busy = false
    root.editing = false
    root.numbering = false
    root.naming = false
    root.pickerOpen = false
    root.confirmingDiscard = false
    root.dirty = false
    root.nudging = false
    root.selected = ""
    root.statusText = status
    root.refresh()
  }

  CtlProcess {
    id: revertProc
    onExited: root.leaveEdit("Changes discarded")
  }

  // ---------------------------------------------------------- processes

  CtlProcess {
    id: currentProc
    command: [root.ctl, "current", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var doc = root.parseJson(text, "current --json")
        if (doc) root.current = doc
        // The compositor's answer is the truth about the live layout, unless
        // a browse switch is in flight and about to change it.
        var layout = (doc && doc.workspace) ? String(doc.workspace.layout || "") : ""
        if (layout !== "") {
          if (root.committedLayout === "" || root.commitOnRefresh) root.committedLayout = layout
          root.commitOnRefresh = false
          if (!browseProc.running) { root.liveLayout = layout; root.browseTarget = layout; root.browseLaunched = layout }
        }
        listProc.running = true
      }
    }
    // The plugin can be added (omarchy plugin add) without the engine and the
    // CLI being installed yet; a start failure here is that, not a bug.
    onExited: function(code, status) {
      if (status !== 0 || code < 0 || code >= 126 || (code !== 0 && root.errorText === "")) root.errorText = root.missingCtlText
    }
  }

  CtlProcess {
    id: listProc
    command: [root.ctl, "list", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var doc = root.parseJson(text, "list --json")
        if (!doc || !Array.isArray(doc.layouts)) return
        var ok = []
        for (var i = 0; i < doc.layouts.length; i++) if (doc.layouts[i].spec) ok.push(doc.layouts[i])
        root.layouts = ok
        if (!root.editing) root.selectActive()
        if (root.pendingView !== "") {
          for (var p = 0; p < ok.length; p++) if (ok[p].name === root.pendingView) root.viewIndex = p
          root.pendingView = ""
        }
        if (ok.length === 0) { root.statusText = "No layouts yet. Press n to make one."; root.statusSticky = true }
      }
    }
  }

  Process {
    id: workspacesProc
    command: [root.ctl, "workspaces", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var doc = root.parseJson(text, "workspaces --json")
        if (doc && Array.isArray(doc.workspaces)) root.workspaces = doc.workspaces
      }
    }
  }

  Process {
    id: windowsProc
    command: [root.ctl, "windows", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var doc = root.parseJson(text, "windows --json")
        if (doc && Array.isArray(doc.windows)) root.windows = doc.windows
      }
    }
  }

  Process {
    id: defaultProc
    command: [root.ctl, "default"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.defaultLayout = String(text || "").trim()
    }
  }

  CtlProcess {
    id: catalogProc
    command: [root.ctl, "scene", "catalog", "--json"].concat(root.workspaceId ? ["--workspace", root.workspaceId] : [])
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var doc = root.parseJson(text, "scene status")
        if (!doc) return
        var old = root.contentCatalog ? root.contentCatalog.current : null
        root.contentCatalog = doc
        if (old && doc.current && (old.phase !== doc.current.phase || JSON.stringify(old.document) !== JSON.stringify(doc.current.document))) {
          root.commitOnRefresh = true
          if (!currentProc.running) currentProc.running = true
        }
      }
    }
  }

  Timer {
    interval: 2000
    repeat: true
    running: root.opened
    onTriggered: if (!catalogProc.running) catalogProc.running = true
  }

  // One generic runner for apply / default / rename / remove / save;
  // refreshes when done.
  CtlProcess {
    id: ctlProc
    stdout: StdioCollector { waitForEnd: true }
    onExited: function(code) {
      root.busy = false
      if (code !== 0) {
        root.commitOnRefresh = false
        root.dismissAfterApply = false
        root.applyQueue = []
        root.statusText = ""
        return
      }
      root.statusText = root.ctlDone
      if (root.applyQueue.length > 0) {
        var next = root.applyQueue.slice()
        var id = next.shift()
        root.applyQueue = next
        root.applyTo(id)
        return
      }
      if (root.dismissAfterApply) {
        // The switch is persisted now: closing must not revert it.
        root.dismissAfterApply = false
        if (root.viewed) root.committedLayout = "lua:" + root.viewed.name
        root.liveLayout = root.committedLayout
        root.dismiss()
        return
      }
      root.refresh()
    }
  }

  Timer {
    interval: 2200
    running: root.statusText !== "" && root.errorText === "" && !root.busy && !root.statusSticky
    onTriggered: root.statusText = ""
  }

  // ------------------------------------------------------------ keyboard

  function handleKey(event) {
    var plain = !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
    var ctrl = event.modifiers & Qt.ControlModifier
    var shift = event.modifiers & Qt.ShiftModifier
    var k = event.key

    if (root.naming || root.renaming) {
      if (k === Qt.Key_Escape) { root.naming = false; root.renaming = false; root.errorText = ""; keys.forceActiveFocus(); return true }
      return false
    }

    if (k === Qt.Key_Space && plain && !shift) {
      if (!event.isAutoRepeat) root.peeking = true
      return true
    }

    if (k === Qt.Key_Question || (shift && k === Qt.Key_Slash)) { setPref("showKeys", !root.showKeys); return true }

    if (k === Qt.Key_Escape) {
      if (root.confirmingDelete) { root.confirmingDelete = false; return true }
      if (root.choosingNew) { root.choosingNew = false; return true }
      if (root.confirmingDiscard) { root.confirmingDiscard = false; return true }
      if (root.pickerOpen) { root.pickerOpen = false; return true }
      if (root.numbering) { finishNumbering(); return true }
      if (root.editing) {
        if (!root.dirty) { leaveEdit(""); return true }
        root.confirmingDiscard = true
        return true
      }
      dismiss()
      return true
    }

    if (root.choosingNew) {
      if (plain && k === Qt.Key_B) { startEdit(true, true); return true }
      if (plain && k === Qt.Key_C && root.viewed) { startEdit(true, false); return true }
      return true
    }

    if (root.confirmingDiscard) {
      if (plain && k === Qt.Key_D) { discard(); return true }
      if ((plain && k === Qt.Key_W) || (ctrl && k === Qt.Key_S)) { requestSave(); return true }
      if (k === Qt.Key_Return || k === Qt.Key_Enter) { root.confirmingDiscard = false; return true }
      return true
    }

    if (root.numbering) {
      if (k === Qt.Key_Return || k === Qt.Key_Enter) { finishNumbering(); return true }
      if (k === Qt.Key_Backspace) { var next = root.numberingFill.slice(); next.pop(); root.numberingFill = next; return true }
      return true
    }

    if (root.editing) {
      if (shift && plain) {
        if (k === Qt.Key_Right || k === Qt.Key_L) { nudgeSelected("w", 0.01); return true }
        if (k === Qt.Key_Left || k === Qt.Key_H) { nudgeSelected("w", -0.01); return true }
        if (k === Qt.Key_Down || k === Qt.Key_J) { nudgeSelected("h", 0.01); return true }
        if (k === Qt.Key_Up || k === Qt.Key_K) { nudgeSelected("h", -0.01); return true }
      }
      if (k === Qt.Key_Right || (plain && k === Qt.Key_L)) { selectNeighbor("right"); return true }
      if (k === Qt.Key_Left || (plain && k === Qt.Key_H)) { selectNeighbor("left"); return true }
      if (k === Qt.Key_Down || (plain && k === Qt.Key_J)) { selectNeighbor("down"); return true }
      if (k === Qt.Key_Up || (plain && k === Qt.Key_K)) { selectNeighbor("up"); return true }
      if (plain && k === Qt.Key_C) { splitSelected("columns"); return true }
      if (plain && k === Qt.Key_R) { splitSelected("rows"); return true }
      if ((plain && k === Qt.Key_X) || k === Qt.Key_Delete) { deleteZone(root.selected); return true }
      if (plain && k === Qt.Key_F) { startNumbering(); return true }
      if (plain && k === Qt.Key_U) { undo(); return true }
      if (plain && k === Qt.Key_S) { if (root.selectedZone) zoneProp("spacer", !root.selectedZone.spacer); return true }
      if ((plain && k === Qt.Key_W) || (ctrl && k === Qt.Key_S)) { requestSave(); return true }
      if (k === Qt.Key_Tab) {
        var names = Editor.leafNames(root.draft)
        if (names.length > 0) root.selected = names[(names.indexOf(root.selected) + 1) % names.length]
        return true
      }
      return true
    }

    if (root.contentMode) {
      if (k === Qt.Key_Tab) {
        var contentNames = root.activeSpec ? Editor.leafNames(root.activeSpec) : []
        if (contentNames.length) root.selected = contentNames[(contentNames.indexOf(root.selected) + 1) % contentNames.length]
        return true
      }
      if (k === Qt.Key_Left || k === Qt.Key_Right || k === Qt.Key_Up || k === Qt.Key_Down) {
        if (root.activeSpec) root.selected = root.selected ? Editor.neighbor(root.activeSpec, root.area, root.selected,
          k === Qt.Key_Left ? "l" : k === Qt.Key_Right ? "r" : k === Qt.Key_Up ? "u" : "d") : Editor.leafNames(root.activeSpec)[0]
        return true
      }
    }
    if (k === Qt.Key_Right || k === Qt.Key_Down || (plain && (k === Qt.Key_L || k === Qt.Key_J))) { step(1); return true }
    if (k === Qt.Key_Left || k === Qt.Key_Up || (plain && (k === Qt.Key_H || k === Qt.Key_K))) { step(-1); return true }
    if (k === Qt.Key_Return || k === Qt.Key_Enter) { if (root.viewedIsActive) dismiss(); else applyViewed(true); return true }
    if (plain && k === Qt.Key_R) { refresh(); return true }
    if (plain && k === Qt.Key_E) { startEdit(false); return true }
    if (plain && k === Qt.Key_N) { root.confirmingDelete = false; root.choosingNew = !root.choosingNew; return true }
    if (k === Qt.Key_F2) { startRename(); return true }
    if (k === Qt.Key_Delete || (plain && k === Qt.Key_D)) { root.choosingNew = false; if (root.viewed && !root.viewedIsDefault) root.confirmingDelete = !root.confirmingDelete; return true }
    return false
  }

  function handleKeyRelease(event) {
    if (event.key === Qt.Key_Space && !event.isAutoRepeat) { root.peeking = false; return true }
    return false
  }

  // ------------------------------------------------------------------- UI

  PanelWindow {
    id: window
    visible: root.opened || scrimRect.opacity > 0
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "hypertile"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    // Chrome keeps clear of the bar and of any other reserved edge.
    readonly property var reserved: (root.current && root.current.reserved) || ({})
    readonly property int edgeTop: (reserved.top || 0) + Style.spacing.huge
    readonly property int edgeBottom: (reserved.bottom || 0) + Style.spacing.huge
    readonly property int edgeRight: (reserved.right || 0) + Style.spacing.huge
    readonly property int edgeLeft: (reserved.left || 0) + Style.spacing.huge

    Rectangle {
      id: scrimRect
      anchors.fill: parent
      color: root.scrim
      // Lighter while browsing: the windows underneath are the preview.
      // Gone while peeking.
      opacity: !root.opened || root.peeking ? 0 : (root.editing ? 1 : 0.55)
      Behavior on opacity { NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
      Rectangle {
        anchors.fill: parent
        color: Util.alpha(Color.background, 0.18)
      }
    }

    // Everything but the scrim: fades and settles from a hair smaller.
    Item {
      id: stage
      anchors.fill: parent
      opacity: root.opened ? 1 : 0
      scale: root.opened ? 1 : 0.985
      transformOrigin: Item.Center
      Behavior on opacity { NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
      Behavior on scale { NumberAnimation { duration: root.motionSlow; easing.type: Easing.OutCubic } }

      Item {
        id: keys
        anchors.fill: parent
        focus: true
        Keys.onPressed: function(event) { if (root.handleKey(event)) event.accepted = true }
        Keys.onReleased: function(event) { if (root.handleKeyRelease(event)) event.accepted = true }
      }

      // Single pointer handler for the whole layout area: zones select or
      // number, dividers drag, outside closes (view mode) or deselects.
      MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: {
          var d = root.dragDivider || root.hoverDivider
          if (!d) return Qt.ArrowCursor
          return d.kind === "columns" ? Qt.SplitHCursor : Qt.SplitVCursor
        }
        readonly property int threshold: Style.space(10)

        function inArea(x, y) {
          var a = root.area
          return a && x >= a.x && x < a.x + a.w && y >= a.y && y < a.y + a.h
        }

        function zoneAt(x, y) {
          return ((root.editing || root.contentMode) && root.activeSpec && inArea(x, y)) ? Editor.leafAt(root.activeSpec, root.area, x, y) : ""
        }

        onPositionChanged: function(mouse) {
          if (root.dragDivider) { root.resizeDivider(root.dragDivider, mouse.x, mouse.y); return }
          root.hoverDivider = root.editing ? Editor.dividerAt(root.dividers, mouse.x, mouse.y, threshold) : null
          root.hoverZone = zoneAt(mouse.x, mouse.y)
        }
        onExited: { root.hoverDivider = null; root.hoverZone = "" }

        onPressed: function(mouse) {
          keys.forceActiveFocus()
          root.pickerOpen = false
          root.confirmingDelete = false
          root.choosingNew = false
          if (root.naming) root.naming = false
          if (root.renaming) root.renaming = false
          if (!root.editing) {
            if (root.contentMode) { root.selected = zoneAt(mouse.x, mouse.y); return }
            if (mouse.button === Qt.LeftButton) root.dismiss()
            return
          }
          if (mouse.button === Qt.LeftButton && !root.numbering) {
            var d = Editor.dividerAt(root.dividers, mouse.x, mouse.y, threshold)
            if (d) { root.pushUndo(); root.nudging = false; root.dragDivider = d; return }
          }
          var name = zoneAt(mouse.x, mouse.y)
          if (root.numbering) { if (name !== "") root.numberZone(name); return }
          if (mouse.button === Qt.RightButton) { if (name !== "") root.deleteZone(name); return }
          root.selected = name
          root.confirmingDiscard = false
        }

        onReleased: function(mouse) {
          if (root.dragDivider) {
            root.resizeDivider(root.dragDivider, mouse.x, mouse.y)
            root.dragDivider = null
            root.hoverDivider = Editor.dividerAt(root.dividers, mouse.x, mouse.y, threshold)
          }
        }
      }

      // Layout area outline, so gaps and the bar read as "outside".
      Rectangle {
        visible: root.area !== null
        x: root.area ? root.area.x : 0
        y: root.area ? root.area.y : 0
        width: root.area ? root.area.w : 0
        height: root.area ? root.area.h : 0
        color: "transparent"
        border.width: 1
        border.color: Util.alpha(root.foreground, root.peeking ? 0.06 : 0.16)
      }

      Repeater {
        model: zoneModel
        ZoneItem { overlay: root }
      }

      Repeater {
        model: root.dividers
        Divider { overlay: root }
      }

      // The inspector rail: header, actions, and the sections for this mode.
      // Docks on either side; fades while peeking.
      Rail {
        id: rail
        overlay: root
        anchors.top: parent.top
        anchors.topMargin: window.edgeTop
        // Positioned by x rather than a left/right anchor: flipping the
        // side rebinds the two anchors one at a time, and while both are
        // set the rail is stretched across the screen and loses its width.
        x: root.dockLeft ? window.edgeLeft : parent.width - window.edgeRight - width
        maxHeight: window.height - window.edgeTop - window.edgeBottom
        opacity: root.peeking ? 0.12 : 1
        Behavior on opacity { NumberAnimation { duration: root.motionFast; easing.type: Easing.OutCubic } }
        transform: Translate {
          x: root.opened ? 0 : (root.dockLeft ? -Style.space(28) : Style.space(28))
          Behavior on x { NumberAnimation { duration: root.motionSlow; easing.type: Easing.OutCubic } }
        }
      }

      // Status and errors, only while there is something to say.
      Card {
        id: toast
        overlay: root
        readonly property string text: root.errorText !== "" ? root.errorText : root.statusText
        // Keep the last message while fading out.
        property string shown: ""
        onTextChanged: if (text !== "") shown = text
        opacity: text !== "" && !root.peeking ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: root.motionFast; easing.type: Easing.OutCubic } }
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: window.edgeBottom
        width: toastText.implicitWidth + root.uiPad * 2
        height: toastText.implicitHeight + root.uiPad * 1.2
        urgent: root.errorText !== ""
        Text {
          id: toastText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: toast.shown
          color: root.errorText !== "" ? Color.urgent : root.foreground
          font.family: root.fontFamily
          font.pixelSize: root.uiFontSmall
        }
      }
    }
  }

  // ------------------------------------------------------------ helpers

  function aspectPreset(a) {
    for (var i = 0; i < aspectPresets.length; i++) {
      var p = aspectPresets[i]
      if (p.value !== null && Math.abs(p.value - a) < 0.01) return p
    }
    return null
  }

  // The preset's exact value when `a` is within rounding of one.
  function aspectKey(a) {
    var p = aspectPreset(a)
    return p ? p.value : a
  }

  function aspectLabel(a) {
    var p = aspectPreset(a)
    return p ? p.label : (Math.round(a * 100) / 100) + ":1"
  }

  // Scriptable from the terminal: omarchy-shell hypertile <method> [args]
  IpcHandler {
    target: "hypertile"
    function close(): void { root.dismiss() }
    function next(): void { root.step(1) }
    function prev(): void { root.step(-1) }
    function apply(): void { root.applyViewed(false) }
    function use(): void { root.applyViewed(true) }
    function deleteLayout(): void { root.deleteViewed() }
    function rename(name: string): void { root.renameViewed(name) }
    function applyTo(workspace: string): void { root.applyTo(workspace) }
    function applyMonitor(monitor: string): void { root.applyMonitor(monitor) }
    function setDefault(): void { root.setDefault() }
    function inCycle(on: bool): void { root.setInCycle(on) }
    function dock(side: string): void { root.setPref("dockLeft", side === "left") }
    function keysHint(on: bool): void { root.setPref("showKeys", on) }
    function peek(on: bool): void { root.peeking = on }
    function refresh(): void { root.refresh() }
    function content(on: bool): void { root.showContent(on) }
    function assign(kind: string, computer: string, profile: string): void { root.assignContent(kind, computer, profile) }
    function scene(action: string, name: string): void { root.sceneAction(action, name) }
    function viewed(): string { return root.viewed ? root.viewed.name : "" }
    function view(name: string): void {
      if (root.editing) return
      for (var i = 0; i < root.layouts.length; i++) if (root.layouts[i].name === name) { root.viewAt(i); return }
    }
    // editing
    function edit(): void { root.startEdit(false) }
    function newLayout(): void { root.startEdit(true, false) }
    function newBlank(): void { root.startEdit(true, true) }
    function select(name: string): void { root.selected = name }
    function move(dir: string): void { root.selectNeighbor(dir) }
    function nudge(axis: string, delta: real): void { root.nudgeSelected(axis, delta) }
    function size(name: string, axis: string, fraction: real): void { root.selected = name; root.setSelectedExtent(axis, fraction) }
    function renameZone(name: string, to: string): void { root.selected = name; root.renameSelected(to) }
    function split(name: string, kind: string): void { root.selected = name; root.splitSelected(kind) }
    function remove(name: string): void { root.deleteZone(name) }
    function renumber(csv: string): void {
      if (!root.editing) return
      root.edit(Editor.setFill(root.draft, String(csv).split(",").map(function(s) { return s.trim() })))
    }
    function resize(pathCsv: string, index: int, ratio: real): void {
      if (!root.editing) return
      var path = String(pathCsv).trim() === "" ? [] : String(pathCsv).split(",").map(function(s) { return parseInt(s, 10) })
      root.edit(Editor.resizeSiblings(root.draft, path, index, ratio))
    }
    function zoneProp(name: string, key: string, value: string): void {
      root.selected = name
      var v = value === "" ? null : (value === "true" ? true : (value === "false" ? false : (isNaN(Number(value)) ? value : Number(value))))
      root.zoneProp(key, v)
    }
    function capacity(name: string, value: int): void { root.selected = name; root.zoneCapacity(value) }
    function layoutProp(key: string, value: string): void {
      var v = value === "" ? null : (isNaN(Number(value)) ? value : Number(value))
      root.layoutProp(key, v)
    }
    function gap(which: string, value: string): void { root.gap(which, value === "" ? null : Number(value)) }
    function addRule(cls: string, zone: string): void { root.selected = zone; root.addClassRule(cls) }
    function removeRule(index: int): void { root.removeRule(index) }
    function undo(): void { root.undo() }
    function saveAs(name: string): void { root.saveAs(name) }
    function discard(): void { root.discard() }
    function draft(): string { return root.draft ? JSON.stringify(root.draft) : "" }
    function state(): string {
      return JSON.stringify({ editing: root.editing, name: root.draftName, dirty: root.dirty, selected: root.selected,
        numbering: root.numbering, confirmingDiscard: root.confirmingDiscard, choosingNew: root.choosingNew, peeking: root.peeking,
        undo: root.undoStack.length, status: root.statusText, error: root.errorText,
        workspaces: root.workspaces.length, windows: root.windows.length, defaultLayout: root.defaultLayout,
        committed: root.committedLayout, live: root.liveLayout, dockLeft: root.dockLeft, showKeys: root.showKeys,
        area: root.area, contentMode: root.contentMode, scene: root.contentCatalog ? root.contentCatalog.current : null })
    }
  }
}
