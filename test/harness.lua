-- Pure-Lua test harness for hypertile. Run: lua test/harness.lua
-- Builds fake layout contexts, runs providers, and checks the boxes.

package.path = "./?.lua;" .. package.path
local hypertile = require("hypertile")

local failures, checks = 0, 0

local function check(cond, msg)
  checks = checks + 1
  if not cond then
    failures = failures + 1
    print("FAIL: " .. msg)
  end
end

local function fmt_box(b)
  return string.format("(%d,%d %dx%d)", b.x, b.y, b.w, b.h)
end

-- Build a ctx with n targets. `wins` optionally supplies window fields per index.
local function make_ctx(n, wins, area)
  area = area or { x = 0, y = 0, w = 6144, h = 2560 }
  local ctx = { area = area, targets = {}, placed = {} }
  for i = 1, n do
    local win = wins and wins[i] or { class = "w" .. i, title = "t" .. i, address = "0x" .. i }
    win.address = win.address or ("0x" .. i)
    local target = { index = i, window = win, box = { x = 0, y = 0, w = 0, h = 0 } }
    function target:place(box)
      self.box = box
      ctx.placed[self.index] = box
    end
    target.set_box = target.place
    ctx.targets[i] = target
  end
  return ctx
end

-- Capture the provider registered by an existing hl.layout.register-style file.
local function load_legacy_provider(path)
  local captured
  _G.hl = { layout = { register = function(_, provider) captured = provider end } }
  dofile(path)
  _G.hl = nil
  return captured
end

local function same_box(a, b)
  return a and b and a.x == b.x and a.y == b.y and a.w == b.w and a.h == b.h
end

-- Legacy rounds each stack item's height independently; hypertile rounds
-- edges so stacked items never leave a 1px seam. Allow 1px on w/h only.
local function near_box(a, b)
  return a and b and a.x == b.x and a.y == b.y and math.abs(a.w - b.w) <= 1 and math.abs(a.h - b.h) <= 1
end

---------------------------------------------------------------------------
-- 1. Equivalence with the hand-written 20/60/20 ultrawide layout.
---------------------------------------------------------------------------
local legacy = load_legacy_provider("test/fixtures/legacy-ultrawide.lua")
check(legacy ~= nil, "loaded legacy ultrawide provider")

local ultrawide = hypertile.compile({
  columns = {
    { name = "left", w = 0.2 },
    { name = "center", w = 0.6 },
    { name = "right", w = 0.2 },
  },
  fill = { "center", "right", "left" },
  cycle = { "right", "left", "center" },
  empty = "keep",
  single = "slot",
})

for n = 1, 9 do
  local a = make_ctx(n)
  local b = make_ctx(n)
  legacy.recalculate(a)
  hypertile.recalculate(ultrawide, b, { pins = {}, sizes = {} })
  for i = 1, n do
    check(
      near_box(a.placed[i], b.placed[i]),
      string.format("n=%d target %d legacy %s vs hypertile %s", n, i,
        a.placed[i] and fmt_box(a.placed[i]) or "nil",
        b.placed[i] and fmt_box(b.placed[i]) or "nil")
    )
  end
end
print(string.format("equivalence: %d windows checked against legacy layout", 9))

---------------------------------------------------------------------------
-- 2. Collapse: empty columns are absorbed.
---------------------------------------------------------------------------
local collapsing = hypertile.compile({
  columns = {
    { name = "left", w = 0.2 },
    { name = "center", w = 0.6 },
    { name = "right", w = 0.2 },
  },
  fill = { "center", "right", "left" },
  empty = "collapse",
})
do
  local ctx = make_ctx(1)
  hypertile.recalculate(collapsing, ctx, { pins = {}, sizes = {} })
  check(same_box(ctx.placed[1], { x = 0, y = 0, w = 6144, h = 2560 }), "single window fills area under collapse: " .. fmt_box(ctx.placed[1]))

  ctx = make_ctx(2)
  hypertile.recalculate(collapsing, ctx, { pins = {}, sizes = {} })
  -- center 0.6 + right 0.2 renormalize to 0.75 / 0.25
  check(same_box(ctx.placed[1], { x = 0, y = 0, w = 4608, h = 2560 }), "two windows: center renormalized to 75%: " .. fmt_box(ctx.placed[1]))
  check(same_box(ctx.placed[2], { x = 4608, y = 0, w = 1536, h = 2560 }), "two windows: right renormalized to 25%: " .. fmt_box(ctx.placed[2]))
end

---------------------------------------------------------------------------
-- 3. Rules route windows by class; capacity spills over.
---------------------------------------------------------------------------
local ruled = hypertile.compile({
  columns = {
    { name = "left", w = 1 },
    { name = "center", w = 3 },
    { name = "right", w = 1 },
  },
  fill = { "center", "right", "left" },
  rules = {
    { class = "^chromium$", slot = "center" },
    { class = "ghostty", slot = "right" },
  },
  capacity = { right = 2 },
  empty = "keep",
})
do
  local ctx = make_ctx(5, {
    { class = "com.mitchellh.ghostty" },
    { class = "com.mitchellh.ghostty" },
    { class = "com.mitchellh.ghostty" }, -- over capacity: falls to fill order
    { class = "chromium" },
    { class = "other" },
  })
  local boxes, buckets = hypertile.recalculate(ruled, ctx, { pins = {}, sizes = {} })
  check(#buckets.right == 2, "capacity limits right column to 2, got " .. #buckets.right)
  check(buckets.right[1].index == 1 and buckets.right[2].index == 2, "first two ghostty windows land in right")
  -- Unassigned: ghostty#3 -> center (fill 1); other -> right is full -> left (fill 3).
  check(#buckets.center == 2, "center gets overflow ghostty + chromium, got " .. #buckets.center)
  check(buckets.center[1].index == 3 and buckets.center[2].index == 4, "center keeps window order (3 then 4)")
  check(#buckets.left == 1 and buckets.left[1].index == 5, "other skips the full right column and lands in left")
  check(boxes.left ~= nil and boxes.center ~= nil and boxes.right ~= nil, "all three slots have boxes under empty=keep")
  -- Stacking: two windows in center, vertical halves.
  check(ctx.placed[3].h == 1280 and ctx.placed[4].y == 1280, "center stack splits into halves: " .. fmt_box(ctx.placed[3]) .. " " .. fmt_box(ctx.placed[4]))
end

---------------------------------------------------------------------------
-- 4. Nested rows inside a column, with weights.
---------------------------------------------------------------------------
local nested = hypertile.compile({
  columns = {
    { name = "main", w = 2 },
    { w = 1, rows = { { name = "top", h = 1 }, { name = "bottom", h = 2 } } },
  },
  fill = { "main", "top", "bottom" },
  empty = "keep",
})
do
  local ctx = make_ctx(3, nil, { x = 100, y = 50, w = 3000, h = 900 })
  hypertile.recalculate(nested, ctx, { pins = {}, sizes = {} })
  check(same_box(ctx.placed[1], { x = 100, y = 50, w = 2000, h = 900 }), "main takes 2/3 width: " .. fmt_box(ctx.placed[1]))
  check(same_box(ctx.placed[2], { x = 2100, y = 50, w = 1000, h = 300 }), "top takes 1/3 height: " .. fmt_box(ctx.placed[2]))
  check(same_box(ctx.placed[3], { x = 2100, y = 350, w = 1000, h = 600 }), "bottom takes 2/3 height: " .. fmt_box(ctx.placed[3]))
end

---------------------------------------------------------------------------
-- 5. layout_msg: pin and size overrides change placement.
---------------------------------------------------------------------------
do
  local state = { pins = {}, sizes = {} }
  local ctx = make_ctx(3)
  local active = ctx.targets[3].window -- would normally go to "left"
  local r = hypertile.handle_msg(ultrawide, state, "pin center", active)
  check(r == true, "pin returns true")
  local _, buckets = hypertile.recalculate(ultrawide, ctx, state)
  check(#buckets.center == 2 and buckets.center[1].index == 1 and buckets.center[2].index == 3, "pinned window joins center in window order")
  check(#buckets.left == 0, "left is empty after pin")

  r = hypertile.handle_msg(ultrawide, state, "size center 0.8", active)
  check(r == true, "size returns true")
  hypertile.recalculate(ultrawide, ctx, state)
  -- weights: left 0.2, center 0.8, right 0.2 -> center = 0.8/1.2 of width
  local expect_w = math.floor(0.2 / 1.2 * 6144 + 0.8 / 1.2 * 6144 + 0.5) - math.floor(0.2 / 1.2 * 6144 + 0.5)
  check(ctx.placed[1].w == expect_w, string.format("center width after size override: got %d want %d", ctx.placed[1].w, expect_w))

  r = hypertile.handle_msg(ultrawide, state, "pin nowhere", active)
  check(type(r) == "string", "unknown slot reports an error string: " .. tostring(r))
  r = hypertile.handle_msg(ultrawide, state, "reset", active)
  check(r == true and next(state.pins) == nil and next(state.sizes) == nil, "reset clears state")
end

---------------------------------------------------------------------------
-- 6. grow is relative to the spec weight; tag rules accept Hyprland's "*" suffix.
---------------------------------------------------------------------------
do
  local state = { pins = {}, sizes = {} }
  hypertile.handle_msg(ultrawide, state, "grow center 0.2", nil)
  check(math.abs(state.sizes.center - 0.8) < 1e-9, "grow adds to the spec weight (0.6 + 0.2)")
  local tagged = hypertile.compile({
    columns = { { name = "a" }, { name = "b" } },
    fill = { "a", "b" },
    rules = { { tag = "terminal", slot = "b" } },
    empty = "keep",
  })
  local ctx = make_ctx(2, { { class = "x", tags = { "default-opacity*", "terminal*" } }, { class = "y", tags = {} } })
  local _, buckets = hypertile.recalculate(tagged, ctx, state)
  check(#buckets.b == 1 and buckets.b[1].index == 1, "tag rule matches 'terminal*' as reported by Hyprland")
  check(#buckets.a == 1 and buckets.a[1].index == 2, "untagged window follows fill order")
end

---------------------------------------------------------------------------
-- 7. Quad center: fixed quadrants, nothing collapses.
-- Fill order: tl tr bl br right right left left.
---------------------------------------------------------------------------
local quad = hypertile.compile({
  columns = {
    { name = "left", w = 0.2 },
    { w = 0.6, rows = {
      { columns = { { name = "tl" }, { name = "tr" } } },
      { columns = { { name = "bl" }, { name = "br" } } },
    } },
    { name = "right", w = 0.2 },
  },
  fill = { "tl", "tr", "bl", "br", "right", "right", "left", "left" },
  empty = "keep",
  single = "slot",
})
do
  local W, H = 6144, 2560
  local cx = math.floor(W * 0.2 + 0.5)
  local cw = math.floor(W * 0.8 + 0.5) - cx
  local qw = math.floor(cx + cw / 2 + 0.5) - cx
  local TL = { x = cx, y = 0, w = qw, h = H / 2 }
  local TR = { x = cx + qw, y = 0, w = cw - qw, h = H / 2 }
  local BL = { x = cx, y = H / 2, w = qw, h = H / 2 }
  local BR = { x = cx + qw, y = H / 2, w = cw - qw, h = H / 2 }
  local s = { pins = {}, sizes = {} }
  for n = 1, 4 do
    local ctx = make_ctx(n)
    hypertile.recalculate(quad, ctx, s)
    local want = { TL, TR, BL, BR }
    for i = 1, n do
      check(same_box(ctx.placed[i], want[i]), string.format("quad n=%d window %d stays in its quadrant: %s", n, i, fmt_box(ctx.placed[i])))
    end
  end

  local ctx = make_ctx(8)
  local _, buckets = hypertile.recalculate(quad, ctx, s)
  check(buckets.right[1].index == 5 and buckets.right[2].index == 6, "quad: 5 and 6 stack in right")
  check(buckets.left[1].index == 7 and buckets.left[2].index == 8, "quad: 7 and 8 stack in left")
  check(ctx.placed[5].x == cx + cw and ctx.placed[5].h == H / 2 and ctx.placed[6].y == H / 2, "quad: right stack halves: " .. fmt_box(ctx.placed[5]) .. " " .. fmt_box(ctx.placed[6]))
  check(ctx.placed[7].x == 0 and ctx.placed[8].y == H / 2, "quad: left stack halves: " .. fmt_box(ctx.placed[7]) .. " " .. fmt_box(ctx.placed[8]))

  ctx = make_ctx(9)
  _, buckets = hypertile.recalculate(quad, ctx, s)
  check(#buckets.tl == 2 and buckets.tl[2].index == 9, "quad: 9th window cycles back to tl and stacks")
end

---------------------------------------------------------------------------
-- 8. Hot swap: registering a name again swaps the spec inside the live provider.
---------------------------------------------------------------------------
do
  local registered = {}
  _G.hl = { layout = { register = function(name, provider) registered[name] = provider end } }
  hypertile.registered = {}
  local two = { columns = { { name = "a" }, { name = "b" } }, fill = { "a", "b" }, empty = "keep", single = "slot" }
  local three = { columns = { { name = "a" }, { name = "b" }, { name = "c" } }, fill = { "a", "b", "c" }, empty = "keep", single = "slot" }
  local _, _, swapped = hypertile.layout("swap", two)
  check(swapped == false and registered.swap ~= nil, "first registration registers with the compositor")
  local ctx = make_ctx(1)
  registered.swap.recalculate(ctx)
  check(ctx.placed[1].w == 3072, "provider uses the first spec (half width): " .. fmt_box(ctx.placed[1]))
  local count = 0
  _G.hl.layout.register = function() count = count + 1 end
  _, _, swapped = hypertile.layout("swap", three)
  check(swapped == true and count == 0, "second registration swaps without calling the compositor")
  ctx = make_ctx(1)
  registered.swap.recalculate(ctx)
  check(ctx.placed[1].w == 2048, "same provider now places with the new spec (third width): " .. fmt_box(ctx.placed[1]))
  check(#hypertile.names() == 1 and hypertile.names()[1] == "swap", "names() lists the layout once")
  _G.hl = nil
end

---------------------------------------------------------------------------
-- 9. Aspect, scale, spacers, per-slot stack.
---------------------------------------------------------------------------
do
  -- A square in the middle of the screen: one slot, aspect 1, scale 0.7.
  local square = hypertile.compile({ name = "main", aspect = 1, scale = 0.7, single = "slot" })
  local ctx = make_ctx(1)
  hypertile.recalculate(square, ctx, { pins = {}, sizes = {} })
  local b = ctx.placed[1]
  check(b.w == b.h and b.w == 1792, "square: 70% of the 2560 height, square: " .. fmt_box(b))
  check(b.x == math.floor((6144 - 1792) / 2 + 0.5) and b.y == math.floor((2560 - 1792) / 2 + 0.5), "square: centered: " .. fmt_box(b))

  -- With single = "collapse" the lone window still keeps its slot's shape.
  local square2 = hypertile.compile({ name = "main", aspect = 1, scale = 0.7 })
  ctx = make_ctx(1)
  hypertile.recalculate(square2, ctx, { pins = {}, sizes = {} })
  check(ctx.placed[1].w == 1792 and ctx.placed[1].h == 1792, "single=collapse still applies aspect/scale: " .. fmt_box(ctx.placed[1]))

  -- Aspect inside a tall slot fits the width instead.
  local tall = hypertile.compile({ columns = { { name = "a", aspect = 16 / 9 }, { name = "b" } }, empty = "keep", single = "slot" })
  ctx = make_ctx(2)
  hypertile.recalculate(tall, ctx, { pins = {}, sizes = {} })
  local a = ctx.placed[1]
  check(a.w == 3072 and math.abs(a.h - 3072 * 9 / 16) <= 1 and a.y > 0, "16:9 in a 3072x2560 slot fits the width: " .. fmt_box(a))

  -- Spacers: never take windows, never collapse, excluded from default fill.
  local hole = hypertile.compile({
    columns = {
      { name = "pad-l", w = 1, spacer = true },
      { name = "main", w = 2 },
      { name = "pad-r", w = 1, spacer = true },
    },
    empty = "collapse",
    single = "slot",
  })
  check(#hole.fill == 1 and hole.fill[1] == "main", "default fill skips spacers: " .. table.concat(hole.fill, ","))
  ctx = make_ctx(3)
  local _, buckets = hypertile.recalculate(hole, ctx, { pins = {}, sizes = {} })
  check(#buckets.main == 3 and #buckets["pad-l"] == 0, "all windows stack in main, spacers stay empty")
  check(ctx.placed[1].x == 1536 and ctx.placed[1].w == 3072, "spacers keep their space under empty=collapse: " .. fmt_box(ctx.placed[1]))
  local state = { pins = { ["0x1"] = "pad-l" }, sizes = {} }
  _, buckets = hypertile.recalculate(hole, ctx, state)
  check(#buckets["pad-l"] == 0, "a pin to a spacer is ignored")

  local ok, err = pcall(hypertile.compile, { columns = { { name = "a", spacer = true }, { name = "b" } }, fill = { "a" } })
  check(not ok and tostring(err):find("spacer"), "fill may not reference a spacer: " .. tostring(err))
  ok, err = pcall(hypertile.compile, { columns = { { name = "a", spacer = true }, { name = "b", spacer = true } } })
  check(not ok and tostring(err):find("every slot is a spacer"), "all-spacer layouts rejected")
  ok, err = pcall(hypertile.compile, { name = "a", scale = 2 })
  check(not ok and tostring(err):find("scale"), "scale > 1 rejected")
  ok, err = pcall(hypertile.compile, { name = "a", gaps = { inner = -1 } })
  check(not ok and tostring(err):find("gaps"), "negative gap rejected")
  local g = hypertile.compile({ name = "a", gaps = { inner = 0, outer = 12 }, border = 0 })
  check(g.gaps.outer == 12 and g.border == 0, "gaps and border carried on the compiled spec")
  check(hypertile.compile({ name = "a", rounding = 12 }).rounding == 12, "rounding carried on the compiled spec")
  ok, err = pcall(hypertile.compile, { name = "a", rounding = 21 })
  check(not ok and tostring(err):find("rounding"), "rounding above 20 rejected")

  -- Per-slot stack direction.
  local hstack = hypertile.compile({ columns = { { name = "a", stack = "h" }, { name = "b" } }, fill = { "a", "a" }, empty = "keep", single = "slot" })
  ctx = make_ctx(2)
  hypertile.recalculate(hstack, ctx, { pins = {}, sizes = {} })
  check(ctx.placed[1].w == 1536 and ctx.placed[2].x == 1536 and ctx.placed[1].h == 2560, "stack = h splits the slot side by side: " .. fmt_box(ctx.placed[1]) .. " " .. fmt_box(ctx.placed[2]))
end

---------------------------------------------------------------------------
-- 10. Rules follow the numbering: an app allowed in several zones fills
-- them lowest number first, whatever order the rules were written in.
---------------------------------------------------------------------------
do
  local spec = hypertile.compile({
    columns = { { name = "a" }, { name = "b" }, { name = "c" }, { name = "d" }, { name = "e" } },
    fill = { "a", "b", "c", "d", "e" },          -- a=1 b=2 c=3 d=4 e=5
    rules = {
      { class = "term", slot = "d" },            -- rules deliberately out of numbering order
      { class = "term", slot = "b" },
      { class = "term", slot = "e" },
      { class = "term", slot = "c" },
      { class = "web", slot = "a" },
    },
    capacity = { b = 1, c = 1, d = 1, e = 1 },
    empty = "keep", single = "slot",
  })
  local classes = { "web", "term", "term", "term", "term", "term", "other" }
  local ctx = make_ctx(#classes, (function()
    local w = {}
    for i, c in ipairs(classes) do w[i] = { class = c } end
    return w
  end)())
  local _, buckets = hypertile.recalculate(spec, ctx, { pins = {}, sizes = {} })
  local function slot_of(i)
    for name, list in pairs(buckets) do
      for _, t in ipairs(list) do
        if t.index == i then return name end
      end
    end
  end
  check(slot_of(1) == "a", "web -> a")
  check(slot_of(2) == "b" and slot_of(3) == "c" and slot_of(4) == "d" and slot_of(5) == "e",
    "terms fill b, c, d, e in numbering order: " .. table.concat({ slot_of(2), slot_of(3), slot_of(4), slot_of(5) }, ","))
  check(slot_of(6) == "a", "a sixth term with every rule slot full falls back to the fill order (a has no capacity)")
  check(slot_of(7) == "a", "an unrelated window follows the fill order too")
end

---------------------------------------------------------------------------
-- 11. never_split: one window, never an overflow target.
---------------------------------------------------------------------------
do
  local spec = hypertile.compile({
    columns = { { name = "main", never_split = true }, { name = "side" } },
    fill = { "main", "side" },
    capacity = { side = 1 },
    empty = "keep", single = "slot",
  })
  local ctx = make_ctx(4)
  local _, buckets = hypertile.recalculate(spec, ctx, { pins = {}, sizes = {} })
  check(#buckets.main == 1 and buckets.main[1].index == 1, "never_split zone keeps exactly its first window")
  check(#buckets.side == 3, "overflow stacks in the other zone even past its capacity, never in main: side=" .. #buckets.side)

  -- With a rule pointing at it, a second matching window goes elsewhere.
  local ruled = hypertile.compile({
    columns = { { name = "main", never_split = true }, { name = "side" } },
    fill = { "side", "main" },
    rules = { { class = "web", slot = "main" } },
    empty = "keep", single = "slot",
  })
  ctx = make_ctx(2, { { class = "web" }, { class = "web" } })
  _, buckets = hypertile.recalculate(ruled, ctx, { pins = {}, sizes = {} })
  check(#buckets.main == 1 and #buckets.side == 1, "second ruled window skips the full never_split zone")

  -- If everything is never_split, the last one still has to take it.
  local all = hypertile.compile({ columns = { { name = "a", never_split = true }, { name = "b", never_split = true } }, empty = "keep", single = "slot" })
  ctx = make_ctx(3)
  _, buckets = hypertile.recalculate(all, ctx, { pins = {}, sizes = {} })
  check(#buckets.a + #buckets.b == 3, "every window is still placed when all zones are never_split")
  -- The overflow window overlaps the slot at full size; the slot is not split.
  local lone = hypertile.compile({ name = "main", never_split = true, aspect = 1.5, scale = 0.5, fill = { "main" }, empty = "keep", single = "slot" })
  local lctx = make_ctx(3)
  hypertile.recalculate(lone, lctx, { pins = {}, sizes = {} })
  check(same_box(lctx.placed[1], lctx.placed[2]) and same_box(lctx.placed[2], lctx.placed[3]), "windows overflowing a lone never_split zone overlap it at full size: " .. fmt_box(lctx.placed[1]) .. " " .. fmt_box(lctx.placed[2]))
  check(lctx.placed[1].w == 1920 and lctx.placed[1].h == 1280, "and that box is the fitted one: " .. fmt_box(lctx.placed[1]))
end

---------------------------------------------------------------------------
-- 12. state.jiggle (used by `hypertile-ctl heal`): one pixel smaller while
-- set, exact again when cleared.
---------------------------------------------------------------------------
do
  local state = { pins = {}, sizes = {} }
  local ctx = make_ctx(3)
  hypertile.recalculate(ultrawide, ctx, state)
  local before = ctx.placed[1]
  local center_w, center_h = before.w, before.h
  state.jiggle = true
  hypertile.recalculate(ultrawide, ctx, state)
  check(ctx.placed[1].w == center_w - 1 and ctx.placed[1].h == center_h - 1, "jiggle shrinks each box by 1px: " .. fmt_box(ctx.placed[1]))
  state.jiggle = false
  hypertile.recalculate(ultrawide, ctx, state)
  check(same_box(ctx.placed[1], before), "clearing jiggle restores the exact box")
  local one = make_ctx(1)
  hypertile.recalculate(hypertile.compile({ name = "a" }), one, { pins = {}, sizes = {}, jiggle = true })
  check(one.placed[1].w == 6143 and one.placed[1].h == 2559, "jiggle applies to the lone-window path too")
  -- Scoped to a workspace id: only windows on that workspace shrink.
  local scoped = { pins = {}, sizes = {}, jiggle = 8 }
  local on8 = make_ctx(2, { { workspace = { id = 8 } }, { workspace = { id = 8 } } })
  hypertile.recalculate(ultrawide, on8, scoped)
  check(on8.placed[1].w == center_w - 1, "jiggle scoped to workspace 8 shrinks windows on workspace 8")
  local on2 = make_ctx(2, { { workspace = { id = 2 } }, { workspace = { id = 2 } } })
  hypertile.recalculate(ultrawide, on2, scoped)
  check(on2.placed[1].w == center_w, "jiggle scoped to workspace 8 leaves workspace 2 alone")
end

---------------------------------------------------------------------------
-- 13. Spec validation.
---------------------------------------------------------------------------
do
  local function rejects(spec, pattern, label)
    local ok, err = pcall(hypertile.compile, spec)
    check(not ok and tostring(err):find(pattern, 1, true), label .. ": " .. tostring(err))
  end
  rejects({ columns = { { name = "a" }, { name = "a" } } }, "duplicate", "duplicate slot names rejected")
  rejects({ columns = { { name = "a" } }, fill = { "b" } }, "unknown slot", "fill with unknown slot rejected")
  rejects({ columns = { { name = "a" } }, fill = {} }, "fill must name", "an empty fill list is rejected")
  rejects({ columns = { { name = "a" } }, cycle = {} }, "cycle must name", "an empty cycle list is rejected")
  rejects({ columns = { { name = "a", w = 0 }, { name = "b" } } }, "size must be", "a zero weight is rejected")
  rejects({ columns = { { name = "a", w = -1 }, { name = "b" } } }, "size must be", "a negative weight is rejected")
  rejects({ columns = { { name = "a" } }, empty = "bogus" }, "empty must be one of", "an unknown empty policy is rejected")
  rejects({ columns = { { name = "a", empty = "bogus", rows = { { name = "b" } } } } }, "empty", "an unknown per-node empty policy is rejected")
  rejects({ columns = { { name = "a" } }, single = "bogus" }, "single must be one of", "an unknown single policy is rejected")
  rejects({ columns = { { name = "a", stack = "x" } } }, "stack on slot a", "an unknown per-slot stack direction is rejected")
  rejects({ columns = { { name = "a" } }, capacity = { nope = 1 } }, "capacity references unknown slot", "capacity on an unknown slot is rejected")
  rejects({ columns = { { name = "a" }, { name = "gap", spacer = true } }, capacity = { gap = 1 } }, "spacer slot", "capacity on a spacer is rejected")

  -- Runtime messages reject what compile cannot see.
  local spec = hypertile.compile({ columns = { { name = "a" }, { name = "gap", spacer = true } } })
  local state = { pins = {}, sizes = {} }
  local win = { address = "0x1" }
  check(hypertile.handle_msg(spec, state, "pin gap", win) == "slot gap is a spacer", "pinning a spacer is refused")
  check(hypertile.handle_msg(spec, state, "size a 0", win) == "size must be > 0", "a zero size override is refused")
  check(hypertile.handle_msg(spec, state, "size a -2", win) == "size must be > 0", "a negative size override is refused")
  check(type(hypertile.handle_msg(spec, state, "bogus", win)) == "string", "an unknown message reports an error string")
end

print(string.format("%d checks, %d failures", checks, failures))
os.exit(failures == 0 and 0 or 1)
