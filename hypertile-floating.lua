-- Window size and placement on Omarchy's floating workspaces (the triangle
-- in the bar).
--
-- Omarchy opens a window there at min(1100, 64%) x min(760, 68%) of the
-- monitor, with no setting. A floating window the user has sized can be
-- saved as the default instead. It is kept as a share of the monitor, so it
-- carries across scales and the halves of a split screen. A rule matching
-- the tag Omarchy's open rule gives the window replaces that rule's size and
-- position: Hyprland applies the last matching rule, and rechecks rules that
-- match on a tag after the first pass sets tags, so this one still wins
-- when Omarchy registers another open rule later. Every other way Omarchy
-- floats a window (a workspace starting to float, a window carried in or
-- leaving fullscreen, the arrangement a config load makes) gets the same
-- size.
--
-- Hyprland moves a floating window by its monitor's offset when the
-- workspace changes monitor. It never brings the window back inside a screen
-- that shrank, rescaled, or came back elsewhere, so changing the monitor
-- input could leave windows half off the screen. After a display change,
-- windows on a floating workspace are fitted back inside their monitor. A
-- window shrunk to fit a screen it was passing through gets its size back
-- once a screen it fits on returns.

local M = {}

local OPENED_TAG = "omarchy-mode-opened"
local FLOATED_TAG = "omarchy-mode-floated"
local WORKSPACE_TAG = "omarchy-floating-workspace"
local RULE = "hypertile-floating-open-"
local STEPS = 5
-- Hyprland's stand-in while no real monitor is connected.
local FALLBACK = "FALLBACK"
-- The smallest share saved; smaller is more likely a mistake than a choice.
local MIN_SHARE = 0.1

local state_path, size, cascade = nil, nil, 0
-- Display state across config reloads, which start a fresh Lua state: the
-- monitors as last fitted, and the windows shrunk to fit, by address.
local display_path, display = nil, { monitors = nil, shrunk = {} }
local fit_timer
-- The size the open rules carry, and the one rule of them enabled.
local ruled, enabled_step = nil, nil
-- Windows Omarchy had claimed before this config load arranged them.
local claimed_before_load

local function quote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function json()
  return require("hypr.hypertile-json")
end

local function has_tag(window, tag)
  for _, t in ipairs(window.tags or {}) do
    if t == tag or t == tag .. "*" then return true end
  end
  return false
end
M.has_tag = has_tag

local function round(n)
  return math.floor(n + 0.5)
end

-- The monitor in layout coordinates, as rule expressions see it
-- (monitor_w, monitor_h), and the part of it the bar leaves free for a
-- window box. A title bar is drawn above the box, so it takes from the top.
function M.area(monitor, titlebar)
  if not monitor or not monitor.width or not monitor.scale or monitor.scale <= 0 then return nil end
  -- Rounded: a scale of 4/3 comes back as 1.33333337, a hair under 4608.
  local w = round(monitor.width / monitor.scale)
  local h = round(monitor.height / monitor.scale)
  if (monitor.transform or 0) % 2 == 1 then w, h = h, w end
  local r = monitor.reserved or {}
  local left, right, top, bottom = r.left or 0, r.right or 0, (r.top or 0) + (titlebar or 0), r.bottom or 0
  return {
    x = monitor.x + left, y = monitor.y + top,
    w = w - left - right, h = h - top - bottom,
    monitor_w = w, monitor_h = h,
  }
end

-- A box moved, and if it has to be shrunk, to lie inside the area.
function M.fit(box, area)
  local w, h = math.min(box.w, area.w), math.min(box.h, area.h)
  local x = math.max(area.x, math.min(box.x, area.x + area.w - w))
  local y = math.max(area.y, math.min(box.y, area.y + area.h - h))
  return { x = x, y = y, w = w, h = h }
end

local function offset(step)
  return step * 24 - 48
end

-- The box a saved size gives a window on this area, centered and stepped
-- like Omarchy's own cascade so windows opened in a row do not stack.
function M.open_box(saved, area, step)
  local w = round(area.monitor_w * saved.width)
  local h = round(area.monitor_h * saved.height)
  return M.fit({
    x = area.x + round((area.w - w) / 2) + offset(step or 0),
    y = area.y + round((area.h - h) / 2) + offset(step or 0),
    w = w, h = h,
  }, area)
end

function M.valid(saved)
  return type(saved) == "table"
    and type(saved.width) == "number" and saved.width >= MIN_SHARE and saved.width <= 1
    and type(saved.height) == "number" and saved.height >= MIN_SHARE and saved.height <= 1
end

-- The share of its monitor a window covers, to two decimal places of a percent.
function M.share(window)
  local area = M.area(window.monitor)
  if not area or not window.size then return nil end
  local function part(n, of) return math.min(1, round(n / of * 10000) / 10000) end
  return { width = part(window.size.x, area.monitor_w), height = part(window.size.y, area.monitor_h) }
end

function M.describe(saved)
  if not M.valid(saved) then return "Omarchy's size" end
  return string.format("%d%% × %d%% of the screen", round(saved.width * 100), round(saved.height * 100))
end

local function read_json(path)
  local file = path and io.open(path, "r")
  if not file then return nil end
  local text = file:read("a")
  file:close()
  local ok, value = pcall(json().decode, text)
  return ok and value or nil
end

-- Write through a temporary file, so a failed write leaves the old one whole.
local function write_json(path, value)
  local tmp = path .. ".tmp"
  local file, err = io.open(tmp, "w")
  if not file then return nil, err end
  local wrote, write_err = file:write(json().encode(value), "\n")
  local closed, close_err = file:close()
  if not wrote or not closed then
    os.remove(tmp)
    return nil, write_err or close_err
  end
  local ok, rename_err = os.rename(tmp, path)
  if not ok then
    os.remove(tmp)
    return nil, rename_err
  end
  return true
end

local function same_size(a, b)
  return a ~= nil and b ~= nil and a.width == b.width and a.height == b.height
end

-- One rule per cascade step, only the current one enabled. Hyprland adds a
-- named rule's effects to the ones it has, so the effects are only written
-- when the size changes; stepping just moves which rule is enabled. The
-- expressions are in the monitor's layout coordinates and center on the
-- whole monitor; the bar's strip is left free once the window is up.
local function sync_rule()
  if not hl.window_rule then return end
  if not size then
    if ruled then
      for step = 0, STEPS - 1 do hl.window_rule({ name = RULE .. step, enabled = false }) end
    end
    ruled, enabled_step = nil, nil
    return
  end
  if not same_size(ruled, size) then
    local w = string.format("monitor_w*%.4f", size.width)
    local h = string.format("monitor_h*%.4f", size.height)
    for step = 0, STEPS - 1 do
      hl.window_rule({
        name = RULE .. step,
        enabled = step == cascade,
        match = { tag = OPENED_TAG },
        size = w .. " " .. h,
        move = string.format("(monitor_w-%s)/2+(%d) (monitor_h-%s)/2+(%d)", w, offset(step), h, offset(step)),
      })
    end
    ruled, enabled_step = { width = size.width, height = size.height }, cascade
    return
  end
  if enabled_step ~= cascade then
    hl.window_rule({ name = RULE .. enabled_step, enabled = false })
    hl.window_rule({ name = RULE .. cascade, enabled = true })
    enabled_step = cascade
  end
end

-- The next window opened or floated takes the next step.
local function advance()
  cascade = (cascade + 1) % STEPS
  sync_rule()
end

-- A floating resize keeps the window's center where it was, so the move
-- always follows a resize to put the corner where it belongs.
local function set_box(window, box)
  local target = "address:" .. window.address
  local resized = box.w ~= window.size.x or box.h ~= window.size.y
  if resized then
    hl.dispatch(hl.dsp.window.resize({ x = box.w, y = box.h, relative = false, window = target }))
  end
  if resized or box.x ~= window.at.x or box.y ~= window.at.y then
    hl.dispatch(hl.dsp.window.move({ x = box.x, y = box.y, relative = false, window = target }))
  end
end

-- Omarchy's title bars (hyprbars) sit on windows tagged as on a floating
-- workspace, outside the box Hyprland reports for the window.
local function titlebar(window)
  if not has_tag(window, WORKSPACE_TAG) or not hl.get_config then return 0 end
  local ok, enabled = pcall(hl.get_config, "plugin.hyprbars.enabled")
  if not ok or enabled ~= true then return 0 end
  local found, height = pcall(hl.get_config, "plugin.hyprbars.bar_height")
  return found and tonumber(height) or 0
end

-- Only mapped floating windows on a numbered workspace of a real monitor,
-- not fullscreen, are moved. The dock's minimized windows wait on a special
-- workspace; a window on the fallback output is between screens.
local function movable(window)
  local ws = window and window.workspace and tonumber(window.workspace.id)
  return window and window.address and window.floating and window.mapped ~= false
    and not window.hidden and (window.fullscreen or 0) == 0 and window.at and window.size
    and ws ~= nil and ws >= 1 and window.monitor and window.monitor.name ~= FALLBACK
end

local function by_address(address)
  for _, window in ipairs(hl.get_windows()) do
    if window.address == address then return window end
  end
  return nil
end

local function save_display()
  if display_path then write_json(display_path, display) end
end

-- What a display change is measured against: every monitor's place, size,
-- scale, rotation and reserved edges.
function M.monitors_signature()
  if not hl.get_monitors then return nil end
  local parts = {}
  for _, m in ipairs(hl.get_monitors()) do
    local r = m.reserved or {}
    parts[#parts + 1] = string.format("%s:%d,%d,%dx%d@%.4f/%d/%d,%d,%d,%d", tostring(m.name), m.x or 0, m.y or 0,
      m.width or 0, m.height or 0, m.scale or 1, m.transform or 0, r.top or 0, r.bottom or 0, r.left or 0, r.right or 0)
  end
  table.sort(parts)
  return table.concat(parts, ";")
end

-- Give a window the mode just floated the saved size, at the cascade's step.
function M.place(window)
  if not size then return M.keep(window) end
  if not movable(window) then return false end
  local area = M.area(window.monitor, titlebar(window))
  if not area then return false end
  set_box(window, M.open_box(size, area, cascade))
  advance()
  return true
end

-- Fit one window inside its monitor's free area; true when it changed. A
-- window shrunk earlier is fitted at the size it had before, so it grows
-- back when the screen allows, unless it has been resized since.
function M.keep(window)
  if not movable(window) then return false end
  local area = M.area(window.monitor, titlebar(window))
  if not area or area.w <= 0 or area.h <= 0 then return false end
  local address = window.address
  local want_w, want_h = window.size.x, window.size.y
  local memo = display.shrunk[address]
  if memo then
    if memo.fw == want_w and memo.fh == want_h then
      want_w, want_h = memo.w, memo.h
    else
      display.shrunk[address], memo = nil, nil
      save_display()
    end
  end
  local fitted = M.fit({ x = window.at.x, y = window.at.y, w = want_w, h = want_h }, area)
  if fitted.w < want_w or fitted.h < want_h then
    display.shrunk[address] = { w = want_w, h = want_h, fw = fitted.w, fh = fitted.h }
    save_display()
  elseif memo then
    display.shrunk[address] = nil
    save_display()
  end
  if fitted.x == window.at.x and fitted.y == window.at.y and fitted.w == window.size.x and fitted.h == window.size.y then
    return false
  end
  set_box(window, fitted)
  return true
end

-- A window just opened by Omarchy's rule. The rule floats most windows at
-- the saved size, but an app its own tile rule holds (Chrome) opens tiled,
-- and Omarchy floats it straight after at its own size: that one takes the
-- saved size at the step the rule would have used. Either way the window is
-- kept off the bar, as the rule centers on the whole monitor.
function M.opened(window, step)
  if size and movable(window) then
    local area = M.area(window.monitor, titlebar(window))
    if area then
      local box = M.open_box(size, area, step)
      -- Hyprland rounds the rule's size its own way, so a pixel either way is the rule's.
      if math.abs(window.size.x - box.w) > 1 or math.abs(window.size.y - box.h) > 1 then
        set_box(window, box)
        return true
      end
    end
  end
  return M.keep(window)
end

function M.keep_all()
  local moved, open = 0, {}
  for _, window in ipairs(hl.get_windows()) do
    open[window.address] = true
    if has_tag(window, WORKSPACE_TAG) and M.keep(window) then moved = moved + 1 end
  end
  for address in pairs(display.shrunk) do
    if not open[address] then display.shrunk[address] = nil end
  end
  display.monitors = M.monitors_signature()
  save_display()
  return moved
end

-- Display changes come in bursts (a monitor leaves, comes back, then takes
-- its scale), so the windows are fitted once the burst settles.
local function schedule_keep(delay)
  if not hl.timer then return end
  if fit_timer then fit_timer:set_enabled(false) end
  fit_timer = hl.timer(function()
    fit_timer = nil
    M.keep_all()
  end, { timeout = delay or 600, type = "oneshot" })
end
M.schedule_keep = schedule_keep

local function notify(title, body)
  if hl.exec_cmd then
    hl.exec_cmd("notify-send --app-name=Hypertile -t 4000 " .. quote(title) .. " " .. quote(body))
  end
end

-- Save the focused floating window's size as the default. Returns a line
-- for the CLI; with notice, also says it on screen (the keybinding).
function M.save_active(notice)
  local window = hl.get_active_window()
  local function fail(message)
    if notice then notify("Floating window size not saved", message) end
    return "error: " .. message
  end
  if not window then return fail("No window is focused.") end
  if not window.floating or (window.fullscreen or 0) ~= 0 then
    return fail("Focus a floating window sized the way new ones should open.")
  end
  local saved = M.share(window)
  if not M.valid(saved) then return fail("That window is too small to use as the default.") end
  if not state_path then return fail("Hypertile has not finished loading.") end
  os.execute("mkdir -p " .. quote(state_path:match("^(.*)/[^/]*$")))
  local ok, err = write_json(state_path, saved)
  if not ok then return fail("Could not save the size: " .. tostring(err)) end
  size = saved
  sync_rule()
  local line = "New windows on floating workspaces open at " .. M.describe(saved) .. "."
  if notice then notify("Floating window size saved", line) end
  return line
end

-- A missing file is already reset; any other failure leaves the size in use.
function M.reset()
  if state_path then
    local ok, err, code = os.remove(state_path)
    if not ok and code ~= 2 then return "error: Could not reset the size: " .. tostring(err) end
  end
  size = nil
  sync_rule()
  return "New windows on floating workspaces open at Omarchy's size."
end

function M.saved()
  return size
end

-- Windows the mode has claimed, by address, before it changes anything.
function M.claimed()
  local out = {}
  if not hl.get_windows then return out end
  for _, window in ipairs(hl.get_windows()) do
    if has_tag(window, FLOATED_TAG) then out[window.address] = true end
  end
  return out
end

-- After Omarchy floats windows: size the ones it claimed just now.
function M.claimed_since(before)
  if not size then return end
  for _, window in ipairs(hl.get_windows()) do
    if not before[window.address] and has_tag(window, FLOATED_TAG) then M.place(window) end
  end
end

-- Called as the config starts loading, before Omarchy's saved modes arrange
-- the open windows, so attach can size the windows that arrangement floats.
function M.before_load()
  claimed_before_load = M.claimed()
end

-- Omarchy rearranges a window shortly after it moves workspace or leaves
-- fullscreen. Once it has: a window it newly claimed takes the saved size,
-- and one already floating there is fitted to its screen.
local function after_omarchy(window)
  local address, was_claimed = window.address, has_tag(window, FLOATED_TAG)
  hl.timer(function()
    local now = by_address(address)
    if not now then return end
    if not was_claimed and has_tag(now, FLOATED_TAG) then
      M.place(now)
    elseif has_tag(now, WORKSPACE_TAG) then
      M.keep(now)
    end
  end, { timeout = 20, type = "oneshot" })
end

-- Run on every config load (Hyprland starts a fresh Lua state each time),
-- after Omarchy has registered its open rules and arranged the windows.
function M.attach(state_home, runtime_dir)
  state_path = state_home .. "/hypertile/floating-size.json"
  size, cascade, ruled, enabled_step = nil, 0, nil, nil
  local saved = read_json(state_path)
  if M.valid(saved) then size = { width = saved.width, height = saved.height } end
  sync_rule()

  -- Without a runtime directory the display state lasts until the next load.
  display_path = nil
  if runtime_dir and runtime_dir ~= "" then
    os.execute("mkdir -p " .. quote(runtime_dir .. "/hypertile"))
    display_path = runtime_dir .. "/hypertile/floating-display.json"
  end
  local kept = read_json(display_path)
  display = {
    monitors = type(kept) == "table" and type(kept.monitors) == "string" and kept.monitors or nil,
    shrunk = type(kept) == "table" and type(kept.shrunk) == "table" and kept.shrunk or {},
  }

  if claimed_before_load then
    M.claimed_since(claimed_before_load)
    claimed_before_load = nil
  end
  if not hl.on then return end

  hl.on("window.open", function(window)
    if not has_tag(window, OPENED_TAG) then return end
    -- The rule placed this window at the current step; the next one steps on.
    local step = cascade
    advance()
    local address = window.address
    hl.timer(function() M.opened(by_address(address), step) end, { timeout = 1, type = "oneshot" })
  end)
  hl.on("window.move_to_workspace", after_omarchy)
  hl.on("window.fullscreen", after_omarchy)

  for _, event in ipairs({ "monitor.added", "monitor.removed", "monitor.layout_changed" }) do
    hl.on(event, function() schedule_keep() end)
  end
  -- A monitor coming back reloads the config, which drops the watchers above
  -- and any fit they had scheduled. A reload with the same monitors as the
  -- last fit leaves windows where the user put them.
  local now = M.monitors_signature()
  if display.monitors == nil then
    display.monitors = now
    save_display()
  elseif display.monitors ~= now then
    schedule_keep()
  end
end

-- SUPER+ALT+SHIFT+Home, next to Omarchy's SUPER+ALT+Home that saves a
-- window's width.
function M.bind()
  o.bind("SUPER + ALT + SHIFT + Home", "Save floating window size as default", function()
    M.save_active(true)
  end)
end

return M
