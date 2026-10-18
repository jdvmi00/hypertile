-- Floating is not a Hyprland layout, and a floating workspace keeps reporting
-- the tiled layout underneath. Whether it floats is read here, from a mirror
-- of Omarchy's own record, which is private to its module.

local M = {}

local modes, default_mode = {}, nil
local omarchy_workspace_mode, wrapped
local rules_dir, shell_bin

local function quote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

-- Omarchy leaves named and special workspaces as they are.
local function numbered(ws)
  return tostring(ws):match("^[1-9]%d*$") ~= nil
end

function M.floating(ws)
  if not numbered(ws) then return false end
  local mode = modes[tostring(ws)]
  if mode ~= nil then return mode == "floating" end
  return default_mode == "floating"
end

local function pick_rule(rule)
  local ws = tostring(rule.workspace)
  if omarchy_workspace_mode and numbered(ws) then omarchy_workspace_mode({ workspace = ws, mode = rule.layout }) end
  modes[ws] = rule.layout
  return hl.workspace_rule(rule)
end

-- Run rule source from the bridge's rule_source as the user's pick for its
-- workspace, which ends Omarchy's floating mode there.
function M.pick(source, chunkname)
  local picking = setmetatable({ workspace_rule = pick_rule }, { __index = hl })
  local env = setmetatable({ hl = picking }, { __index = _G })
  local chunk, err = load(source, chunkname or "=hypertile-pick", "t", env)
  if not chunk then error(err, 0) end
  return chunk()
end

local function written(dir)
  local out = {}
  local handle = io.popen("find " .. quote(dir) .. " -maxdepth 1 -type f -name '*.lua' -printf '%T@ %f\\n' 2>/dev/null")
  if not handle then return out end
  for line in handle:lines() do
    local at, name = line:match("^(%S+) (.+)%.lua$")
    if name then out[name] = tonumber(at) end
  end
  handle:close()
  return out
end

local function read(path)
  local file = io.open(path, "r")
  if not file then return "" end
  local text = file:read("a")
  file:close()
  return text
end

-- Before the wrapper existed, Omarchy's toggle left hypertile's rule behind,
-- so a workspace could have both files. The newer one was the user's pick.
-- Since then a pair only means omarchy-hyprland-workspace-layout-default kept
-- a busy workspace as it was, and hypertile's rule stands.
local function migrate(state_home, omarchy_dir, ours, theirs)
  local done = state_home .. "/hypertile/omarchy-modes-migrated"
  local marker = io.open(done, "r")
  if marker then
    marker:close()
    return
  end
  for ws, at in pairs(theirs) do
    if numbered(ws) and ours[ws] then
      if ours[ws] > at then
        os.remove(omarchy_dir .. "/" .. ws .. ".lua")
        modes[ws] = nil
      else
        os.remove(rules_dir .. "/" .. ws .. ".lua")
      end
    end
  end
  os.execute("mkdir -p " .. quote(state_home .. "/hypertile"))
  marker = io.open(done, "w")
  if marker then marker:close() end
end

-- Run once per config load, after Omarchy's saved modes have loaded and
-- before hypertile's rules apply. The mirror reads each mode as Omarchy's
-- saved call passes it to o.workspace_mode.
function M.attach(state_home)
  modes, default_mode = {}, nil
  rules_dir = state_home .. "/hypertile/workspace-rules"
  shell_bin = os.getenv("HYPERTILE_SHELL_BIN") or "omarchy-shell"
  local omarchy_dir = state_home .. "/omarchy/workspace-layouts"
  local theirs = written(omarchy_dir)
  for name in pairs(theirs) do
    local text = read(omarchy_dir .. "/" .. name .. ".lua")
    if name == "default" then
      default_mode = text:match('default = "([^"]*)"')
    elseif numbered(name) then
      modes[name] = text:match('mode = "([^"]*)"')
    end
  end
  migrate(state_home, omarchy_dir, written(rules_dir), theirs)
  if type(o) ~= "table" or type(o.workspace_mode) ~= "function" or o.workspace_mode == wrapped then return end
  omarchy_workspace_mode = o.workspace_mode
  -- Omarchy's toggle reaches this through hyprctl eval.
  wrapped = function(spec)
    omarchy_workspace_mode(spec)
    if spec.default then
      default_mode = spec.default
      return
    end
    local ws = tostring(spec.workspace)
    modes[ws] = spec.mode
    os.remove(rules_dir .. "/" .. ws .. ".lua")
    hl.exec_cmd(quote(shell_bin) .. " -q hypertile-bar refresh")
  end
  o.workspace_mode = wrapped
end

return M
