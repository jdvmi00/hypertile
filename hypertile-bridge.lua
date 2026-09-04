-- hypertile bridge: everything an editor or CLI needs to read, write,
-- preview, and apply layouts without touching Lua source by hand.
--
-- Layout files live one per layout in <config>/hypr/layouts/<name>.lua and
-- look like:
--
--   local hypertile = require("hypr.hypertile")
--   hypertile.layout("quad", { ...spec... })
--
-- The JSON form exchanged with editors is:
--
--   { "name": "quad", "spec": { ...same fields as the Lua spec... } }
--
-- Reading a layout back is done by executing its file with a recording
-- stub in place of the engine, never by parsing text, so hand edits keep
-- working as long as they are valid Lua.

local modname = ... or "hypertile-bridge"
local prefix = modname:match("^(.-)hypertile%-bridge$") or ""
local hypertile = require(prefix .. "hypertile")
local json = require(prefix .. "hypertile-json")

local M = {}

local home = os.getenv("HOME") or ""
local function env_or(name, fallback)
  local v = os.getenv(name)
  if v == nil or v == "" then
    return fallback
  end
  return v
end

M.paths = {
  config_home = env_or("XDG_CONFIG_HOME", home .. "/.config"),
  state_home = env_or("XDG_STATE_HOME", home .. "/.local/state"),
  runtime = env_or("XDG_RUNTIME_DIR", "/tmp"),
}
M.paths.layouts_dir = env_or("HYPERTILE_LAYOUTS_DIR", M.paths.config_home .. "/hypr/layouts")
-- Persisted workspace rules. Kept outside Hyprland's config tree and read by
-- the loader with io.open, so writing one does not trip the config watcher.
-- Omarchy's per-workspace file is removed when hypertile takes a workspace
-- over, because Omarchy's loader runs last.
M.paths.rules_dir = env_or("HYPERTILE_RULES_DIR", M.paths.state_home .. "/hypertile/workspace-rules")
M.paths.workspace_state_dir = M.paths.state_home .. "/omarchy/workspace-layouts"

-- Overridable for tests.
M.hyprctl_bin = env_or("HYPERTILE_HYPRCTL_BIN", "hyprctl")
M.shell_bin = env_or("HYPERTILE_SHELL_BIN", "omarchy-shell")

---------------------------------------------------------------------------
-- Helpers
---------------------------------------------------------------------------

local function shell_quote(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function read_file(path)
  local f, err = io.open(path, "r")
  if not f then
    return nil, err
  end
  local s = f:read("a")
  f:close()
  return s
end
M.read_file = read_file

local function write_file(path, content)
  local f, err = io.open(path, "w")
  if not f then
    return nil, err
  end
  f:write(content)
  f:close()
  return true
end

-- A reader never sees a half-written file: the content lands in a sibling
-- and is renamed into place.
local function write_file_atomic(path, content)
  local ok, err = write_file(path .. ".tmp", content)
  if not ok then
    return nil, err
  end
  local renamed, rerr = os.rename(path .. ".tmp", path)
  if not renamed then
    os.remove(path .. ".tmp")
    return nil, rerr
  end
  return true
end

local function ensure_dir(dir)
  os.execute("mkdir -p " .. shell_quote(dir))
end

-- Stems of the .lua files directly in `dir`, sorted by `sort` with `flags`.
local function lua_files(dir, flags)
  local out = {}
  local handle = io.popen("find " .. shell_quote(dir) .. " -maxdepth 1 -type f -name '*.lua' -printf '%f\\n' 2>/dev/null | sort " .. (flags or ""))
  if not handle then
    return out
  end
  for filename in handle:lines() do
    out[#out + 1] = (filename:gsub("%.lua$", ""))
  end
  handle:close()
  return out
end

function M.valid_name(name)
  return type(name) == "string" and name:match("^[%w][%w_%-]*$") ~= nil
end

local function invalid_name(name)
  return "invalid layout name " .. tostring(name) .. " (letters, digits, _ and - only)"
end

local function valid_workspace(id)
  return tostring(id):match("^%d+$") ~= nil
end

-- Hyprland's own tiled layouts; anything else names a hypertile layout.
M.builtins = { "dwindle", "scrolling", "master" }
local builtin = {}
for _, name in ipairs(M.builtins) do
  builtin[name] = true
end

-- A bare hypertile name becomes "lua:<name>"; built-ins and prefixed names
-- pass through.
local function qualify(layout)
  if layout:match(":") or builtin[layout] then
    return layout
  end
  return "lua:" .. layout
end

-- Strip JSON metatables so specs compare and serialize plainly.
local function plain(v)
  if type(v) ~= "table" then
    return v
  end
  local out = {}
  for k, x in pairs(v) do
    out[k] = plain(x)
  end
  return out
end
M.plain = plain

---------------------------------------------------------------------------
-- Reading layout files
---------------------------------------------------------------------------

-- Execute a layout file with a recording engine. Returns a list of
-- { name = ..., spec = ... } in registration order.
function M.load_file(path)
  local captured = {}
  local recorder = {
    layout = function(name, spec)
      captured[#captured + 1] = { name = name, spec = spec }
    end,
  }
  local env = setmetatable({
    require = function(mod)
      if mod == "hypr.hypertile" or mod == "hypertile" then
        return recorder
      end
      return require(mod)
    end,
    hl = setmetatable({}, {
      __index = function()
        return function() end
      end,
    }),
  }, { __index = _G })
  local chunk, err = loadfile(path, "t", env)
  if not chunk then
    return nil, err
  end
  local ok, run_err = pcall(chunk)
  if not ok then
    return nil, run_err
  end
  return captured
end

-- Sorted list of { name, path, spec } across the layouts directory. A file
-- with an error is reported with `error` set instead of `spec`.
function M.list()
  local out = {}
  for _, stem in ipairs(lua_files(M.paths.layouts_dir)) do
    local path = M.paths.layouts_dir .. "/" .. stem .. ".lua"
    local entries, err = M.load_file(path)
    if not entries then
      out[#out + 1] = { name = stem, path = path, error = err }
    else
      for _, e in ipairs(entries) do
        out[#out + 1] = { name = e.name, path = path, spec = e.spec }
      end
    end
  end
  return out
end

function M.load(name)
  for _, entry in ipairs(M.list()) do
    if entry.name == name then
      if entry.error then
        return nil, entry.error
      end
      return entry.spec, entry.path
    end
  end
  return nil, "no layout named " .. tostring(name)
end

---------------------------------------------------------------------------
-- Validation and JSON
---------------------------------------------------------------------------

function M.validate(name, spec)
  if not M.valid_name(name) then
    return nil, invalid_name(name)
  end
  if type(spec) ~= "table" then
    return nil, "spec must be an object"
  end
  local ok, err = pcall(hypertile.compile, plain(spec))
  if not ok then
    return nil, (tostring(err):gsub("^.-hypertile: ", ""))
  end
  return true
end

M.json = json

function M.to_json(name, spec)
  return json.encode({ name = name, spec = plain(spec) })
end

-- Returns name, spec or nil, err.
function M.from_json(text)
  local ok, doc = pcall(json.decode, text)
  if not ok then
    return nil, doc
  end
  if type(doc) ~= "table" or type(doc.name) ~= "string" or type(doc.spec) ~= "table" then
    return nil, 'expected {"name": ..., "spec": {...}}'
  end
  local spec = plain(doc.spec)
  local valid, err = M.validate(doc.name, spec)
  if not valid then
    return nil, err
  end
  return doc.name, spec
end

---------------------------------------------------------------------------
-- Serialization to Lua
---------------------------------------------------------------------------

local function fmt_number(n)
  if math.floor(n) == n and math.abs(n) < 1e15 then
    return string.format("%d", n)
  end
  return string.format("%.14g", n)
end

local function fmt_scalar(v)
  local t = type(v)
  if t == "string" then
    return string.format("%q", v)
  elseif t == "number" then
    return fmt_number(v)
  elseif t == "boolean" then
    return tostring(v)
  end
  error("hypertile: cannot serialize " .. t)
end

local function is_list(t)
  return #t > 0
end

-- Keys in the order they read best. Anything unlisted goes after, sorted.
local node_order = { "name", "w", "h", "size", "spacer", "never_split", "aspect", "scale", "stack", "empty", "columns", "rows" }
local top_order = { "columns", "rows", "name", "w", "h", "spacer", "never_split", "aspect", "scale", "fill", "cycle", "rules", "capacity", "gaps", "border", "rounding", "stack", "empty", "single", "in_cycle" }
local rule_order = { "class", "title", "tag", "slot" }

local function ordered_keys(t, order)
  local seen, keys = {}, {}
  for _, k in ipairs(order) do
    if t[k] ~= nil then
      keys[#keys + 1] = k
      seen[k] = true
    end
  end
  local rest = {}
  for k in pairs(t) do
    if not seen[k] then
      rest[#rest + 1] = k
    end
  end
  table.sort(rest, function(a, b)
    return tostring(a) < tostring(b)
  end)
  for _, k in ipairs(rest) do
    keys[#keys + 1] = k
  end
  return keys
end

local function fmt_key(k)
  if type(k) == "string" and k:match("^[%a_][%w_]*$") then
    return k
  end
  return "[" .. fmt_scalar(k) .. "]"
end

local function is_flat_scalar_list(t)
  for _, v in ipairs(t) do
    if type(v) == "table" then
      return false
    end
  end
  return true
end

local write_table

local function write_value(v, indent, order)
  if type(v) ~= "table" then
    return fmt_scalar(v)
  end
  return write_table(v, indent, order)
end

-- Leaf nodes and rules fit on one line; containers and lists expand.
local function one_line(t, order)
  local parts = {}
  for _, k in ipairs(ordered_keys(t, order)) do
    parts[#parts + 1] = fmt_key(k) .. " = " .. fmt_scalar(t[k])
  end
  return "{ " .. table.concat(parts, ", ") .. " }"
end

local function has_nested(t)
  for _, v in pairs(t) do
    if type(v) == "table" then
      return true
    end
  end
  return false
end

write_table = function(t, indent, order)
  local inner = indent .. "  "
  if is_list(t) then
    if is_flat_scalar_list(t) then
      local parts = {}
      for _, v in ipairs(t) do
        parts[#parts + 1] = fmt_scalar(v)
      end
      return "{ " .. table.concat(parts, ", ") .. " }"
    end
    local lines = { "{" }
    for _, v in ipairs(t) do
      lines[#lines + 1] = inner .. write_value(v, inner, order) .. ","
    end
    lines[#lines + 1] = indent .. "}"
    return table.concat(lines, "\n")
  end
  if next(t) == nil then
    return "{}"
  end
  if not has_nested(t) then
    return one_line(t, order)
  end
  local lines = { "{" }
  for _, k in ipairs(ordered_keys(t, order)) do
    local v = t[k]
    local child_order = order
    if k == "rules" then
      child_order = rule_order
    elseif k == "columns" or k == "rows" then
      child_order = node_order
    end
    lines[#lines + 1] = inner .. fmt_key(k) .. " = " .. write_value(v, inner, child_order) .. ","
  end
  lines[#lines + 1] = indent .. "}"
  return table.concat(lines, "\n")
end

function M.serialize(name, spec)
  assert(M.valid_name(name), "invalid layout name")
  local body = write_table(plain(spec), "", top_order)
  return table.concat({
    "-- hypertile layout \"" .. name .. "\". Written by hypertile-ctl; plain Lua, edit freely.",
    "-- Select it with a workspace rule or SUPER+L: layout = \"lua:" .. name .. "\".",
    "",
    'local hypertile = require("hypr.hypertile")',
    "",
    'hypertile.layout("' .. name .. '", ' .. body .. ")",
    "",
  }, "\n")
end

---------------------------------------------------------------------------
-- Writing
---------------------------------------------------------------------------

function M.layout_path(name)
  if not M.valid_name(name) then
    return nil, invalid_name(name)
  end
  return M.paths.layouts_dir .. "/" .. name .. ".lua"
end

-- Validates, serializes, and round-trips the written file before returning.
function M.save(name, spec)
  local valid, err = M.validate(name, spec)
  if not valid then
    return nil, err
  end
  ensure_dir(M.paths.layouts_dir)
  local path = M.layout_path(name)
  local ok, werr = write_file_atomic(path, M.serialize(name, spec))
  if not ok then
    return nil, werr
  end
  local back, lerr = M.load_file(path)
  if not back or #back ~= 1 or back[1].name ~= name then
    return nil, "written file failed to load back: " .. tostring(lerr)
  end
  return path
end

-- Where a layout is referenced beyond its own file: persisted workspace
-- rules (workspace-layouts/<id>.lua) and general.layout in looknfeel.lua.
-- Returns { workspaces = { "1", "4" }, default = bool }.
function M.references(name)
  local out = { workspaces = {}, default = false }
  local want = "lua:" .. name
  for _, id in ipairs(lua_files(M.paths.rules_dir, "-V")) do
    local text = read_file(M.paths.rules_dir .. "/" .. id .. ".lua") or ""
    local layout = text:match('layout%s*=%s*"([^"]*)"')
    if layout == want then
      out.workspaces[#out.workspaces + 1] = id
    end
  end
  local default = M.default_layout()
  out.default = default == want
  return out
end

-- Delete a layout file. Refuses while the layout is the default (pick
-- another first) or, unless `force`, while persisted workspace rules
-- point at it; with `force` those rules are dropped so the workspaces
-- fall back to the default on reload. Returns the path, or nil, err.
function M.remove(name, force)
  local path, perr = M.layout_path(name)
  if not path then
    return nil, perr
  end
  local f = io.open(path, "r")
  if not f then
    return nil, "no layout file at " .. path
  end
  f:close()
  local refs = M.references(name)
  if refs.default then
    return nil, name .. " is the default layout; make another layout the default first"
  end
  if #refs.workspaces > 0 and not force then
    return nil, name .. " is used by workspace " .. table.concat(refs.workspaces, ", ") .. " (--force drops those rules)"
  end
  for _, id in ipairs(refs.workspaces) do
    os.remove(M.paths.rules_dir .. "/" .. id .. ".lua")
  end
  local ok, err = os.remove(path)
  if not ok then
    return nil, err
  end
  return path, refs.workspaces
end

-- Rename a layout: write it under the new name, point every persisted
-- workspace rule and the default at the new name, then drop the old file.
-- Returns the new path and the references that were updated, or nil, err.
function M.rename(old, new)
  if not M.valid_name(old) or not M.valid_name(new) then
    return nil, invalid_name(M.valid_name(old) and new or old)
  end
  if old == new then
    return nil, "that is already its name"
  end
  local spec, lerr = M.load(old)
  if not spec then
    return nil, lerr or ("no layout called " .. old)
  end
  local existing = io.open(M.layout_path(new), "r")
  if existing then
    existing:close()
    return nil, "a layout called " .. new .. " already exists"
  end
  local path, serr = M.save(new, spec)
  if not path then
    return nil, serr
  end
  local refs = M.references(old)
  local from = ('layout = "lua:' .. old .. '"'):gsub("%p", "%%%0")
  local to = ('layout = "lua:' .. new .. '"'):gsub("%%", "%%%%")
  for _, id in ipairs(refs.workspaces) do
    local wpath = M.paths.rules_dir .. "/" .. id .. ".lua"
    local text = read_file(wpath)
    if text then
      write_file_atomic(wpath, (text:gsub(from, to)))
    end
  end
  if refs.default then
    M.set_default_layout(new)
  end
  os.remove(M.layout_path(old))
  return path, refs
end

---------------------------------------------------------------------------
-- Talking to the compositor
---------------------------------------------------------------------------

function M.hyprctl(args)
  local cmd = shell_quote(M.hyprctl_bin) .. " " .. args .. " 2>&1"
  local p = io.popen(cmd)
  if not p then
    return nil, "cannot run " .. M.hyprctl_bin
  end
  local out = p:read("a")
  local ok = p:close()
  return out, ok
end

-- Run Lua inside Hyprland from a temp file (avoids shell quoting limits).
-- Returns the text that the chunk wrote to `out_path`, if any.
function M.eval_file(lua_source)
  local dir = M.paths.runtime .. "/hypertile"
  ensure_dir(dir)
  local path = dir .. "/eval-" .. tostring(os.time()) .. "-" .. tostring(math.random(1e6)) .. ".lua"
  local ok, err = write_file(path, lua_source)
  if not ok then
    return nil, err
  end
  local out, success = M.hyprctl("eval " .. shell_quote("dofile(" .. string.format("%q", path) .. ")"))
  os.remove(path)
  if not success or out:match("^error") then
    return nil, ((out or ""):gsub("%s+$", ""))
  end
  return out
end

-- Ask the compositor a question by having it write an answer file.
function M.query(lua_expr_returning_string)
  local dir = M.paths.runtime .. "/hypertile"
  ensure_dir(dir)
  local answer = dir .. "/answer-" .. tostring(os.time()) .. "-" .. tostring(math.random(1e6))
  local src = table.concat({
    "local __value = (function() " .. lua_expr_returning_string .. " end)()",
    "local __f = assert(io.open(" .. string.format("%q", answer) .. ", 'w'))",
    "__f:write(tostring(__value)) __f:close()",
  }, "\n")
  local _, err = M.eval_file(src)
  if err then
    return nil, err
  end
  local text = read_file(answer)
  os.remove(answer)
  if not text then
    return nil, "no answer from the compositor"
  end
  return text
end

-- { id = number, name = string, layout = "lua:quad" | "dwindle" | ... }
function M.active_workspace()
  local text, err = M.query([[
    local ws = hl.get_active_workspace()
    if not ws then return "" end
    return tostring(ws.id) .. "\t" .. tostring(ws.name) .. "\t" .. tostring(ws.tiled_layout)
  ]])
  if not text or text == "" then
    return nil, err or "no active workspace"
  end
  local id, name, layout = text:match("^(.-)\t(.-)\t(.*)$")
  return { id = tonumber(id), name = name, layout = layout }
end

-- Active workspace plus the geometry a layout actually receives on the
-- active monitor: monitor logical size, reserved edges (bar), outer gaps,
-- and the resulting area, all in monitor-local logical pixels. This is
-- what an overlay needs to draw zones exactly where windows will go.
function M.geometry()
  local text, err = M.query([[
    local ws = hl.get_active_workspace()
    local m = hl.get_active_monitor()
    if not m then return "" end
    local g = hl.get_config("general.gaps_out")
    local function gap(side)
      if type(g) == "table" then return tonumber(g[side]) or 0 end
      return tonumber(g) or 0
    end
    local r = m.reserved or {}
    local function res(side, i)
      if type(r) ~= "table" then return 0 end
      return tonumber(r[side] or r[i]) or 0
    end
    local gi = hl.get_config("general.gaps_in")
    local inner = type(gi) == "table" and (tonumber(gi.top) or 0) or (tonumber(gi) or 0)
    local border = tonumber(hl.get_config("general.border_size")) or 0
    local rounding = tonumber(hl.get_config("decoration.rounding")) or 0
    return table.concat({
      tostring(ws and ws.id or ""), tostring(ws and ws.name or ""), tostring(ws and ws.tiled_layout or ""),
      tostring(m.name), tostring(m.x), tostring(m.y), tostring(m.width), tostring(m.height), tostring(m.scale),
      tostring(res("top", 1)), tostring(res("right", 2)), tostring(res("bottom", 3)), tostring(res("left", 4)),
      tostring(gap("top")), tostring(gap("right")), tostring(gap("bottom")), tostring(gap("left")),
      tostring(inner), tostring(border), tostring(rounding),
    }, "\t")
  ]])
  if not text or text == "" then
    return nil, err or "no active monitor"
  end
  local f = {}
  for field in (text .. "\t"):gmatch("(.-)\t") do
    f[#f + 1] = field
  end
  local scale = tonumber(f[9]) or 1
  if scale <= 0 then
    scale = 1
  end
  local width = (tonumber(f[7]) or 0) / scale
  local height = (tonumber(f[8]) or 0) / scale
  local reserved = { top = tonumber(f[10]) or 0, right = tonumber(f[11]) or 0, bottom = tonumber(f[12]) or 0, left = tonumber(f[13]) or 0 }
  local gaps = { top = tonumber(f[14]) or 0, right = tonumber(f[15]) or 0, bottom = tonumber(f[16]) or 0, left = tonumber(f[17]) or 0 }
  local area = {
    x = reserved.left + gaps.left,
    y = reserved.top + gaps.top,
    w = width - reserved.left - reserved.right - gaps.left - gaps.right,
    h = height - reserved.top - reserved.bottom - gaps.top - gaps.bottom,
  }
  return {
    workspace = { id = tonumber(f[1]), name = f[2], layout = f[3] },
    monitor = { name = f[4], x = tonumber(f[5]) or 0, y = tonumber(f[6]) or 0, width = width, height = height, scale = scale },
    reserved = reserved,
    gaps_out = gaps,
    gaps_in = tonumber(f[18]) or 0,
    border_size = tonumber(f[19]) or 0,
    rounding = tonumber(f[20]) or 0,
    area = area,
  }
end

-- Lua source for a workspace rule that selects `layout` and carries the
-- layout's gutters. Fields the layout leaves unset fall back to the global
-- config values, so switching away from a zero-gap layout restores gaps.
--
-- The rule write is the whole switch: Hyprland re-places the workspace on
-- its own refresh. Do not add resizes or re-applies here (docs/INTERNALS.md,
-- Stale windows).
local function rule_source(workspace, layout, spec)
  local gaps = spec and type(spec.gaps) == "table" and spec.gaps or {}
  local function field(value, key)
    if value ~= nil then
      return fmt_number(tonumber(value))
    end
    return 'hl.get_config("general.' .. key .. '")'
  end
  -- Rounding is a window property, so it rides on a window rule for the
  -- workspace's tiled windows; floating windows keep their own rules. The
  -- rule is named so that re-applying updates it in place: unnamed window
  -- rules accumulate in the compositor for the life of the session.
  local rounding = spec and spec.rounding ~= nil and fmt_number(tonumber(spec.rounding)) or 'hl.get_config("decoration.rounding")'
  local ws = tostring(workspace)
  return "hl.workspace_rule({ workspace = " .. string.format("%q", ws)
    .. ", layout = " .. string.format("%q", layout)
    .. ", gaps_in = " .. field(gaps.inner, "gaps_in")
    .. ", gaps_out = " .. field(gaps.outer, "gaps_out")
    .. ", border_size = " .. field(spec and spec.border, "border_size")
    .. " })\n"
    .. "hl.window_rule({ name = " .. string.format("%q", "hypertile-workspace-" .. ws)
    .. ", match = { workspace = " .. string.format("%q", ws) .. ", float = false }, rounding = " .. rounding .. " })"
end
M.rule_source = rule_source -- exported for the tests

local function ws_literal(workspace)
  return tonumber(workspace) and tostring(tonumber(workspace)) or string.format("%q", tostring(workspace))
end

local function resolve_workspace(workspace)
  if workspace then
    return workspace
  end
  local active, err = M.active_workspace()
  if not active then
    return nil, err
  end
  return active.id
end

-- Manual recovery for a window drawn smaller than its tile: every box shrinks
-- by 1px and is restored 120ms later, so the compositor sends a fresh
-- configure. Never called automatically.
local function heal_source(workspace)
  local ws_lit = ws_literal(workspace)
  return "do\n"
    .. "  local __ok, __ht = pcall(require, \"hypr.hypertile\")\n"
    .. "  local __ws = hl.get_workspace(" .. ws_lit .. ")\n"
    .. "  local __name = __ws and tostring(__ws.tiled_layout):match(\"^lua:(.+)$\")\n"
    .. "  local __st = __ok and __name and __ht.state and __ht.state[__name]\n"
    .. "  local function __nudge()\n"
    .. "    for _, __w in ipairs(hl.get_windows({ workspace = " .. ws_lit .. ", floating = false })) do\n"
    .. "      hl.dispatch(hl.dsp.window.resize({ x = 0, y = 0, relative = true, window = __w }))\n"
    .. "    end\n"
    .. "  end\n"
    .. "  if __st then\n"
    .. "    __st.jiggle = " .. (tonumber(workspace) and tostring(tonumber(workspace)) or "true") .. "\n"
    .. "    __nudge()\n"
    .. "    hl.timer(function() __st.jiggle = false; __nudge() end, { timeout = 120, type = \"oneshot\" })\n"
    .. "  else\n"
    .. "    __nudge()\n"
    .. "  end\n"
    .. "end"
end
M.heal_source = heal_source -- exported for the tests

function M.heal(workspace)
  local ws, werr = resolve_workspace(workspace)
  if not ws then
    return nil, werr
  end
  local _, err = M.eval_file(heal_source(ws))
  if err then
    return nil, err
  end
  return tostring(ws)
end

-- Register (or hot-swap) a layout in the running compositor without
-- touching disk, and optionally point a workspace at it. A `hyprctl reload`
-- discards it. Returns true or nil, err.
function M.preview(name, spec, workspace)
  local valid, err = M.validate(name, spec)
  if not valid then
    return nil, err
  end
  local src = {
    'local hypertile = require("hypr.hypertile")',
    "hypertile.layout(" .. string.format("%q", name) .. ", " .. write_table(plain(spec), "", top_order) .. ")",
  }
  if workspace then
    src[#src + 1] = rule_source(workspace, "lua:" .. name, spec)
  end
  local _, eerr = M.eval_file(table.concat(src, "\n"))
  if eerr then
    return nil, eerr
  end
  return true
end

-- Point a workspace at a layout, live and persisted. `layout` is a full
-- layout name like "lua:quad" or "dwindle"; a bare hypertile name gets the
-- "lua:" prefix. opts.persist = false switches the running compositor only:
-- the rule file is left alone, so the next reload puts the workspace back.
-- The overlay browses layouts that way. Returns layout, workspace id.
function M.apply(layout, workspace, opts)
  local persist = not (opts and opts.persist == false)
  layout = qualify(layout)
  local ws, wserr = resolve_workspace(workspace)
  if not ws then
    return nil, wserr
  end
  if not valid_workspace(ws) then
    return nil, "invalid workspace id " .. tostring(ws)
  end
  local id = tostring(ws)
  -- A hypertile layout brings its gutters along; built-ins get the globals.
  local spec
  local hname = layout:match("^lua:(.+)$")
  if hname then
    local lerr
    spec, lerr = M.load(hname)
    if not spec then
      return nil, lerr
    end
  end
  local src = rule_source(id, layout, spec)
  local _, err = M.eval_file(src)
  if err then
    return nil, err
  end
  if not persist then
    return layout, id
  end
  ensure_dir(M.paths.rules_dir)
  local ok, werr = write_file_atomic(M.paths.rules_dir .. "/" .. id .. ".lua", src .. "\n")
  if not ok then
    return nil, werr
  end
  -- Removing Omarchy's file is itself a watched write, so it happens only on
  -- first takeover.
  os.remove(M.paths.workspace_state_dir .. "/" .. id .. ".lua")
  return layout, id
end

-- What a layout is called on screen: "lua:columns" is columns, a built-in
-- is capitalised.
function M.display_name(layout)
  local s = tostring(layout or "")
  local name = s:match("^lua:(.+)$")
  if name then
    return name
  end
  if s == "" then
    return ""
  end
  return s:sub(1, 1):upper() .. s:sub(2)
end

-- Names of the layouts SUPER+L walks: every saved layout in name order,
-- except those whose spec says `in_cycle = false`.
function M.cycle_names()
  local names = {}
  for _, e in ipairs(M.list()) do
    if not e.error and not (e.spec and e.spec.in_cycle == false) then
      names[#names + 1] = e.name
    end
  end
  return names
end

-- The layout after `current` in the cycle: every layout name given, in
-- order, then dwindle. A current layout outside the cycle (scrolling, a
-- layout since deleted or taken out of the cycle) starts it over.
function M.cycle_target(current, names, reverse)
  local cycle = {}
  for _, n in ipairs(names) do
    cycle[#cycle + 1] = "lua:" .. n
  end
  cycle[#cycle + 1] = "dwindle"
  local at = 0
  for i, l in ipairs(cycle) do
    if l == current then
      at = i
    end
  end
  if at == 0 then
    return reverse and cycle[#cycle] or cycle[1]
  end
  local step = reverse and -1 or 1
  return cycle[((at - 1 + step) % #cycle) + 1]
end

-- Notify the shell: OSD when `osd` is set, bar refresh always. Best effort;
-- without a shell the switch itself is already done.
function M.notify_shell(layout, osd)
  local quiet = " >/dev/null 2>&1"
  if osd then
    local payload = json.encode({ icon = "\u{F1CAC}", message = M.display_name(layout), duration = 1200 })
    os.execute(shell_quote(M.shell_bin) .. " -q osd show " .. shell_quote(payload) .. quiet)
  end
  os.execute(shell_quote(M.shell_bin) .. " -q hypertile-bar refresh" .. quiet)
end

-- Open windows: { { class, title, workspace, address, floating }, ... }
function M.windows()
  local text, err = M.query([[
    local out = {}
    for _, w in ipairs(hl.get_windows({ mapped = true })) do
      local ws = w.workspace and tostring(w.workspace.id) or ""
      local title = (tostring(w.title):gsub("[\t\n]", " "))
      out[#out + 1] = table.concat({ tostring(w.class), title, ws, tostring(w.address), tostring(w.floating) }, "\t")
    end
    return table.concat(out, "\n")
  ]])
  if not text then
    return nil, err
  end
  local out = {}
  for line in text:gmatch("[^\n]+") do
    local class, title, ws, address, floating = line:match("^(.-)\t(.-)\t(.-)\t(.-)\t(.*)$")
    if class then
      out[#out + 1] = { class = class, title = title, workspace = tonumber(ws), address = address, floating = floating == "true" }
    end
  end
  return out
end

-- Workspaces: { { id, name, monitor, layout, windows, active }, ... } sorted by id.
function M.workspaces()
  local text, err = M.query([[
    local out = {}
    for _, ws in ipairs(hl.get_workspaces()) do
      out[#out + 1] = table.concat({ tostring(ws.id), tostring(ws.name), ws.monitor and tostring(ws.monitor.name) or "", tostring(ws.tiled_layout), tostring(ws.windows or 0), tostring(ws.active) }, "\t")
    end
    return table.concat(out, "\n")
  ]])
  if not text then
    return nil, err
  end
  local out = {}
  for line in text:gmatch("[^\n]+") do
    local id, name, monitor, layout, windows, active = line:match("^(.-)\t(.-)\t(.-)\t(.-)\t(.-)\t(.*)$")
    if id then
      out[#out + 1] = { id = tonumber(id), name = name, monitor = monitor, layout = layout, windows = tonumber(windows) or 0, active = active == "true" }
    end
  end
  table.sort(out, function(a, b)
    return (a.id or 0) < (b.id or 0)
  end)
  return out
end

-- The default layout for workspaces without a rule lives in looknfeel.lua
-- as general.layout. Read it, or replace it in place (the line must exist).
M.looknfeel_path = M.paths.config_home .. "/hypr/looknfeel.lua"
local layout_pattern = '(general%s*=%s*{[^}]-layout%s*=%s*")([^"]*)(")'

function M.default_layout()
  local text = read_file(M.looknfeel_path)
  if not text then
    return nil, "cannot read " .. M.looknfeel_path
  end
  local _, value = text:match(layout_pattern)
  if not value then
    return nil, "no general.layout in " .. M.looknfeel_path
  end
  return value
end

function M.set_default_layout(layout)
  layout = qualify(layout)
  local before = read_file(M.looknfeel_path)
  if not before then
    return nil, "cannot read " .. M.looknfeel_path
  end
  local text, count = before:gsub(layout_pattern, function(pre, _, post)
    return pre .. layout .. post
  end, 1)
  if count == 0 then
    return nil, "no general.layout in " .. M.looknfeel_path .. "; set it by hand once"
  end
  write_file(M.looknfeel_path .. ".bak", before)
  local ok, err = write_file_atomic(M.looknfeel_path, text)
  if not ok then
    return nil, err
  end
  return layout
end

function M.reload()
  local out, ok = M.hyprctl("reload")
  if not ok then
    return nil, out
  end
  local errors = M.hyprctl("configerrors") or ""
  errors = errors:gsub("^%s+", ""):gsub("%s+$", "")
  if errors ~= "" then
    return nil, errors
  end
  return true
end

return M
