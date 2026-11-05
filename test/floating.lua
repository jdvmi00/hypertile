-- Window size and placement on Omarchy's floating workspaces.
package.path = "./?.lua;" .. package.path
package.loaded["hypr.hypertile-json"] = require("hypertile-json")
local floating = require("hypertile-floating")

-- The Dell at 4/3 scale (as Hyprland reports it) under a 26px bar, placed
-- above another screen.
local dell = { x = 0, y = -1920, width = 6144, height = 2560, scale = 1.3333333730697632, transform = 0,
  reserved = { top = 26, bottom = 0, left = 0, right = 0 } }
local area = floating.area(dell)
assert(area.monitor_w == 4608 and area.monitor_h == 1920, "layout size of a scaled monitor")
assert(area.x == 0 and area.y == -1894 and area.w == 4608 and area.h == 1894, "the bar's strip is left out")
local rotated = floating.area({ x = 0, y = 0, width = 3840, height = 2160, scale = 2, transform = 1 })
assert(rotated.monitor_w == 1080 and rotated.monitor_h == 1920, "a rotated monitor swaps sides")

-- Fitting moves first and shrinks only what cannot fit.
local inside = floating.fit({ x = 100, y = -1800, w = 1000, h = 800 }, area)
assert(inside.x == 100 and inside.y == -1800 and inside.w == 1000 and inside.h == 800, "a window inside stays")
local right = floating.fit({ x = 4000, y = -1800, w = 1600, h = 800 }, area)
assert(right.x == 3008 and right.w == 1600, "half off the right edge comes back whole")
local under_bar = floating.fit({ x = 0, y = -1920, w = 1000, h = 800 }, area)
assert(under_bar.y == -1894, "a window under the bar moves below it")
local big = floating.fit({ x = -500, y = -2500, w = 6144, h = 2560 }, area)
assert(big.x == 0 and big.y == -1894 and big.w == 4608 and big.h == 1894, "a window bigger than the screen shrinks to it")
-- A window left at a 6144-wide monitor's coordinates after the scale returns.
local stale = floating.fit({ x = 5200, y = 300, w = 1500, h = 1200 }, area)
assert(stale.x == 3108 and stale.y == -1200, "a window off the screen entirely is brought back")

-- Saved shares and the box they open at.
local saved = floating.share({ size = { x = 2304, y = 1344 }, monitor = dell })
assert(saved.width == 0.5 and saved.height == 0.7, "a window's share of its monitor")
assert(floating.valid(saved) and not floating.valid({ width = 0.05, height = 0.5 })
  and not floating.valid({ width = 1.2, height = 0.5 }) and not floating.valid(nil), "share bounds")
local box = floating.open_box(saved, area, 2)
assert(box.w == 2304 and box.h == 1344 and box.x == 1152 and box.y == -1894 + 275, "centered on the free area")
local tall = floating.open_box({ width = 0.5, height = 1 }, area, 4)
assert(tall.h == 1894 and tall.y == -1894, "a full-height share still clears the bar")
local titled = floating.area(dell, 30)
assert(titled.y == -1864 and titled.h == 1864 and titled.monitor_h == 1920, "a title bar takes from the top")
assert(floating.describe(saved) == "50% × 70% of the screen" and floating.describe(nil) == "Omarchy's size", "descriptions")

-- Saving from the focused window, the rule, and keeping windows on screen.
local pipe = assert(io.popen("mktemp -d /tmp/hypertile-floating-XXXXXX"))
local temporary = assert(pipe:read("l")); assert(pipe:close())
local rules, effects, dispatched, handlers, timers, notices = {}, {}, {}, {}, {}, {}
local active
local windows = {}
local monitors = { dell }
local function window(address, x, y, w, h, extra)
  local result = { address = address, at = { x = x, y = y }, size = { x = w, y = h }, floating = true,
    mapped = true, hidden = false, fullscreen = 0, monitor = dell, workspace = { id = 1 },
    tags = { "omarchy-floating-workspace", "omarchy-mode-floated" } }
  for k, v in pairs(extra or {}) do result[k] = v end
  return result
end
hl = {
  -- Like Hyprland: a known name keeps its rule, and effects add to its list.
  window_rule = function(spec)
    local rule = rules[spec.name] or {}
    rules[spec.name] = rule
    rule.enabled = spec.enabled ~= false
    if spec.match then rule.match = spec.match end
    for _, key in ipairs({ "size", "move" }) do
      if spec[key] then
        rule[key] = spec[key]
        effects[spec.name] = (effects[spec.name] or 0) + 1
      end
    end
  end,
  on = function(event, callback) handlers[event] = callback end,
  timer = function(callback, options)
    local timer = { callback = callback, timeout = options.timeout, enabled = true }
    function timer:set_enabled(value) self.enabled = value end
    timers[#timers + 1] = timer
    return timer
  end,
  get_active_window = function() return active end,
  get_windows = function() return windows end,
  get_monitors = function() return monitors end,
  exec_cmd = function(command) notices[#notices + 1] = command end,
  -- Omarchy's title bars, as its floating mode configures them.
  get_config = function(key)
    if key == "plugin.hyprbars.enabled" then return true end
    if key == "plugin.hyprbars.bar_height" then return 30 end
    error("no such option " .. key)
  end,
  dispatch = function(action) dispatched[#dispatched + 1] = action end,
  dsp = { window = {
    resize = function(args) args.kind = "resize"; return args end,
    move = function(args) args.kind = "move"; return args end,
  } },
}
local function run_timers()
  local pending = timers
  timers = {}
  for _, timer in ipairs(pending) do
    if timer.enabled then timer.callback() end
  end
end
local function enabled_rules()
  local out = {}
  for name, rule in pairs(rules) do
    if rule.enabled then out[#out + 1] = name end
  end
  return out
end
local runtime = temporary .. "/runtime"
local function reload()
  rules, effects, timers = {}, {}, {}
  floating.before_load()
  floating.attach(temporary, runtime)
end

reload()
assert(next(rules) == nil, "no saved size leaves Omarchy's rule alone")
assert(handlers["window.open"] and handlers["monitor.added"] and handlers["window.fullscreen"], "watchers")
assert(#timers == 0, "the first load of a session records the monitors without fitting")

active = window("a", 100, -1800, 2304, 1344, { floating = false })
assert(floating.save_active(true):match("^error"), "a tiled window is not saved")
assert(notices[#notices]:find("not saved", 1, true), "the keybinding says why")
active.floating = true
local line = floating.save_active(true)
assert(line:find("50% × 70%", 1, true), "the CLI hears the saved size")
local state = temporary .. "/hypertile/floating-size.json"
local file = assert(io.open(state))
local stored = require("hypertile-json").decode(file:read("a")); file:close()
assert(stored.width == 0.5 and stored.height == 0.7, "saved to the state file")
local rule = rules["hypertile-floating-open-0"]
assert(rule.enabled and rule.match.tag == "omarchy-mode-opened", "the rule follows Omarchy's open tag")
assert(rule.size == "monitor_w*0.5000 monitor_h*0.7000", "the rule sizes by share")
assert(rule.move == "(monitor_w-monitor_w*0.5000)/2+(-48) (monitor_h-monitor_h*0.7000)/2+(-48)", "and centers")
assert(rules["hypertile-floating-open-1"].move:find("+(-24)", 1, true), "each cascade step has its rule")
assert(#enabled_rules() == 1, "one step is enabled at a time")

-- A failed write keeps the saved size. A directory where the temporary
-- file goes refuses the write even for root, which CI runs as.
assert(os.execute("mkdir '" .. state .. ".tmp'"))
active.size = { x = 3000, y = 1500 }
local refused = floating.save_active(false)
assert(refused:match("^error: Could not save"), "a failed write is reported: " .. refused)
file = assert(io.open(state))
stored = require("hypertile-json").decode(file:read("a")); file:close()
assert(stored.width == 0.5 and floating.saved().width == 0.5, "and the old size stays, on disk and in use")
-- A full disk too: the write fails at close, and the old file stays.
assert(os.execute("rmdir '" .. state .. ".tmp' && ln -s /dev/full '" .. state .. ".tmp'"))
refused = floating.save_active(false)
assert(refused:match("^error: Could not save"), "a write the disk refuses is reported: " .. refused)
file = assert(io.open(state))
stored = require("hypertile-json").decode(file:read("a")); file:close()
assert(stored.width == 0.5 and floating.saved().width == 0.5, "and the saved file is untouched")
-- So does a failed reset: a non-empty directory in the file's place cannot
-- be removed, by root either.
assert(os.execute("mv '" .. state .. "' '" .. state .. ".keep' && mkdir -p '" .. state .. "/held'"))
local kept = floating.reset()
assert(kept:match("^error: Could not reset"), "a failed reset is reported: " .. kept)
assert(floating.saved() and #enabled_rules() == 1, "and the size stays in use")
assert(os.execute("rm -r '" .. state .. "' && mv '" .. state .. ".keep' '" .. state .. "'"))
active.size = { x = 2304, y = 1344 }

-- A reload with the same monitors starts again from the file and moves nothing.
local placed_by_hand = window("hand", 100, -1915, 1000, 800)
windows = { placed_by_hand }
reload()
assert(rules["hypertile-floating-open-0"].size == "monitor_w*0.5000 monitor_h*0.7000", "the size survives a reload")
assert(#timers == 0, "an ordinary reload leaves windows where they are")

-- A window Omarchy's rule opened steps the cascade and is kept off the bar.
local opened = window("o", 1152, -1920, 2304, 1344, { tags = { "omarchy-floating-workspace", "omarchy-mode-opened*" } })
windows = { opened }
local written = effects["hypertile-floating-open-0"]
handlers["window.open"](opened)
assert(rules["hypertile-floating-open-1"].enabled and not rules["hypertile-floating-open-0"].enabled, "the next window steps on")
assert(effects["hypertile-floating-open-0"] == written and effects["hypertile-floating-open-1"] == written,
  "stepping adds no effects to the rules")
dispatched = {}
run_timers()
assert(#dispatched == 1 and dispatched[1].kind == "move" and dispatched[1].y == -1864, "the new window's title bar clears the bar")
handlers["window.open"](window("plain", 0, 0, 10, 10, { tags = {} }))
assert(rules["hypertile-floating-open-1"].enabled, "other windows leave the cascade alone")

-- Chrome opens tiled under its own tile rule, and Omarchy floats it at its
-- own size before the rule's size can apply: it takes the saved size at the
-- step it opened at, and the next window steps on from there.
local chrome = window("chrome", 1800, -1300, 1100, 760, { tags = { "omarchy-floating-workspace", "omarchy-mode-floated",
  "omarchy-mode-opened*", "chromium-based-browser*" } })
windows, dispatched = { chrome }, {}
handlers["window.open"](chrome)
assert(rules["hypertile-floating-open-2"].enabled, "Chrome steps the cascade like any other window")
run_timers()
assert(#dispatched == 2 and dispatched[1].kind == "resize" and dispatched[1].x == 2304 and dispatched[1].y == 1344,
  "a window Omarchy floated at its own size as it opened takes the saved size")
assert(dispatched[2].kind == "move" and dispatched[2].x == 1152 + 1 * 24 - 48 and dispatched[2].y == -1864 + 260 + 1 * 24 - 48,
  "at the step it opened at: " .. tostring(dispatched[2].x) .. "," .. tostring(dispatched[2].y))

-- After a display change, only windows off their floating workspace's screen move.
local off = window("off", 4000, -1800, 1600, 800)
local fine = window("fine", 100, -1800, 1000, 800)
local tiled = window("tiled", 4000, -1800, 1600, 800, { tags = {} })
local minimized = window("min", 9000, -1800, 1600, 800, { workspace = { id = -98 } })
local full = window("full", 9000, -1800, 1600, 800, { fullscreen = 1 })
local between = window("between", 9000, -1800, 1600, 800, { monitor = { name = "FALLBACK", x = 0, y = 0,
  width = 1920, height = 1080, scale = 1, reserved = {} } })
windows = { off, fine, tiled, minimized, full, between }
dispatched, timers = {}, {}
handlers["monitor.added"]()
handlers["monitor.layout_changed"]()
assert(#timers == 2 and not timers[1].enabled and timers[2].enabled, "a burst of changes fits once")
run_timers()
assert(#dispatched == 1 and dispatched[1].window == "address:off" and dispatched[1].x == 3008, "only the stray window moves")

-- A resize keeps the center, so a shrunk window is always moved into place too.
local wide = window("wide", 0, -1864, 5000, 1000)
windows, dispatched = { wide }, {}
assert(floating.keep(wide), "a window wider than the screen is fitted")
assert(#dispatched == 2 and dispatched[1].kind == "resize" and dispatched[1].x == 4608
  and dispatched[2].kind == "move" and dispatched[2].x == 0 and dispatched[2].y == -1864, "resized, then moved to its corner")

-- A window shrunk to a screen it passed through gets its size back.
local small = { name = "DP-1", x = 0, y = -1920, width = 2560, height = 1440, scale = 1, transform = 0,
  reserved = { top = 26, bottom = 0, left = 0, right = 0 } }
local roaming = window("roaming", 0, -1864, 3000, 1300, { monitor = small })
windows, dispatched = { roaming }, {}
floating.keep(roaming)
assert(dispatched[1].x == 2560 and dispatched[1].y == 1300, "shrunk to the smaller screen")
roaming.size, roaming.monitor = { x = 2560, y = 1300 }, dell
dispatched = {}
reload() -- the screen coming back reloads the config
floating.keep(roaming)
assert(dispatched[1].kind == "resize" and dispatched[1].x == 3000 and dispatched[1].y == 1300, "back to its size on the bigger screen")
roaming.size, roaming.monitor, dispatched = { x = 3000, y = 1300 }, small, {}
floating.keep(roaming)
roaming.size, roaming.monitor, dispatched = { x = 2000, y = 1000 }, dell, {}
floating.keep(roaming)
assert(#dispatched == 0, "a window resized by hand since keeps the new size")

-- A changed monitor layout at load fits windows the earlier load could not.
monitors = { small }
local stray = window("stray", 2400, -1800, 1000, 800, { monitor = small })
windows, dispatched = { stray }, {}
reload()
assert(#timers == 1, "a reload after a display change fits windows")
run_timers()
assert(dispatched[1].kind == "move" and dispatched[1].x == 1560, "the stray window comes back")
monitors = { dell }
reload()
timers = {}

-- Windows the mode floats get the saved size, at the current step, and the
-- next window opened steps on.
local before = floating.claimed()
local newly = window("new", 0, -1800, 1100, 760)
windows = { off, newly }
before[off.address] = true
dispatched = {}
local step = 0
for i = 0, 4 do if rules["hypertile-floating-open-" .. i].enabled then step = i end end
floating.claimed_since(before)
assert(#dispatched == 2 and dispatched[1].kind == "resize" and dispatched[1].x == 2304 and dispatched[1].y == 1344,
  "the newly floated window takes the saved size")
assert(dispatched[2].x == 1152 + step * 24 - 48, "at the step the open rule would have used")
assert(rules["hypertile-floating-open-" .. ((step + 1) % 5)].enabled, "the next open steps past it")

-- The arrangement Omarchy makes while the config loads gets the saved size too.
local retiled = window("retiled", 0, -1800, 1000, 700, { floating = false, tags = { "omarchy-floating-workspace" } })
windows = { retiled }
rules, effects, timers = {}, {}, {}
floating.before_load()
retiled.floating, retiled.size = true, { x = 1100, y = 760 }
retiled.tags = { "omarchy-floating-workspace", "omarchy-mode-floated" }
dispatched = {}
floating.attach(temporary, runtime)
assert(dispatched[1].kind == "resize" and dispatched[1].x == 2304, "a window Omarchy floats at load takes the saved size")

-- A tiled window carried onto a floating workspace is sized once Omarchy floats it.
local carried = window("carried", 0, -1800, 1100, 760, { floating = false, tags = {} })
windows = { carried }
timers, dispatched = {}, {}
handlers["window.move_to_workspace"](carried)
carried.floating, carried.tags = true, { "omarchy-floating-workspace", "omarchy-mode-floated" }
run_timers()
assert(#dispatched == 2 and dispatched[1].x == 2304, "a carried window takes the saved size")
-- One floating already (back from the dock) keeps its size but is fitted.
local docked = window("docked", 4000, -1800, 1600, 800)
windows, timers, dispatched = { docked }, {}, {}
handlers["window.move_to_workspace"](docked)
run_timers()
assert(#dispatched == 1 and dispatched[1].kind == "move" and dispatched[1].x == 3008, "a window back from the dock is fitted")

-- Leaving fullscreen fits a floating window, and sizes one Omarchy floats then.
local maximized = window("max", 4000, -1800, 1600, 800, { fullscreen = 1 })
windows, timers, dispatched = { maximized }, {}, {}
handlers["window.fullscreen"](maximized)
run_timers()
assert(#dispatched == 0, "entering fullscreen leaves the window alone")
handlers["window.fullscreen"](maximized)
maximized.fullscreen = 0
run_timers()
assert(#dispatched == 1 and dispatched[1].x == 3008, "leaving fullscreen fits the window to its screen")
local unfull = window("unfull", 0, -1800, 1100, 760, { floating = false, tags = { "omarchy-floating-workspace" } })
windows, timers, dispatched = { unfull }, {}, {}
handlers["window.fullscreen"](unfull)
unfull.floating, unfull.tags = true, { "omarchy-floating-workspace", "omarchy-mode-floated" }
run_timers()
assert(dispatched[1].kind == "resize" and dispatched[1].x == 2304, "a window Omarchy floats after fullscreen takes the saved size")

assert(floating.reset():find("Omarchy's size", 1, true), "reset")
assert(#enabled_rules() == 0, "reset turns the rules off")
assert(io.open(state) == nil, "reset removes the file")
assert(floating.reset():find("Omarchy's size", 1, true), "resetting again is fine")

assert(os.execute("rm -rf '" .. temporary .. "'"))
print("floating windows: all checks passed")
