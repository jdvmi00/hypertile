// Geometry.js: zone rectangles for a hypertile spec, mirroring the tree walk
// in hypertile.lua under the "keep" policy (every slot drawn, nothing
// collapsed), which is what a picture of the static layout should show.
//
// Plain script so QML can `import "Geometry.js" as Geometry` and node can
// evaluate it for tests. No dependencies, no top-level state.

function normalize(node) {
  var size = node.w !== undefined ? node.w : (node.h !== undefined ? node.h : (node.size !== undefined ? node.size : 1))
  if (node.columns) {
    return { kind: "h", size: size, children: node.columns.map(normalize) }
  }
  if (node.rows) {
    return { kind: "v", size: size, children: node.rows.map(normalize) }
  }
  return { kind: "leaf", size: size, name: String(node.name === undefined ? "?" : node.name), stack: node.stack,
           spacer: node.spacer === true, neverSplit: node.never_split === true, aspect: node.aspect !== undefined ? Number(node.aspect) : undefined,
           scale: node.scale !== undefined ? Number(node.scale) : undefined }
}

function leafNodes(node, out) {
  if (node.kind === "leaf") out.push(node)
  else for (var i = 0; i < node.children.length; i++) leafNodes(node.children[i], out)
  return out
}

// Mirror of hypertile.lua's fit_box: shrink to aspect (w/h) and scale, centered.
function fitBox(box, aspect, scale) {
  if (!aspect && !scale) return box
  var w = box.w, h = box.h
  if (aspect) {
    if (w / h > aspect) w = h * aspect
    else h = w / aspect
  }
  if (scale) { w = w * scale; h = h * scale }
  return { x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w: w, h: h }
}

function roundBox(x, y, w, h) {
  var x0 = Math.floor(x + 0.5), y0 = Math.floor(y + 0.5)
  var x1 = Math.floor(x + w + 0.5), y1 = Math.floor(y + h + 0.5)
  return { x: x0, y: y0, w: Math.max(1, x1 - x0), h: Math.max(1, y1 - y0) }
}

// Fills out[name] = { x, y, w, h } (unrounded) for every leaf. The same
// subdivision as Editor.layoutTree, which also needs the containers.
function walk(node, box, out) {
  if (node.kind === "leaf") { out[node.name] = box; return }
  var total = 0
  for (var i = 0; i < node.children.length; i++) total += node.children[i].size
  total = total || 1
  var horizontal = node.kind === "h"
  var extent = horizontal ? box.w : box.h
  var offset = 0
  for (var j = 0; j < node.children.length; j++) {
    var child = node.children[j]
    var length = extent * (child.size / total)
    if (j === node.children.length - 1) length = extent - offset
    var childBox = horizontal
      ? { x: box.x + offset, y: box.y, w: length, h: box.h }
      : { x: box.x, y: box.y + offset, w: box.w, h: length }
    walk(child, childBox, out)
    offset += length
  }
}

// Which fill positions land in each slot: { right: [5, 6], ... }.
// `override`, when given, is used verbatim even if empty (numbering mode).
function fillNumbers(spec, names, override) {
  var fill = Array.isArray(override) ? override
    : (Array.isArray(spec.fill) && spec.fill.length > 0 ? spec.fill : names)
  var map = {}
  for (var i = 0; i < fill.length; i++) {
    var slot = String(fill[i])
    if (!map[slot]) map[slot] = []
    map[slot].push(i + 1)
  }
  return map
}

// Zones for drawing: one entry per leaf, in tree order.
//   { name, x, y, w, h, fit: {x,y,w,h}, numbers: [..], stack, spacer,
//     aspect, scale, pctW, pctH }
// `fit` is where a window actually lands (aspect/scale applied).
function zones(spec, area, fillOverride) {
  if (!spec || !area) return []
  var tree = normalize(spec)
  var leaves = leafNodes(tree, [])
  var names = []
  var fillable = []
  for (var k = 0; k < leaves.length; k++) { names.push(leaves[k].name); if (!leaves[k].spacer) fillable.push(leaves[k].name) }
  var boxes = {}
  walk(tree, { x: area.x, y: area.y, w: area.w, h: area.h }, boxes)
  var numbers = fillNumbers(spec, fillable, fillOverride)
  var out = []
  for (var i = 0; i < leaves.length; i++) {
    var leaf = leaves[i]
    var name = leaf.name
    var b = roundBox(boxes[name].x, boxes[name].y, boxes[name].w, boxes[name].h)
    var f = fitBox(boxes[name], leaf.aspect, leaf.scale)
    var fr = roundBox(f.x, f.y, f.w, f.h)
    out.push({
      name: name,
      x: b.x, y: b.y, w: b.w, h: b.h,
      fit: fr,
      fitted: !!(leaf.aspect || leaf.scale),
      numbers: leaf.spacer ? [] : (numbers[name] || []),
      stack: leaf.stack || spec.stack || "v",
      spacer: leaf.spacer,
      neverSplit: leaf.neverSplit,
      aspect: leaf.aspect,
      scale: leaf.scale,
      pctW: area.w > 0 ? Math.round(100 * boxes[name].w / area.w) : 0,
      pctH: area.h > 0 ? Math.round(100 * boxes[name].h / area.h) : 0
    })
  }
  return out
}

// The area a layout receives on a monitor: minus reserved edges and the
// layout's outer gap (or the global one when the layout leaves it unset).
function areaFor(current, spec) {
  if (!current || !current.monitor) return null
  var m = current.monitor, r = current.reserved || {}
  var g = current.gaps_out || {}
  var outer = (spec && spec.gaps && spec.gaps.outer !== undefined) ? Number(spec.gaps.outer) : null
  var gt = outer !== null ? outer : (g.top || 0), gr = outer !== null ? outer : (g.right || 0)
  var gb = outer !== null ? outer : (g.bottom || 0), gl = outer !== null ? outer : (g.left || 0)
  return {
    x: (r.left || 0) + gl,
    y: (r.top || 0) + gt,
    w: m.width - (r.left || 0) - (r.right || 0) - gl - gr,
    h: m.height - (r.top || 0) - (r.bottom || 0) - gt - gb
  }
}

// One-line summary of what happens after the fill order is exhausted, in
// fill positions rather than zone names: "then repeats from 1" when the
// cycle is the fill order itself, otherwise "then 2 → 3 → 1 repeating".
function cycleSummary(spec) {
  var fill = Array.isArray(spec.fill) ? spec.fill : []
  var cycle = Array.isArray(spec.cycle) && spec.cycle.length > 0 ? spec.cycle : fill
  if (cycle.length === 0) return ""
  if (cycle.join("\u0000") === fill.join("\u0000")) return "then repeats from 1"
  var pos = {}
  for (var i = 0; i < fill.length; i++) if (pos[fill[i]] === undefined) pos[fill[i]] = i + 1
  var out = []
  for (var j = 0; j < cycle.length; j++) out.push(pos[cycle[j]] !== undefined ? String(pos[cycle[j]]) : cycle[j])
  return "then " + out.join(" → ") + " repeating"
}
