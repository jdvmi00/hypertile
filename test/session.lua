-- Compositor adapter for session recovery, against a fake `hl` whose swaps
-- take effect in the compositor but never refresh the engine's order cache
-- (the asynchronous case the adapter must not depend on).
package.path = "./?.lua;" .. package.path

local order = { "a", "b", "c", "d" }
local dispatched = {}
local windows = {}
for _, address in ipairs(order) do
  windows[#windows + 1] = { address = address, workspace = { id = 1, name = "1", tiled_layout = "lua:test" }, mapped = true, at = { x = 0, y = 0 }, size = { x = 1, y = 1 } }
end
local engine = {
  live = { test = { orders = { ["1"] = { "a", "b", "c", "d" }, ["7"] = { "gone" } }, spec = { name = "live" }, state = { pins = {}, sizes = {} } } },
  state = { test = { pins = {}, sizes = {} } },
  registered = {},
}
function engine.layout(name, spec)
  engine.registered[#engine.registered + 1] = name
  engine.live[name] = { orders = {}, spec = spec, state = { pins = {}, sizes = {} } }
  engine.state[name] = engine.live[name].state
end
local rules = {}
package.loaded["hypertile"] = engine
package.loaded["hypertile-bridge"] = {
  rule_source = function(layout, workspace, spec)
    rules[#rules + 1] = { layout = layout, workspace = workspace, spec = spec }
    return "return true"
  end,
}
local function tag(kind)
  return function(args) args.kind = kind; return args end
end
hl = {
  get_monitors = function() return { { name = "DP-1", x = 0, y = 0 } } end,
  get_windows = function() return windows end,
  get_workspaces = function() return { { id = 1, name = "1", tiled_layout = "lua:test", monitor = { name = "DP-1" }, visible = true } } end,
  get_active_window = function() return windows[1] end,
  get_active_workspace = function() return { id = 1, name = "1" } end,
  dsp = {
    window = { resize = tag("resize"), swap = tag("swap"), move = tag("move"), float = tag("float"), pin = tag("pin"), fullscreen_state = tag("fullscreen") },
    workspace = { move = tag("workspace") },
    focus = tag("focus"),
  },
  dispatch = function(args)
    dispatched[#dispatched + 1] = args
    if args.kind == "swap" then
      local a, b = args.window:sub(9), args.target:sub(9)
      local ia, ib
      for i, address in ipairs(order) do
        if address == a then ia = i end
        if address == b then ib = i end
      end
      assert(ia and ib, "swap names live windows")
      order[ia], order[ib] = order[ib], order[ia]
      -- Deliberately no recalculation: engine.live.test.orders stays stale.
    end
  end,
}

local session = require("hypertile-session")

-- Order restoration: saved order o1..o4 maps to live c, a, d, b.
local snapshot = {
  workspaces = { { selector = "1", layout = "lua:test", order = { "o1", "o2", "o3", "o4" }, monitor = "DP-1", visible = true } },
  windows = {}, layouts = {}, active = nil, workspace = "1",
}
local result = session.finish({ snapshot = snapshot, matches = { o1 = "c", o2 = "a", o3 = "d", o4 = "b" } })
assert(table.concat(order, ",") == "c,a,d,b", "order restored without relying on recalculation: " .. table.concat(order, ","))
assert(#result.warnings == 0, "no warnings")
local swaps = 0
for _, args in ipairs(dispatched) do if args.kind == "swap" then swaps = swaps + 1 end end
assert(swaps <= 3, "at most n-1 swaps")

-- A stale cache (a matched window missing from it) skips reordering and says so.
dispatched = {}
engine.live.test.orders["1"] = { "a", "b", "c" }
result = session.finish({ snapshot = snapshot, matches = { o1 = "c", o2 = "a", o3 = "d", o4 = "b" } })
assert(#result.warnings == 1 and result.warnings[1]:find("order cache is stale", 1, true), "stale cache reported")
for _, args in ipairs(dispatched) do assert(args.kind ~= "swap", "no swaps from a stale cache") end

-- prepare: a registered layout keeps its live spec; a missing one is re-registered from the snapshot.
session.prepare({
  layouts = { test = { spec = { name = "saved" }, sizes = { s = 1 } }, old = { spec = { name = "old" }, sizes = {} } },
  workspaces = { { selector = "1", layout = "lua:test" }, { selector = "2", layout = "lua:old" }, { selector = "3", layout = "dwindle" } },
})
assert(#engine.registered == 1 and engine.registered[1] == "old", "only the missing layout is registered")
assert(engine.live.test.spec.name == "live", "existing layout keeps its current definition")
assert(engine.state.test.sizes.s == 1, "saved sizes restored")
assert(rules[1].spec.name == "live" and rules[2].spec.name == "old" and rules[3].spec == nil, "rules use the live spec when there is one")

-- snapshot prunes cached orders for workspaces that no longer exist.
engine.live.test.orders["1"] = { "a", "b", "c", "d" }
local snap = session.snapshot()
assert(engine.live.test.orders["7"] == nil and engine.live.test.orders["1"], "stale workspace order pruned")
assert(#snap.workspaces == 1 and table.concat(snap.workspaces[1].order, ",") == "a,b,c,d", "snapshot order follows the engine cache")

print("session adapter: all checks passed")
