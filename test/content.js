const fs = require("fs"), vm = require("vm"), assert = require("assert")
const C = {}
vm.runInNewContext(fs.readFileSync("plugin/Content.js", "utf8"), C)
const catalog = { streams: [{ computer: "mac", desired: true, observed: "window-ready", assignment: { workspace: "1", zone: "right" } }],
  current: { phase: "ready", sources: [{ type: "empty", zone: "left" }] } }
assert.strictEqual(C.source(catalog, "1", "right", true).computer, "mac")
assert.strictEqual(C.source(catalog, "2", "right", true), null)
assert.strictEqual(C.source(catalog, "1", "right", false), null)
assert.strictEqual(C.label(C.source(catalog, "1", "left", true)), "Empty")
assert.strictEqual(C.status("window-ready"), "Connected")
assert.strictEqual(C.status("none"), "")
assert.strictEqual(C.status(undefined), "")
assert(C.troubled("needs-attention") && !C.troubled("window-ready"))
assert(C.audio("continuous").includes("continues"))
assert(C.audio("host").includes("muted"))
// Labels, chips and states for every kind of content.
const mac = C.source(catalog, "1", "right", true)
assert.strictEqual(C.label(mac), "mac")
assert.strictEqual(C.chip(mac), "mac")
assert.strictEqual(C.state(mac).text, "Connected")
assert.strictEqual(C.state(mac).urgent, false)
const connecting = { type: "stream", computer: "mac", profile: "desktop", status: "connecting" }
assert.strictEqual(C.label(connecting), "mac · desktop")
assert.strictEqual(C.chip(connecting), "mac · Connecting…")
const broken = { type: "stream", computer: "mac", profile: "desktop", status: "needs-attention", error: "boom" }
assert.strictEqual(C.state(broken).text, "Needs attention")
assert.strictEqual(C.state(broken).urgent, true)
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
// Profile traits: only what differs from the defaults.
assert.strictEqual(C.traits({ name: "desktop", audio: "focus", input: "absolute", system_keys: "never", keep_awake: "visible" }), "")
assert.strictEqual(C.traits({ name: "m", audio: "host", input: "relative", system_keys: "always", keep_awake: "always" }), "host audio · captured pointer · system keys")
assert.strictEqual(C.traits({ audio: "continuous" }), "audio continues")
// The scene header.
assert.strictEqual(C.sceneTitle(null), "No scene")
assert.strictEqual(C.sceneTitle({ phase: "none", document: null }), "No scene")
assert.strictEqual(C.sceneTitle({ phase: "restored", document: { name: "work" } }), "No scene")
assert.strictEqual(C.sceneTitle({ phase: "ready", document: {} }), "Unsaved scene")
assert.strictEqual(C.sceneTitle({ phase: "ready", document: { name: "work" } }), "work")
assert.strictEqual(C.sceneModified({ phase: "ready", modified: true, document: { name: "work" } }), true)
assert.strictEqual(C.sceneModified({ phase: "ready", modified: true, document: {} }), false)
assert.strictEqual(C.sceneModified({ phase: "restored", modified: true, document: { name: "work" } }), false)
assert.strictEqual(C.sceneMeta({ phase: "ready" }, "quad", "1"), "quad on workspace 1  ·  Ready")
assert.strictEqual(C.sceneMeta({ phase: "none" }, "quad", "1"), "quad on workspace 1")
assert.strictEqual(C.sceneMeta(null, "", ""), "")
const report = {current: {window_ready_ms: 1234, reason: "reconnect"}, last_measurement: {profile: "desktop",
  metrics: {decode_ms: 0, network_rtt_ms: 3, rendered_fps: 60, network_drop_pct: 0, jitter_drop_pct: 0}},
  readability: "unverified", advice: []}
assert(C.performance(report).includes("1.23 s"))
assert(C.performance(report).includes("Decode 0.00 ms"))
assert(C.performance(report).includes("Network loss 0.00%"))
assert(!C.performance(report).includes("encode"))
assert(C.performance({}).includes("No completed"))
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
