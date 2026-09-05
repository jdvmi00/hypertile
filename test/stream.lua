package.path = "./?.lua;" .. package.path
local engine = require("hypertile")
local spec = { columns = { { name = "local" }, { name = "remote" } },
  fill = { "remote", "local" }, empty = "collapse", single = "collapse" }
local compiled = engine.compile(spec)
local function context(workspace, addresses)
  local ctx = { targets = {}, area = { x = 0, y = 0, w = 1000, h = 600 } }
  for _, address in ipairs(addresses) do
    local t = { window = { address = address, workspace = { id = workspace } } }
    function t:place(box) self.box = box end
    ctx.targets[#ctx.targets + 1] = t
  end
  return ctx
end
local state = { pins = { local1 = "remote" }, sizes = {}, reservations = { ["1"] = { remote = true } } }
local ctx = context(1, { "local1" })
engine.recalculate(compiled, ctx, state)
assert(ctx.targets[1].box.w == 500 and ctx.targets[1].box.x == 0, "offline reservation defeats local pins and single collapse")
ctx = context(2, { "local1" })
engine.recalculate(compiled, ctx, state)
assert(ctx.targets[1].box.w == 1000, "reservation does not leak to another workspace")
state.reservations["1"].remote = "stream"
ctx = context(1, { "local1", "stream", "local2", "local3" })
engine.recalculate(compiled, ctx, state)
assert(ctx.targets[2].box.x == 500 and ctx.targets[2].box.w == 500, "owned window takes its zone")
for _, i in ipairs({ 1, 3, 4 }) do assert(ctx.targets[i].box.x == 0, "overflow cannot enter a reserved zone") end
state.reservations = {}
ctx = context(1, { "local1" })
engine.recalculate(compiled, ctx, state)
assert(ctx.targets[1].box.w == 1000, "release restores ordinary fill")

local ws = { id = 1, name = "1", tiled_layout = "lua:test" }
local windows = { { address = "a", pid = 123, stable_id = 9, class = "com.moonlight_stream.Moonlight",
  title = "Laptop - Moonlight", mapped = true, workspace = ws } }
local calls = {}
local rules = {}
local function tagged(name)
  return function(args) args.kind = name; return args end
end
hl = {
  window_rule = function(rule) rules[rule.name] = rule end,
  get_workspaces = function() return { ws } end,
  get_windows = function() return windows end,
  dsp = { window = { resize = tagged("resize"), move = tagged("move"), fullscreen_state = tagged("fullscreen"),
                    float = tagged("float") }, focus = tagged("focus") },
  dispatch = function(args) calls[#calls + 1] = args end,
}
engine.provider("test", spec)
local session = require("hypertile-session")
local source = { computer = "laptop", profile = "desktop", workspace = "1", layout = "lua:test", zone = "remote", title = "Laptop - Moonlight" }
session.stream_assign(source)
assert(engine.state.test.reservations["1"].remote == true)
assert(rules["hypertile-stream-laptop"].enabled and rules["hypertile-stream-laptop"].no_initial_focus,
  "final-window launch rule exists before the final window")
assert(rules["hypertile-stream-laptop"].workspace == "1 silent")
source.address, source.pid, source.stable_id, source.title = "a", 123, 9, "Laptop - Moonlight"
session.stream_assign(source)
assert(engine.state.test.reservations["1"].remote == "a")
for _, call in ipairs(calls) do
  assert(call.kind ~= "focus", "placement never steals focus")
  if call.kind == "move" then assert(call.silent == true and call.window == "address:a") end
end
calls = {}
source.placed = true
windows[1].fullscreen = 2
session.stream_assign(source)
for _, call in ipairs(calls) do assert(call.kind ~= "fullscreen", "reconciliation preserves later user fullscreen") end
local ok = pcall(session.stream_assign, { computer = "other", workspace = "1", layout = "lua:test", zone = "remote" })
assert(not ok, "second owner rejected")
ok = pcall(session.stream_assign, { computer = "other", workspace = "1", layout = "lua:test", zone = "local" })
assert(not ok, "one overflow zone remains available")
source.stable_id = 10
ok = pcall(session.stream_assign, source)
assert(not ok, "reused address/pid is not enough to identify a window")
session.stream_release({ computer = "laptop" })
assert(not engine.state.test.reservations["1"].remote, "release clears the reservation")
assert(rules["hypertile-stream-laptop"].enabled == false, "release disables the temporary host rule")

-- Real engine assignment with an uncapped fill sequence: swapping must not
-- stack an unrelated local window into the newly freed source zone.
spec = { columns = { { name = "one" }, { name = "two" }, { name = "three" }, { name = "four" } },
  fill = { "one", "two", "three", "four" }, empty = "keep", single = "slot" }
engine.provider("test", spec)
windows = {}
for i, address in ipairs({ "a", "b", "c", "d" }) do
  windows[i] = { address = address, pid = i, stable_id = i, mapped = true, workspace = ws,
    class = (i == 1 or i == 4) and "com.moonlight_stream.Moonlight" or "terminal",
    title = address .. " - Moonlight", fullscreen = 0 }
end
local function assign_source(id, i, zone)
  local w = windows[i]
  session.stream_assign({ computer = id, profile = "desktop", workspace = "1", layout = "lua:test", zone = zone,
    address = w.address, pid = w.pid, stable_id = w.stable_id, title = w.title, placed = true })
end
assign_source("laptop", 1, "two")
assign_source("second", 4, "four")
engine.live.test.orders["1"] = { "a", "b", "c", "d" }
local function positions()
  local targets = {}
  for _, w in ipairs(windows) do targets[#targets + 1] = { window = w } end
  local s = engine.state.test
  local buckets = engine.assign(engine.live.test.compiled, targets,
    { pins = s.pins, exclusive_pins = s.exclusive_pins, reserved = s.reservations["1"] })
  local result = {}
  for zone, bucket in pairs(buckets) do
    for _, t in ipairs(bucket) do result[t.window.address] = zone end
  end
  return result
end
local function plan(a, b) return session.stream_swap_plan({ windows = { windows[a], windows[b] } }) end
local before = positions()
assert(before.a == "two" and before.b == "one" and before.c == "three" and before.d == "four")
local exchange = plan(1, 2)
calls = {}
session.stream_swap_apply(exchange)
session.stream_swap_apply(exchange) -- lost reply: absolute replay, no toggle
local after = positions()
assert(after.a == "one" and after.b == "two" and after.c == "three" and after.d == "four",
  "source/local swap preserves unrelated windows and handles uncapped fill")
windows[5] = { address = "extra", pid = 5, stable_id = 5, workspace = ws, mapped = true }
assert(positions().extra ~= "one" and positions().extra ~= "four", "new local windows avoid both source reservations")
windows[5] = nil
for _, call in ipairs(calls) do assert(call.kind == "resize", "swap only refreshes layout; never focuses, moves, or restarts") end
session.stream_swap_apply(plan(2, 3))
after = positions()
assert(after.b == "three" and after.c == "two" and after.a == "one", "displaced local windows remain swappable")
exchange = plan(1, 4)
session.stream_swap_apply(exchange)
after = positions()
assert(after.a == "four" and after.d == "one", "two source reservations exchange atomically")
session.stream_swap_cancel(exchange)
after = positions()
assert(after.a == "one" and after.d == "four", "cancel restores both sides of an uncertain exchange")
exchange = plan(1, 2)
windows[2].stable_id = 99
ok = pcall(session.stream_swap_apply, exchange)
assert(not ok and positions().a == "one", "stale target rejects the whole swap before changing reservations")
windows[2].stable_id = 2
windows[2].fullscreen = 2
ok = pcall(session.stream_swap_apply, exchange)
assert(not ok and positions().a == "one", "fullscreen change rejects the whole swap")
windows[2].fullscreen = 0
session.stream_swap_apply(exchange)
session.stream_swap_cancel(exchange)
assert(positions().b == "three" and engine.state.test.exclusive_pins.b, "cancel restores the previous local swap pin")
-- A swapped local pin survives session placement and is still releasable.
session.place({ address = "b", layout = "lua:test", saved = { workspace = "1", pin = "three", pin_exclusive = true } })
assert(engine.state.test.exclusive_pins.b)
engine.handle_msg(engine.live.test.compiled, engine.state.test, "unpin", windows[2])
assert(not engine.state.test.exclusive_pins.b and not engine.state.test.pins.b)
print("stream placement: all checks passed")
