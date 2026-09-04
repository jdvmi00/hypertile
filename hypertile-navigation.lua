-- Directional focus and swaps for layouts whose tiles do not share edges.
local M = {}

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
  if active.fullscreen ~= 0 then return end
  local target = M.neighbor(active, hl.get_windows({ workspace = active.workspace, floating = false }), direction)
  if target then
    if swap then
      hl.dispatch(hl.dsp.window.swap({ target = "address:" .. target.address }))
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
  for _, entry in ipairs({ { "LEFT", "l" }, { "RIGHT", "r" }, { "UP", "u" }, { "DOWN", "d" } }) do
    local key, direction = entry[1], entry[2]
    hl.unbind("SUPER + SHIFT + " .. key)
    o.bind("SUPER + SHIFT + " .. key, "Swap window " .. key:lower() .. " (gap-aware)", function() M.swap(direction) end)
    hl.unbind("SUPER + " .. key)
    o.bind("SUPER + " .. key, "Focus window " .. key:lower() .. " (gap-aware)", function() M.focus(direction) end)
  end
end

return M
