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
dispatched, a.fullscreen = nil, nil
nav.focus("l")
assert(dispatched and dispatched.window == "address:left", "missing fullscreen means ordinary tiled window")
a.fullscreen = 0
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

-- The slot can change between navigation's snapshot and the move itself.
local move_to_empty = session.move_to_empty
local notification
hl.exec_cmd = function(command) notification = command end
session.move_to_empty = function() error("move unavailable: zone isn't empty") end
apps = { app }
recalculate()
local prior_zone = zone(app)
assert(pcall(nav.swap, "l"), "failed empty-slot move does not escape key callback")
assert(notification and notification:find("Hypertile move", 1, true)
  and notification:find("move unavailable", 1, true), "failed move explains the error")
assert(zone(app) == prior_zone, "failed move leaves window in place")
session.move_to_empty = move_to_empty

-- Numbered selection captures identity before focus leaves the window.
package.loaded["hypr.hypertile-json"] = require("hypertile-json")
hl.get_active_monitor = function() return {name="DP-2"} end
hl.get_active_workspace = function() return ws end
hl.get_active_window = function() return app end
provider = engine.provider("numbered", {columns={{name="a"}, {name="gap", spacer=true},
  {name="b"}, {name="c"}}, fill={"c", "a", "b", "b"}, empty="keep", single="slot"})
ws.tiled_layout = "lua:numbered"
apps = {app, other}
recalculate()
local numbered = engine.live.numbered
local request = nav.capture()
assert(request.monitor == "DP-2" and request.source == "c" and #request.slots == 3)
assert(request.slots[1].numbers[1] == 2 and request.slots[2].numbers[1] == 3
  and request.slots[2].numbers[2] == 4 and request.slots[3].numbers[1] == 1,
  "picker uses configured fill numbers, not tree indexes; stack aliases retained")
assert(request.slots[1].x == 10 and request.slots[1].y == 30, "slot boxes are monitor-local")
request.zone = "b"
hl.get_active_window = function() return other end
nav.move(request)
assert(zone(app) == "b" and zone(other) == "a", "captured window moves despite a focus change")
assert(dispatched.window == "address:app", "focus follows the moved window")
assert(not pcall(nav.move, request), "reusing a request after its source moved is rejected")
assert(pcall(nav.move, request, true), "drag release accepts native reinsertion into a different source slot")
local saved_id = request.stable_id
request.stable_id = -1
assert(not pcall(nav.move, request, true), "drag still rejects a changed window identity")
request.stable_id = saved_id
hl.get_active_window = function() return app end
request = nav.capture()
request.zone = "a"
nav.move(request)
assert(zone(app) == "a" and zone(other) == "b", "numbered occupied selection swaps")
request = nav.capture()
request.zone = request.source
dispatched = nil
nav.move(request)
assert(zone(app) == "a" and zone(other) == "b", "current tile leaves assignments alone")

local function rejected(change, restore, message)
  local value = nav.capture()
  value.zone = "c"
  local before_app, before_other = zone(app), zone(other)
  change(value)
  assert(not pcall(nav.move, value), message)
  restore()
  assert(zone(app) == before_app and zone(other) == before_other, message .. " preserves placement")
end
rejected(function(r) r.stable_id = 999 end, function() end, "reused address rejected")
rejected(function() app.floating = true end, function() app.floating = false end, "floating window rejected")
rejected(function() app.fullscreen = 2 end, function() app.fullscreen = 0 end, "fullscreen window rejected")
rejected(function() numbered.spec.single = "fill" end, function() numbered.spec.single = "slot" end, "edited layout rejected")
rejected(function() hl.get_active_workspace = function() return {id=99} end end,
  function() hl.get_active_workspace = function() return ws end end, "workspace change rejected")
rejected(function() apps = {other} end, function() apps = {app, other} end, "closed source rejected")
rejected(function(r) r.zone = "gap" end, function() end, "spacer rejected")
rejected(function() numbered.state.scene_empty = {["7"]={c=true}} end,
  function() numbered.state.scene_empty = {} end, "new reservation rejected")

-- Unmanaged occupied tiles use the native swap, with explicit source focus.
numbered.state.pins, numbered.state.exclusive_pins = {}, {}
recalculate()
request = nav.capture()
request.zone = "a"
local events = {}
local dispatch = hl.dispatch
hl.dispatch = function(args) events[#events+1] = args end
nav.move(request)
assert(events[1].window == "address:app" and events[2].target == "address:other"
  and events[3].window == "address:app", "native swap focuses captured source first")
hl.dispatch = dispatch

nav.pick()
assert(notification:find('shell toggle jmartin.hypertile', 1, true)
  and notification:find('"mode": "move"', 1, true), "shortcut passes captured request to shell")
ws.tiled_layout = "dwindle"
assert(not pcall(nav.capture), "built-in layout has no numbered picker")
print("numbered tile navigation: all checks passed")

-- The picker must show fitted window destinations, including empty tiles,
-- while directional navigation keeps using the full layout slots.
provider = engine.provider("aspect-picker", {rows={{name="a", aspect=1.5},
  {name="b", aspect=1.5}, {name="c", aspect=1.5}, {name="d", aspect=1.5}},
  empty="keep", single="slot"})
ws.tiled_layout = "lua:aspect-picker"
apps = {app}
recalculate()
request = nav.capture()
for i, slot in ipairs(request.slots) do
  assert(slot.w == 225 and slot.h == 150 and slot.x == 397.5
    and slot.y == 30 + (i-1)*150, "3:2 row " .. i .. " draws only its fitted area")
end
local raw = session.navigation_slots(app)
assert(raw.size.x == 1000, "picker fitting does not alter directional slot geometry")
assert(math.abs(request.slots[1].x - (app.at.x-2000)) <= .5
  and request.slots[1].w == app.size.x, "picker follows actual placement on an offset monitor")

provider = engine.provider("scaled-picker", {columns={{name="left"},
  {name="center", aspect=1.5, scale=.75}, {name="right"}},
  fill={"center", "left", "right"}, empty="keep", single="slot"})
ws.tiled_layout = "lua:scaled-picker"
recalculate()
request = nav.capture()
local center = request.slots[2]
assert(math.abs(center.w - 250) < .001 and math.abs(center.h - 250/1.5) < .001,
  "center outline honors both aspect and scale")
assert(math.abs(center.x - (app.at.x-2000)) <= .5 and math.abs(center.y - (app.at.y+800)) <= .5
  and math.abs(center.y + center.h - (app.at.y+800+app.size.y)) <= .5,
  "center outline matches placed window within edge rounding")
print("fitted tile outlines: all checks passed")

-- Drag hit testing uses logical coordinates relative to the original monitor.
local monitor = {name="offset", position={x=-2000,y=400}}
local drag_request = {monitor="offset", slots={{zone="a",x=10,y=20,w=100,h=80},
  {zone="b",x=110,y=20,w=100,h=80}}}
assert(nav.drag_slot(drag_request, {x=-1990,y=420}, monitor) == "a")
assert(nav.drag_slot(drag_request, {x=-1890,y=420}, monitor) == "b", "shared edge belongs to one slot")
assert(not nav.drag_slot(drag_request, {x=-1991,y=420}, monitor), "gap is not a drop target")
assert(not nav.drag_slot(drag_request, {x=-1990,y=500}, monitor), "bottom edge is outside")
assert(not nav.drag_slot(drag_request, {x=-1990,y=420}, {name="other",position=monitor.position}))

-- Exercise capture/update/release without depending on an actual pointer.
local capture, move, open_file, rename = nav.capture, nav.move, io.open, os.rename
local cursor = {x=-1990,y=420}
local writes, opened, moves, timers = {}, {}, {}, {}
io.open = function() return {write=function(_, value) writes[#writes+1]=value end, close=function() end} end
os.rename = function() return true end
hl.get_cursor_pos = function() return cursor end
hl.get_monitor_at_cursor = function() return monitor end
hl.get_active_workspace = function() return ws end
local dragged = {address="dragged",stable_id=42,pid=100,workspace=ws,
  at={x=-2000,y=400},size={x=300,y=200}}
hl.get_windows = function() return {dragged} end
hl.get_active_window = function() return nil end -- Unfocused tile under pointer.
hl.exec_cmd = function(value) opened[#opened+1]=value end
hl.timer = function(callback, options)
  local timer = {callback=callback, options=options, enabled=true,
    set_enabled=function(self, value) self.enabled=value end}
  timers[#timers+1]=timer
  return timer
end
nav.capture = function(target)
  assert(target == dragged, "capture window under pointer, even if unfocused")
  return {address="dragged",stable_id=42,pid=100,monitor="offset",workspace=ws.id,slots=drag_request.slots}
end
nav.move = function(request, after_drag) moves[#moves+1]={zone=request.zone,after_drag=after_drag} end
nav.drag_begin()
assert(#opened == 1 and #timers == 1 and timers[1].enabled)
cursor = {x=-1850,y=450}
nav.drag_end()
assert(#moves == 1 and moves[1].zone == "b" and moves[1].after_drag)
assert(not timers[1].enabled and writes[#writes]:find('"active": false',1,true))
nav.drag_end()
assert(#moves == 1, "duplicate/ordinary releases do not move anything")
nav.drag_begin()
cursor = {x=-2500,y=450}
nav.drag_end()
assert(#moves == 1, "release outside leaves the native drag alone")
cursor = {x=-1990,y=420}
nav.drag_begin()
hl.get_active_workspace = function() return {id=999} end
nav.drag_end()
assert(#moves == 1, "workspace switch cancels tile placement")
hl.get_active_workspace = function() return ws end
nav.capture = function() error("not tiled") end
nav.drag_begin()
assert(#timers == 3, "unsupported windows do not start an overlay")
nav.capture, nav.move, io.open, os.rename = capture, move, open_file, rename
print("tile drag: all checks passed")
