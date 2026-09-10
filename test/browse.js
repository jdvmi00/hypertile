// Exercise the actual overlay routing, including the managed-content regression.
const fs = require("fs"), vm = require("vm"), assert = require("assert")
const qml = fs.readFileSync("plugin/Overlay.qml", "utf8")
const functions = ["browseTo", "browseArgs", "runBrowse", "revertBrowse"].map(name => {
  const start = qml.indexOf("  function " + name + "(")
  assert(start >= 0, name)
  const end = qml.indexOf("\n  }", start) + 4
  return qml.slice(start, end)
}).join("\n")
const detached = []
const context = {
  root: {ctl: "ctl", workspaceId: "1", opened: true, editing: false, contentMode: false, managedContent: true,
    contentCatalog: {}, catalogFailed: false, browseToken: "", committedLayout: "lua:quad",
    browseTarget: "lua:quad", browseLaunched: "lua:quad", liveLayout: "lua:quad"},
  browseProc: {running: false}, browseTimer: {stop() {}}, Editor: {newId: () => "owner"},
  Quickshell: {execDetached: args => detached.push(args)}
}
vm.createContext(context)
vm.runInContext(functions, context)
context.browseTo("lua:wide")
assert(context.browseProc.running, "managed content must still move the underlying windows")
assert.deepStrictEqual(Array.from(context.browseProc.command), ["ctl", "scene", "browse", "lua:wide", "--workspace", "1", "--browse-token", "owner", "--json"])
context.browseTo("lua:tall")
assert.strictEqual(context.browseProc.command[3], "lua:wide", "inflight switch stays serialized")
context.browseProc.running = false
context.runBrowse()
assert.strictEqual(context.browseProc.command[3], "lua:tall", "newest layout wins")
context.revertBrowse()
assert.deepStrictEqual(Array.from(detached[0]), ["ctl", "scene", "browse-end", "--workspace", "1", "--browse-token", "owner", "--json"])
assert.strictEqual(context.root.browseToken, "")
assert.strictEqual(context.root.liveLayout, "lua:quad")
context.browseProc.running = false
context.runBrowse()
assert.strictEqual(context.browseProc.running, false, "late completion cannot reopen a closed preview")
context.root.managedContent = false
context.browseTo("lua:wide")
assert.deepStrictEqual(Array.from(context.browseProc.command), ["ctl", "apply", "lua:wide", "--workspace", "1", "--no-persist", "--quiet"])

// The list can be ready before the scene catalog. Keep the latest choice
// until it is safe to decide whether the workspace needs a managed preview.
Object.assign(context.root, {contentCatalog: null, catalogFailed: false,
  browseTarget: "lua:quad", browseLaunched: "lua:quad", liveLayout: "lua:quad"})
context.browseProc.running = false
context.browseTo("lua:wide")
context.browseTo("lua:tall")
assert.strictEqual(context.root.browseTarget, "lua:tall", "catalog loading must not discard the latest selection")
assert.strictEqual(context.root.liveLayout, "lua:quad", "a queued preview is not live yet")
assert.strictEqual(context.browseProc.running, false, "wait for scene ownership before moving windows")
context.root.contentCatalog = {}
context.root.managedContent = true
context.runBrowse()
assert.strictEqual(context.browseProc.command[3], "lua:tall", "catalog readiness resumes the queued managed preview")

// The same queue resumes through the ordinary path if Scenes is unavailable.
Object.assign(context.root, {contentCatalog: null, managedContent: false,
  browseToken: "", browseTarget: "lua:quad", browseLaunched: "lua:quad", liveLayout: "lua:quad"})
context.browseProc.running = false
context.browseTo("lua:wide")
context.root.catalogFailed = true
context.runBrowse()
assert.deepStrictEqual(Array.from(context.browseProc.command), ["ctl", "apply", "lua:wide", "--workspace", "1", "--no-persist", "--quiet"])

// Closing or entering Scenes before readiness cancels the pending selection.
for (const contentMode of [false, true]) {
  Object.assign(context.root, {opened: true, contentMode: false, contentCatalog: null,
    catalogFailed: false, browseTarget: "lua:quad", browseLaunched: "lua:quad", liveLayout: "lua:quad"})
  context.browseProc.running = false
  context.browseTo("lua:wide")
  context.root.contentMode = contentMode
  context.revertBrowse()
  context.root.opened = contentMode
  context.root.contentCatalog = {}
  context.runBrowse()
  assert.strictEqual(context.browseProc.running, false, "late catalog completion must not start a canceled preview")
}
console.log("layout browse routing: all checks passed")
