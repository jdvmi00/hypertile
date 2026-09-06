-- Compositor side of session recovery. Persistence and launching belong to
-- hypertile-session (the external service); this module only reads/applies
-- desktop state. Calls enter through hyprctl eval on the compositor thread.
local modname = ... or "hypertile-session"
local prefix = modname:match("^(.-)hypertile%-session$") or ""
local engine = require(prefix .. "hypertile")
local json = require(prefix .. "hypertile-json")
local M = {}
local scene_content = {}

local function selector(ws)
  if ws.special then return ws.name end
  if ws.id > 0 then return tostring(ws.id) end
  return "name:" .. ws.name
end

function M.snapshot()
  local out = { windows = json.array(), workspaces = json.array(), layouts = {}, monitors = json.array() }
  out.scene_content = scene_content
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
      local scene_app
      for workspace, scene in pairs(scene_content) do
        if workspace == selector(win.workspace) then
          for _, ref in pairs(scene.app_placements or {}) do
            if ref.address == win.address and ref.pid == win.pid and ref.stable_id == win.stable_id
              and live and live.state.pins[win.address] == ref.zone then scene_app = true end
          end
        end
      end
      out.windows[#out.windows + 1] = {
        address = win.address, stable_id = win.stable_id, pid = win.pid, class = win.class, title = win.title,
        initial_class = win.initial_class, initial_title = win.initial_title,
        workspace = selector(win.workspace), monitor = win.monitor and win.monitor.name,
        at = win.at, size = win.size, floating = win.floating, pinned = win.pinned,
        fullscreen = win.fullscreen, fullscreen_client = win.fullscreen_client,
        pin = live and live.state.pins[win.address], grouped = win.group ~= nil,
        pin_exclusive = live and live.state.exclusive_pins and live.state.exclusive_pins[win.address] or nil,
        scene_app = scene_app,
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

local function refresh_workspace(ws)
  -- Target a window explicitly: neither this nor session.place changes focus.
  for _, w in ipairs(hl.get_windows()) do
    if w.mapped and w.workspace and w.workspace.id == ws.id and not w.floating and (w.fullscreen or 0) == 0 then
      dispatch(hl.dsp.window.resize, { window = "address:" .. w.address, x = 0, y = 0, relative = true })
      break
    end
  end
end

function M.scene_layout(request)
  local bridge = require(prefix .. "hypertile-bridge")
  if request.spec then engine.layout(request.layout:match("^lua:(.+)$"), request.spec) end
  local rule = bridge.rule_source(request.workspace, request.layout, request.spec)
  assert(load(rule, "=scene-workspace", "t"))()
  return rule -- Persistence belongs to the external writer, never nested hyprctl.
end

function M.scene_clear(request)
  local old = scene_content[request.workspace]
  if not old then return true end
  local windows = {}
  for _, w in ipairs(hl.get_windows()) do windows[w.address] = w end
  local live = engine.live[old.layout:match("^lua:(.+)$")]
  if live then
    if live.state.scene_empty then live.state.scene_empty[tostring(old.workspace_id)] = nil end
    for _, p in ipairs(old.pins or {}) do
      local w = windows[p.address]
      if w and w.stable_id == p.stable_id and w.pid == p.pid and w.workspace
        and selector(w.workspace) == request.workspace and live.state.pins[p.address] == p.zone then
        live.state.pins[p.address] = p.before
        if live.state.exclusive_pins then live.state.exclusive_pins[p.address] = p.exclusive end
      end
    end
  end
  scene_content[request.workspace] = nil
  for _, ws in ipairs(hl.get_workspaces()) do if selector(ws) == request.workspace then refresh_workspace(ws) end end
  return true
end

function M.scene_content_apply(request)
  local previous = scene_content[request.workspace]
  if request.operation and previous and previous.operation == request.operation then return previous end
  local ws, live
  for _, w in ipairs(hl.get_workspaces()) do
    if selector(w) == request.workspace and w.tiled_layout == request.layout then ws = w end
  end
  if not ws and request.allow_missing_workspace and request.operation then
    for _, w in ipairs(hl.get_workspaces()) do
      assert(selector(w) ~= request.workspace, "scene workspace layout changed")
    end
    assert(request.workspace:match("^[1-9][0-9]*$"), "invalid scene workspace")
    ws = { id = tonumber(request.workspace) }
  end
  assert(ws, "scene workspace or layout changed")
  live = engine.live[request.layout:match("^lua:(.+)$")]
  assert(live, "scene requires a Hypertile layout")
  local empty, blocked = {}, {}
  for _, source in ipairs(request.sources) do
    local zone = source.zone_id and live.compiled.zone_ids[source.zone_id] or source.zone
    assert(zone and live.compiled.leaf_set[zone], "scene zone no longer exists")
    source.zone = zone
    if source.type == "empty" then empty[zone], blocked[zone] = true, true end
    assert(source.type == "local" or source.type == "app" or source.type == "empty", "unsupported scene source type")
  end
  local available = false
  for _, zone in ipairs(live.compiled.cycle) do if not blocked[zone] then available = true end end
  assert(available, "leave one fill zone for local windows")
  M.scene_clear(request)
  live.state.scene_empty = live.state.scene_empty or {}
  live.state.scene_empty[tostring(ws.id)] = empty
  live.state.exclusive_pins = live.state.exclusive_pins or {}
  local record = { workspace_id = ws.id, layout = request.layout, operation = request.operation,
    app_placements = {}, pins = json.array(), results = json.array() }
  scene_content[request.workspace] = record
  for _, source in ipairs(request.sources) do
    if source.type == "local" and source.app_class then
      local matches = {}
      for _, w in ipairs(hl.get_windows()) do
        if w.mapped and w.workspace and w.workspace.id == ws.id and not w.floating
          and w.class == source.app_class then matches[#matches + 1] = w end
      end
      local result = { zone = source.zone, status = "needs-attention", error = #matches == 0 and "Open this app on the workspace" or "More than one matching app window is open" }
      if #matches == 1 then
        local w = matches[1]
        record.pins[#record.pins + 1] = { address = w.address, pid = w.pid, stable_id = w.stable_id,
          zone = source.zone, before = live.state.pins[w.address], exclusive = live.state.exclusive_pins[w.address] }
        live.state.pins[w.address], live.state.exclusive_pins[w.address] = source.zone, true
        result.status, result.error = "ready", nil
      end
      record.results[#record.results + 1] = result
    end
  end
  refresh_workspace(ws)
  return { results = record.results, pins = record.pins }
end

-- Called once per scene operation, with a live identity rather than a class
-- dispatcher. Validation and placement happen together on the compositor thread.
function M.scene_app_place(request)
  local record = assert(scene_content[request.workspace], "Scene was superseded")
  assert(request.operation and record.operation == request.operation, "Scene was superseded")
  assert(record.layout == request.layout, "Scene layout changed")
  local live = assert(engine.live[request.layout:match("^lua:(.+)$")], "Scene layout is unavailable")
  request.zone = live.compiled.zone_ids[request.zone_id]
  assert(request.zone and not live.compiled.leaf_opts[request.zone].spacer, "Scene zone is unavailable")
  local ws
  for _, candidate in ipairs(hl.get_workspaces()) do
    if selector(candidate) == request.workspace then
      assert(candidate.tiled_layout == request.layout, "Scene workspace layout changed")
      ws = candidate
    end
  end
  local previous = record.app_placements[request.zone_id]
  if previous then return previous end
  local matches = {}
  for _, w in ipairs(hl.get_windows()) do
    if w.mapped and w.workspace and w.class == request.app_class
      and (not request.app_title or w.title == request.app_title) then matches[#matches + 1] = w end
  end
  assert(#matches == 1, "App window match changed or is ambiguous")
  local w = matches[1]
  assert(w.address == request.address and w.stable_id == request.stable_id and w.pid == request.pid,
    "App window identity changed")
  local pin = { address = w.address, stable_id = w.stable_id, pid = w.pid, zone = request.zone,
    before = live.state.pins[w.address], exclusive = (live.state.exclusive_pins or {})[w.address] }
  -- Mark consumed before dispatching. A lost IPC reply or later manual move
  -- must not turn the next call into a second placement.
  record.app_placements[request.zone_id] = pin
  record.pins[#record.pins + 1] = pin
  M.place({ address = w.address, layout = request.layout,
    saved = { workspace = request.workspace, pin = request.zone, pin_exclusive = true, floating = false } })
  if ws then refresh_workspace(ws) end
  return pin
end

function M.scene_restore_pins(request)
  for _, saved in ipairs(request.windows or {}) do
    for _, w in ipairs(hl.get_windows()) do
      if w.address == saved.address and w.stable_id == saved.stable_id and w.pid == saved.pid
        and w.workspace and selector(w.workspace) == request.workspace then
        local live = engine.live[w.workspace.tiled_layout:match("^lua:(.+)$")]
        if live and live.state.pins[w.address] == saved.zone then
          live.state.pins[w.address] = saved.before
          live.state.exclusive_pins = live.state.exclusive_pins or {}
          live.state.exclusive_pins[w.address] = saved.exclusive
        end
      end
    end
  end
  for _, ws in ipairs(hl.get_workspaces()) do if selector(ws) == request.workspace then refresh_workspace(ws) end end
  return true
end

local function swap_windows(request)
  local found = {}
  for i, ref in ipairs(request.windows) do
    for _, w in ipairs(hl.get_windows()) do
      if w.address == ref.address and w.stable_id == ref.stable_id then found[i] = w end
    end
    local w = found[i]
    assert(w and w.mapped and w.workspace and not w.floating and not w.hidden and (w.fullscreen or 0) == 0,
      "swap unavailable: window closed, moved or became fullscreen")
  end
  assert(#found == 2 and found[1].address ~= found[2].address, "swap needs two different windows")
  local ws = found[1].workspace
  assert(ws.id == found[2].workspace.id, "swap unavailable: windows must share a workspace")
  local live = engine.live[ws.tiled_layout:match("^lua:(.+)$")]
  assert(live, "swap unavailable: workspace must use Hypertile")
  return found, ws, live
end

-- Resolve actual engine assignments, including rules, pins and reservations.
-- Planning validates both windows without changing either pin.
function M.swap_plan(request)
  local windows, ws, live = swap_windows(request)
  local by_address, targets = {}, {}
  for _, w in ipairs(hl.get_windows()) do
    if w.mapped and w.workspace and w.workspace.id == ws.id and not w.floating then by_address[w.address] = w end
  end
  for _, address in ipairs(live.orders[tostring(ws.id)] or {}) do
    if by_address[address] then targets[#targets + 1] = { window = by_address[address] }; by_address[address] = nil end
  end
  assert(next(by_address) == nil, "swap unavailable: waiting for layout order")
  local reserved = {}
  for name in pairs((live.state.scene_empty or {})[tostring(ws.id)] or {}) do reserved[name] = true end
  local buckets = engine.assign(live.compiled, targets, {
    pins = live.state.pins, exclusive_pins = live.state.exclusive_pins,
    reserved = reserved,
  })
  local plan = { workspace = selector(ws), layout = ws.tiled_layout, windows = json.array() }
  for i, w in ipairs(windows) do
    local zone
    for name, bucket in pairs(buckets) do
      for _, t in ipairs(bucket) do
        if t.window.address == w.address then
          assert(#bucket == 1, "swap unavailable: use a zone containing one window")
          zone = name
        end
      end
    end
    assert(zone, "swap unavailable: window has no zone")
    plan.windows[i] = { address = w.address, stable_id = w.stable_id, pid = w.pid,
      before = zone, before_id = live.compiled.leaf_opts[zone].id,
      pin = live.state.pins[w.address],
      exclusive = live.state.exclusive_pins and live.state.exclusive_pins[w.address] or nil }
  end
  assert(plan.windows[1].before ~= plan.windows[2].before, "swap unavailable: windows share a zone")
  for i, ref in ipairs(plan.windows) do
    ref.zone = plan.windows[3 - i].before
    ref.zone_id = live.compiled.leaf_opts[ref.zone].id
  end
  return plan
end

-- Absolute assignments make retry after a lost IPC reply safe. Validate the
-- entire exchange before changing either pin; never focus or relaunch.
function M.swap_apply(plan)
  local windows, ws, live = swap_windows(plan)
  assert(selector(ws) == plan.workspace and ws.tiled_layout == plan.layout, "swap unavailable: layout changed")
  for i, w in ipairs(windows) do
    local ref = plan.windows[i]
    assert(w.pid == ref.pid, "swap unavailable: window identity changed")
    assert(live.compiled.leaf_set[ref.zone] and not live.compiled.leaf_opts[ref.zone].spacer,
      "swap unavailable: zone changed")
    assert((not ref.zone_id or live.compiled.leaf_opts[ref.zone].id == ref.zone_id)
      and (not ref.before_id or (live.compiled.leaf_opts[ref.before] or {}).id == ref.before_id),
      "swap unavailable: zone identity changed")
    local pin = live.state.pins[w.address]
    assert(pin == ref.pin or pin == ref.zone, "swap unavailable: pin changed")
  end
  local zones = {}
  for name in pairs((live.state.scene_empty or {})[tostring(ws.id)] or {}) do
    zones[name] = true
    for _, ref in ipairs(plan.windows) do assert(ref.zone ~= name, "swap unavailable: zone is intentionally empty") end
  end
  local available = false
  for _, zone in ipairs(live.compiled.cycle) do if not zones[zone] then available = true end end
  assert(available, "swap unavailable: leave one fill zone for local windows")
  live.state.exclusive_pins = live.state.exclusive_pins or {}
  for _, ref in ipairs(plan.windows) do
    live.state.pins[ref.address] = ref.zone
    live.state.exclusive_pins[ref.address] = true
  end
  refresh_workspace(ws)
  return true
end

function M.swap(active, target)
  local live = engine.live[active.workspace.tiled_layout:match("^lua:(.+)$")]
  if not live.state.pins[active.address] and not live.state.pins[target.address] then return false end
  local request = { windows = { active, target } }
  local ok, err = pcall(function() M.swap_apply(M.swap_plan(request)) end)
  if not ok then
    local function quote(v) return "'" .. tostring(v):gsub("'", "'\\''") .. "'" end
    hl.exec_cmd("notify-send 'Hypertile swap' " .. quote(err))
  end
  return true
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
    assert(load(bridge.rule_source(ws.selector, ws.layout, spec), "=session-workspace", "t"))()
  end
  return true
end

-- Apply one matched window, without changing focus. Window IDs are supplied
-- by the service's match result, never reused across compositor instances.
function M.place(request)
  local saved, address = request.saved, request.address
  local window = "address:" .. address
  dispatch(hl.dsp.window.fullscreen_state, { window = window, internal = 0, client = 0, action = "set" })
  dispatch(hl.dsp.window.move, { window = window, workspace = saved.workspace, follow = false })
  dispatch(hl.dsp.window.float, { window = window, action = saved.floating and "on" or "off" })
  if saved.floating then
    dispatch(hl.dsp.window.resize, { window = window, x = saved.size.x, y = saved.size.y })
    dispatch(hl.dsp.window.move, { window = window, x = saved.at.x, y = saved.at.y })
    dispatch(hl.dsp.window.pin, { window = window, action = saved.pinned and "on" or "off" })
  end
  for _, live in pairs(engine.live) do
    live.state.pins[address] = nil
    if live.state.exclusive_pins then live.state.exclusive_pins[address] = nil end
  end
  if saved.pin and request.layout then
    local name = request.layout:match("^lua:(.+)$")
    if name and engine.state[name] then
      local state = engine.state[name]
      state.pins[address] = saved.pin
      state.exclusive_pins = state.exclusive_pins or {}
      state.exclusive_pins[address] = saved.pin_exclusive or nil
    end
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
