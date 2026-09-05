-- hypertile: a spec-driven zone layout provider for Hyprland's Lua layout API.
--
-- A spec describes a tree of named slots (zones). Windows are assigned to
-- slots by rules (class/title/tag match), by pins set at runtime through
-- layout_msg, or by a fill order. Windows sharing a slot are stacked. The
-- spec format is documented in README.md, "Spec".
--
-- Leaf semantics that are not obvious from the code: `aspect` (w/h) fits
-- the largest box of that ratio inside the slot and `scale` shrinks it,
-- both centered. A `spacer` never takes windows and is never collapsed. A
-- `never_split` slot holds one window and is never an overflow target while
-- another slot exists; when none does, extra windows overlap it at full
-- size instead of splitting it.
--
-- Sizes (w/h) are weights normalized among siblings; a missing size is 1.
-- They can be overridden at runtime through layout_msg.
--
-- The module never touches the `hl` global at load time, so it runs under a
-- plain `lua` interpreter for tests; `hl` is used only inside layout_msg and
-- registration, where a live compositor is guaranteed.

local M = {}

-- Per-layout runtime state: pins (window address -> slot) and size overrides.
M.state = {}

-- Layout names in registration order (deduplicated), for cycling keybinds.
M.registered = {}

function M.names()
  local out = {}
  for i, name in ipairs(M.registered) do
    out[i] = name
  end
  return out
end

local function round_box(x, y, w, h)
  local x0 = math.floor(x + 0.5)
  local y0 = math.floor(y + 0.5)
  local x1 = math.floor(x + w + 0.5)
  local y1 = math.floor(y + h + 0.5)
  return { x = x0, y = y0, w = math.max(1, x1 - x0), h = math.max(1, y1 - y0) }
end

---------------------------------------------------------------------------
-- Spec normalization: turn the user-facing shorthand into a uniform tree.
-- Node: { kind = "leaf", name = s, size = n } or
--       { kind = "h"|"v", size = n, children = {...} }
---------------------------------------------------------------------------

local EMPTY_POLICIES = { collapse = true, keep = true }
local SINGLE_POLICIES = { collapse = true, slot = true }
local STACK_DIRECTIONS = { v = true, h = true }

local function assert_one_of(value, allowed, what)
  if value ~= nil then
    local names = {}
    for k in pairs(allowed) do
      names[#names + 1] = k
    end
    table.sort(names)
    assert(allowed[value], "hypertile: " .. what .. ' must be one of "' .. table.concat(names, '", "') .. '"')
  end
end

local function normalize_node(node, path)
  local size = tonumber(node.w or node.h or node.size or 1)
  assert(size and size > 0, "hypertile: size must be a number > 0 at " .. (path == "" and "root" or path))
  assert_one_of(node.empty, EMPTY_POLICIES, "empty" .. (path == "" and "" or " at " .. path))
  if node.columns then
    local out = { kind = "h", size = size, empty = node.empty, children = {} }
    for i, child in ipairs(node.columns) do
      out.children[i] = normalize_node(child, path .. "/c" .. i)
    end
    return out
  elseif node.rows then
    local out = { kind = "v", size = size, empty = node.empty, children = {} }
    for i, child in ipairs(node.rows) do
      out.children[i] = normalize_node(child, path .. "/r" .. i)
    end
    return out
  end
  assert(node.name, "hypertile: leaf without a name at " .. path)
  assert_one_of(node.stack, STACK_DIRECTIONS, "stack on slot " .. node.name)
  return {
    kind = "leaf",
    name = node.name,
    id = node.id,
    size = size,
    stack = node.stack,
    spacer = node.spacer == true,
    never_split = node.never_split == true,
    aspect = tonumber(node.aspect),
    scale = tonumber(node.scale),
  }
end

-- Leaf names in tree order, and each leaf node by name.
local function collect_leaves(node, names, by_name)
  if node.kind == "leaf" then
    names[#names + 1] = node.name
    by_name[node.name] = node
  else
    for _, child in ipairs(node.children) do
      collect_leaves(child, names, by_name)
    end
  end
  return names
end

function M.compile(spec)
  local tree = normalize_node(spec, "")
  local leaf_opts = {}
  local leaves = {}
  local seen = {}
  for _, name in ipairs(collect_leaves(tree, {}, leaf_opts)) do
    assert(not seen[name], "hypertile: duplicate slot name " .. name)
    seen[name] = true
    leaves[#leaves + 1] = name
  end
  local leaf_set = seen
  assert(spec.layout_id == nil or (type(spec.layout_id) == "string" and spec.layout_id:match("^[%w_%-]+$") and #spec.layout_id <= 128), "hypertile: invalid layout id")
  local zone_ids = {}
  for _, name in ipairs(leaves) do
    local id = leaf_opts[name].id
    if id ~= nil then
      assert(type(id) == "string" and id:match("^[%w_%-]+$") and #id <= 128, "hypertile: invalid zone id")
      assert(not zone_ids[id], "hypertile: duplicate zone id " .. id)
      zone_ids[id] = name
    end
  end
  local fillable = {}
  for _, name in ipairs(leaves) do
    local o = leaf_opts[name]
    if not o.spacer then
      fillable[#fillable + 1] = name
    end
    assert(o.aspect == nil or o.aspect > 0, "hypertile: aspect must be > 0 on slot " .. name)
    assert(o.scale == nil or (o.scale > 0 and o.scale <= 1), "hypertile: scale must be in (0, 1] on slot " .. name)
  end
  assert(#fillable > 0, "hypertile: every slot is a spacer; at least one must take windows")
  local function assert_fillable(name, what)
    assert(leaf_set[name], "hypertile: " .. what .. " references unknown slot " .. tostring(name))
    assert(not leaf_opts[name].spacer, "hypertile: " .. what .. " references spacer slot " .. tostring(name))
  end
  local fill = spec.fill or fillable
  local cycle = spec.cycle or fill
  assert(#fill > 0, "hypertile: fill must name at least one slot")
  assert(#cycle > 0, "hypertile: cycle must name at least one slot")
  -- Position of each slot in the numbering (first occurrence); slots that
  -- never appear in fill sort after the numbered ones, in tree order.
  local fill_pos = {}
  for i, name in ipairs(fill) do
    fill_pos[name] = fill_pos[name] or i
  end
  for i, name in ipairs(leaves) do
    fill_pos[name] = fill_pos[name] or (#fill + i)
  end
  for _, name in ipairs(fill) do
    assert_fillable(name, "fill")
  end
  for _, name in ipairs(cycle) do
    assert_fillable(name, "cycle")
  end
  for _, rule in ipairs(spec.rules or {}) do
    assert_fillable(rule.slot, "rule")
  end
  for name, cap in pairs(spec.capacity or {}) do
    assert_fillable(name, "capacity")
    assert(tonumber(cap) and tonumber(cap) >= 1, "hypertile: capacity." .. name .. " must be a number >= 1")
  end
  assert_one_of(spec.stack, STACK_DIRECTIONS, "stack")
  assert_one_of(spec.single, SINGLE_POLICIES, "single")
  if spec.gaps ~= nil then
    assert(type(spec.gaps) == "table", "hypertile: gaps must be a table { inner = n, outer = n }")
    for _, k in ipairs({ "inner", "outer" }) do
      local v = spec.gaps[k]
      assert(v == nil or (tonumber(v) and tonumber(v) >= 0), "hypertile: gaps." .. k .. " must be a number >= 0")
    end
  end
  assert(spec.border == nil or (tonumber(spec.border) and tonumber(spec.border) >= 0), "hypertile: border must be a number >= 0")
  assert(spec.rounding == nil or (tonumber(spec.rounding) and tonumber(spec.rounding) >= 0 and tonumber(spec.rounding) <= 20),
    "hypertile: rounding must be a number from 0 to 20")
  assert(spec.in_cycle == nil or type(spec.in_cycle) == "boolean", "hypertile: in_cycle must be true or false")
  return {
    tree = tree,
    leaves = leaves,
    fillable = fillable,
    leaf_set = leaf_set,
    zone_ids = zone_ids,
    leaf_opts = leaf_opts,
    fill = fill,
    fill_pos = fill_pos,
    cycle = cycle,
    rules = spec.rules or {},
    capacity = spec.capacity or {},
    stack = spec.stack or "v",
    empty = spec.empty or "collapse",
    single = spec.single or "collapse",
    gaps = spec.gaps,
    border = spec.border,
    rounding = spec.rounding,
  }
end

---------------------------------------------------------------------------
-- Assignment: decide which slot each target goes to.
---------------------------------------------------------------------------

local function window_matches(rule, win)
  if not win then
    return false
  end
  if rule.class and not (win.class and string.find(win.class, rule.class)) then
    return false
  end
  if rule.title and not (win.title and string.find(win.title, rule.title)) then
    return false
  end
  if rule.tag then
    local tags = win.tags
    local found = false
    -- Hyprland reports static tags with a trailing "*" (e.g. "terminal*").
    local function tag_eq(t)
      return t == rule.tag or t == rule.tag .. "*"
    end
    if type(tags) == "table" then
      for _, t in ipairs(tags) do
        if tag_eq(t) then
          found = true
        end
      end
    elseif type(tags) == "string" then
      found = tag_eq(tags)
    end
    if not found then
      return false
    end
  end
  return true
end

local function window_key(win)
  if not win then
    return nil
  end
  return win.address or win.stable_id
end

-- Returns { slotname = { target, ... } }. Windows keep their target order
-- inside a slot regardless of whether they arrived by pin, rule, or fill.
function M.assign(compiled, targets, state)
  local pins = state and state.pins or {}
  local reserved = state and state.reserved or {}
  -- A local window exchanged with a reserved source takes one whole zone.
  -- Ordinary pins retain their existing stacking behavior. Only live swap
  -- pins exclude ordinary fill; overflow may still use these local zones.
  local occupied = {}
  for _, target in ipairs(targets) do
    local key = window_key(target.window)
    if key and state and state.exclusive_pins and state.exclusive_pins[key] and pins[key] then
      occupied[pins[key]] = true
    end
  end
  local slot_of = {}
  local count = {}
  for _, name in ipairs(compiled.leaves) do
    count[name] = 0
  end

  local function take(name, i)
    slot_of[i] = name
    count[name] = count[name] + 1
  end

  local function has_room(name)
    if reserved[name] or occupied[name] then return false end
    if compiled.leaf_opts[name].never_split then
      return count[name] < 1
    end
    local cap = compiled.capacity[name]
    return not cap or count[name] < cap
  end

  -- Pass 1: pins and rules.
  local unassigned = {}
  for i, target in ipairs(targets) do
    local win = target.window
    local key = window_key(win)
    local slot = key and pins[key]
    for name, owner in pairs(reserved) do
      if key == owner then slot = name end
    end
    if slot and compiled.leaf_set[slot] and not compiled.leaf_opts[slot].spacer
      and (not reserved[slot] or reserved[slot] == key) then
      take(slot, i)
    else
      -- Among every rule this window matches, take the slot with the lowest
      -- fill number that still has room, so an app allowed in zones 5..8
      -- fills them 5, 6, 7, 8 regardless of the order the rules were added.
      local best, best_pos
      for _, rule in ipairs(compiled.rules) do
        if compiled.leaf_set[rule.slot] and window_matches(rule, win) and has_room(rule.slot) then
          local pos = compiled.fill_pos[rule.slot] or math.huge
          if not best or pos < best_pos then
            best, best_pos = rule.slot, pos
          end
        end
      end
      if best then
        take(best, i)
      else
        unassigned[#unassigned + 1] = i
      end
    end
  end

  -- Pass 2: fill order, then cycle, skipping full slots. If every slot is
  -- full, fall through to the cycle regardless of capacity, but still avoid
  -- never-split slots unless nothing else exists.
  local fill_i, cycle_i = 1, 1
  local function next_slot()
    local name
    if fill_i <= #compiled.fill then
      name = compiled.fill[fill_i]
      fill_i = fill_i + 1
    else
      name = compiled.cycle[cycle_i]
      cycle_i = cycle_i % #compiled.cycle + 1
    end
    return name
  end
  for _, i in ipairs(unassigned) do
    local placed = false
    for _ = 1, #compiled.fill + #compiled.cycle do
      local name = next_slot()
      if has_room(name) then
        take(name, i)
        placed = true
        break
      end
    end
    if not placed then
      local fallback
      for _ = 1, #compiled.cycle do
        local name = next_slot()
        if not reserved[name] and not compiled.leaf_opts[name].never_split then
          fallback = name
          break
        end
      end
      if not fallback then
        for _, name in ipairs(compiled.cycle) do
          if not reserved[name] then fallback = name; break end
        end
      end
      assert(fallback, "stream assignments must leave a local overflow zone")
      take(fallback, i)
    end
  end

  local buckets = {}
  for _, name in ipairs(compiled.leaves) do
    buckets[name] = {}
    buckets[name].reserved = reserved[name] ~= nil
  end
  for i, target in ipairs(targets) do
    table.insert(buckets[slot_of[i]], target)
  end
  return buckets
end

---------------------------------------------------------------------------
-- Geometry: walk the tree, dropping empty subtrees when empty == "collapse".
---------------------------------------------------------------------------

local function subtree_has_windows(node, buckets)
  if node.kind == "leaf" then
    -- A spacer is a fixed hole: it is never collapsed away.
    return node.spacer or buckets[node.name].reserved or #buckets[node.name] > 0
  end
  for _, child in ipairs(node.children) do
    if subtree_has_windows(child, buckets) then
      return true
    end
  end
  return false
end

local function node_size(node, overrides)
  if node.kind == "leaf" and overrides and overrides[node.name] then
    return overrides[node.name]
  end
  return node.size
end

-- Fills `out[slot] = box` for each leaf. `empty` is the inherited policy;
-- a container may override it for its own children and descendants.
local function walk(node, box, compiled, buckets, overrides, out, empty)
  if node.kind == "leaf" then
    out[node.name] = box
    return
  end
  empty = node.empty or empty
  local live = {}
  for _, child in ipairs(node.children) do
    if empty == "keep" or subtree_has_windows(child, buckets) then
      live[#live + 1] = child
    end
  end
  if #live == 0 then
    return
  end
  local total = 0
  for _, child in ipairs(live) do
    total = total + node_size(child, overrides)
  end
  local horizontal = node.kind == "h"
  local extent = horizontal and box.w or box.h
  local offset = 0
  for i, child in ipairs(live) do
    local share = node_size(child, overrides) / total
    local start = offset
    local length = extent * share
    if i == #live then
      length = extent - offset
    end
    local child_box
    if horizontal then
      child_box = { x = box.x + start, y = box.y, w = length, h = box.h }
    else
      child_box = { x = box.x, y = box.y + start, w = box.w, h = length }
    end
    walk(child, child_box, compiled, buckets, overrides, out, empty)
    offset = offset + length
  end
end

-- Shrink `box` to `aspect` (w/h) and/or `scale`, centered. Returns the
-- original box when neither is set.
local function fit_box(box, opts)
  if not opts or (not opts.aspect and not opts.scale) then
    return box
  end
  local w, h = box.w, box.h
  if opts.aspect then
    if w / h > opts.aspect then
      w = h * opts.aspect
    else
      h = w / opts.aspect
    end
  end
  if opts.scale then
    w = w * opts.scale
    h = h * opts.scale
  end
  return { x = box.x + (box.w - w) / 2, y = box.y + (box.h - h) / 2, w = w, h = h }
end

local function place_stack(targets, box, dir, jiggle)
  local n = #targets
  if jiggle then
    box = { x = box.x, y = box.y, w = math.max(1, box.w - 1), h = math.max(1, box.h - 1) }
  end
  for i, target in ipairs(targets) do
    local b
    if dir == "h" then
      local x = box.x + box.w * (i - 1) / n
      local w = (i == n) and (box.x + box.w - x) or (box.w / n)
      b = round_box(x, box.y, w, box.h)
    else
      local y = box.y + box.h * (i - 1) / n
      local h = (i == n) and (box.y + box.h - y) or (box.h / n)
      b = round_box(box.x, y, box.w, h)
    end
    target:place(b)
  end
end

-- Pure function: given compiled spec, ctx-like {area, targets}, and state,
-- returns { [slot] = box } and places every target. Used by both the live
-- provider and the test harness.
function M.recalculate(compiled, ctx, state)
  local targets = ctx.targets
  local n = #targets
  if n == 0 then
    return {}
  end
  local area = ctx.area
  -- Reservations are workspace-specific and contain only placement data.
  -- The external controller owns every process and network operation.
  local win = targets[1].window
  local workspace = win and win.workspace and tostring(win.workspace.id)
  local reserved = {}
  for name, owner in pairs(state and state.reservations and state.reservations[workspace] or {}) do reserved[name] = owner end
  for name in pairs(state and state.scene_empty and state.scene_empty[workspace] or {}) do reserved[name] = true end
  state = setmetatable({ reserved = reserved }, { __index = state or {} })
  local buckets = M.assign(compiled, targets, state)
  -- state.jiggle: true for every workspace on this layout, or a workspace
  -- id to jiggle only that workspace (looked up from the first window).
  local jiggle = state and state.jiggle
  if type(jiggle) == "number" then
    local w = targets[1].window
    local ws = w and w.workspace
    jiggle = ws ~= nil and ws.id == jiggle
  end
  state = state or { pins = {}, sizes = {} }
  local jstate = { pins = state.pins, sizes = state.sizes, jiggle = jiggle and true or false }
  if n == 1 and compiled.single == "collapse" and next(reserved) == nil then
    -- The lone window takes the whole area, but keeps its slot's shape.
    local slot
    for _, name in ipairs(compiled.leaves) do
      if #buckets[name] > 0 then
        slot = name
        break
      end
    end
    local full = fit_box({ x = area.x, y = area.y, w = area.w, h = area.h }, slot and compiled.leaf_opts[slot])
    local j = jstate.jiggle and 1 or 0
    targets[1]:place(round_box(full.x, full.y, full.w - j, full.h - j))
    return { ["*"] = full }, buckets
  end
  local boxes = {}
  walk(compiled.tree, { x = area.x, y = area.y, w = area.w, h = area.h }, compiled, buckets, jstate.sizes, boxes, compiled.empty)
  for _, name in ipairs(compiled.leaves) do
    local box = boxes[name]
    if box and #buckets[name] > 0 then
      local opts = compiled.leaf_opts[name]
      if opts.never_split then
        -- A never-split slot only holds more than one window when nothing
        -- else could take it; they overlap at the slot's full box (the
        -- focused one on top) rather than splitting it.
        local full = fit_box(box, opts)
        local j = jstate.jiggle and 1 or 0
        for _, target in ipairs(buckets[name]) do
          target:place(round_box(full.x, full.y, math.max(1, full.w - j), math.max(1, full.h - j)))
        end
      else
        place_stack(buckets[name], fit_box(box, opts), opts.stack or compiled.stack, jstate.jiggle)
      end
    end
  end
  return boxes, buckets
end

---------------------------------------------------------------------------
-- layout_msg: runtime commands. Messages are space-separated words:
--   pin <slot>        pin the active window to <slot>
--   unpin             remove the active window's pin
--   size <slot> <n>   set slot weight to n (absolute, > 0)
--   grow <slot> <d>   add d to slot weight (may be negative; floor 0.05)
--   reset             clear pins and size overrides
--   relayout          no-op; the compositor recalculates after any message
---------------------------------------------------------------------------

local function words(s)
  local out = {}
  for w in string.gmatch(s or "", "%S+") do
    out[#out + 1] = w
  end
  return out
end

function M.handle_msg(compiled, state, msg, active_window)
  local argv = words(msg)
  local cmd = argv[1]
  if cmd == "pin" then
    local slot = argv[2]
    if not compiled.leaf_set[slot] then
      return "unknown slot " .. tostring(slot)
    end
    if compiled.leaf_opts[slot].spacer then
      return "slot " .. slot .. " is a spacer"
    end
    local key = window_key(active_window)
    if not key then
      return "no active window"
    end
    state.pins[key] = slot
    if state.exclusive_pins then state.exclusive_pins[key] = nil end
    return true
  elseif cmd == "unpin" then
    local key = window_key(active_window)
    if key then
      state.pins[key] = nil
      if state.exclusive_pins then state.exclusive_pins[key] = nil end
    end
    return true
  elseif cmd == "size" or cmd == "grow" then
    local slot, val = argv[2], tonumber(argv[3])
    if not compiled.leaf_set[slot] or not val then
      return "usage: " .. cmd .. " <slot> <number>"
    end
    if cmd == "size" and val <= 0 then
      return "size must be > 0"
    end
    local cur = state.sizes[slot] or compiled.leaf_opts[slot].size
    state.sizes[slot] = (cmd == "size") and val or math.max(0.05, cur + val)
    return true
  elseif cmd == "reset" then
    state.pins = {}
    state.exclusive_pins = {}
    state.sizes = {}
    return true
  elseif cmd == "relayout" then
    return true
  end
  return "unknown command " .. tostring(cmd)
end

---------------------------------------------------------------------------
-- Provider factory and registration.
---------------------------------------------------------------------------

-- The live record per layout name. The provider closures read the compiled
-- spec through it, so calling M.layout again with the same name swaps the
-- spec in place (Hyprland refuses to register a name twice, and a running
-- editor needs to preview edits without a reload).
M.live = {}

function M.provider(name, spec)
  local compiled = M.compile(spec)
  local state = M.state[name] or { pins = {}, sizes = {} }
  M.state[name] = state
  local live = M.live[name] or {}
  live.compiled = compiled
  live.spec = spec
  live.state = state
  live.orders = live.orders or {}
  M.live[name] = live
  return {
    recalculate = function(ctx)
      -- Keep only addresses, never compositor-owned targets/userdata. Session
      -- recovery needs the compositor's order (which changes on swaps).
      local order, workspace = {}, nil
      for _, target in ipairs(ctx.targets) do
        local win = target.window
        if win and win.workspace then
          workspace = tostring(win.workspace.id)
          order[#order + 1] = window_key(win)
        end
      end
      if workspace then live.orders[workspace] = order end
      local ok, err = pcall(M.recalculate, live.compiled, ctx, live.state)
      if not ok then
        print("hypertile[" .. name .. "]: " .. tostring(err))
      end
    end,
    -- Hyprland recalculates the workspace right after layout_msg returns, so
    -- state changes take effect on their own. A returned string surfaces as
    -- a dispatcher error to the caller.
    layout_msg = function(_, msg)
      local active = (hl and hl.get_active_window) and hl.get_active_window() or nil
      return M.handle_msg(live.compiled, live.state, msg, active)
    end,
  }, compiled, state
end

local function is_registered(name)
  for _, n in ipairs(M.registered) do
    if n == name then
      return true
    end
  end
  return false
end

-- Register under Hyprland's Lua layout namespace, or hot-swap the spec if
-- the name is already registered. Workspace rules refer to it as
-- "lua:<name>". Returns compiled, state, and whether this was a swap.
function M.layout(name, spec)
  local provider, compiled, state = M.provider(name, spec)
  if is_registered(name) then
    return compiled, state, true
  end
  assert(hl and hl.layout and hl.layout.register, "hypertile.layout needs the Hyprland `hl` global")
  hl.layout.register(name, provider)
  M.registered[#M.registered + 1] = name
  return compiled, state, false
end

return M
