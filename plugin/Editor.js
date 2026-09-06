// Editor.js: pure edit operations on a hypertile spec, plus container
// geometry for divider hit-testing. Every operation returns a new spec and
// leaves its input untouched. Plain script: QML imports it, node tests it.
//
// Spec shape (same as the Lua side):
//   root = { columns|rows: [node...] | name, fill, cycle, rules, capacity, ... }
//   node = { name, w|h|size, stack } | { w|h|size, empty, columns|rows: [...] }
// Paths are arrays of child indices from the root; [] is the root.

function clone(v) { return JSON.parse(JSON.stringify(v)) }

// The options that belong to a zone rather than to the layout.
var LEAF_KEYS = ["id", "stack", "spacer", "never_split", "aspect", "scale"]

function newId() { return "z-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2) }

// Names and fill numbers are editable labels; scene references use these IDs.
// A copy gets new identities. Splitting keeps the original half's identity.
function identify(input, fresh) {
  var spec = clone(input)
  if (fresh || !spec.layout_id) spec.layout_id = newId()
  function walk(node) {
    var kids = childrenOf(node)
    if (kids) { for (var i = 0; i < kids.length; i++) walk(kids[i]) }
    else if (fresh || !node.id) node.id = newId()
  }
  walk(spec)
  return spec
}

function copyLeafOptions(from, to) {
  for (var i = 0; i < LEAF_KEYS.length; i++) if (from[LEAF_KEYS[i]] !== undefined) to[LEAF_KEYS[i]] = from[LEAF_KEYS[i]]
}

function dropLeafOptions(node) {
  delete node.name
  for (var i = 0; i < LEAF_KEYS.length; i++) delete node[LEAF_KEYS[i]]
}

function kindOf(node) {
  if (!node) return null
  if (Array.isArray(node.columns)) return "columns"
  if (Array.isArray(node.rows)) return "rows"
  return null
}

function childrenOf(node) {
  var k = kindOf(node)
  return k ? node[k] : null
}

function sizeOf(node) {
  if (node.w !== undefined) return Number(node.w)
  if (node.h !== undefined) return Number(node.h)
  if (node.size !== undefined) return Number(node.size)
  return 1
}

// Children of a columns container carry `w`; children of rows carry `h`.
function sizeKeyFor(kind) { return kind === "columns" ? "w" : "h" }

function setSize(node, kind, value) {
  delete node.w; delete node.h; delete node.size
  node[sizeKeyFor(kind)] = value
}

function nodeAt(spec, path) {
  var n = spec
  for (var i = 0; i < path.length; i++) {
    var kids = childrenOf(n)
    if (!kids || !kids[path[i]]) return null
    n = kids[path[i]]
  }
  return n
}

function leafNames(node, out) {
  out = out || []
  var kids = childrenOf(node)
  if (!kids) { out.push(String(node.name)); return out }
  for (var i = 0; i < kids.length; i++) leafNames(kids[i], out)
  return out
}

// { node, parent, index, path } for the leaf called `name`, or null.
function findLeaf(node, name, path, parent, index) {
  path = path || []
  var kids = childrenOf(node)
  if (!kids) return String(node.name) === name ? { node: node, parent: parent || null, index: index, path: path } : null
  for (var i = 0; i < kids.length; i++) {
    var hit = findLeaf(kids[i], name, path.concat([i]), node, i)
    if (hit) return hit
  }
  return null
}

function uniqueName(spec, base) {
  var names = leafNames(spec)
  var taken = {}
  for (var i = 0; i < names.length; i++) taken[names[i]] = true
  base = String(base || "zone").replace(/-\d+$/, "")
  if (!taken[base]) return base
  for (var n = 2; n < 1000; n++) {
    var cand = base + "-" + n
    if (!taken[cand]) return cand
  }
  return base + "-" + Date.now()
}

function isSpacer(node) { return node && node.spacer === true }

// Leaves that can take windows (spacers excluded), in tree order.
function fillableNames(spec) {
  var out = []
  function walk(node) {
    var kids = childrenOf(node)
    if (!kids) { if (!isSpacer(node)) out.push(String(node.name)); return }
    for (var i = 0; i < kids.length; i++) walk(kids[i])
  }
  walk(spec)
  return out
}

function ensureFill(spec) {
  var fillable = fillableNames(spec)
  if (Array.isArray(spec.fill)) spec.fill = spec.fill.filter(function(n) { return fillable.indexOf(n) !== -1 })
  if (!Array.isArray(spec.fill) || spec.fill.length === 0) spec.fill = fillable
  return spec
}

// ------------------------------------------------------------------ split

// Split leaf `name` into two along `kind` ("columns" = side by side,
// "rows" = stacked). If the parent already splits that way, the new zone
// becomes a sibling and the two share the original's weight; otherwise the
// leaf becomes a container of two equal halves. The new zone is numbered
// right after the original in the fill order.
function splitZone(input, name, kind) {
  if (!findLeaf(input, name)) return input
  var spec = clone(input)
  var hit = findLeaf(spec, name)
  ensureFill(spec) // before the new leaf exists, so it is numbered exactly once below
  var newName = uniqueName(spec, name)
  var leaf = hit.node
  var parent = hit.parent
  var wasSpacer = isSpacer(leaf)

  if (parent && kindOf(parent) === kind) {
    var half = sizeOf(leaf) / 2
    setSize(leaf, kind, half)
    var sibling = { name: newName, id: newId() }
    setSize(sibling, kind, half)
    childrenOf(parent).splice(hit.index + 1, 0, sibling)
  } else {
    var first = { name: leaf.name }
    // Only per-zone options travel to the half; when the root is the leaf,
    // `leaf` is the whole spec and must not leak fill/gaps/rules into a zone.
    copyLeafOptions(leaf, first)
    var second = { name: newName, id: newId() }
    if (parent) {
      var container = {}
      setSize(container, kindOf(parent), sizeOf(leaf))
      container[kind] = [first, second]
      childrenOf(parent)[hit.index] = container
    } else {
      // The root itself was a single leaf: it becomes a container in place.
      // Its per-zone options moved onto `first`; the layout-level keys stay.
      dropLeafOptions(spec)
      spec[kind] = [first, second]
    }
  }

  var last = -1
  for (var i = 0; i < spec.fill.length; i++) if (spec.fill[i] === name) last = i
  if (last === -1) spec.fill.push(newName)
  else spec.fill.splice(last + 1, 0, newName)
  ensureFill(spec)
  return spec
}

// ----------------------------------------------------------------- delete

function stripRefs(spec, name) {
  if (Array.isArray(spec.fill)) spec.fill = spec.fill.filter(function(n) { return n !== name })
  if (Array.isArray(spec.cycle)) {
    spec.cycle = spec.cycle.filter(function(n) { return n !== name })
    if (spec.cycle.length === 0) delete spec.cycle
  }
  if (Array.isArray(spec.rules)) {
    spec.rules = spec.rules.filter(function(r) { return r.slot !== name })
    if (spec.rules.length === 0) delete spec.rules
  }
  if (spec.capacity && spec.capacity[name] !== undefined) {
    delete spec.capacity[name]
    if (Object.keys(spec.capacity).length === 0) delete spec.capacity
  }
}

// Replace `container` (at `path`) by its only remaining child, keeping the
// container's weight under the grandparent.
function collapse(spec, path) {
  var container = nodeAt(spec, path)
  var child = childrenOf(container)[0]
  if (path.length === 0) {
    // The layout-level `empty` policy stays; a container child's own
    // override becomes the policy since its subtree is now the whole layout.
    delete spec.columns; delete spec.rows
    dropLeafOptions(spec)
    var ck = kindOf(child)
    if (ck) {
      spec[ck] = child[ck]
      if (child.empty !== undefined) spec.empty = child.empty
    } else {
      spec.name = child.name
      copyLeafOptions(child, spec)
    }
    return
  }
  var parentPath = path.slice(0, -1)
  var parent = nodeAt(spec, parentPath)
  var index = path[path.length - 1]
  var weight = sizeOf(container)
  var replacement = clone(child)
  setSize(replacement, kindOf(parent), weight)
  childrenOf(parent)[index] = replacement
}

function deleteZone(input, name) {
  if (leafNames(input).length <= 1) return input
  var found = findLeaf(input, name)
  if (!found || !found.parent) return input
  var spec = clone(input)
  var hit = findLeaf(spec, name)
  var parentPath = hit.path.slice(0, -1)
  childrenOf(hit.parent).splice(hit.index, 1)
  if (childrenOf(hit.parent).length === 1) collapse(spec, parentPath)
  stripRefs(spec, name)
  ensureFill(spec)
  return spec
}

// ----------------------------------------------------------------- resize

// Move the boundary between children `index` and `index + 1` of the
// container at `path` so the first takes `ratio` of their combined weight.
function resizeSiblings(input, path, index, ratio) {
  var source = nodeAt(input, path)
  var kind = kindOf(source)
  if (!kind || !source[kind][index] || !source[kind][index + 1]) return input
  var spec = clone(input)
  var kids = nodeAt(spec, path)[kind]
  var a = kids[index], b = kids[index + 1]
  var total = sizeOf(a) + sizeOf(b)
  var r = Math.max(0.05, Math.min(0.95, ratio))
  var wa = total * r
  var wb = total - wa
  setSize(a, kind, Math.round(wa * 1000) / 1000)
  setSize(b, kind, Math.round(wb * 1000) / 1000)
  return spec
}

function setFill(input, list) {
  var spec = clone(input)
  var names = fillableNames(spec)
  var ok = list.filter(function(n) { return names.indexOf(n) !== -1 })
  spec.fill = ok.length > 0 ? ok : names
  // A cycle written for the old numbering is likely wrong now; the engine
  // defaults cycle to fill when absent.
  delete spec.cycle
  return spec
}

// ------------------------------------------------------------ properties

// Set (or, with value === null/undefined, clear) a leaf option (LEAF_KEYS).
// Spacers lose every reference; un-spacing appends the zone to the fill
// order. Returns the input untouched when nothing changes.
function setZoneProp(input, name, key, value) {
  var found = findLeaf(input, name)
  if (!found) return input
  if (key === "spacer" && value === true && !isSpacer(found.node) && fillableNames(input).length <= 1) return input // keep one real zone
  var spec = clone(input)
  var leaf = findLeaf(spec, name).node
  if (key === "spacer") {
    if (value === true) {
      leaf.spacer = true
      stripRefs(spec, name)
      ensureFill(spec)
    } else {
      delete leaf.spacer
      ensureFill(spec)
      if (spec.fill.indexOf(name) === -1) spec.fill.push(name)
    }
    return spec
  }
  if (value === null || value === undefined || value === "") delete leaf[key]
  else leaf[key] = value
  return spec
}

// Layout-level options: empty, single, stack, border, rounding, in_cycle.
function setLayoutProp(input, key, value) {
  var spec = clone(input)
  if (value === null || value === undefined || value === "") delete spec[key]
  else spec[key] = value
  return spec
}

function setGap(input, which, value) {
  var spec = clone(input)
  var gaps = spec.gaps ? clone(spec.gaps) : {}
  if (value === null || value === undefined) delete gaps[which]
  else gaps[which] = Math.max(0, Math.round(value))
  if (Object.keys(gaps).length === 0) delete spec.gaps
  else spec.gaps = gaps
  return spec
}

function setCapacity(input, name, value) {
  var spec = clone(input)
  var cap = spec.capacity ? clone(spec.capacity) : {}
  if (value === null || value === undefined || value < 1) delete cap[name]
  else cap[name] = Math.round(value)
  if (Object.keys(cap).length === 0) delete spec.capacity
  else spec.capacity = cap
  return spec
}

// Rules route windows to zones: { class|title|tag: pattern, slot: zone }.
function addRule(input, rule) {
  if (!rule || !rule.slot || fillableNames(input).indexOf(rule.slot) === -1) return input
  var existing = Array.isArray(input.rules) ? input.rules : []
  for (var i = 0; i < existing.length; i++) {
    var r = existing[i]
    if (r.slot === rule.slot && r.class === rule.class && r.title === rule.title && r.tag === rule.tag) return input
  }
  var spec = clone(input)
  spec.rules = existing.concat([rule])
  return spec
}

function removeRule(input, index) {
  if (!Array.isArray(input.rules) || index < 0 || index >= input.rules.length) return input
  var spec = clone(input)
  var rules = spec.rules.slice()
  rules.splice(index, 1)
  if (rules.length === 0) delete spec.rules
  else spec.rules = rules
  return spec
}

// Rules targeting one zone, with their index in spec.rules.
function rulesFor(spec, name) {
  var out = []
  var rules = Array.isArray(spec.rules) ? spec.rules : []
  for (var i = 0; i < rules.length; i++) if (rules[i].slot === name) out.push({ index: i, rule: rules[i] })
  return out
}

// Escape a window class for an exact-match Lua pattern.
function exactPattern(text) {
  return "^" + String(text).replace(/[%^$().[\]*+\-?]/g, function(c) { return "%" + c }) + "$"
}

// --------------------------------------------------------------- geometry

// Unrounded boxes for every node, subdivided as Geometry.walk does. Returns:
//   { leaves: { name: box }, containers: [ { path, kind, box, kids: [ { box, size } ] } ] }
function layoutTree(spec, area) {
  var out = { leaves: {}, containers: [] }
  function walk(node, box, path) {
    var kind = kindOf(node)
    if (!kind) { out.leaves[String(node.name)] = box; return }
    var kids = node[kind]
    var total = 0
    for (var i = 0; i < kids.length; i++) total += sizeOf(kids[i])
    var horizontal = kind === "columns"
    var extent = horizontal ? box.w : box.h
    var offset = 0
    var entry = { path: path, kind: kind, box: box, kids: [] }
    for (var j = 0; j < kids.length; j++) {
      var length = extent * (sizeOf(kids[j]) / (total || 1))
      if (j === kids.length - 1) length = extent - offset
      var childBox = horizontal
        ? { x: box.x + offset, y: box.y, w: length, h: box.h }
        : { x: box.x, y: box.y + offset, w: box.w, h: length }
      entry.kids.push({ box: childBox, size: sizeOf(kids[j]) })
      walk(kids[j], childBox, path.concat([j]))
      offset += length
    }
    out.containers.push(entry)
  }
  walk(spec, { x: area.x, y: area.y, w: area.w, h: area.h }, [])
  return out
}

// One entry per boundary between siblings:
//   { path, index, kind, pos, x, y, w, h, start, span }
// `pos` is the boundary coordinate (x for columns, y for rows); the strip
// (x, y, w, h) is the boundary line itself with zero thickness, `start` and
// `span` describe the two siblings' combined extent for turning a pointer
// position into a ratio.
function dividers(spec, area) {
  var tree = layoutTree(spec, area)
  var out = []
  for (var c = 0; c < tree.containers.length; c++) {
    var entry = tree.containers[c]
    for (var i = 0; i < entry.kids.length - 1; i++) {
      var a = entry.kids[i].box, b = entry.kids[i + 1].box
      if (entry.kind === "columns") {
        out.push({ path: entry.path, index: i, kind: entry.kind, pos: b.x, x: b.x, y: a.y, w: 0, h: a.h, start: a.x, span: a.w + b.w })
      } else {
        out.push({ path: entry.path, index: i, kind: entry.kind, pos: b.y, x: a.x, y: b.y, w: a.w, h: 0, start: a.y, span: a.h + b.h })
      }
    }
  }
  return out
}

// Nearest divider to (px, py) within `threshold` pixels, or null.
function dividerAt(divs, px, py, threshold) {
  var best = null, bestDist = threshold
  for (var i = 0; i < divs.length; i++) {
    var d = divs[i]
    var dist, inside
    if (d.kind === "columns") {
      dist = Math.abs(px - d.pos)
      inside = py >= d.y && py <= d.y + d.h
    } else {
      dist = Math.abs(py - d.pos)
      inside = px >= d.x && px <= d.x + d.w
    }
    if (inside && dist <= bestDist) { best = d; bestDist = dist }
  }
  return best
}

// Name of the leaf containing (px, py), or "".
function leafAt(spec, area, px, py) {
  var tree = layoutTree(spec, area)
  for (var name in tree.leaves) {
    var b = tree.leaves[name]
    if (px >= b.x && px < b.x + b.w && py >= b.y && py < b.y + b.h) return name
  }
  return ""
}

// ----------------------------------------------------------------- rename

// Layout and zone names: they become file names and Lua keys.
function validName(name) { return /^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(String(name || "")) }

// Rename leaf `from` to `to`; fill, cycle, rules, and capacity follow. The
// input is returned untouched when the name is invalid or already taken.
function renameZone(input, from, to) {
  to = String(to || "").trim()
  if (from === to || !validName(to)) return input
  if (leafNames(input).indexOf(to) !== -1) return input
  var spec = clone(input)
  var hit = findLeaf(spec, from)
  if (!hit) return input
  hit.node.name = to
  var swap = function(n) { return n === from ? to : n }
  if (Array.isArray(spec.fill)) spec.fill = spec.fill.map(swap)
  if (Array.isArray(spec.cycle)) spec.cycle = spec.cycle.map(swap)
  if (Array.isArray(spec.rules)) spec.rules = spec.rules.map(function(r) { var c = clone(r); if (c.slot === from) c.slot = to; return c })
  if (spec.capacity && spec.capacity[from] !== undefined) {
    var cap = {}
    for (var k in spec.capacity) cap[k === from ? to : k] = spec.capacity[k]
    spec.capacity = cap
  }
  return spec
}

// ------------------------------------------------------------- navigation

// The leaf nearest to `name` in direction `dir` (left/right/up/down):
// candidates lie past the matching edge; the closest wins, then the one
// sharing the most extent on the other axis. Returns "" when nothing is there.
function neighbor(spec, area, name, dir) {
  var tree = layoutTree(spec, area)
  var a = tree.leaves[name]
  if (!a) return ""
  var best = "", bestScore = -Infinity
  for (var n in tree.leaves) {
    if (n === name) continue
    var b = tree.leaves[n]
    var beyond, dist, overlap
    if (dir === "right") { beyond = b.x >= a.x + a.w - 1; dist = b.x - (a.x + a.w) }
    else if (dir === "left") { beyond = b.x + b.w <= a.x + 1; dist = a.x - (b.x + b.w) }
    else if (dir === "down") { beyond = b.y >= a.y + a.h - 1; dist = b.y - (a.y + a.h) }
    else { beyond = b.y + b.h <= a.y + 1; dist = a.y - (b.y + b.h) }
    if (!beyond) continue
    if (dir === "left" || dir === "right") overlap = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)
    else overlap = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)
    if (overlap <= 0) continue
    // Closest first, then the one sharing the most extent; on a tie the
    // first in tree order (top-left first) wins.
    var score = -Math.max(0, dist) * 100000 + overlap
    if (score > bestScore) { bestScore = score; best = n }
  }
  return best
}

// The divider forming leaf `name`'s edge on `side` (left/right/top/bottom):
// the deepest boundary sitting on that edge and covering the leaf. Null
// when the edge is the layout's own.
function edgeDivider(spec, area, name, side) {
  var tree = layoutTree(spec, area)
  var a = tree.leaves[name]
  if (!a) return null
  var divs = dividers(spec, area)
  var vertical = side === "left" || side === "right"
  var edge = side === "left" ? a.x : side === "right" ? a.x + a.w : side === "top" ? a.y : a.y + a.h
  var best = null
  for (var i = 0; i < divs.length; i++) {
    var d = divs[i]
    if (vertical !== (d.kind === "columns")) continue
    if (Math.abs(d.pos - edge) > 1) continue
    var covers = vertical ? (d.y <= a.y + 1 && d.y + d.h >= a.y + a.h - 1) : (d.x <= a.x + 1 && d.x + d.w >= a.x + a.w - 1)
    if (!covers) continue
    var length = vertical ? d.h : d.w
    if (!best || length < (vertical ? best.h : best.w)) best = d
  }
  return best
}

// Move one of the leaf's edges by `delta` (a fraction of the layout area,
// signed: positive is right or down). Shift+arrow uses this. The far edge
// on that axis moves when it can, otherwise the near one, so a zone at the
// screen's edge still resizes.
function nudge(input, area, name, axis, delta) {
  var horizontal = axis === "w"
  var far = edgeDivider(input, area, name, horizontal ? "right" : "bottom")
  var near = far ? null : edgeDivider(input, area, name, horizontal ? "left" : "top")
  var d = far || near
  if (!d) return input
  var px = delta * (horizontal ? area.w : area.h)
  var ratio = (d.pos + px - d.start) / Math.max(1, d.span)
  return resizeSiblings(input, d.path, d.index, ratio)
}

// Give leaf `name` `fraction` of the layout area along `axis` ("w" or "h").
// The nearest ancestor sized on that axis is the node that changes (the
// leaf itself when its parent splits that way, otherwise the column or row
// it lives in); its siblings shrink or grow in proportion. Returns the
// input untouched when nothing on that axis is resizable.
function setZoneExtent(input, area, name, axis, fraction) {
  var kind = axis === "w" ? "columns" : "rows"
  var hit = findLeaf(input, name)
  if (!hit) return input
  var path = hit.path
  while (path.length > 0 && kindOf(nodeAt(input, path.slice(0, -1))) !== kind) path = path.slice(0, -1)
  if (path.length === 0) return input
  var spec = clone(input)
  var parentPath = path.slice(0, -1)
  var parent = nodeAt(spec, parentPath)
  var kids = childrenOf(parent)
  var tree = layoutTree(spec, area)
  var parentBox = null
  for (var i = 0; i < tree.containers.length; i++) if (tree.containers[i].path.join() === parentPath.join()) parentBox = tree.containers[i].box
  if (!parentBox) return input
  var extent = axis === "w" ? parentBox.w : parentBox.h
  var want = Math.max(0, Math.min(1, fraction)) * (axis === "w" ? area.w : area.h)
  var r = Math.max(0.05, Math.min(0.95, want / Math.max(1, extent)))
  var total = 0
  for (var k = 0; k < kids.length; k++) total += sizeOf(kids[k])
  var node = kids[path[path.length - 1]]
  var old = sizeOf(node)
  var next = r * (total - old) / (1 - r)
  setSize(node, kind, Math.round(next * 1000) / 1000)
  return spec
}

// Which node setZoneExtent would change for `name` on `axis`: "zone" when
// the leaf itself, "column"/"row" for an ancestor, "" when nothing.
function extentTarget(spec, name, axis) {
  var kind = axis === "w" ? "columns" : "rows"
  var hit = findLeaf(spec, name)
  if (!hit) return ""
  var path = hit.path
  var depth = 0
  while (path.length > 0 && kindOf(nodeAt(spec, path.slice(0, -1))) !== kind) { path = path.slice(0, -1); depth++ }
  if (path.length === 0) return ""
  if (depth === 0) return "zone"
  var ancestor = nodeAt(spec, path)
  return kindOf(ancestor) === "rows" ? "column" : (kindOf(ancestor) === "columns" ? "row" : "group")
}

function toDoc(name, spec) {
  return { name: name, spec: spec }
}
