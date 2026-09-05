-- Compositor side of session recovery. Persistence and launching belong to
-- hypertile-session (the external service); this module only reads/applies
-- desktop state. Calls enter through hyprctl eval on the compositor thread.
local modname = ... or "hypertile-session"
local prefix = modname:match("^(.-)hypertile%-session$") or ""
local engine = require(prefix .. "hypertile")
local json = require(prefix .. "hypertile-json")
local M = {}
local streams = {}

local function selector(ws)
  if ws.special then return ws.name end
  if ws.id > 0 then return tostring(ws.id) end
  return "name:" .. ws.name
end

function M.snapshot()
  local out = { windows = json.array(), workspaces = json.array(), layouts = {}, monitors = json.array() }
  out.streams = json.array()
  for _, source in pairs(streams) do out.streams[#out.streams + 1] = source end
  for _, mon in ipairs(hl.get_monitors()) do
    out.monitors[#out.monitors + 1] = { name = mon.name, x = mon.x, y = mon.y }
  end
  local existing = {}
  for _, ws in ipairs(hl.get_workspaces()) do
    existing[tostring(ws.id)] = true
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
  -- The engine caches an order per workspace id and never sees a workspace
  -- go away; this query runs every few seconds, so prune here.
  for _, live in pairs(engine.live) do
    for id in pairs(live.orders or {}) do
      if not existing[id] then live.orders[id] = nil end
    end
  end
  for _, win in ipairs(hl.get_windows()) do
    if win.mapped and win.workspace then
      local name = win.workspace.tiled_layout:match("^lua:(.+)$")
      local live = name and engine.live[name]
      local source
      for id, s in pairs(streams) do
        if s.address == win.address and s.pid == win.pid and s.stable_id == win.stable_id then source = id end
      end
      out.windows[#out.windows + 1] = {
        address = win.address, stable_id = win.stable_id, pid = win.pid, class = win.class, title = win.title,
        initial_class = win.initial_class, initial_title = win.initial_title,
        workspace = selector(win.workspace), monitor = win.monitor and win.monitor.name,
        at = win.at, size = win.size, floating = win.floating, pinned = win.pinned,
        fullscreen = win.fullscreen, fullscreen_client = win.fullscreen_client,
        pin = live and live.state.pins[win.address], grouped = win.group ~= nil,
        stream = source,
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

local function stream_target(request)
  for _, ws in ipairs(hl.get_workspaces()) do
    if selector(ws) == request.workspace then
      if ws.tiled_layout ~= request.layout then error("assignment-invalid: workspace layout changed") end
      local live = engine.live[request.layout:match("^lua:(.+)$")]
      if not live or not live.compiled.leaf_set[request.zone]
        or live.compiled.leaf_opts[request.zone].spacer then error("assignment-invalid: zone is missing or a spacer") end
      return ws, live
    end
  end
  error("assignment-invalid: workspace is unavailable")
end

function M.stream_check(request)
  local ws, live = stream_target(request)
  local zones = {}
  for _, s in pairs(streams) do
    if s.computer ~= request.computer and s.workspace == request.workspace then
      if s.zone == request.zone then error("zone already owned by " .. s.computer) end
      zones[s.zone] = true
    end
  end
  zones[request.zone] = true
  local available = false
  for _, name in ipairs(live.compiled.cycle) do if not zones[name] then available = true end end
  if not available then error("assignment-invalid: leave one fill zone for local windows") end
  return { workspace_id = ws.id }
end

local function refresh_workspace(ws)
  -- Target a window explicitly: neither this nor session.place changes focus.
  for _, w in ipairs(hl.get_windows()) do
    if w.mapped and w.workspace and w.workspace.id == ws.id and not w.floating and (w.fullscreen or 0) == 0 then
      dispatch(hl.dsp.window.resize, { window = "address:" .. w.address, x = 0, y = 0, relative = true })
      break
    end
  end
end

function M.stream_release(request)
  local old = streams[request.computer]
  if not old then return true end
  streams[request.computer] = nil
  if hl.window_rule then
    hl.window_rule({ name = "hypertile-stream-" .. request.computer, enabled = false })
  end
  for _, live in pairs(engine.live) do
    local reservations = live.state.reservations or {}
    local slots = reservations[tostring(old.workspace_id)]
    if slots then slots[old.zone] = nil end
    if old.address then live.state.pins[old.address] = nil end
  end
  for _, ws in ipairs(hl.get_workspaces()) do
    if ws.id == old.workspace_id then refresh_workspace(ws) end
  end
  return true
end

function M.stream_assign(request)
  local checked = M.stream_check(request)
  local ws, live = stream_target(request)
  local found
  if request.address then
    for _, w in ipairs(hl.get_windows()) do
      if w.address == request.address and w.pid == request.pid and w.stable_id == request.stable_id
        and w.class == "com.moonlight_stream.Moonlight" and w.title == request.title then found = w end
    end
    if not found then error("stream window identity changed") end
  end
  M.stream_release(request)
  request.workspace_id = checked.workspace_id
  streams[request.computer] = request
  if hl.window_rule and request.title then
    -- Launch rules can be consumed by Moonlight's temporary renderer window.
    -- Cover the subsequent host-titled window while this source is assigned.
    local title = request.title:gsub("([^%w _%-])", "\\%1")
    hl.window_rule({ name = "hypertile-stream-" .. request.computer, enabled = true,
      match = { class = "^com\\.moonlight_stream\\.Moonlight$", title = "^" .. title .. "$" },
      workspace = request.workspace .. " silent", no_initial_focus = true,
      suppress_event = "fullscreen maximize activate activatefocus fullscreenoutput" })
  end
  live.state.reservations = live.state.reservations or {}
  local key = tostring(ws.id)
  live.state.reservations[key] = live.state.reservations[key] or {}
  live.state.reservations[key][request.zone] = request.address or true
  if found then
    -- Clear startup fullscreen once. Reconciliation must not undo a later
    -- explicit compositor fullscreen action on the already placed window.
    if not request.placed or selector(found.workspace) ~= request.workspace or found.floating then
      M.place({ address = found.address, layout = request.layout,
        saved = { workspace = request.workspace, pin = request.zone, floating = false } })
    end
    live.state.pins[found.address] = request.zone
  end
  refresh_workspace(ws)
  return true
end

function M.stream_focus(request)
  local s = streams[request.computer]
  if not s or not s.address then error("stream has no ready window") end
  for _, w in ipairs(hl.get_windows()) do
    if w.address == s.address and w.pid == s.pid and w.stable_id == s.stable_id then
      dispatch(hl.dsp.focus, { window = "address:" .. w.address })
      return true
    end
  end
  error("stream window has closed")
end

function M.stream_launch(request)
  M.stream_check(request)
  -- exec preserves the PID through the small launcher and into Moonlight,
  -- so Hyprland's launch rules apply to this process only.
  local result = hl.dispatch(hl.dsp.exec_cmd(request.command, {
    workspace = request.workspace .. " silent", no_initial_focus = true,
    suppress_event = "fullscreen maximize activate activatefocus fullscreenoutput",
  }))
  if type(result) == "table" and result.error then error(result.error) end
  return true
end

function M.stream_inhibit(request)
  local s = streams[request.computer]
  if not s or not s.address then return false end
  for _, w in ipairs(hl.get_windows()) do
    if w.address == s.address and w.pid == s.pid and w.stable_id == s.stable_id then
      dispatch(hl.dsp.window.set_prop, { window = "address:" .. w.address, prop = "idle_inhibit",
        value = request.enabled and "always" or "none" })
      return true
    end
  end
  return false
end

-- A layout that still exists keeps its current definition: the user may have
-- edited it since the snapshot, and silently reverting to the saved spec
-- until the next reload would be surprising. Only a layout that no longer
-- exists is re-registered from the snapshot so its workspaces can be rebuilt.
local function current_spec(name, saved)
  local live = engine.live[name]
  if live then return live.spec end
  return saved and saved.spec
end

function M.prepare(snapshot)
  local bridge = require(prefix .. "hypertile-bridge")
  for name, saved in pairs(snapshot.layouts) do
    if not engine.live[name] then
      engine.layout(name, saved.spec)
    end
    engine.state[name].sizes = saved.sizes
  end
  for _, ws in ipairs(snapshot.workspaces) do
    local name = ws.layout:match("^lua:(.+)$")
    local spec = name and current_spec(name, snapshot.layouts[name])
    assert(load(bridge.rule_source(ws.layout, ws.selector, spec), "=session-workspace", "t"))()
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

-- Reorder a workspace's tiled windows so that the matched ones sit in their
-- saved sequence. The compositor's order is read once, from the engine's
-- cache, and then tracked locally through each swap: whether the compositor
-- recalculates synchronously after a swap is not something to depend on.
local function reorder(live, wanted, warnings, label)
  dispatch(hl.dsp.window.resize, { window = "address:" .. wanted[1], x = 0, y = 0, relative = true })
  local current_ws
  for _, w in ipairs(hl.get_windows()) do
    if w.address == wanted[1] and w.workspace then current_ws = tostring(w.workspace.id) end
  end
  local order, index = {}, {}
  for i, address in ipairs(live.orders[current_ws] or {}) do
    order[i], index[address] = address, i
  end
  for _, address in ipairs(wanted) do
    if not index[address] then
      warnings[#warnings + 1] = "workspace " .. label .. ": window order not restored (order cache is stale)"
      return
    end
  end
  for i, address in ipairs(wanted) do
    local occupant = order[i]
    if occupant ~= address then
      dispatch(hl.dsp.window.swap, { window = "address:" .. address, target = "address:" .. occupant })
      local from = index[address]
      order[i], order[from] = address, occupant
      index[address], index[occupant] = i, from
    end
  end
end

function M.finish(request)
  local snapshot, matches = request.snapshot, request.matches
  local warnings = json.array()
  local monitors = {}
  for _, mon in ipairs(hl.get_monitors()) do monitors[mon.name] = true end
  for _, ws in ipairs(snapshot.workspaces) do
    local name = ws.layout:match("^lua:(.+)$")
    local live = name and engine.live[name]
    local wanted = {}
    for _, old in ipairs(ws.order) do
      if matches[old] then wanted[#wanted + 1] = matches[old] end
    end
    if live and wanted[1] then
      reorder(live, wanted, warnings, ws.selector)
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
  return { warnings = warnings }
end

return M
