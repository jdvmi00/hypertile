-- The hand-written provider that predates the engine; the harness checks
-- the engine reproduces its placement.
--
-- 20/60/20 ultrawide grid:
-- 1 center 60%, 2 right 20%, 3 left 20%, 4 stack right, 5 stack left, 6 stack center.
-- Close removes that window; remaining keep this order.

local function column_for(i)
  if i == 1 then
    return "center"
  elseif i == 2 then
    return "right"
  elseif i == 3 then
    return "left"
  end
  local k = (i - 4) % 3
  if k == 0 then
    return "right"
  elseif k == 1 then
    return "left"
  end
  return "center"
end

local function box(x, y, w, h)
  return {
    x = math.floor(x + 0.5),
    y = math.floor(y + 0.5),
    w = math.max(1, math.floor(w + 0.5)),
    h = math.max(1, math.floor(h + 0.5)),
  }
end

local function place_stack(targets, col)
  local n = #targets
  if n == 0 then
    return
  end
  for i, target in ipairs(targets) do
    local y = col.y + col.h * (i - 1) / n
    local h = (i == n) and (col.y + col.h - y) or (col.h / n)
    target:place(box(col.x, y, col.w, h))
  end
end

hl.layout.register("ultrawide", {
  recalculate = function(ctx)
    local n = #ctx.targets
    if n == 0 then
      return
    end

    local area = ctx.area
    local left = box(area.x, area.y, area.w * 0.2, area.h)
    local center = box(area.x + area.w * 0.2, area.y, area.w * 0.6, area.h)
    local right = box(area.x + area.w * 0.8, area.y, area.w * 0.2, area.h)

    if n == 1 then
      ctx.targets[1]:place(center)
      return
    end

    local cols = { left = {}, center = {}, right = {} }
    for i = 1, n do
      table.insert(cols[column_for(i)], ctx.targets[i])
    end

    place_stack(cols.left, left)
    place_stack(cols.center, center)
    place_stack(cols.right, right)
  end,
})
