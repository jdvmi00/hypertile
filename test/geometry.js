// Geometry.js tests (node). Run from the repo root: node test/geometry.js
// Evaluates the plain-script file the QML overlay imports, then checks its
// zones against the same cases the Lua harness uses.

const fs = require("fs")
const path = require("path")
const vm = require("vm")

const src = fs.readFileSync(path.join(__dirname, "..", "plugin", "Geometry.js"), "utf8")
const ctx = {}
vm.runInNewContext(src + "\nthis.zones = zones; this.cycleSummary = cycleSummary; this.fillNumbers = fillNumbers; this.areaFor = areaFor; this.fitBox = fitBox;", ctx)

let checks = 0, failures = 0
function check(cond, msg) {
  checks++
  if (!cond) { failures++; console.log("FAIL: " + msg) }
}
function byName(zones) {
  const m = {}
  for (const z of zones) m[z.name] = z
  return m
}
function fmt(z) { return `(${z.x},${z.y} ${z.w}x${z.h})` }

const area = { x: 10, y: 36, w: 6124, h: 2514 } // 6144x2560, a 26 px bar, a 10 px outer gap

// Ultrawide: 20/60/20; the expected boxes are the engine's placement for this area.
const ultrawide = {
  columns: [{ name: "left", w: 0.2 }, { name: "center", w: 0.6 }, { name: "right", w: 0.2 }],
  fill: ["center", "right", "left"], cycle: ["right", "left", "center"], empty: "keep", single: "slot",
}
{
  const z = byName(ctx.zones(ultrawide, area))
  check(z.left.x === 10 && z.left.w === 1225 && z.left.h === 2514, "ultrawide left: " + fmt(z.left))
  check(z.center.x === 1235 && z.center.w === 3674, "ultrawide center: " + fmt(z.center))
  check(z.right.x === 4909 && z.right.w === 1225, "ultrawide right: " + fmt(z.right))
  check(z.center.numbers.join() === "1" && z.right.numbers.join() === "2" && z.left.numbers.join() === "3", "ultrawide fill numbers")
  check(ctx.cycleSummary(ultrawide) === "then 2 → 3 → 1 repeating", "cycle summary: " + ctx.cycleSummary(ultrawide))
  check(ctx.cycleSummary({ columns: [{ name: "a" }, { name: "b" }], fill: ["a", "b"] }) === "then repeats from 1", "cycle summary when cycle is the fill order")
}

// Quad: the engine's placement for eight windows (gaps aside).
const quad = {
  columns: [
    { name: "left", w: 0.2 },
    { w: 0.6, rows: [{ columns: [{ name: "tl" }, { name: "tr" }] }, { columns: [{ name: "bl" }, { name: "br" }] }] },
    { name: "right", w: 0.2 },
  ],
  fill: ["tl", "tr", "bl", "br", "right", "right", "left", "left"], empty: "keep", single: "slot",
}
{
  const zs = ctx.zones(quad, area)
  check(zs.length === 6 && zs.map(z => z.name).join() === "left,tl,tr,bl,br,right", "quad zones in tree order: " + zs.map(z => z.name).join())
  const z = byName(zs)
  check(z.tl.x === 1235 && z.tl.y === 36 && z.tl.w === 1837 && z.tl.h === 1257, "quad tl: " + fmt(z.tl))
  check(z.tr.x === 3072 && z.tr.w === 1837, "quad tr: " + fmt(z.tr))
  check(z.bl.y === 1293 && z.bl.h === 1257, "quad bl: " + fmt(z.bl))
  check(z.br.x === 3072 && z.br.y === 1293, "quad br: " + fmt(z.br))
  check(z.right.numbers.join() === "5,6" && z.left.numbers.join() === "7,8", "quad stacked numbers on side columns")
  check(z.tl.pctW === 30 && z.tl.pctH === 50 && z.left.pctW === 20 && z.left.pctH === 100, "quad percentages")
  // Edges meet with no seam.
  check(z.tl.x + z.tl.w === z.tr.x && z.tr.x + z.tr.w === z.right.x && z.left.x + z.left.w === z.tl.x, "quad columns tile exactly")
  check(z.tl.y + z.tl.h === z.bl.y && z.bl.y + z.bl.h === area.y + area.h, "quad rows tile exactly")
}

// Weighted nested rows.
{
  const nested = { columns: [{ name: "main", w: 2 }, { w: 1, rows: [{ name: "top", h: 1 }, { name: "bottom", h: 2 }] }], fill: ["main", "top", "bottom"] }
  const z = byName(ctx.zones(nested, { x: 100, y: 50, w: 3000, h: 900 }))
  check(z.main.x === 100 && z.main.w === 2000 && z.main.h === 900, "nested main: " + fmt(z.main))
  check(z.top.x === 2100 && z.top.w === 1000 && z.top.h === 300, "nested top: " + fmt(z.top))
  check(z.bottom.y === 350 && z.bottom.h === 600, "nested bottom: " + fmt(z.bottom))
}

// Defaults: no fill means tree order; empty inputs are safe.
{
  const z = byName(ctx.zones({ columns: [{ name: "a" }, { name: "b" }] }, { x: 0, y: 0, w: 100, h: 100 }))
  check(z.a.numbers.join() === "1" && z.b.numbers.join() === "2", "fill defaults to tree order")
  check(ctx.zones(null, area).length === 0 && ctx.zones(quad, null).length === 0, "null inputs give no zones")
  check(ctx.zones({ name: "only" }, { x: 0, y: 0, w: 10, h: 10 }).length === 1, "single-leaf spec is one zone")
}

// Aspect, scale, spacers, areaFor.
{
  const z = ctx.zones({ name: "main", aspect: 1, scale: 0.7 }, area)[0]
  check(z.fitted && z.fit.w === z.fit.h && z.fit.w === 1760, "square zone fit: 70% of 2514 = 1760: " + JSON.stringify(z.fit))
  check(z.fit.x === Math.floor(10 + (6124 - 1759.8) / 2 + 0.5) && z.fit.y === Math.floor(36 + (2514 - 1759.8) / 2 + 0.5), "square zone centered: " + JSON.stringify(z.fit))
  check(z.x === 10 && z.w === 6124, "zone box itself is still the full area")

  const hole = ctx.zones({ columns: [{ name: "pad", spacer: true }, { name: "main", w: 2 }] }, area)
  const byN = byName(hole)
  check(byN.pad.spacer === true && byN.pad.numbers.length === 0, "spacer zone has no fill number")
  check(byN.main.numbers.join() === "1", "default numbering skips spacers")
  const numbered = ctx.zones({ columns: [{ name: "pad", spacer: true }, { name: "main" }], fill: ["main", "main"] }, area)
  check(byName(numbered).main.numbers.join() === "1,2", "explicit fill still applies")

  const current = { monitor: { width: 6144, height: 2560 }, reserved: { top: 26, right: 0, bottom: 0, left: 0 }, gaps_out: { top: 10, right: 10, bottom: 10, left: 10 } }
  const a1 = ctx.areaFor(current, {})
  check(a1.x === 10 && a1.y === 36 && a1.w === 6124 && a1.h === 2514, "areaFor with global gaps matches the bridge: " + JSON.stringify(a1))
  const a0 = ctx.areaFor(current, { gaps: { outer: 0 } })
  check(a0.x === 0 && a0.y === 26 && a0.w === 6144 && a0.h === 2534, "areaFor with outer gap 0: " + JSON.stringify(a0))
  const a40 = ctx.areaFor(current, { gaps: { outer: 40, inner: 0 } })
  check(a40.x === 40 && a40.w === 6064, "areaFor with outer gap 40: " + JSON.stringify(a40))
  check(ctx.areaFor(null, {}) === null, "areaFor without geometry is null")
  const wide = ctx.fitBox({ x: 0, y: 0, w: 1000, h: 200 }, 1, undefined)
  check(wide.w === 200 && wide.h === 200 && wide.x === 400, "fitBox aspect 1 in a wide box uses the height")
}

console.log(`${checks} checks, ${failures} failures`)
process.exit(failures === 0 ? 0 : 1)
