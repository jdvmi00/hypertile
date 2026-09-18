-- Load every hypertile layout in ~/.config/hypr/layouts/*.lua (sorted).
-- Each file registers one layout with hypertile.layout("<name>", {...}).
-- Required from hyprland.lua; re-run on every reload so saved layouts
-- appear without editing this file.

local paths = require("default.hypr.paths")

local layouts_dir = paths.config_home .. "/hypr/layouts"

-- A hand-edited layout must not abort the rest of hyprland.lua. Keep the
-- sorted/reload behavior of require_all, but isolate each file's failure.
local function quote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end
local files = io.popen("find " .. quote(layouts_dir)
  .. " -maxdepth 1 -type f -name '*.lua' -printf '%f\\n' 2>/dev/null | sort")
if files then
  for filename in files:lines() do
    local module = "hypr.layouts." .. filename:gsub("%.lua$", "")
    package.loaded[module] = nil
    local ok, err = pcall(require, module)
    if not ok then
      local message = filename .. ": " .. tostring(err)
      print("hypertile: " .. message)
      if hl.exec_cmd then
        hl.exec_cmd("notify-send --app-name=Hypertile 'Layout could not load' " .. quote(message))
      end
    end
  end
  files:close()
end

-- Persisted workspace rules written by `hypertile-ctl apply`. They are read
-- with io.open on purpose: files the config requires are watched by the
-- compositor, and writing a watched file reloads the whole config. They are
-- applied once the config has finished loading, so the global gaps and
-- rounding they refer to are the user's values, not the defaults.
local state_home = os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")
local rules_dir = state_home .. "/hypertile/workspace-rules"

local function apply_persisted_rules()
  local quoted_dir = "'" .. rules_dir:gsub("'", "'\\''") .. "'"
  local handle = io.popen("find " .. quoted_dir .. " -maxdepth 1 -type f -name '*.lua' -printf '%f\\n' 2>/dev/null | sort -V")
  if not handle then
    return
  end
  for filename in handle:lines() do
    local f = io.open(rules_dir .. "/" .. filename, "r")
    if f then
      local text = f:read("a")
      f:close()
      local chunk, err = load(text, "=hypertile-rule:" .. filename, "t")
      if chunk then
        local ok, rerr = pcall(chunk)
        if not ok then
          print("hypertile: workspace rule " .. filename .. " failed: " .. tostring(rerr))
        end
      else
        print("hypertile: workspace rule " .. filename .. " does not parse: " .. tostring(err))
      end
    end
  end
  handle:close()
end
-- Timers fire only after the config chunk has finished, so the shortest
-- one-shot is enough to run after looknfeel.lua has set the globals.
if hl.timer then
  hl.timer(apply_persisted_rules, { timeout = 1, type = "oneshot" })
else
  apply_persisted_rules()
end

-- Restore confirmed display intent before either service recovers windows.
-- The display controller serializes reloads and recovers interrupted previews;
-- each long-lived service has its own single-writer guard.
if hl.timer then
  hl.timer(function()
    local bin = (os.getenv("HOME") or "") .. "/.local/bin/"
    local commands = {}
    local display = bin .. "hypertile-displays"
    local f = io.open(display, "r")
    if f then
      f:close()
      commands[#commands + 1] = quote(display) .. " restore"
      commands[#commands + 1] = "(" .. quote(display) .. " watch >/dev/null 2>&1 &)"
    end
    for _, name in ipairs({ "hypertile-scenes", "hypertile-session" }) do
      local command = bin .. name
      local service = io.open(command, "r")
      if service then
        service:close()
        commands[#commands + 1] = "(" .. quote(command) .. " daemon >/dev/null 2>&1 &)"
      end
    end
    if #commands > 0 then
      hl.exec_cmd(table.concat(commands, " && "))
    end
  end, { timeout = 500, type = "oneshot" })
end
