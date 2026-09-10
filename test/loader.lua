-- A bad layout must not prevent the other layouts or later config from loading.
package.path = "./?.lua;" .. package.path
local engine = require("hypertile")
local bridge = require("hypertile-bridge")
local pipe = assert(io.popen("mktemp -d /tmp/hypertile-loader-XXXXXX"))
local temporary = assert(pipe:read("l")); assert(pipe:close())
assert(os.execute("mkdir -p '" .. temporary .. "/hypr/layouts'"))
package.path = temporary .. "/?.lua;" .. package.path
package.loaded["hypr.hypertile"] = engine
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
assert(#timers == 3, "persisted rules and services still scheduled after bad files")
bridge.paths.layouts_dir = temporary .. "/hypr/layouts"
local entries = bridge.list()
assert(#entries == 4 and entries[1].error and entries[2].error and entries[3].error and entries[4].spec,
  "CLI catalog identifies the same three bad layouts")
write("a-broken", 'require("hypr.hypertile").layout("fixed", {name="a"})')
assert(pcall(loader), "subsequent reload can recover a repaired file")
assert(engine.live.fixed and #notices == 5, "repaired layout registers; only two errors remain")
assert(os.execute("rm -rf '" .. temporary .. "'"))
print("layout loader: all checks passed")
