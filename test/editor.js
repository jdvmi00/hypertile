// Editor.js tests (node). Run from the repo root: node test/editor.js
// Every produced spec is also pushed through `hypertile-ctl validate`, so
// the JS edits can never build something the Lua engine rejects.

const fs = require("fs")
const path = require("path")
const vm = require("vm")
const { spawnSync } = require("child_process")

const root = path.join(__dirname, "..")
function load(file, exports) {
  const src = fs.readFileSync(path.join(root, "plugin", file), "utf8")
  const ctx = {}
  vm.runInNewContext(src + "\n" + exports.map(e => `this.${e} = ${e};`).join(""), ctx)
  return ctx
}
const E = load("Editor.js", ["splitZone", "deleteZone", "resizeSiblings", "setFill", "layoutTree", "dividers", "dividerAt", "leafAt", "leafNames", "uniqueName", "nodeAt", "kindOf",
  "fillableNames", "setZoneProp", "setLayoutProp", "setGap", "setCapacity", "addRule", "removeRule", "rulesFor", "exactPattern",
  "renameZone", "neighbor", "edgeDivider", "nudge", "setZoneExtent", "extentTarget", "validName"])
const G = load("Geometry.js", ["zones"])

let checks = 0, failures = 0
function check(cond, msg) { checks++; if (!cond) { failures++; console.log("FAIL: " + msg) } }

function validate(name, spec) {
  const r = spawnSync("lua", ["bin/hypertile-ctl", "validate", "-"], {
    cwd: root, input: JSON.stringify({ name, spec }), env: { ...process.env, HYPERTILE_SRC: root, HYPERTILE_LAYOUTS_DIR: "/nonexistent" }, encoding: "utf8",
  })
  return { ok: r.status === 0, err: (r.stderr || "").trim() }
}
function assertValid(label, spec) {
  const v = validate("t", spec)
  check(v.ok, label + " validates with the Lua engine: " + v.err)
}

const area = { x: 0, y: 0, w: 1000, h: 500 }
const ultrawide = { columns: [{ name: "left", w: 0.2 }, { name: "center", w: 0.6 }, { name: "right", w: 0.2 }], fill: ["center", "right", "left"], cycle: ["right", "left", "center"], empty: "keep", single: "slot" }
const quad = {
  columns: [
    { name: "left", w: 0.2 },
    { w: 0.6, rows: [{ columns: [{ name: "tl" }, { name: "tr" }] }, { columns: [{ name: "bl" }, { name: "br" }] }] },
    { name: "right", w: 0.2 },
  ],
  fill: ["tl", "tr", "bl", "br", "right", "right", "left", "left"], empty: "keep", single: "slot",
}

// ---- split: leaf becomes a container when the parent splits the other way
{
  const s = E.splitZone(ultrawide, "center", "rows")
  check(E.leafNames(s).join() === "left,center,center-2,right", "split center into rows: " + E.leafNames(s).join())
  const c = s.columns[1]
  check(E.kindOf(c) === "rows" && c.w === 0.6 && c.rows.length === 2, "center became a rows container keeping w=0.6")
  check(s.fill.join() === "center,center-2,right,left", "new zone numbered right after center: " + s.fill.join())
  check(ultrawide.columns[1].name === "center", "input spec untouched")
  const z = G.zones(s, area)
  const byName = {}; z.forEach(x => byName[x.name] = x)
  check(byName.center.h === 250 && byName["center-2"].y === 250, "halves are equal in height")
  assertValid("split into rows", s)
}

// ---- split: sibling insert when the parent already splits that way
{
  const s = E.splitZone(quad, "tl", "columns")
  const row = s.columns[1].rows[0]
  check(row.columns.length === 3 && row.columns[1].name === "tl-2", "tl split into columns inserts a sibling: " + row.columns.map(n => n.name).join())
  check(row.columns[0].w === 0.5 && row.columns[1].w === 0.5 && row.columns[2].w === undefined, "tl and tl-2 share tl's weight, tr unchanged")
  check(s.fill.join() === "tl,tl-2,tr,bl,br,right,right,left,left", "fill: " + s.fill.join())
  assertValid("sibling split", s)
  const s2 = E.splitZone(s, "tl", "columns")
  check(E.leafNames(s2).indexOf("tl-3") !== -1, "names stay unique: " + E.leafNames(s2).join())
}

// ---- split the root when the spec is a single leaf
{
  const s = E.splitZone({ name: "only" }, "only", "columns")
  check(s.columns && s.columns.length === 2 && s.name === undefined, "single-leaf root becomes a columns container")
  check(s.fill.join() === "only,only-2", "root split fill")
  assertValid("root split", s)
}

// ---- delete with collapse
{
  const s = E.splitZone(ultrawide, "center", "rows")
  const back = E.deleteZone(s, "center-2")
  check(E.leafNames(back).join() === "left,center,right", "deleting the new half restores the leaf: " + E.leafNames(back).join())
  check(back.columns[1].name === "center" && back.columns[1].w === 0.6, "collapsed leaf keeps the container's weight")
  check(back.fill.join() === "center,right,left", "fill cleaned: " + back.fill.join())
  check(back.cycle.join() === "right,left,center", "cycle kept when still valid")
  assertValid("delete with collapse", back)

  const q1 = E.deleteZone(quad, "tr")
  const row0 = q1.columns[1].rows[0]
  check(E.kindOf(row0) === null && row0.name === "tl", "deleting tr collapses row 0 into tl")
  check(q1.fill.join() === "tl,bl,br,right,right,left,left", "fill without tr: " + q1.fill.join())
  const q2 = E.deleteZone(q1, "tl")
  const center = q2.columns[1]
  check(E.kindOf(center) === "columns" && center.w === 0.6 && center.columns.map(n => n.name).join() === "bl,br", "deleting tl collapses the rows container into the bottom row: " + JSON.stringify(center))
  assertValid("nested collapse", q2)

  const one = E.deleteZone({ name: "only" }, "only")
  check(one.name === "only", "the last zone cannot be deleted")

  const withRules = Object.assign({}, quad, { rules: [{ class: "x", slot: "tr" }, { class: "y", slot: "tl" }], capacity: { tr: 1, tl: 2 } })
  const cleaned = E.deleteZone(withRules, "tr")
  check(cleaned.rules.length === 1 && cleaned.rules[0].slot === "tl" && cleaned.capacity.tr === undefined && cleaned.capacity.tl === 2, "rules and capacity for the deleted zone are dropped")
  assertValid("delete with rules", cleaned)
}

// ---- resize
{
  const s = E.resizeSiblings(ultrawide, [], 0, 0.5)
  check(s.columns[0].w === 0.4 && s.columns[1].w === 0.4 && s.columns[2].w === 0.2, "left/center split 50/50 of their 0.8: " + JSON.stringify(s.columns))
  const clamped = E.resizeSiblings(ultrawide, [], 1, 0.001)
  check(Math.abs(clamped.columns[1].w - 0.04) < 1e-6, "ratio clamps at 5%: " + clamped.columns[1].w)
  const deep = E.resizeSiblings(quad, [1], 0, 0.25)
  check(deep.columns[1].rows[0].h === 0.5 && deep.columns[1].rows[1].h === 1.5, "rows get h weights: " + JSON.stringify(deep.columns[1].rows.map(r => r.h)))
  assertValid("resize", deep)
}

// ---- fill
{
  const s = E.setFill(ultrawide, ["left", "center", "center", "bogus"])
  check(s.fill.join() === "left,center,center" && s.cycle === undefined, "setFill keeps only real zones and drops cycle: " + s.fill.join())
  const empty = E.setFill(ultrawide, [])
  check(empty.fill.join() === "left,center,right", "empty fill falls back to tree order")
  assertValid("setFill", s)
}

// ---- geometry: dividers and hit testing
{
  const divs = E.dividers(quad, area)
  check(divs.length === 5, "quad has 5 dividers (2 root, 1 center rows, 1 per row): " + divs.length)
  const rootDiv = divs.find(d => d.path.length === 0 && d.index === 0)
  check(rootDiv.kind === "columns" && rootDiv.pos === 200 && rootDiv.start === 0 && rootDiv.span === 800, "root divider between left and center: " + JSON.stringify(rootDiv))
  const hit = E.dividerAt(divs, 203, 100, 8)
  check(hit && hit.path.length === 0 && hit.index === 0, "dividerAt finds the root divider near x=200")
  check(E.dividerAt(divs, 203, 600, 8) === null, "dividerAt ignores points outside the divider's extent")
  check(E.dividerAt(divs, 250, 100, 8) === null, "dividerAt ignores far points")
  const rowDiv = divs.find(d => d.path.length === 1 && d.kind === "rows")
  check(rowDiv && rowDiv.pos === 250 && rowDiv.x === 200 && rowDiv.w === 600, "center rows divider: " + JSON.stringify(rowDiv))
  // Drag math: pointer at x=400 on the root divider -> ratio 0.5 -> left/center 0.4/0.4.
  const ratio = (400 - rootDiv.start) / rootDiv.span
  const dragged = E.resizeSiblings(quad, rootDiv.path, rootDiv.index, ratio)
  check(dragged.columns[0].w === 0.4 && dragged.columns[1].w === 0.4, "dragging the root divider to x=400 gives 0.4/0.4")
  check(E.leafAt(quad, area, 250, 100) === "tl" && E.leafAt(quad, area, 900, 400) === "right" && E.leafAt(quad, area, -5, 5) === "", "leafAt finds zones by point")
}

// ---- uniqueName strips a numeric suffix before counting
{
  check(E.uniqueName(quad, "tl") === "tl-2", "uniqueName tl -> tl-2")
  check(E.uniqueName({ columns: [{ name: "a" }, { name: "a-2" }] }, "a-2") === "a-3", "uniqueName a-2 -> a-3")
}

// ---- spacers
{
  const s = E.setZoneProp(ultrawide, "left", "spacer", true)
  check(s.columns[0].spacer === true, "left marked as spacer")
  check(s.fill.join() === "center,right" && s.cycle.join() === "right,center", "spacer removed from fill and cycle: " + s.fill.join() + " / " + s.cycle.join())
  check(E.fillableNames(s).join() === "center,right", "fillableNames skips spacers")
  assertValid("spacer", s)
  const back = E.setZoneProp(s, "left", "spacer", false)
  check(back.columns[0].spacer === undefined && back.fill.join() === "center,right,left", "un-spacing appends to fill: " + back.fill.join())
  const only = E.setZoneProp({ columns: [{ name: "a", spacer: true }, { name: "b" }] }, "b", "spacer", true)
  check(only.columns[1].spacer === undefined, "the last real zone cannot become a spacer")
  const split = E.splitZone(s, "left", "rows")
  check(split.columns[0].rows[0].spacer === true && split.columns[0].rows[1].spacer === undefined, "splitting a spacer keeps it a spacer, the new half is a real zone")
  check(split.fill.indexOf("left-2") !== -1 && split.fill.indexOf("left") === -1, "new half is fillable, the spacer half is not: " + split.fill.join())
  assertValid("split spacer", split)
  const renum = E.setFill(s, ["left", "right", "center"])
  check(renum.fill.join() === "right,center", "setFill ignores spacers")
  const del = E.deleteZone(s, "center")
  check(E.fillableNames(del).join() === "right" && del.fill.join() === "right", "deleting leaves a spacer plus one real zone")
  assertValid("delete beside spacer", del)
}

// ---- aspect, scale, stack, capacity, layout props, gaps
{
  let s = E.setZoneProp(quad, "tl", "aspect", 1)
  s = E.setZoneProp(s, "tl", "scale", 0.5)
  s = E.setZoneProp(s, "tl", "stack", "h")
  const tl = s.columns[1].rows[0].columns[0]
  check(tl.aspect === 1 && tl.scale === 0.5 && tl.stack === "h", "zone props set: " + JSON.stringify(tl))
  assertValid("zone props", s)
  s = E.setZoneProp(s, "tl", "aspect", null)
  check(s.columns[1].rows[0].columns[0].aspect === undefined, "zone prop cleared")
  const sp = E.splitZone(s, "tl", "rows")
  check(sp.columns[1].rows[0].columns[0].rows[0].scale === 0.5 && sp.columns[1].rows[0].columns[0].rows[0].stack === "h", "split keeps the original's options on its half")

  s = E.setCapacity(quad, "right", 2)
  check(s.capacity.right === 2, "capacity set")
  s = E.setCapacity(s, "right", 0)
  check(s.capacity === undefined, "capacity cleared drops the table")
  s = E.setLayoutProp(quad, "empty", "collapse")
  s = E.setLayoutProp(s, "border", 0)
  check(s.empty === "collapse" && s.border === 0, "layout props set")
  s = E.setLayoutProp(s, "border", null)
  check(s.border === undefined, "layout prop cleared")
  s = E.setGap(quad, "inner", 0)
  s = E.setGap(s, "outer", 24.6)
  check(s.gaps.inner === 0 && s.gaps.outer === 25, "gaps set and rounded: " + JSON.stringify(s.gaps))
  assertValid("gaps", s)
  s = E.setGap(s, "inner", null); s = E.setGap(s, "outer", null)
  check(s.gaps === undefined, "clearing both gaps drops the table")
}

// ---- rules
{
  let s = E.addRule(quad, { class: E.exactPattern("com.mitchellh.ghostty"), slot: "right" })
  check(s.rules.length === 1 && s.rules[0].class === "^com%.mitchellh%.ghostty$", "rule added with an escaped exact pattern: " + JSON.stringify(s.rules))
  s = E.addRule(s, { class: E.exactPattern("com.mitchellh.ghostty"), slot: "right" })
  check(s.rules.length === 1, "duplicate rule ignored")
  s = E.addRule(s, { title: "Docs", slot: "tl" })
  check(E.rulesFor(s, "right").length === 1 && E.rulesFor(s, "tl")[0].index === 1, "rulesFor lists rules per zone with indices")
  assertValid("rules", s)
  check(E.addRule(s, { class: "x", slot: "nope" }).rules.length === 2, "rule for unknown zone ignored")
  const spacer = E.setZoneProp(s, "tl", "spacer", true)
  check(E.rulesFor(spacer, "tl").length === 0, "spacer drops its rules")
  s = E.removeRule(s, 0)
  check(s.rules.length === 1 && s.rules[0].slot === "tl", "removeRule by index")
  s = E.removeRule(s, 0)
  check(s.rules === undefined, "removing the last rule drops the list")
  check(E.exactPattern("a-b(c)") === "^a%-b%(c%)$", "exactPattern escapes Lua magic characters")
}

// ---- root collapse then split keeps the layout keys on the root
{
  let s = quad
  for (const n of ["tr", "bl", "br", "right", "left"]) s = E.deleteZone(s, n)
  check(s.name === "tl" && s.columns === undefined, "deleting down to one zone leaves a root leaf: " + JSON.stringify(s))
  check(s.empty === "keep" && s.single === "slot", "root collapse keeps the layout's empty/single policies: empty=" + s.empty)
  const withOpts = Object.assign({}, s, { gaps: { inner: 2 }, border: 1, aspect: 1.5, stack: "h" })
  const again = E.splitZone(withOpts, "tl", "columns")
  const first = again.columns[0]
  check(first.aspect === 1.5 && first.stack === "h" && first.fill === undefined && first.gaps === undefined && first.border === undefined && first.single === undefined,
    "root split moves only zone options onto the half: " + JSON.stringify(first))
  check(again.aspect === undefined && again.stack === undefined && again.gaps.inner === 2 && again.border === 1 && again.empty === "keep",
    "root split keeps layout keys on the root and drops the leaf ones: " + JSON.stringify(Object.keys(again)))
  assertValid("root split after collapse", again)
  // A container child's own empty override becomes the policy on collapse.
  const nested = { columns: [{ name: "a" }, { empty: "collapse", rows: [{ name: "b" }, { name: "c" }] }], empty: "keep" }
  const c = E.deleteZone(nested, "a")
  check(c.rows && c.empty === "collapse", "collapsing to a container child adopts its empty override")
}

// ---- never_split
{
  let s = E.setZoneProp(quad, "tl", "never_split", true)
  check(s.columns[1].rows[0].columns[0].never_split === true, "never_split set on a zone")
  assertValid("never_split", s)
  const sp = E.splitZone(s, "tl", "rows")
  check(sp.columns[1].rows[0].columns[0].rows[0].never_split === true && sp.columns[1].rows[0].columns[0].rows[1].never_split === undefined, "split keeps never_split on the original half only")
  s = E.setZoneProp(s, "tl", "never_split", null)
  check(s.columns[1].rows[0].columns[0].never_split === undefined, "never_split cleared")
  let root = E.setZoneProp({ name: "only" }, "only", "never_split", true)
  root = E.splitZone(root, "only", "columns")
  check(root.never_split === undefined && root.columns[0].never_split === true, "root split moves never_split onto the zone")
}

// ---- rename: every reference follows, bad or taken names are refused
{
  const withRefs = { ...quad, rules: [{ class: "^foot$", slot: "tl" }], capacity: { tl: 2 }, cycle: ["tl", "right"] }
  const s = E.renameZone(withRefs, "tl", "main")
  check(E.leafNames(s).indexOf("main") !== -1 && E.leafNames(s).indexOf("tl") === -1, "rename changes the leaf")
  check(s.fill[0] === "main" && s.cycle[0] === "main" && s.rules[0].slot === "main" && s.capacity.main === 2 && s.capacity.tl === undefined, "rename carries fill, cycle, rules, capacity")
  check(E.renameZone(quad, "tl", "tr") === quad, "rename to a taken name is refused")
  check(E.renameZone(quad, "tl", "bad name") === quad && !E.validName("-x") && E.validName("a-1"), "rename validates the name")
  assertValid("renamed", s)
}

// ---- neighbour: spatial selection
{
  check(E.neighbor(quad, area, "tl", "right") === "tr", "right of tl is tr: " + E.neighbor(quad, area, "tl", "right"))
  check(E.neighbor(quad, area, "tl", "down") === "bl", "below tl is bl")
  check(E.neighbor(quad, area, "tl", "left") === "left", "left of tl is left")
  check(E.neighbor(quad, area, "tr", "right") === "right", "right of tr is right")
  check(E.neighbor(quad, area, "left", "left") === "", "nothing left of left")
  check(E.neighbor(quad, area, "right", "left") === "tr", "left of right: both quadrants tie, the first in tree order wins")
}

// ---- edge dividers and nudging
{
  const d = E.edgeDivider(quad, area, "tl", "right")
  check(d && d.kind === "columns" && d.pos === 500 && d.h === 250, "tl's right edge is the tl|tr boundary: " + JSON.stringify(d))
  check(E.edgeDivider(quad, area, "left", "left") === null, "left's left edge is the layout's own")
  const grown = E.nudge(quad, area, "tl", "w", 0.05)
  const z = {}; G.zones(grown, area).forEach(x => z[x.name] = x)
  check(z.tl.w === 350 && z.tr.w === 250, "shift-right grows tl by 5% of the area: " + z.tl.w + "/" + z.tr.w)
  const edge = E.nudge(quad, area, "right", "w", 0.05)
  const z2 = {}; G.zones(edge, area).forEach(x => z2[x.name] = x)
  check(z2.right.w === 150, "a zone on the screen edge moves its near edge instead: " + z2.right.w)
  const tall = E.nudge(quad, area, "tl", "h", -0.1)
  const z3 = {}; G.zones(tall, area).forEach(x => z3[x.name] = x)
  check(z3.tl.h === 200 && z3.bl.h === 300, "shift-up shrinks tl's height: " + z3.tl.h)
  assertValid("nudged", grown)
}

// ---- exact size
{
  const s = E.setZoneExtent(ultrawide, area, "center", "w", 0.5)
  const z = {}; G.zones(s, area).forEach(x => z[x.name] = x)
  check(z.center.w === 500 && z.left.w === 250 && z.right.w === 250, "center set to 50%, siblings share the rest: " + [z.left.w, z.center.w, z.right.w].join())
  check(E.extentTarget(quad, "tl", "w") === "zone" && E.extentTarget(quad, "tl", "h") === "row", "tl sizes its own width and its row's height: " + E.extentTarget(quad, "tl", "h"))
  check(E.extentTarget(ultrawide, "center", "h") === "", "center has no height to set")
  const col = E.setZoneExtent(quad, area, "tl", "h", 0.3)
  const zc = {}; G.zones(col, area).forEach(x => zc[x.name] = x)
  check(zc.tl.h === 150 && zc.bl.h === 350, "tl height 30% of the area: " + zc.tl.h)
  const deep = { columns: [{ name: "a", w: 1 }, { w: 1, rows: [{ name: "b" }, { name: "c" }] }] }
  check(E.extentTarget(deep, "b", "w") === "column", "b's width is its column's")
  const dw = E.setZoneExtent(deep, area, "b", "w", 0.25)
  const zd = {}; G.zones(dw, area).forEach(x => zd[x.name] = x)
  check(zd.b.w === 250 && zd.a.w === 750, "setting b's width resizes its column: " + zd.b.w)
  assertValid("sized", s)
}

console.log(`${checks} checks, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
