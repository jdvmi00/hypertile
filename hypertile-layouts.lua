-- Load every hypertile layout in ~/.config/hypr/layouts/*.lua (sorted).
-- Each file registers one layout with hypertile.layout("<name>", {...}).
-- Required from hyprland.lua; re-run on every reload so saved layouts
-- appear without editing this file.

local paths = require("default.hypr.paths")
local require_all = require("default.hypr.require_all")

local layouts_dir = paths.config_home .. "/hypr/layouts"

require_all.files(layouts_dir, "hypr.layouts", { reload = true })

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

-- The service holds an exclusive writer lock, so reloads cannot create a
-- second watcher or trigger a second restore. Start after workspace rules.
if hl.timer then
  hl.timer(function()
    local command = (os.getenv("HOME") or "") .. "/.local/bin/hypertile-session"
    local f = io.open(command, "r")
    if f then
      f:close()
      hl.exec_cmd("'" .. command:gsub("'", "'\\''") .. "' daemon")
    end
  end, { timeout = 1000, type = "oneshot" })
end
