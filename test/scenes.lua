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
  dsp = { window = { resize = tag("resize"), move = tag("move"), float = tag("float"), fullscreen_state = tag("fullscreen") }, focus = tag("focus"), send_key_state = tag("key") },
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
local ok = pcall(engine.compile, { columns = { { name = "a", id = "same" }, { name = "b", id = "same" } } })
assert(not ok, "duplicate zone identities are refused")
-- Ordinary apps share no stream reservation or launch rule. Match and move
-- one final window, rejecting a second copy and recycled compositor identities.
windows[2] = nil
windows[1].title = "Document"
request.operation = "app-operation"
session.scene_content_apply(request)
local place = { workspace = "1", layout = "lua:test", operation = "app-operation", zone_id = "b", zone = "middle",
  address = "a", stable_id = 1, pid = 11, app_class = "editor", app_title = "Document" }
local count = #calls
place.stable_id = 999
assert(not pcall(session.scene_app_place, place) and #calls == count, "reused address cannot receive app placement")
place.stable_id = 1
windows[2] = { address = "extra", stable_id = 44, pid = 77, class = "editor", title = "Document", workspace = ws, mapped = true }
assert(not pcall(session.scene_app_place, place) and #calls == count, "atomic placement rejects a late duplicate")
windows[2] = nil
local pin = session.scene_app_place(place)
assert(pin.zone == "middle" and engine.state.test.pins.a == "middle")
assert(engine.state.test.exclusive_pins.a, "generic app occupies the requested zone")
local ws2 = { id = 2, name = "2", tiled_layout = "lua:test" }
windows[1].workspace = ws2
count = #calls
session.scene_app_place(place)
assert(#calls == count, "a repeated operation never moves a departed app back")
session.scene_content_apply(request)
assert(#calls == count, "repeated content apply preserves the original operation")
session.scene_clear({ workspace = "1" })
assert(engine.state.test.pins.a == "middle", "clearing a scene preserves a window moved to another workspace")
assert(not pcall(session.scene_app_place, place) and #calls == count, "superseded operation cannot place a late window")
windows[1].workspace = ws
request.operation = "new-app-operation"
session.scene_content_apply(request)
place.operation = request.operation
hl.get_workspaces = function() return {} end
local before = #calls
session.scene_app_place(place)
assert(#calls > before, "a pending app can recreate its vanished empty workspace")
local move
for i = before + 1, #calls do if calls[i].kind == "move" then move = calls[i] end end
assert(move and move.workspace == "1" and move.follow == false, "app placement does not take focus")
-- Reconciliation remaps a placed app by stable zone ID without issuing
-- another move. The eligibility check and pin transfer are atomic.
for _, departure in ipairs({ "none", "workspace", "floating", "pin", "identity" }) do
  hl.get_workspaces = function() return { ws } end
  session.scene_clear({ workspace = "1" })
  windows[1].workspace, windows[1].floating, windows[1].stable_id = ws, false, 1
  engine.provider("test", spec)
  engine.state.test.pins.a = "left"
  local content = { workspace = "1", layout = "lua:test", operation = "before-" .. departure,
    sources = { { type = "app", zone_id = "b", zone = "middle" }, { type = "empty", zone_id = "c", zone = "right" } } }
  session.scene_content_apply(content)
  place.operation = content.operation
  local original = session.scene_app_place(place)
  assert(original.before == "left")
  if departure == "workspace" then windows[1].workspace = ws2
  elseif departure == "floating" then windows[1].floating = true
  elseif departure == "pin" then engine.state.test.pins.a = "right"
  elseif departure == "identity" then windows[1].stable_id = 99 end
  engine.provider("test", { layout_id = "layout", columns = {
    { name = "left", id = "a" }, { name = "renamed", id = "b" }, { name = "right", id = "c" } },
    fill = { "left", "renamed", "right" } })
  content.operation = "after-" .. departure
  content.preserve_apps = { b = true }
  local before = #calls
  local reconciled = session.scene_content_apply(content)
  for i = before + 1, #calls do assert(calls[i].kind ~= "move", "reconcile must not dispatch another move") end
  if departure == "none" then
    assert(engine.state.test.pins.a == "renamed" and engine.state.test.exclusive_pins.a)
    assert(#reconciled.pins == 1 and reconciled.pins[1].before == "left")
    before = #calls
    place.operation = content.operation
    session.scene_app_place(place)
    assert(#calls == before, "reconciliation retains the consumed placement")
    session.scene_content_apply(content)
    assert(#calls == before, "a lost reconciliation reply is idempotent")
    session.scene_clear({ workspace = "1" })
    assert(engine.state.test.pins.a == "left", "later clear restores the original pin")
  else
    assert(#reconciled.pins == 0, "departed or recycled windows cannot be reclaimed")
    assert(engine.state.test.pins.a ~= "renamed", "reconciliation preserves the departure")
  end
end
print("scene adapter: all checks passed")
