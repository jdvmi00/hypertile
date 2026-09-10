const fs = require("fs"), vm = require("vm"), assert = require("assert")
const C = {}
vm.runInNewContext(fs.readFileSync("plugin/Content.js", "utf8"), C)
const catalog = {current: {phase: "ready", sources: [{type: "empty", zone: "left"}]}}
assert.strictEqual(C.source(catalog, "1", "left", false), null)
assert.strictEqual(C.label(C.source(catalog, "1", "left", true)), "Empty")
assert.strictEqual(C.label(null), "Local windows")
assert.strictEqual(C.chip(null), "")
assert.strictEqual(C.state(null).text, "")
assert(C.detail(null).includes("fill order"))
assert.strictEqual(C.chip({ type: "empty", zone: "left" }), "Empty")
const app = { type: "local", zone: "left", app_class: "org.example.Editor", status: "needs-attention", error: "Open this app on the workspace" }
assert.strictEqual(C.label(app), "org.example.Editor")
assert.strictEqual(C.state(app).text, "Pending")
assert.strictEqual(C.detail(app), "Open this app on the workspace")
assert.strictEqual(C.detail({ type: "local", zone: "left", app_class: "x", status: "ready" }), "One matching window is pinned here")
// The scene header.
assert.strictEqual(C.sceneTitle(null), "No scene")
assert.strictEqual(C.sceneTitle({ phase: "none", document: null }), "No scene")
assert.strictEqual(C.sceneTitle({ phase: "restored", document: { name: "work" } }), "No scene")
assert.strictEqual(C.sceneTitle({ phase: "ready", document: {} }), "Unsaved scene")
assert.strictEqual(C.sceneTitle({ phase: "ready", document: { name: "work" } }), "work")
assert.strictEqual(C.sceneModified({ phase: "ready", modified: true, document: { name: "work" } }), true)
assert.strictEqual(C.sceneModified({ phase: "ready", modified: true, document: {} }), false)
assert.strictEqual(C.sceneModified({ phase: "restored", modified: true, document: { name: "work" } }), false)
assert.strictEqual(C.sceneTitle({ phase: "none", document: null }, "1"), "Workspace 1")
assert.strictEqual(C.sceneTitle({ phase: "restored", document: { name: "work" } }, "2"), "Workspace 2")
assert.strictEqual(C.sceneMeta({ phase: "ready" }, "quad", "1"), "quad  ·  workspace 1  ·  Ready")
assert.strictEqual(C.sceneMeta({ phase: "none" }, "quad", "1"), "quad  ·  local windows in every zone")
assert.strictEqual(C.sceneMeta({ phase: "restored" }, "quad", "1"), "quad  ·  Previous arrangement restored")
assert.strictEqual(C.sceneMeta(null, "", ""), "")
assert.strictEqual(C.managed(null), false)
assert.strictEqual(C.managed({phase: "none"}), false)
assert.strictEqual(C.managed({phase: "restored"}), false)
assert.strictEqual(C.managed({phase: "waiting-session"}), false)
assert.strictEqual(C.managed({phase: "needs-attention"}), true)
assert.strictEqual(C.managed({phase: "ready"}), true)
assert.match(C.sceneMeta({phase: "needs-attention", deleted: true}, "quad", "1"), /Deleted scene/)
assert.match(C.retrySummary({sources: []}), /opens no apps/)
assert.match(C.retrySummary({sources: [{type: "app", app_name: "MacBook"}, {type: "local", app_class: "foot"}]}), /opens or reuses MacBook\./)
const placing = { phase: "connecting", sources: [
  { type: "app", zone: "a", status: "ready" }, { type: "app", zone: "b", status: "waiting-window" },
  { type: "local", zone: "c", app_class: "x", status: "needs-attention" }, { type: "local", zone: "d" }, { type: "empty", zone: "e" }] }
assert.strictEqual(C.sceneProgress(placing), "1 of 3 placed  ·  1 needs attention")
assert.strictEqual(C.sceneMeta(placing, "quad", "1"), "quad  ·  workspace 1  ·  1 of 3 placed  ·  1 needs attention")
assert.strictEqual(C.sceneProgress({ phase: "layout", sources: placing.sources }), "Applying layout…")
assert.strictEqual(C.sceneProgress({ phase: "ready", sources: [] }), "Ready")
// Scene cards and the picker.
assert.strictEqual(JSON.stringify(C.appNames([{ type: "app", app_name: "MacBook (Remote Desktop)" }, { type: "local", app_class: "foot" }, { type: "empty" }, { type: "local" }])), '["MacBook","foot"]')
assert.strictEqual(C.summary(["A", "B", "C", "D"]), "A, B +2")
assert.strictEqual(C.summary(["A", "B"]), "A, B")
assert.strictEqual(C.summary([]), "")
assert.strictEqual(C.isRemoteDesktop({ desktop_id: "remote-desktops-macbook.desktop" }), true)
assert.strictEqual(C.isRemoteDesktop({ desktop_id: "foot.desktop", app_title: "x - Moonlight" }), true)
assert.strictEqual(C.isRemoteDesktop({ desktop_id: "foot.desktop" }), false)
assert.strictEqual(C.displayName("Work laptop (Remote Desktop)"), "Work laptop")
assert.strictEqual(C.label({ type: "app", desktop_id: "remote-desktops-macbook.desktop", app_name: "MacBook (Remote Desktop)" }), "MacBook")
assert.strictEqual(C.matches("", ["anything"]), true)
assert.strictEqual(C.matches("  CHR ", ["Google Chrome", "google-chrome"]), true)
assert.strictEqual(C.matches("zzz", ["Google Chrome", null]), false)
const windows = [{ class: "foot", title: "~", workspace: 1 }, { class: "foot", title: "vim", workspace: "1" }, { class: "cursor", title: "a.py - Cursor", workspace: 1 }, { class: "x", title: "", workspace: 2 }, { title: "no class", workspace: 1 }]
assert.strictEqual(JSON.stringify(C.openApps(windows, "1")), JSON.stringify([{ app_class: "cursor", count: 1, title: "a.py - Cursor" }, { app_class: "foot", count: 2, title: "vim" }]))
assert.strictEqual(JSON.stringify(C.openApps(windows, "3")), "[]")
catalog.current.phase = "restored"
assert.strictEqual(C.source(catalog, "1", "left", true), null)
const E = {}
vm.runInNewContext(fs.readFileSync("plugin/Editor.js", "utf8"), E)
const original = E.identify({ columns: [{ name: "a" }, { name: "b" }], fill: ["a", "b"] })
const a = E.findLeaf(original, "a").node.id
const renamed = E.renameZone(original, "a", "renamed")
assert.strictEqual(E.findLeaf(renamed, "renamed").node.id, a)
assert.strictEqual(E.findLeaf(E.setFill(original, ["b", "a"]), "a").node.id, a)
const split = E.splitZone(original, "a", "rows")
assert.strictEqual(E.findLeaf(split, "a").node.id, a)
assert.notStrictEqual(E.findLeaf(split, "a-2").node.id, a)
assert(!E.findLeaf(E.deleteZone(original, "a"), "a"))
const fresh = E.identify(original, true)
assert.notStrictEqual(fresh.layout_id, original.layout_id)
assert.notStrictEqual(E.findLeaf(fresh, "a").node.id, a)
console.log("content and scene identities: all checks passed")
assert.equal(C.label({ type: "app", desktop_id: "remote-desktops-macbook.desktop", app_name: "MacBook" }), "MacBook")
assert.equal(C.state({ type: "app", status: "moved" }).text, "Moved")
assert.match(C.detail({ type: "app", status: "moved" }), /Moved by you/)
assert.match(C.detail({ type: "app", status: "closed" }), /Closed by you/)
// Zone positions in words.
const area = { x: 10, y: 40, w: 6124, h: 2510 }
const quad = [{ name: "main", x: 10, y: 40, w: 3062, h: 1255 }, { name: "main-2", x: 3072, y: 40, w: 3062, h: 1255 },
  { name: "main-3", x: 10, y: 1295, w: 3062, h: 1255 }, { name: "main-4", x: 3072, y: 1295, w: 3062, h: 1255 }]
assert.strictEqual(JSON.stringify(C.positionLabels(quad, area)), JSON.stringify({ main: "Top left", "main-2": "Top right", "main-3": "Bottom left", "main-4": "Bottom right" }))
const cols = [{ name: "a", x: 10, y: 40, w: 2041, h: 2510 }, { name: "b", x: 2051, y: 40, w: 2041, h: 2510 }, { name: "c", x: 4092, y: 40, w: 2042, h: 2510 }]
assert.strictEqual(JSON.stringify(C.positionLabels(cols, area)), JSON.stringify({ a: "Left", b: "Center", c: "Right" }))
assert.strictEqual(C.positionLabel({ x: 10, y: 40, w: 6124, h: 2510 }, area), "Full screen")
assert.strictEqual(C.positionLabel({ x: 2000, y: 900, w: 2000, h: 800 }, area), "Middle center")
// Four columns: the two inner ones would both be "Center", so they fall back to their names.
const four = [{ name: "a", x: 10, y: 40, w: 1531, h: 2510 }, { name: "b", x: 1541, y: 40, w: 1531, h: 2510 }, { name: "c", x: 3072, y: 40, w: 1531, h: 2510 }, { name: "d", x: 4603, y: 40, w: 1531, h: 2510 }]
assert.strictEqual(JSON.stringify(C.positionLabels(four, area)), JSON.stringify({ a: "Left", b: "", c: "", d: "Right" }))
assert.strictEqual(JSON.stringify(C.positionLabels(quad, null)), "{}")
