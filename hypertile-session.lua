-- Compositor side of session recovery. Persistence and launching belong to
-- hypertile-session (the external service); this module only reads/applies
-- desktop state. Calls enter through hyprctl eval on the compositor thread.
local modname = ... or "hypertile-session"
local prefix = modname:match("^(.-)hypertile%-session$") or ""
local engine = require(prefix .. "hypertile")
local json = require(prefix .. "hypertile-json")
local M = {}

local function selector(ws)
  if ws.special then return ws.name end
  if ws.id > 0 then return tostring(ws.id) end
  return "name:" .. ws.name
end

function M.snapshot()
  local out = { windows = json.array(), workspaces = json.array(), layouts = {}, monitors = json.array() }
  for _, mon in ipairs(hl.get_monitors()) do
    out.monitors[#out.monitors + 1] = { name = mon.name, x = mon.x, y = mon.y }
  end
  for _, ws in ipairs(hl.get_workspaces()) do
    local name = ws.tiled_layout:match("^lua:(.+)$")
    local live = name and engine.live[name]
    out.workspaces[#out.workspaces + 1] = {
      id = ws.id, selector = selector(ws), layout = ws.tiled_layout,
      monitor = ws.monitor and ws.monitor.name, visible = ws.visible, special = ws.special,
      order = json.array(live and live.orders[tostring(ws.id)] or {}),
    }
    if live then
      out.layouts[name] = { spec = live.spec, sizes = live.state.sizes }
    end
  end
  for _, win in ipairs(hl.get_windows()) do
    if win.mapped and win.workspace then
      local name = win.workspace.tiled_layout:match("^lua:(.+)$")
      local live = name and engine.live[name]
      out.windows[#out.windows + 1] = {
        address = win.address, stable_id = win.stable_id, pid = win.pid, class = win.class, title = win.title,
        initial_class = win.initial_class, initial_title = win.initial_title,
        workspace = selector(win.workspace), monitor = win.monitor and win.monitor.name,
        at = win.at, size = win.size, floating = win.floating, pinned = win.pinned,
        fullscreen = win.fullscreen, fullscreen_client = win.fullscreen_client,
        pin = live and live.state.pins[win.address], grouped = win.group ~= nil,
      }
    end
  end
  -- Empty workspaces do not give layout callbacks a window from which to
  -- identify the workspace. Filter their cached order against live windows.
  local tiled = {}
  for _, win in ipairs(out.windows) do
    if not win.floating then tiled[win.address] = win.workspace end
  end
  for _, ws in ipairs(out.workspaces) do
    local order = json.array()
    for _, address in ipairs(ws.order) do
      if tiled[address] == ws.selector then order[#order + 1] = address end
    end
    ws.order = order
  end
  local active = hl.get_active_window()
  local ws = hl.get_active_workspace()
  out.active = active and active.address
  out.workspace = ws and selector(ws)
  table.sort(out.windows, function(a, b) return a.address < b.address end)
  table.sort(out.workspaces, function(a, b) return a.selector < b.selector end)
  table.sort(out.monitors, function(a, b) return a.name < b.name end)
  return out
end

local function dispatch(fn, args)
  local result = hl.dispatch(fn(args))
  if type(result) == "table" and result.error then error(result.error) end
end

function M.prepare(snapshot)
  local bridge = require(prefix .. "hypertile-bridge")
  for name, saved in pairs(snapshot.layouts) do
    engine.layout(name, saved.spec)
    engine.state[name].sizes = saved.sizes
  end
  for _, ws in ipairs(snapshot.workspaces) do
    local name = ws.layout:match("^lua:(.+)$")
    local saved = name and snapshot.layouts[name]
    assert(load(bridge.rule_source(ws.layout, ws.selector, saved and saved.spec), "=session-workspace", "t"))()
  end
  return true
end

-- Apply one matched window, without changing focus. Window IDs are supplied
-- by the service's match result, never reused across compositor instances.
function M.place(request)
  local saved, address = request.saved, request.address
  local window = "address:" .. address
  dispatch(hl.dsp.window.fullscreen_state, { window = window, internal = 0, client = 0, action = "set" })
  dispatch(hl.dsp.window.move, { window = window, workspace = saved.workspace, silent = true })
  dispatch(hl.dsp.window.float, { window = window, action = saved.floating and "on" or "off" })
  if saved.floating then
    dispatch(hl.dsp.window.resize, { window = window, x = saved.size.x, y = saved.size.y })
    dispatch(hl.dsp.window.move, { window = window, x = saved.at.x, y = saved.at.y })
    dispatch(hl.dsp.window.pin, { window = window, action = saved.pinned and "on" or "off" })
  end
  for _, live in pairs(engine.live) do live.state.pins[address] = nil end
  if saved.pin and request.layout then
    local name = request.layout:match("^lua:(.+)$")
    if name and engine.state[name] then engine.state[name].pins[address] = saved.pin end
  end
  return true
end

function M.finish(request)
  local snapshot, matches = request.snapshot, request.matches
  local monitors = {}
  for _, mon in ipairs(hl.get_monitors()) do monitors[mon.name] = true end
  for _, ws in ipairs(snapshot.workspaces) do
    local name = ws.layout:match("^lua:(.+)$")
    local live = name and engine.live[name]
    local wanted = {}
    for _, old in ipairs(ws.order) do
      if matches[old] then wanted[#wanted + 1] = matches[old] end
    end
    -- A no-op resize requests a recalculation without changing target order.
    if live and wanted[1] then
      dispatch(hl.dsp.window.resize, { window = "address:" .. wanted[1], x = 0, y = 0, relative = true })
      local current_ws
      for _, w in ipairs(hl.get_windows()) do
        if w.address == wanted[1] then current_ws = tostring(w.workspace.id) end
      end
      for i, address in ipairs(wanted) do
        local order = live.orders[current_ws] or {}
        if order[i] and order[i] ~= address then
          dispatch(hl.dsp.window.swap, { window = "address:" .. address, target = "address:" .. order[i] })
        end
      end
    end
    local populated = false
    for _, saved in ipairs(snapshot.windows) do
      if saved.workspace == ws.selector and matches[saved.address] then populated = true end
    end
    if monitors[ws.monitor] and populated then
      dispatch(hl.dsp.workspace.move, { workspace = ws.selector, monitor = ws.monitor })
    end
  end
  for _, saved in ipairs(snapshot.windows) do
    local address = matches[saved.address]
    if address then
      -- Moving a workspace between monitors also moves its floating windows.
      -- Restore their global coordinates after that move, before fullscreen.
      if saved.floating then
        local at, size = saved.at, saved.size
        if not monitors[saved.monitor] then
          for _, win in ipairs(hl.get_windows()) do
            if win.address == address and win.monitor then
              local mon = win.monitor
              local width, height = mon.width / mon.scale, mon.height / mon.scale
              size = { x = math.min(size.x, width), y = math.min(size.y, height) }
              at = { x = math.max(mon.x, math.min(at.x, mon.x + width - size.x)),
                y = math.max(mon.y, math.min(at.y, mon.y + height - size.y)) }
            end
          end
        end
        dispatch(hl.dsp.window.resize, { window = "address:" .. address, x = size.x, y = size.y })
        dispatch(hl.dsp.window.move, { window = "address:" .. address, x = at.x, y = at.y })
      end
      dispatch(hl.dsp.window.fullscreen_state, {
        window = "address:" .. address, internal = saved.fullscreen,
        client = saved.fullscreen_client, action = "set",
      })
    end
  end
  for _, ws in ipairs(snapshot.workspaces) do
    if ws.visible and not ws.special and monitors[ws.monitor] then
      dispatch(hl.dsp.focus, { workspace = ws.selector })
    end
  end
  if snapshot.active and matches[snapshot.active] then
    dispatch(hl.dsp.focus, { window = "address:" .. matches[snapshot.active] })
  elseif snapshot.workspace then
    dispatch(hl.dsp.focus, { workspace = snapshot.workspace })
  end
  return true
end

return M
