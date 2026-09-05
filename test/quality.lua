package.path = "./?.lua;" .. package.path
local engine = require("hypertile")
engine.provider("test", { columns = { { name = "local" }, { name = "remote" } } })
local ws = { id = 1, name = "1", tiled_layout = "lua:test" }
local local_win = { address = "local", pid = 1, stable_id = 1, class = "editor", workspace = ws, mapped = true }
local remote = { address = "remote", pid = 2, stable_id = 2, class = "com.moonlight_stream.Moonlight",
  title = "Laptop - Moonlight", workspace = ws, mapped = true }
local windows, active, calls = { local_win, remote }, local_win, {}
local function tag(kind) return function(args) args = args or {}; args.kind = kind; return args end end
hl = { get_windows = function() return windows end, get_workspaces = function() return {ws} end,
  get_monitors = function() return {} end, get_active_window = function() return active end,
  get_active_workspace = function() return ws end,
  dsp = { window = { resize = tag("resize"), close = tag("close") }, focus = tag("focus"), release_input_capture = tag("release") },
  dispatch = function(args) calls[#calls + 1] = args end }
local session = require("hypertile-session")
session.stream_assign({ computer = "laptop", profile = "desktop", workspace = "1", layout = "lua:test", zone = "remote",
  address = "remote", pid = 2, stable_id = 2, title = remote.title, placed = true })
session.snapshot()
calls = {}
assert(not session.stream_local({computer = "laptop"}).released and #calls == 0, "never takes focus from another app")
active = remote
assert(session.stream_local({computer = "laptop"}).released)
assert(calls[1].kind == "release" and calls[2].window == "address:local", "explicit return releases capture and focuses the remembered local window")
calls = {}
session.stream_close({computer = "laptop"})
assert(#calls == 1 and calls[1].kind == "close" and calls[1].window == "address:remote", "reconnect closes only the owned stream without focus")
remote.stable_id = 99
assert(not session.stream_close({computer = "laptop"}) and #calls == 1, "reused window address is never closed")
assert(not session.stream_local({computer = "laptop"}).released and #calls == 1)
print("quality controls: all checks passed")
