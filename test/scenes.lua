package.path = "./?.lua;" .. package.path
local engine = require("hypertile")
local spec = { layout_id = "layout", columns = { { name = "left", id = "a" }, { name = "middle", id = "b" }, { name = "right", id = "c" } },
  fill = { "left", "middle", "right" }, empty = "collapse", single = "collapse" }
engine.provider("test", spec)
local ws = { id = 1, name = "1", tiled_layout = "lua:test" }
local windows = {
  { address = "a", stable_id = 1, pid = 11, class = "editor", workspace = ws, mapped = true, fullscreen = 0 },
  { address = "b", stable_id = 2, pid = 22, class = "terminal", workspace = ws, mapped = true, fullscreen = 0 },
}
local calls, timers = {}, {}
local function tag(kind) return function(args) args.kind = kind; return args end end
hl = { get_windows = function() return windows end, get_workspaces = function() return { ws } end,
  window_rule = function() end, timer = function(callback) timers[#timers + 1] = callback end,
  dsp = { window = { resize = tag("resize") }, focus = tag("focus"), send_key_state = tag("key") },
  dispatch = function(args) calls[#calls + 1] = args end }
local session = require("hypertile-session")
package.loaded["hypertile-bridge"] = {
  rule_source = function() return "hl.scene_test_applied = true" end,
  apply = function() error("must not call hyprctl from the compositor thread") end,
}
assert(session.scene_layout({ workspace = "1", layout = "dwindle" }) == "hl.scene_test_applied = true")
assert(hl.scene_test_applied, "scene layout applies directly without recursive IPC")
local request = { workspace = "1", layout = "lua:test", sources = {
  { type = "empty", zone = "right", zone_id = "c" }, { type = "local", zone = "left", zone_id = "a", app_class = "editor" } } }
local result = session.scene_content_apply(request)
assert(result.results[1].status == "ready" and result.pins[1].stable_id == 1)
assert(engine.state.test.scene_empty["1"].right and not engine.state.test.scene_empty["2"])
local ctx = { area = { x = 0, y = 0, w = 900, h = 500 }, targets = {} }
for _, w in ipairs(windows) do
  local target = { window = w, place = function(self, box) self.box = box end }
  ctx.targets[#ctx.targets + 1] = target
end
engine.recalculate(engine.live.test.compiled, ctx, engine.state.test)
assert(ctx.targets[1].box.x == 0 and ctx.targets[2].box.x == 300, "local app pin and empty reservation preserve fill")
local ok, error = pcall(session.stream_check, { computer = "laptop", workspace = "1", layout = "lua:test", zone = "right" })
assert(not ok and tostring(error):find("intentionally empty"), "stream cannot claim Empty")
local checked = session.stream_check({ computer = "laptop", workspace = "1", layout = "lua:test", zone = "old-name", zone_id = "b" })
assert(checked.zone == "middle" and checked.zone_id == "b", "stable identity resolves a renamed zone")
engine.state.test.pins.a = "middle"
engine.provider("other", spec)
engine.state.other.pins.a = "left"
session.scene_clear({ workspace = "1" })
assert(engine.state.test.pins.a == "middle", "scene removal preserves a manually changed app pin")
assert(engine.state.other.pins.a == "left", "scene removal preserves the window's pin in other layouts")
assert(not engine.state.test.scene_empty["1"], "scene removal clears Empty")
windows[3] = { address = "c", stable_id = 3, pid = 33, class = "editor", workspace = ws, mapped = true }
result = session.scene_content_apply(request)
assert(result.results[1].status == "needs-attention" and #result.pins == 0, "ambiguous app never picks an arbitrary window")
windows[3] = nil
windows[2].class, windows[2].title = "com.moonlight_stream.Moonlight", "Laptop - Moonlight"
session.stream_assign({ computer = "laptop", profile = "desktop", workspace = "1", layout = "lua:test", zone = "middle",
  address = "b", stable_id = 2, pid = 22, title = "Laptop - Moonlight", placed = true })
calls = {}
session.stream_shortcut({ computer = "laptop", action = "clipboard" })
assert(#calls == 1 and calls[1].kind == "focus", "explicit clipboard action focuses the client for its Wayland offer")
timers[1]()
assert(calls[2].key == "V" and calls[2].state == "down" and calls[2].window == "address:b")
timers[2]()
assert(calls[3].state == "up" and calls[3].window == "address:b", "shortcut releases its synthetic key on the same owned window")
windows[2].stable_id = 999
ok = pcall(session.stream_shortcut, { computer = "laptop", action = "clipboard" })
assert(not ok and #calls == 3, "shortcut refuses a reused address")
ok = pcall(engine.compile, { columns = { { name = "a", id = "same" }, { name = "b", id = "same" } } })
assert(not ok, "duplicate zone identities are refused")
print("scene adapter: all checks passed")
