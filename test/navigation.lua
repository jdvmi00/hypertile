package.path = "./?.lua;" .. package.path
local nav = require("hypertile-navigation")
local function window(address, x, y, w, h, extra)
  local result = { address = address, at = { x = x, y = y }, size = { x = w, y = h }, workspace = { id = 1 }, fullscreen = 0 }
  for k, v in pairs(extra or {}) do result[k] = v end
  return result
end
local a = window("a", 3494, 42, 2218, 1246)
local left = window("left", 432, 42, 2218, 1246)
local down = window("down", 3494, 1302, 1102, 1246)
local diagonal = window("diagonal", 4610, 1302, 1102, 1246)
assert(nav.neighbor(a, { a, left, down, diagonal }, "l") == left, "cross 844px gap")
assert(nav.neighbor(left, { a, left }, "r") == a, "reverse direction")
assert(nav.neighbor(a, { down, diagonal }, "d") == diagonal, "prefer center alignment")
assert(nav.neighbor(down, { a, left }, "u") == a, "up")
assert(nav.neighbor(a, { left }, "r") == nil, "no wrapping")
assert(nav.neighbor(a, { diagonal }, "r") == diagonal, "diagonal fallback")
for _, extra in ipairs({ { floating = true }, { hidden = true }, { mapped = false }, { fullscreen = 2 }, { workspace = { id = 2 } } }) do
  assert(nav.neighbor(a, { window("excluded", 432, 42, 2218, 1246, extra) }, "l") == nil, "exclude unavailable windows")
end
local dispatched
hl = {
  get_active_window = function() return a end,
  get_windows = function() return { a, left } end,
  dsp = { window = { swap = function(args) return args end }, focus = function(args) args.focus = true; return args end },
  dispatch = function(args) dispatched = args end,
}
package.loaded["hypr.hypertile"] = { live = { test = {} } }
local routed
package.loaded["hypr.hypertile-session"] = { navigation_slots = function() end, swap = function(first, second)
  if routed then routed.first, routed.second = first, second; return true end
  return false
end }
a.workspace.tiled_layout = "lua:test"
nav.swap("l")
assert(dispatched.target == "address:left", "swap by address")
dispatched, routed = nil, {}
nav.swap("l")
assert(routed.first == a and routed.second == left and not dispatched, "managed swap bypasses native reorder")
routed = nil
dispatched = nil
nav.swap("u")
assert(dispatched == nil, "no neighbor does nothing")
nav.focus("l")
assert(dispatched.focus and dispatched.window == "address:left", "focus same neighbor by address")
dispatched = nil
nav.focus("u")
assert(dispatched == nil, "focus does not wrap")
a.workspace.tiled_layout = "dwindle"
nav.swap("l")
assert(dispatched.direction == "l", "standard layouts use stock swap")
nav.focus("r")
assert(dispatched.focus and dispatched.direction == "r", "standard layouts use stock focus")
print("navigation: all checks passed")

-- Exercise the real provider/session path, including recalculation after keys.
local engine = require("hypertile")
local session = require("hypertile-session")
package.loaded["hypr.hypertile"] = engine
package.loaded["hypr.hypertile-session"] = session
local provider
hl.layout = { register = function(name, value) provider = value end }
dofile("layouts/quad.lua")
local ws = {id=7, name="7", tiled_layout="lua:quad"}
local live = engine.live.quad
local app = window("app", 0, 0, 1, 1, {workspace=ws, mapped=true, stable_id=1, pid=11})
local apps = {app}
local function recalculate()
  local ctx = {area={x=10, y=30, w=1000, h=600}, targets={}}
  for _, w in ipairs(apps) do
    ctx.targets[#ctx.targets+1] = {window=w, place=function(_, box)
      w.at = {x=box.x+2000, y=box.y-800} -- Offset monitor, not the origin.
      w.size = {x=box.w, y=box.h}
    end}
  end
  provider.recalculate(ctx)
end
hl.get_active_window = function() return app end
hl.get_windows = function() return apps end
hl.get_workspaces = function() return {ws} end
hl.dsp.window.resize = function(args) args.resize=true; return args end
hl.dispatch = function(args)
  dispatched = args
  if args.resize then recalculate() end
end
recalculate()
local function zone(w)
  return session.navigation_slots(w).zone
end
assert(zone(app) == "tl")
for _, step in ipairs({{"r","tr"}, {"d","br"}, {"l","bl"}, {"u","tl"}, {"l","left"},
  {"r","tl"}, {"r","tr"}, {"r","right"}}) do
  nav.swap(step[1])
  assert(zone(app) == step[2], "single app reaches " .. step[2])
end
dispatched = nil
nav.swap("r")
assert(zone(app) == "right" and not dispatched, "edge does not wrap")
nav.focus("l")
assert(not dispatched, "focus never moves into empty slots")

-- Moving the first fill window must not pull the second into its old slot.
live.state.pins, live.state.exclusive_pins = {}, {}
local other = window("other", 0, 0, 1, 1, {workspace=ws, mapped=true, stable_id=2, pid=22})
apps = {app, other}
recalculate()
assert(zone(app) == "tl" and zone(other) == "tr")
nav.swap("d")
assert(zone(app) == "bl" and zone(other) == "tr", "other app stays put")
nav.swap("r")
nav.swap("u")
assert(zone(app) == "tr" and zone(other) == "br", "occupied destination swaps pinned apps")
nav.swap("d")
assert(zone(app) == "br" and zone(other) == "tr", "swap back")

live.state.scene_empty = {["7"]={bl=true}}
recalculate()
local _, slots = session.navigation_slots(app)
for _, slot in ipairs(slots) do assert(slot.zone ~= "bl", "scene Empty excluded") end
assert(not pcall(session.move_to_empty, app, "bl"), "reservation revalidated")
assert(not pcall(session.move_to_empty, app, "tr"), "occupied slot rejected")
local before = live.state.pins.app
local stale = window("app", 0, 0, 1, 1, {workspace=ws, stable_id=99, pid=11})
assert(not pcall(session.move_to_empty, stale, "left"))
assert(live.state.pins.app == before, "stale identity leaves pins unchanged")

provider = engine.provider("custom", {columns={{name="a"}, {name="gap", spacer=true},
  {name="b"}, {name="c"}}, empty="keep", single="slot"})
ws.tiled_layout = "lua:custom"
apps = {app}
recalculate()
nav.swap("r")
assert(zone(app) == "b", "custom layout skips spacer")
nav.swap("r")
assert(zone(app) == "c", "custom layout empty slot reached")
print("empty-slot navigation: all checks passed")

provider = engine.provider("collapsed", {columns={{name="a"}, {rows={{name="b"}, {name="c"}}}}})
ws.tiled_layout = "lua:collapsed"
recalculate()
assert(app.size.x == 1000, "single window initially collapses")
nav.swap("r")
assert(zone(app) == "b" and app.size.x == 500 and app.size.y == 300,
  "moving into collapsed slot reveals configured geometry")
nav.swap("d")
assert(zone(app) == "c", "nested collapsed slots remain reachable")
local collapsed = engine.live.collapsed
engine.handle_msg(collapsed.compiled, collapsed.state, "reset", app)
recalculate()
assert(app.size.x == 1000, "reset restores collapse policy")
print("collapsed-slot navigation: all checks passed")

provider = engine.provider("stacked", {columns={{name="a"}, {name="b"}},
  fill={"a", "a", "b"}, empty="keep", single="slot"})
ws.tiled_layout = "lua:stacked"
apps = {app, other}
recalculate()
dispatched = nil
nav.swap("d")
assert(dispatched and dispatched.target == "address:other", "retain swaps within a stack")
nav.swap("r")
assert(zone(app) == "b" and zone(other) == "a", "move out of a stack into an empty slot")
print("stack navigation: all checks passed")
