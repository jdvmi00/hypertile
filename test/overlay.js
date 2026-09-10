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
    root, Editor: editor, Content: (() => {const c = {}; vm.runInNewContext(fs.readFileSync("plugin/Content.js", "utf8"), c); return c})(), Qt: {callLater(fn) {later.push(fn)}},
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

// Dismiss follows the scene CLI path and reports that the layout was kept.
{
  const {root, context} = fixture()
  let sent
  context.runCtl = (...args) => {sent = args; return true}
  context.workspaceId = "1"
  root.sceneAction("dismiss")
  assert.deepEqual(clone(sent[0]), ["scene", "dismiss", "--workspace", "1", "--json"])
  assert.equal(sent[2], "Scene dismissed; layout kept")
  assert.equal(context.commitOnRefresh, true)
}

{
  const {root, context} = fixture()
  let sent
  context.runCtl = (...args) => {sent = args; return true}
  root.resumeSession()
  assert.deepEqual(clone(sent[0]), ["session", "resume"])
  assert.equal(sent[2], "Session saving resumed")
}

// Acknowledgement is not completion, and stale catalog operations cannot finish a new request.
{
  const {root} = fixture()
  root.sceneFeedback = {done: "Using work", zone: "", operation: ""}
  root.acceptSceneAction(JSON.stringify({operation: "new", phase: "connecting"}))
  assert.equal(root.statusText, "Placing apps…")
  root.finishSceneFeedback({operation: "old", phase: "ready"})
  assert.equal(root.statusText, "Placing apps…")
  root.finishSceneFeedback({operation: "new", phase: "ready"})
  assert.equal(root.statusText, "Using work")
  assert.equal(root.sceneFeedback, null)
  root.sceneFeedback = {done: "Using work", operation: ""}
  root.acceptSceneAction("broken")
  assert.equal(root.statusText, "Scene update requested")
  assert.equal(root.sceneFeedback, null)
}

// Scene navigation wins only with no zone and no higher-priority confirmation.
{
  const {root, context} = fixture()
  let next = 1
  for (const m of qml.matchAll(/Qt\.(Key_\w+|\w+Modifier)/g)) if (!(m[1] in context.Qt)) context.Qt[m[1]] = next++
  const routed = []
  context.rail = {searchText: '', handleSceneKey: e => {routed.push('scene'); return true}, typeSearch: text => routed.push(text)}
  Object.assign(root, {contentMode: true, selected: '', viewedIsActive: true})
  const event = key => ({key: context.Qt[key], modifiers: 0, text: '', isAutoRepeat: false})
  root.handleKey(event('Key_Down')); assert.deepEqual(routed, ['scene'])
  root.pendingSwitch = {layoutName: 'wide'}
  root.handleKey(event('Key_Down')); assert.equal(routed.length, 1)
  root.pendingSwitch = null; root.selected = 'left'
  context.selectContentNeighbor = dir => routed.push(dir)
  root.handleKey(event('Key_Down')); assert.equal(routed.pop(), 'down')
  context.rail.searchText = 'App'
  root.handleKey({...event('Key_1'), text: '1'}); assert.equal(routed.pop(), '1')
}

// Modified scene replacement asks before any command, including same-name reuse.
for (const target of ['home', 'work']) {
  const {root, context} = fixture()
  const sent = []
  context.runCtl = (...args) => {sent.push(clone(args)); return true}
  context.workspaceId = '1'
  root.contentCatalog = {current: {phase: 'ready', modified: true, document: {name: 'work'}}}
  root.sceneAction('apply', target)
  assert.equal(sent.length, 0)
  assert.equal(root.pendingSwitch.sceneName, target)
  assert.match(root.switchSummary(), /changes to work are not saved/)
  assert.equal(root.selected, '')
  root.viewIndex = 1 // unrelated browsing must not alter the captured scene name
  root.confirmSwitch()
  assert.equal(root.pendingSwitch, null)
  assert.deepEqual(sent[0][0], ['scene','apply',target,'--workspace','1','--json'])
  assert.equal(root.sceneFeedback.done, 'Using ' + target)
  root.confirmSwitch()
  assert.equal(sent.length, 1, 'a confirmation cannot execute twice')
}
{
  const {root, context} = fixture()
  context.workspaceId = '1'
  const sent = []
  context.runCtl = (...args) => {sent.push(clone(args)); return true}
  root.contentCatalog = {current: {phase: 'ready', modified: true, document: {name: 'work'}}}
  root.sceneAction('apply', 'home')
  let next = 1
  for (const m of qml.matchAll(/Qt\.(Key_\w+|\w+Modifier)/g)) if (!(m[1] in context.Qt)) context.Qt[m[1]] = next++
  root.handleKey({key: context.Qt.Key_Escape, modifiers: 0, text: ''})
  assert.equal(root.pendingSwitch, null)
  assert.equal(sent.length, 0, 'Escape keeps the modified scene')
  root.contentCatalog.current.modified = false
  root.sceneAction('apply', 'home')
  assert.equal(sent.length, 1, 'unmodified scenes need no confirmation')
  root.contentCatalog.current.modified = true
  root.sceneAction('apply', 'home', '2')
  assert.equal(sent.length, 2, 'current-workspace modifications do not block a different workspace')
  root.busy = true
  root.sceneAction('apply', 'home')
  assert.equal(root.pendingSwitch, null, 'busy requests cannot create stale confirmation prompts')
}

// Left-clicking the canvas selects a zone, then deselects outside, then closes.
{
  const {root, context, calls} = fixture()
  context.Qt.LeftButton = 1; context.Qt.RightButton = 2
  root.pressContentCanvas('left', 1); assert.equal(root.selected, 'left')
  root.pressContentCanvas('', 2); assert.equal(root.selected, 'left')
  root.pressContentCanvas('', 1); assert.equal(root.selected, ''); assert.equal(calls.length, 0)
  root.pendingSwitch = {sceneName: 'home', workspace: '1'}
  root.pressContentCanvas('', 1); assert.deepEqual(calls, [['hide']])
  assert.equal(root.pendingSwitch, null, 'closing cancels a pending replacement')
}
