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
a.workspace.tiled_layout = "lua:test"
nav.swap("l")
assert(dispatched.target == "address:left", "swap by address")
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
