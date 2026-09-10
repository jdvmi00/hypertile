// Drive the production overlay functions through asynchronous response sequences.
const fs = require("fs"), vm = require("vm"), assert = require("assert")
const qml = fs.readFileSync("plugin/Overlay.qml", "utf8")
const functions = [...qml.matchAll(/^  function (\w+)\(/gm)].map(match => {
  const end = qml.indexOf("\n  }", match.index) + 4
  // Single-line functions end on their own line.
  const lineEnd = qml.indexOf("\n", match.index)
  return qml.slice(match.index, qml.slice(match.index, lineEnd).endsWith("}") ? lineEnd : end)
}).join("\n")
const editor = {}
vm.runInNewContext(fs.readFileSync("plugin/Editor.js", "utf8"), editor)
const clone = value => JSON.parse(JSON.stringify(value))
function fixture() {
  const calls = [], later = []
  const timer = () => ({running: false, restart() {this.running = true}, stop() {this.running = false}})
  const root = {
    opened: true, dismissing: false, busy: false, editing: false, contentMode: false,
    workspaceId: "1", ctl: "ctl", missingCtlText: "CLI is missing",
    committedLayout: "lua:quad", liveLayout: "lua:quad", browseTarget: "lua:quad", browseLaunched: "lua:quad",
    browseToken: "", commitOnRefresh: false, managedContent: false, contentCatalog: null,
    catalogFailed: false, catalogFailures: 0, catalogError: "", errorText: "", statusText: "",
    layouts: [{name: "quad", spec: {name: "main"}}, {name: "wide", spec: {name: "main"}}],
    viewIndex: 0, pendingView: "", applyQueue: [], applyQueueLayout: "", switchConfirmed: false,
    current: {workspace: {id: 1, layout: "lua:quad"}}, shell: {hide() { calls.push(["hide"]) }}
  }
  Object.defineProperty(root, "viewed", {get() {return this.layouts[this.viewIndex] || null}})
  const context = {
    root, Editor: editor, Qt: {callLater(fn) {later.push(fn)}},
    Quickshell: {execDetached(args) {calls.push(clone(args))}},
    browseProc: {running: false}, currentProc: {running: false}, listProc: {running: false},
    catalogProc: {running: false}, ctlProc: {running: false}, previewProc: {running: false},
    workspacesProc: {}, windowsProc: {}, defaultProc: {},
    browseTimer: timer(), previewTimer: timer(), catalogTimeout: timer(),
    keys: {forceActiveFocus() {}},
    saveFile: {setText(text) {calls.push(["save", JSON.parse(text)])}},
    editFile: {setText(text) {calls.push(["preview", text])}}
  }
  vm.createContext(context)
  vm.runInContext(functions, context)
  for (const [key, value] of Object.entries(context)) if (typeof value === "function") root[key] = value
  return {root, context, calls}
}

// A copied layout cannot use its source's name; an edit of the original can.
{
  const {root, calls} = fixture()
  Object.assign(root, {editing: true, draftIsNew: true, draft: {name: "main", layout_id: "copy-id"}, draftName: "quad-copy"})
  root.saveAs("quad")
  assert.match(root.errorText, /already exists/)
  assert.equal(calls.length, 0)
  assert.equal(root.draftName, "quad-copy")
  root.draftIsNew = false
  root.saveAs("quad")
  assert.equal(calls[0][0], "save")
}

// A refresh while the catalog is pending keeps both the selection and request.
{
  const {root, context} = fixture()
  root.viewIndex = 1
  root.browseTo("lua:wide")
  root.acceptCurrent(JSON.stringify({workspace: {id: 1, layout: "lua:quad"}}))
  root.acceptLayouts(JSON.stringify({layouts: root.layouts}))
  assert.equal(root.viewed.name, "wide")
  assert.equal(root.browseTarget, "lua:wide")
  root.finishCatalog(JSON.stringify({scenes: [], apps: []}), "", 0, 0)
  root.runBrowse()
  assert.equal(context.browseProc.command[2], "lua:wide")
}

// Invalid success responses fail promptly, and retry can recover.
for (const text of ["", "{", "null", "[]", "{}", '{"apps":{},"scenes":[]}']) {
  const {root, context} = fixture()
  root.browseTo("lua:wide")
  root.finishCatalog(text, "", 0, 0)
  assert.equal(root.catalogFailed, true)
  assert.equal(root.catalogFailures, 1)
  assert.match(root.catalogError, /unreadable/)
  root.runBrowse()
  assert.equal(context.browseProc.running, true)
  root.retryCatalog()
  assert.equal(context.catalogProc.running, true)
  root.finishCatalog('{"apps":[],"scenes":[]}', "warning on success", 0, 0)
  assert.equal(root.catalogFailed, false)
  assert.equal(root.catalogError, "")
}
{
  const {root, context} = fixture()
  root.finishCatalog("", "connection refused", 1, 0)
  assert.equal(root.catalogFailed, true)
  assert.match(root.catalogError, /Details: connection refused/)
  assert.notEqual(root.catalogError, root.missingCtlText)
  root.pollCatalog()
  assert.equal(context.catalogProc.running, true, "automatic retry continues after first failure")
}

// Dismissal blocks late results even while the shell has not yet called close.
{
  const {root, context, calls} = fixture()
  root.browseTo("lua:wide")
  root.dismiss()
  assert.equal(root.opened, true)
  assert.equal(root.dismissing, true)
  root.finishCatalog('{"apps":[],"scenes":[]}', "", 0, 0)
  root.runBrowse()
  assert.equal(context.browseProc.running, false)
  assert.deepEqual(calls, [["hide"]])
}

// A scene phase update during a lease cannot promote a preview to "In use".
{
  const {root} = fixture()
  Object.assign(root, {managedContent: true, browseToken: "lease", liveLayout: "lua:wide",
    browseTarget: "lua:wide", browseLaunched: "lua:wide", contentCatalog: {current: {phase: "starting"}}})
  root.finishCatalog('{"apps":[],"scenes":[],"current":{"phase":"ready"}}', "", 0, 0)
  root.acceptCurrent('{"workspace":{"id":1,"layout":"lua:wide"}}')
  assert.equal(root.committedLayout, "lua:quad")
  root.liveLayout = root.committedLayout
  root.finishCatalog('{"apps":[],"scenes":[],"current":{"phase":"stopping"}}', "", 0, 0)
  assert.equal(root.sceneCommitOnRefresh, true, "ordinary scene transitions request a saved-layout refresh")
  // A new preview can begin after that request and before its reply.
  root.liveLayout = "lua:wide"
  root.acceptCurrent('{"workspace":{"id":1,"layout":"lua:wide"}}')
  assert.equal(root.committedLayout, "lua:quad", "late scene-refresh replies cannot promote a new preview")
}

// Success stderr is harmless; failures have context and successful actions clear them.
{
  const {root} = fixture()
  root.reportCtlResult("warning", 0, 0, "apply", true)
  assert.equal(root.errorText, "")
  root.reportCtlResult("", 1, 0, "current", false)
  assert.match(root.errorText, /Check that Hyprland is running/)
  root.reportCtlResult("", 0, 0, "current", false)
  assert.notEqual(root.errorText, "", "background reads do not hide action errors")
  root.reportCtlResult("", 0, 0, "apply", true)
  assert.equal(root.errorText, "")
  root.reportCtlResult("", 127, 0, "current", false)
  assert.equal(root.errorText, root.missingCtlText)
}

// Saving a new layout on assigned content asks before applying; confirmation
// keeps the saved name even if the catalog still shows the old selection.
{
  const {root, context} = fixture()
  Object.assign(root, {editing: true, managedContent: true, draftName: "saved-copy", draftIsNew: true,
    contentCatalog: {active_workspaces: ["1"]}})
  root.finishSave(0, 0)
  assert.equal(context.ctlProc.running, false)
  assert.equal(root.pendingSwitch.layoutName, "saved-copy")
  assert.equal(root.viewed.name, "quad")
  root.confirmSwitch()
  assert.deepEqual(clone(context.ctlProc.command), ["ctl", "scene", "layout", "saved-copy", "--workspace", "1", "--json"])
}
for (const draftIsNew of [false, true]) {
  const {root, context, calls} = fixture()
  Object.assign(root, {editing: true, managedContent: true, dirty: true, draftIsNew, draft: {name: "main"}})
  root.doPreview()
  assert.equal(root.statusText, "", "managed edits do not repeat the header as a toast")
  root.discard()
  assert.equal(root.editing, false)
  assert.equal(context.previewProc.running, false)
  assert.equal(context.ctlProc.running, false)
  assert.equal(calls.length, 0)
}

// Sliders push undo before the first change: drag, wheel, or release-only click.
{
  const rail = fs.readFileSync("plugin/Rail.qml", "utf8")
  const start = rail.indexOf("    function changeValue(")
  const code = rail.slice(start, rail.indexOf("\n    }", start) + 6)
  const events = [], slider = {undoStarted: false, dragStarted() {events.push("undo")}, changed(value) {events.push(value)}}
  vm.createContext(slider); vm.runInContext(code, slider)
  slider.changeValue(0.5, true)
  slider.changeValue(0.6, false); slider.changeValue(0.7, false); slider.changeValue(0.7, true)
  slider.changeValue(0.8, false); slider.changeValue(0.8, true)
  assert.deepEqual(events, ["undo", 0.5, "undo", 0.6, 0.7, 0.7, "undo", 0.8, 0.8])
}

// Headers distinguish a saved layout from its preview, and tolerate missing workspace data.
{
  const rail = fs.readFileSync("plugin/Rail.qml", "utf8")
  const start = rail.indexOf("readonly property string metaText: {") + "readonly property string metaText: {".length
  const body = rail.slice(start, rail.indexOf("\n  }", start))
  const {root} = fixture()
  const header = () => vm.runInNewContext("(function() {" + body + "})()", {overlay: root})
  Object.assign(root, {editing: true, managedContent: true, draftIsNew: false})
  assert.match(header(), /Preview off: assigned content stays put/)
  Object.assign(root, {editing: false, liveLayout: "lua:wide"})
  assert.match(header(), /Previewing on workspace 1.*Esc puts quad back/)
  Object.assign(root, {current: {}, workspaceId: "", viewedIsActive: true})
  assert.doesNotThrow(header)
}
console.log("overlay safeguards and feedback: all checks passed")
