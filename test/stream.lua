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
print("stream placement: all checks passed")
