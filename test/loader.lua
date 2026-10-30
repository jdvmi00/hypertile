-- A bad layout must not prevent the other layouts or later config from loading.
package.path = "./?.lua;" .. package.path
local engine = require("hypertile")
local bridge = require("hypertile-bridge")
local pipe = assert(io.popen("mktemp -d /tmp/hypertile-loader-XXXXXX"))
local temporary = assert(pipe:read("l")); assert(pipe:close())
assert(os.execute("mkdir -p '" .. temporary .. "/hypr/layouts'"))
package.path = temporary .. "/?.lua;" .. package.path
package.loaded["hypr.hypertile"] = engine
package.loaded["hypr.hypertile-modes"] = require("hypertile-modes")
package.loaded["default.hypr.paths"] = { config_home = temporary }

local function write(name, content)
  local file = assert(io.open(temporary .. "/hypr/layouts/" .. name .. ".lua", "w"))
  file:write(content); file:close()
end
write("a-broken", 'require("hypr.hypertile").layout("bad", {columns={{name="a"},{name="a"}}})')
write("b-syntax", 'this is not Lua!')
write("c-border", 'require("hypr.hypertile").layout("thin", {name="a",border="thin"})')
write("d-good", 'require("hypr.hypertile").layout("good", {name="a"})')
local notices, timers, registered = {}, {}, {}
hl = {
  layout = { register = function(name) registered[#registered + 1] = name end },
  exec_cmd = function(command) notices[#notices + 1] = command end,
  timer = function(callback, options) timers[#timers + 1] = options.timeout end,
}
local env = setmetatable({
  print = function() end,
  os = setmetatable({ getenv = function(name)
    if name == "XDG_STATE_HOME" or name == "HOME" then return temporary end
  end }, { __index = os }),
}, { __index = _G })
local loader = assert(loadfile("hypertile-layouts.lua", "t", env))
assert(pcall(loader), "broken layouts must not abort the loader")
assert(#registered == 1 and registered[1] == "good", "valid later layout still registers")
assert(#notices == 3 and notices[1]:find("a-broken.lua", 1, true), "errors identify each bad file")
assert(#timers == 2, "persisted rules and services still scheduled after bad files")
bridge.paths.layouts_dir = temporary .. "/hypr/layouts"
local entries = bridge.list()
assert(#entries == 4 and entries[1].error and entries[2].error and entries[3].error and entries[4].spec,
  "CLI catalog identifies the same three bad layouts")
write("a-broken", 'require("hypr.hypertile").layout("fixed", {name="a"})')
assert(pcall(loader), "subsequent reload can recover a repaired file")
assert(engine.live.fixed and #notices == 5, "repaired layout registers; only two errors remain")

local rules = temporary .. "/hypertile/workspace-rules/"
local saved_modes = temporary .. "/omarchy/workspace-layouts/"
assert(os.execute("mkdir -p '" .. rules .. "' '" .. saved_modes .. "'"))
local function save(path, content, stamp)
  local file = assert(io.open(path, "w"))
  file:write(content); file:close()
  assert(os.execute("touch -d '" .. stamp .. "' '" .. path .. "'"))
end
local function exists(path)
  local file = io.open(path, "r")
  if file then file:close() end
  return file ~= nil
end
local function rule(ws, layout)
  return 'hl.workspace_rule({ workspace = "' .. ws .. '", layout = "' .. layout .. '", gaps_in = hl.get_config("general.gaps_in") })\n'
end
save(rules .. "3.lua", rule(3, "lua:good"), "2026-10-01 10:00")
save(rules .. "4.lua", rule(4, "lua:good"), "2026-10-01 12:00")
save(saved_modes .. "4.lua", 'o.workspace_mode({ workspace = "4", mode = "floating" })\n', "2026-10-01 11:00")
save(rules .. "5.lua", rule(5, "lua:good"), "2026-10-01 11:00")
save(saved_modes .. "5.lua", 'o.workspace_mode({ workspace = "5", mode = "floating" })\n', "2026-10-01 12:00")
save(saved_modes .. "2.lua", 'o.workspace_mode({ workspace = "2", mode = "scrolling" })\n', "2026-10-01 12:00")
save(saved_modes .. "default.lua", 'o.workspace_mode({ default = "floating" })\n', "2026-10-01 12:00")
local omarchy_calls, live_rules = {}, {}
local function omarchy_mode(spec) omarchy_calls[#omarchy_calls + 1] = spec end
o = { workspace_mode = omarchy_mode }
local callbacks = {}
notices = {}
hl.timer = function(callback) callbacks[#callbacks + 1] = callback end
hl.get_config = function(key) return key end
hl.workspace_rule = function(spec) live_rules[spec.workspace] = spec end
assert(pcall(loader))
callbacks[1]()
local modes = require("hypertile-modes")
assert(not exists(saved_modes .. "4.lua") and exists(rules .. "4.lua"), "a newer saved rule wins over an older Omarchy mode")
assert(exists(saved_modes .. "5.lua") and not exists(rules .. "5.lua"), "a newer Omarchy mode wins over an older saved rule")
assert(live_rules["3"] and live_rules["4"] and not live_rules["5"], "only the surviving saved rules apply")
assert(live_rules["3"].layout == "lua:good" and live_rules["3"].gaps_in == "general.gaps_in", "a saved rule keeps its gutters")
assert(#omarchy_calls == 2 and omarchy_calls[1].workspace == "3" and omarchy_calls[1].mode == "lua:good"
  and omarchy_calls[2].workspace == "4", "Omarchy records each saved rule as that workspace's mode")
assert(modes.floating(5) and not modes.floating(4) and not modes.floating(3) and not modes.floating(2),
  "per-workspace modes decide floating")
assert(modes.floating(7) and not modes.floating("name:notes"), "the floating default covers numbered workspaces without a mode")

o.workspace_mode({ workspace = "3", mode = "floating" })
assert(omarchy_calls[3] and omarchy_calls[3].mode == "floating", "Omarchy's own call still reaches Omarchy")
assert(not exists(rules .. "3.lua") and modes.floating(3), "Omarchy's later pick replaces the saved rule")
assert(notices[#notices]:find("hypertile-bar refresh", 1, true), "the bar hears about Omarchy's pick")
o.workspace_mode({ default = "dwindle" })
assert(not modes.floating(7) and modes.floating(5), "a new default reaches workspaces without a mode of their own")

local reloaded = {}
o.workspace_mode = function(spec) reloaded[#reloaded + 1] = spec end
callbacks = {}
assert(pcall(loader))
callbacks[1]()
o.workspace_mode({ workspace = "6", mode = "scrolling" })
assert(#reloaded == 2 and reloaded[1].workspace == "4" and reloaded[2].workspace == "6" and #omarchy_calls == 4,
  "a reload wraps Omarchy's fresh function once and drops the old one")

save(saved_modes .. "4.lua", 'o.workspace_mode({ workspace = "4", mode = "dwindle" })\n', "2026-10-02 12:00")
save(saved_modes .. "8.lua", 'o.workspace_mode({ workspace = "8", mode = "lua:good" })\n', "2026-10-02 12:00")
live_rules, callbacks = {}, {}
assert(pcall(loader))
callbacks[1]()
assert(exists(saved_modes .. "4.lua") and exists(rules .. "4.lua") and live_rules["4"].layout == "lua:good" and not modes.floating(4),
  "after the first load, a default change that kept a busy workspace leaves hypertile's rule in charge")
assert(not modes.floating(8), "a saved hypertile layout in Omarchy's file is not the floating default")

assert(os.execute("rm -rf '" .. temporary .. "'"))
print("layout loader: all checks passed")
