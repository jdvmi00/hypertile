-- Directional and numbered navigation for Hypertile layout slots.
local M = {}

local function quote(value)
  return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

-- Capture before the layer surface takes keyboard focus. The request carries
-- identity and layout guards, not a window to look up again by focus later.
function M.capture(active)
  active = active or hl.get_active_window()
  assert(active and active.workspace and not active.floating and not active.hidden
    and (active.fullscreen or 0) == 0, "Select a tiled window first")
  local engine = require("hypr.hypertile")
  local live = engine.live[(active.workspace.tiled_layout or ""):match("^lua:(.+)$")]
  assert(live, "Choose a Hypertile layout first")
  local source, slots = require("hypr.hypertile-session").navigation_slots(active)
  assert(source and slots, "Waiting for the layout; try again")
  local json = require("hypr.hypertile-json")
  local destinations = json.array()
  for _, slot in ipairs(slots) do
    local numbers = json.array()
    for number, zone in ipairs(live.compiled.fill) do
      if zone == slot.zone then numbers[#numbers + 1] = number end
    end
    local box = engine.fit_box({ x = slot.at.x, y = slot.at.y,
      w = slot.size.x, h = slot.size.y }, live.compiled.leaf_opts[slot.zone])
    destinations[#destinations + 1] = { zone = slot.zone, numbers = numbers,
      x = box.x, y = box.y, w = box.w, h = box.h,
      occupied = #slot.windows > 0 }
  end
  return { address = active.address, stable_id = active.stable_id, pid = active.pid,
    workspace = active.workspace.id, layout = active.workspace.tiled_layout,
    spec = json.encode(live.spec), source = source.zone,
    monitor = (active.monitor or hl.get_active_monitor()).name, slots = destinations }
end

function M.move(request, after_drag)
  local function dispatch(command)
    local result = hl.dispatch(command)
    if type(result) == "table" and result.error then error(result.error) end
  end
  assert(type(request) == "table" and type(request.zone) == "string", "Choose a destination tile")
  local active
  for _, w in ipairs(hl.get_windows()) do
    if w.address == request.address and w.stable_id == request.stable_id and w.pid == request.pid then active = w end
  end
  assert(active and active.workspace and active.workspace.id == request.workspace
    and active.workspace.tiled_layout == request.layout and active.mapped ~= false
    and not active.floating and not active.hidden and (active.fullscreen or 0) == 0,
    "The original window changed; reopen the tile picker")
  local ws = hl.get_active_workspace()
  assert(ws and ws.id == request.workspace, "The workspace changed; reopen the tile picker")
  local live = require("hypr.hypertile").live[request.layout:match("^lua:(.+)$")]
  assert(live and require("hypr.hypertile-json").encode(live.spec) == request.spec,
    "The layout changed; reopen the tile picker")
  local session = require("hypr.hypertile-session")
  local source, slots = session.navigation_slots(active)
  assert(source and (after_drag or source.zone == request.source), "The window moved; reopen the tile picker")
  local destination
  for _, slot in ipairs(slots or {}) do if slot.zone == request.zone then destination = slot end end
  assert(destination, "That tile is no longer available")
  if source.zone ~= destination.zone then
    if #destination.windows == 0 then
      session.move_to_empty(active, destination.zone)
    else
      local target = destination.windows[1]
      if live.state.pins[active.address] or live.state.pins[target.address] then
        session.swap_apply(session.swap_plan({ windows = { active, target } }))
      else
        -- Native reorder uses the focused window as its source.
        dispatch(hl.dsp.focus({ window = "address:" .. active.address }))
        dispatch(hl.dsp.window.swap({ target = "address:" .. target.address }))
      end
    end
  end
  dispatch(hl.dsp.focus({ window = "address:" .. active.address }))
  return true
end

function M.pick()
  local ok, request = pcall(M.capture)
  if not ok then
    hl.exec_cmd("notify-send 'Hypertile move' " .. quote(request))
    return
  end
  local payload = require("hypr.hypertile-json").encode({ mode = "move", request = request })
  hl.exec_cmd("omarchy-shell shell toggle jmartin.hypertile " .. quote(payload))
end

-- Native dragging supplies the animation and pointer-following window.
-- Hold the remaining layout in place until the release commits the drop.
-- A tiny runtime file also covers releases that beat the shell opening.
local drag, drag_timer
local drag_path = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/hypertile-tile-drag.json"

local function publish_drag(value)
  local file = io.open(drag_path .. ".tmp", "w")
  if not file then return false end
  file:write(require("hypr.hypertile-json").encode(value))
  file:close()
  return os.rename(drag_path .. ".tmp", drag_path)
end

function M.drag_slot(request, cursor, monitor)
  if not cursor or not monitor or monitor.name ~= request.monitor then return end
  local x, y = cursor.x - monitor.position.x, cursor.y - monitor.position.y
  for _, slot in ipairs(request.slots) do
    if x >= slot.x and x < slot.x + slot.w and y >= slot.y and y < slot.y + slot.h then
      return slot.zone
    end
  end
end

function M.drag_update()
  if not drag then return end
  local exists = false
  for _, window in ipairs(hl.get_windows()) do
    if window.address == drag.request.address and window.stable_id == drag.request.stable_id
      and window.pid == drag.request.pid then exists = true end
  end
  if not exists then
    pcall(drag.restore)
    publish_drag({ token = drag.token, active = false, zone = "" })
    drag = nil
    if drag_timer then drag_timer:set_enabled(false); drag_timer = nil end
    return
  end
  local monitor = hl.get_monitor_at_cursor()
  local cursor = hl.get_cursor_pos()
  local zone = M.drag_slot(drag.request, cursor, monitor)
  local ws = hl.get_active_workspace()
  if not ws or ws.id ~= drag.request.workspace then zone = nil end
  if drag.zone ~= zone then
    drag.zone = zone
    publish_drag({ token = drag.token, zone = zone or "", active = true })
  end
end

function M.drag_begin()
  if drag then return true end
  local active, cursor = hl.get_active_window(), hl.get_cursor_pos()
  if not cursor then return end
  local ws = hl.get_active_workspace()
  if not ws then return end
  local candidates = {}
  for _, window in ipairs(hl.get_windows()) do
    if window.visible ~= false and window.mapped ~= false and not window.hidden
      and window.workspace and window.workspace.id == ws.id
      and cursor.x >= window.at.x and cursor.y >= window.at.y
      and cursor.x < window.at.x + window.size.x and cursor.y < window.at.y + window.size.y then
      -- A floating window under the pointer belongs to the native drag only.
      if window.floating or (window.fullscreen or 0) ~= 0 then return end
      candidates[#candidates + 1] = window
    end
  end
  local target
  if #candidates == 1 then target = candidates[1]
  else
    for _, window in ipairs(candidates) do
      if active and window.address == active.address then target = window end
    end
  end
  if not target then return end
  local ok, request = pcall(M.capture, target)
  if not ok then return end
  local token = tostring({}):gsub("[^%w]", "") .. tostring(os.time())
  local held, restore = pcall(require("hypr.hypertile-session").drag_hold, request)
  if not held then return end
  drag = { request = request, token = token, restore = restore }
  if not publish_drag({ token = token, active = true, zone = "" }) then restore(); drag = nil; return end
  request.dragToken = token
  local payload = require("hypr.hypertile-json").encode({ mode = "move", request = request })
  hl.exec_cmd("omarchy-shell shell toggle jmartin.hypertile " .. quote(payload))
  drag_timer = hl.timer(M.drag_update, { timeout = 32, type = "repeat" })
  M.drag_update()
  return true
end

function M.drag_end(sampled)
  if not drag then return end
  if not sampled then M.drag_update() end
  if not drag then return end
  local finished = drag
  drag = nil
  if drag_timer then drag_timer:set_enabled(false); drag_timer = nil end
  local ok, err = pcall(finished.restore)
  if ok and finished.zone and finished.zone ~= finished.request.source then
    -- Native reinsertion can change compositor order. Restore it before
    -- applying our one explicit move, including drops back into the source.
    finished.request.zone = finished.zone
    ok, err = pcall(M.move, finished.request)
  end
  publish_drag({ token = finished.token, active = false, zone = "" })
  if not ok then hl.exec_cmd("notify-send 'Hypertile drop' " .. quote(err)) end
end

-- Prefer the same row/column, then the closest edges and center alignment.
-- With no aligned candidate, choose the nearest window in the half-plane.
function M.neighbor(active, windows, direction)
  assert(({ l = true, r = true, u = true, d = true })[direction], "invalid direction")
  local horizontal = direction == "l" or direction == "r"
  local axis, cross = horizontal and "x" or "y", horizontal and "y" or "x"
  local sign = (direction == "l" or direction == "u") and -1 or 1
  local a, s = active.at, active.size
  local best, best_score
  for _, w in ipairs(windows) do
    if w.address ~= active.address and w.workspace and active.workspace
      and w.workspace.id == active.workspace.id and w.mapped ~= false
      and not w.hidden and not w.floating and (w.fullscreen or 0) == 0 then
      local b, t = w.at, w.size
      local forward = sign * (b[axis] + t[axis] / 2 - a[axis] - s[axis] / 2)
      if forward > 0 then
        local overlap = math.min(a[cross] + s[cross], b[cross] + t[cross]) - math.max(a[cross], b[cross])
        local offset = math.abs(b[cross] + t[cross] / 2 - a[cross] - s[cross] / 2)
        local gap = math.max(0, forward - (s[axis] + t[axis]) / 2)
        local score = { overlap > 0 and 0 or 1, overlap > 0 and gap or forward * forward + offset * offset, offset, forward, w.address }
        local better = not best_score
        if best_score then
          for i = 1, #score do
            if score[i] ~= best_score[i] then
              better = score[i] < best_score[i]
              break
            end
          end
        end
        if better then best, best_score = w, score end
      end
    end
  end
  return best
end

local function navigate(direction, swap)
  local active = hl.get_active_window()
  if not active or not active.workspace then return end
  local name = active.workspace.tiled_layout:match("^lua:(.+)$")
  if not name or not require("hypr.hypertile").live[name] or active.floating then
    local dispatcher = swap and hl.dsp.window.swap or hl.dsp.focus
    return hl.dispatch(dispatcher({ direction = direction }))
  end
  if (active.fullscreen or 0) ~= 0 then return end
  if swap then
    local session = require("hypr.hypertile-session")
    local source, slots = session.navigation_slots(active)
    if source then
      -- Retain movement within a stacked slot before leaving that slot.
      local stacked = M.neighbor(active, source.windows, direction)
      if stacked then
        if not session.swap(active, stacked) then
          hl.dispatch(hl.dsp.window.swap({ target = "address:" .. stacked.address }))
        end
        return
      end
      local destination = M.neighbor(source, slots, direction)
      if not destination then return end
      if #destination.windows == 0 then
        local ok, result = pcall(session.move_to_empty, active, destination.zone)
        if not ok then
          hl.exec_cmd("notify-send 'Hypertile move' '" .. tostring(result):gsub("'", "'\\''") .. "'")
          return
        end
        return result
      end
      -- Use an actual occupant for swaps, including slots with a stack.
      local target = destination.windows[1]
      if not session.swap(active, target) then
        hl.dispatch(hl.dsp.window.swap({ target = "address:" .. target.address }))
      end
      return
    end
  end
  local target = M.neighbor(active, hl.get_windows({ workspace = active.workspace, floating = false }), direction)
  if target then
    if swap then
      if not require("hypr.hypertile-session").swap(active, target) then
        hl.dispatch(hl.dsp.window.swap({ target = "address:" .. target.address }))
      end
    else
      hl.dispatch(hl.dsp.focus({ window = "address:" .. target.address }))
    end
  end
end

function M.swap(direction)
  return navigate(direction, true)
end

function M.focus(direction)
  return navigate(direction, false)
end

function M.bind()
  -- Config reload destroys Lua timers; close any overlay from that old run.
  local previous = io.open(drag_path, "r")
  if previous then
    local text = previous:read("*a")
    previous:close()
    local ok, value = pcall(require("hypr.hypertile-json").decode, text)
    if ok and type(value) == "table" and value.active then
      publish_drag({ token = value.token, active = false, zone = "" })
    end
  end
  hl.unbind("SUPER + mouse:272")
  local native_drag = hl.dsp.window.drag()
  local native_active = false
  o.bind("SUPER + mouse:272", "Move window or select destination tile", function()
    -- Calling the native dispatcher marks this binding releasePending, so
    -- Hyprland invokes this same callback on release even without SUPER.
    if native_active then
      native_active = false
      M.drag_update()
      local result = hl.dispatch(native_drag)
      M.drag_end(true)
      return result
    end
    M.drag_begin()
    native_active = true
    return hl.dispatch(native_drag)
  end)
  -- Ignore modifiers on release: SUPER may have been released before LMB.
  -- Non-consuming leaves ordinary clicks alone when no Hypertile drag exists.
  o.bind("mouse:272", "Finish tile drop", M.drag_end, { release = true, ignore_mods = true, non_consuming = true })
  hl.unbind("SUPER + ALT + T")
  o.bind("SUPER + ALT + T", "Move window to numbered tile", M.pick)
  for _, entry in ipairs({ { "LEFT", "l" }, { "RIGHT", "r" }, { "UP", "u" }, { "DOWN", "d" } }) do
    local key, direction = entry[1], entry[2]
    hl.unbind("SUPER + SHIFT + " .. key)
    o.bind("SUPER + SHIFT + " .. key, "Swap window " .. key:lower() .. " (gap-aware)", function() M.swap(direction) end)
    hl.unbind("SUPER + " .. key)
    o.bind("SUPER + " .. key, "Focus window " .. key:lower() .. " (gap-aware)", function() M.focus(direction) end)
  end
end

return M
