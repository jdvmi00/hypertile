-- Live probe: register a logging layout on workspace 8 and delegate placement
-- to a hypertile spec. Load with (absolute path, the compositor has no cwd):
--   hyprctl eval "dofile('$PWD/probe.lua')"
-- Everything it learns goes to probe.log next to this file.

local root = (debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$")) or "."
local hypertile = dofile(root .. "/hypertile.lua")

local LOG = root .. "/probe.log"

local function log(...)
  local f = io.open(LOG, "a")
  if not f then
    return
  end
  local parts = { os.date("%H:%M:%S") }
  for i = 1, select("#", ...) do
    parts[#parts + 1] = tostring((select(i, ...)))
  end
  f:write(table.concat(parts, " "), "\n")
  f:close()
end

local function describe(v)
  if type(v) == "table" then
    local keys = {}
    for k in pairs(v) do
      keys[#keys + 1] = tostring(k)
    end
    table.sort(keys)
    return "table{" .. table.concat(keys, ",") .. "}"
  end
  return type(v) .. ":" .. tostring(v)
end

-- Try to enumerate what a value exposes, whether table or userdata.
local function keys_of(v)
  local ok, out = pcall(function()
    local names = {}
    local mt = getmetatable(v)
    if type(v) == "table" then
      for k in pairs(v) do
        names[#names + 1] = tostring(k)
      end
    end
    if type(mt) == "table" then
      for k in pairs(mt) do
        names[#names + 1] = "mt." .. tostring(k)
      end
      if type(mt.__index) == "table" then
        for k in pairs(mt.__index) do
          names[#names + 1] = "idx." .. tostring(k)
        end
      end
    end
    table.sort(names)
    return table.concat(names, ",")
  end)
  return ok and out or ("<keys err " .. tostring(out) .. ">")
end

local function win_summary(w)
  if not w then
    return "nil"
  end
  local ok, s = pcall(function()
    return string.format(
      "addr=%s class=%s title=%q floating=%s fullscreen=%s pinned=%s ws=%s mapped=%s tags=%s",
      tostring(w.address), tostring(w.class), tostring(w.title), tostring(w.floating),
      tostring(w.fullscreen), tostring(w.pinned), tostring(w.workspace and w.workspace.id),
      tostring(w.mapped), describe(w.tags)
    )
  end)
  return ok and s or ("<win err " .. tostring(s) .. ">")
end

local provider, compiled, state = hypertile.provider("hypertile-probe", {
  columns = {
    { name = "left", w = 0.2 },
    { name = "center", w = 0.6 },
    { name = "right", w = 0.2 },
  },
  fill = { "center", "right", "left" },
  cycle = { "right", "left", "center" },
  empty = "collapse",
})

local calls = 0

hl.layout.register("hypertile-probe", {
  recalculate = function(ctx)
    calls = calls + 1
    log("--- recalculate #" .. calls, "ctx=" .. describe(ctx), "keys=" .. keys_of(ctx))
    log("area", string.format("x=%s y=%s w=%s h=%s", ctx.area.x, ctx.area.y, ctx.area.w, ctx.area.h))
    log("targets", #ctx.targets)
    for i, t in ipairs(ctx.targets) do
      log(string.format("  target[%d] index=%s keys=%s box=(%s,%s %sx%s)", i, tostring(t.index), keys_of(t),
        tostring(t.box and t.box.x), tostring(t.box and t.box.y), tostring(t.box and t.box.w), tostring(t.box and t.box.h)))
      log("    window", win_summary(t.window))
    end
    -- Delegate to hypertile.
    provider.recalculate(ctx)
    for i, t in ipairs(ctx.targets) do
      log(string.format("  placed[%d] -> (%s,%s %sx%s)", i, tostring(t.box.x), tostring(t.box.y), tostring(t.box.w), tostring(t.box.h)))
    end
  end,
  layout_msg = function(ctx, msg)
    log("--- layout_msg", string.format("%q", tostring(msg)), "ctx targets=" .. tostring(ctx and #ctx.targets),
      "active=" .. win_summary(hl.get_active_window()))
    local result = provider.layout_msg(ctx, msg)
    log("layout_msg result", tostring(result))
    return result
  end,
})

-- Watch a few events so we can correlate what triggers recalculation.
for _, ev in ipairs({ "window.open", "window.close", "window.active", "workspace.active" }) do
  hl.on(ev, function(...)
    local args = {}
    for i = 1, select("#", ...) do
      args[#args + 1] = describe((select(i, ...)))
    end
    log("event", ev, table.concat(args, " "))
  end)
end

hl.workspace_rule({ workspace = "8", layout = "lua:hypertile-probe" })
log("probe loaded; workspace 8 -> lua:hypertile-probe")
