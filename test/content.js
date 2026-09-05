const fs = require("fs"), vm = require("vm"), assert = require("assert")
const C = {}
vm.runInNewContext(fs.readFileSync("plugin/Content.js", "utf8"), C)
const catalog = { streams: [{ computer: "mac", desired: true, observed: "window-ready", assignment: { workspace: "1", zone: "right" } }],
  current: { phase: "ready", sources: [{ type: "empty", zone: "left" }] } }
assert.strictEqual(C.source(catalog, "1", "right", true).computer, "mac")
assert.strictEqual(C.source(catalog, "2", "right", true), null)
assert.strictEqual(C.source(catalog, "1", "right", false), null)
assert.strictEqual(C.label(C.source(catalog, "1", "left", true)), "Empty")
assert.strictEqual(C.status("window-ready"), "Window ready")
assert(C.audio("continuous").includes("continues"))
assert(C.audio("host").includes("muted"))
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
