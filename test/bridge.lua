-- Bridge tests: JSON, spec <-> Lua round trips, save/list/load, CLI smoke.
-- Run from the repo root: lua test/bridge.lua

local function shell_out(cmd)
  local p = assert(io.popen(cmd))
  local out = p:read("a")
  p:close()
  return (out:gsub("%s+$", ""))
end

local script_dir = (arg and arg[0] or "test/bridge.lua"):match("^(.*)/[^/]*$") or "."
local root = shell_out("cd '" .. script_dir .. "/..' && pwd")
package.path = root .. "/?.lua;" .. package.path

local tmp = shell_out("mktemp -d /tmp/hypertile-test-XXXXXX")
os.execute("mkdir -p '" .. tmp .. "/layouts' '" .. tmp .. "/runtime'")

-- The bridge resolves its paths at require time; point them into tmp afterwards.
local hypertile = require("hypertile")
local json = require("hypertile-json")
local bridge = require("hypertile-bridge")
bridge.paths.layouts_dir = tmp .. "/layouts"
bridge.paths.rules_dir = tmp .. "/workspace-rules"
bridge.paths.workspace_state_dir = tmp .. "/workspace-layouts"
bridge.paths.runtime = tmp .. "/runtime"
bridge.looknfeel_path = tmp .. "/looknfeel.lua"

local failures, checks = 0, 0
local function check(cond, msg)
  checks = checks + 1
  if not cond then
    failures = failures + 1
    print("FAIL: " .. msg)
  end
end

-- File text, or "" when it is missing, so a missing file fails a check
-- instead of crashing the run.
local function slurp(path)
  return bridge.read_file(path) or ""
end

local function exists(path)
  local f = io.open(path, "r")
  if f then
    f:close()
    return true
  end
  return false
end

local function deep_equal(a, b, path)
  path = path or "$"
  if type(a) ~= type(b) then
    return false, path .. ": " .. type(a) .. " vs " .. type(b)
  end
  if type(a) ~= "table" then
    if a == b then
      return true
    end
    return false, path .. ": " .. tostring(a) .. " vs " .. tostring(b)
  end
  for k, v in pairs(a) do
    local ok, why = deep_equal(v, b[k], path .. "." .. tostring(k))
    if not ok then
      return false, why
    end
  end
  for k in pairs(b) do
    if a[k] == nil then
      return false, path .. "." .. tostring(k) .. ": missing on left"
    end
  end
  return true
end

---------------------------------------------------------------------------
-- 1. JSON
---------------------------------------------------------------------------
do
  local doc = {
    name = "x",
    n = 0.2,
    i = 3,
    neg = -1.5,
    s = 'quote " backslash \\ newline \n tab \t',
    t = true,
    f = false,
    list = { 1, "two", { three = 3 } },
    empty_obj = {},
    empty_arr = json.array({}),
    nested = { a = { b = { c = "deep" } } },
  }
  local text = json.encode(doc)
  local back = json.decode(text)
  local ok, why = deep_equal(bridge.plain(doc), bridge.plain(back))
  check(ok, "json round trip: " .. tostring(why))
  check(text:find('"empty_arr": %[%]'), "empty array encodes as []")
  check(text:find('"empty_obj": {}'), "empty object encodes as {}")
  check(json.encode({ b = 1, a = 2 }):find('"a": 2,\n  "b": 1'), "object keys are sorted")
  check(json.encode({ 0.6 }):find("0.6") and json.encode({ 2 }) == "[\n  2\n]", "numbers: floats stay short, integers have no decimal")
  local bad_ok, err = pcall(json.decode, '{"a": [1, 2}')
  check(not bad_ok and tostring(err):find("line 1 col"), "decode error reports position: " .. tostring(err))
  check(json.decode('"\\u00e9"') == "é", "unicode escape decodes to UTF-8")
end

---------------------------------------------------------------------------
-- 2. load_file reads the shipped layouts through the recording stub
---------------------------------------------------------------------------
local quad_spec, ultra_spec
do
  local entries, err = bridge.load_file(root .. "/layouts/quad.lua")
  check(entries and #entries == 1 and entries[1].name == "quad", "quad.lua loads: " .. tostring(err))
  quad_spec = entries and entries[1].spec
  check(quad_spec and quad_spec.fill[8] == "left" and quad_spec.columns[2].rows[2].columns[2].name == "br", "quad spec content intact")

  entries, err = bridge.load_file(root .. "/layouts/ultrawide.lua")
  check(entries and entries[1].name == "ultrawide", "ultrawide.lua loads: " .. tostring(err))
  ultra_spec = entries and entries[1].spec

  local bad, berr = bridge.load_file(root .. "/does-not-exist.lua")
  check(bad == nil and berr, "missing file reports an error")
end

---------------------------------------------------------------------------
-- 3. serialize -> load round trip, and JSON round trip
---------------------------------------------------------------------------
do
  for _, case in ipairs({ { "quad", quad_spec }, { "ultrawide", ultra_spec } }) do
    local name, spec = case[1], case[2]
    local lua_src = bridge.serialize(name, spec)
    local path = tmp .. "/rt-" .. name .. ".lua"
    local f = assert(io.open(path, "w"))
    f:write(lua_src)
    f:close()
    local back = bridge.load_file(path)
    check(back and back[1].name == name, name .. ": serialized file loads")
    local ok, why = deep_equal(spec, back and back[1].spec)
    check(ok, name .. ": serialize/load round trip: " .. tostring(why))

    local text = bridge.to_json(name, spec)
    local jname, jspec = bridge.from_json(text)
    check(jname == name, name .. ": from_json name")
    ok, why = deep_equal(spec, jspec)
    check(ok, name .. ": JSON round trip: " .. tostring(why))
    -- The compiled result must be identical too (what actually places windows).
    local c1, c2 = hypertile.compile(spec), hypertile.compile(jspec)
    ok, why = deep_equal(c1, c2)
    check(ok, name .. ": compiled specs identical after JSON: " .. tostring(why))
  end

  -- Readable output: leaves on one line, containers expanded, rules ordered.
  local src = bridge.serialize("demo", {
    columns = { { name = "a", w = 0.3 }, { w = 0.7, rows = { { name = "b" }, { name = "c", h = 2 } } } },
    fill = { "b", "c", "a" },
    rules = { { slot = "a", class = "^foo$" } },
    capacity = { a = 1 },
    empty = "keep",
  })
  check(src:find('{ name = "a", w = 0.3 },', 1, true), "leaf serialized on one line")
  check(src:find('{ class = "^foo$", slot = "a" }', 1, true), "rule keys ordered class before slot")
  check(src:find('fill = { "b", "c", "a" },', 1, true), "flat string list on one line")
  check(src:find('local hypertile = require("hypr.hypertile")', 1, true), "file requires the engine by config module name")
end

---------------------------------------------------------------------------
-- 4. validate / from_json rejects bad input with useful messages
---------------------------------------------------------------------------
do
  local ok, err = bridge.validate("bad name!", quad_spec)
  check(not ok and err:find("invalid layout name"), "name with spaces/punctuation rejected")
  ok, err = bridge.validate("dup", { columns = { { name = "a" }, { name = "a" } } })
  check(not ok and err:find("duplicate"), "duplicate slots rejected: " .. tostring(err))
  ok, err = bridge.validate("x", { columns = { { name = "a" } }, fill = { "zzz" } })
  check(not ok and err:find("unknown slot"), "unknown fill slot rejected: " .. tostring(err))
  local n, e = bridge.from_json("not json")
  check(n == nil and e:find("json:"), "from_json reports parse errors")
  n, e = bridge.from_json('{"spec": {}}')
  check(n == nil and e:find("expected"), "from_json requires name and spec")
end

---------------------------------------------------------------------------
-- 5. save / list / load / remove against a temp layouts dir
---------------------------------------------------------------------------
do
  local path, err = bridge.save("quad", quad_spec)
  check(path == tmp .. "/layouts/quad.lua", "save writes to layouts dir: " .. tostring(err))
  path, err = bridge.save("ultrawide", ultra_spec)
  check(path ~= nil, "save second layout: " .. tostring(err))
  local list = bridge.list()
  check(#list == 2 and list[1].name == "quad" and list[2].name == "ultrawide", "list returns both, sorted by file name")
  local spec = bridge.load("quad")
  local ok, why = deep_equal(spec, quad_spec)
  check(ok, "load returns the saved spec: " .. tostring(why))

  -- A broken file is reported, not fatal.
  local f = assert(io.open(tmp .. "/layouts/broken.lua", "w"))
  f:write("this is not lua (")
  f:close()
  list = bridge.list()
  local broken
  for _, e in ipairs(list) do
    if e.name == "broken" then
      broken = e
    end
  end
  check(broken and broken.error, "broken layout file listed with an error")
  check(#list == 3, "other layouts still listed alongside the broken one")

  local removed = bridge.remove("broken")
  check(removed and not bridge.load("broken"), "remove deletes the file")
  local none, nerr = bridge.remove("broken")
  check(none == nil and nerr, "removing a missing layout reports an error")
  check(bridge.save("bad name", quad_spec) == nil, "save refuses invalid names")
end

---------------------------------------------------------------------------
-- 6. Compositor calls use a fake hyprctl so the protocol is exercised
---------------------------------------------------------------------------
do
  -- A fake hyprctl that runs `eval dofile(...)` chunks under plain lua with
  -- a stub `hl`, so query()/preview()/apply() are tested end to end.
  local fake = tmp .. "/fake-hyprctl"
  local f = assert(io.open(fake, "w"))
  f:write(([[#!/usr/bin/env bash
log="%s/hyprctl.log"
echo "$*" >> "$log"
case "$1" in
  eval)
    code="$2"
    file="${code#dofile(\"}"; file="${file%%\")}"
    if grep -q HYPERTILE_FAKE_FAIL "$file"; then echo "error: forced failure"; exit 1; fi
    lua -e '
      hl = {
        get_active_workspace = function() return { id = 3, name = "3", tiled_layout = "lua:quad" } end,
        get_active_monitor = function() return { name = "DP-1", x = 0, y = 0, width = 5120, height = 2880, scale = 2, reserved = { top = 26, right = 0, bottom = 0, left = 0 } } end,
        get_config = function(k)
          if k == "general.gaps_out" then return { top = 10, right = 10, bottom = 10, left = 10 } end
          if k == "general.gaps_in" then return { top = 5, right = 5, bottom = 5, left = 5 } end
          if k == "general.border_size" then return 2 end
          if k == "decoration.rounding" then return 6 end
        end,
        get_windows = function() return { { class = "chromium", title = "Docs\ttab", workspace = { id = 1 }, address = "0x1", floating = false }, { class = "ghostty", title = "sh", workspace = { id = 3 }, address = "0x2", floating = true } } end,
        timer = function(cb, opts) local f = io.open("%s/dispatch.log", "a"); f:write("timer ", tostring(opts.timeout), " ", tostring(opts.type), "\n"); f:close(); if opts.type ~= "repeat" then cb() end; return { set_enabled = function() end } end,
        get_workspace = function(id) return { id = id, tiled_layout = "lua:quad" } end,
        get_workspaces = function() return { { id = 3, name = "3", monitor = { name = "DP-1" }, tiled_layout = "lua:quad", windows = 2, active = true }, { id = 1, name = "1", monitor = { name = "DP-1" }, tiled_layout = "dwindle", windows = 1, active = false } } end,
        workspace_rule = function(spec)
          local function g(v) if type(v) == "table" then return "css" .. tostring(v.top) end return tostring(v) end
          local f = io.open("%s/rule.log", "a"); f:write(spec.workspace, " ", spec.layout, " in=", g(spec.gaps_in), " out=", g(spec.gaps_out), " border=", g(spec.border_size), "\n"); f:close()
        end,
        window_rule = function(spec)
          local f = io.open("%s/rule.log", "a"); f:write("window ", tostring(spec.match.workspace), " float=", tostring(spec.match.float), " rounding=", tostring(spec.rounding), "\n"); f:close()
        end,
        layout = { register = function() end },
        dispatch = function(d) local f = io.open("%s/dispatch.log", "a"); f:write(tostring(d), "\n"); f:close() end,
        dsp = { window = { resize = function(opts) return "resize x=" .. opts.x .. " relative=" .. tostring(opts.relative) end }, layout = function(msg) return "layout " .. msg end },
      }
      package.preload["hypr.hypertile"] = function() return dofile("%s/hypertile.lua") end
      '"$code"'
    ' && echo ok
    ;;
  reload) echo ok ;;
  configerrors) echo "" ;;
esac
]]):format(tmp, tmp, tmp, tmp, tmp, root))
  f:close()
  os.execute("chmod +x '" .. fake .. "'")
  bridge.hyprctl_bin = fake

  local active, err = bridge.active_workspace()
  check(active and active.id == 3 and active.layout == "lua:quad", "active_workspace parses the compositor answer: " .. tostring(err))

  local ok, perr = bridge.preview("quad", quad_spec, 3)
  check(ok, "preview evaluates without error: " .. tostring(perr))
  local rules = slurp(tmp .. "/rule.log")
  check(rules:find("3 lua:quad in=css5 out=css10 border=2"), "preview rule falls back to global gaps/border: " .. rules)
  local gapped = bridge.plain(quad_spec); gapped.gaps = { inner = 0, outer = 24 }; gapped.border = 0
  check(bridge.preview("quad", gapped, 3), "preview with gaps")
  rules = slurp(tmp .. "/rule.log")
  check(rules:find("3 lua:quad in=0 out=24 border=0"), "preview rule carries the layout's gutters: " .. rules)
  local src = bridge.rule_source("7", "lua:x", { gaps = { inner = 3 } })
  check(src:find('gaps_in = 3') and src:find('gaps_out = hl.get_config%("general.gaps_out"%)'), "rule_source mixes literal and global fields: " .. src)
  local rsrc = bridge.rule_source(2, "lua:x", { rounding = 14 })
  check(rsrc:find("rounding = 14 })", 1, true), "a layout's rounding rides on the window rule: " .. rsrc)
  check(src:find('hl.window_rule({ name = "hypertile-workspace-7", match = { workspace = "7", float = false }, rounding = hl.get_config("decoration.rounding") })', 1, true), "rule_source names the rounding rule per workspace so re-applies replace it: " .. src)
  check(not exists(tmp .. "/dispatch.log"), "preview writes the rule only: no resize, no timer (the compositor re-places windows itself)")

  local failed, ferr = bridge.eval_file("-- HYPERTILE_FAKE_FAIL\nreturn 1")
  check(failed == nil and tostring(ferr):find("forced failure", 1, true), "eval_file returns nil, err when hyprctl fails: " .. tostring(ferr))

  local geo, gerr = bridge.geometry()
  check(geo ~= nil, "geometry() answers: " .. tostring(gerr))
  check(geo and geo.monitor.width == 2560 and geo.monitor.height == 1440, "geometry divides by scale (logical size)")
  check(geo and geo.area.x == 10 and geo.area.y == 36 and geo.area.w == 2540 and geo.area.h == 1394,
    "geometry area = monitor minus reserved minus gaps: " .. (geo and (geo.area.x .. "," .. geo.area.y .. " " .. geo.area.w .. "x" .. geo.area.h) or "nil"))
  check(geo and geo.workspace.id == 3 and geo.workspace.layout == "lua:quad", "geometry carries the workspace")
  check(geo and geo.gaps_in == 5 and geo.border_size == 2, "geometry reports global inner gap and border")

  local layout, id = bridge.apply("ultrawide")
  check(layout == "lua:ultrawide" and id == "3", "apply defaults to the active workspace and adds lua: prefix")
  check(not exists(tmp .. "/dispatch.log"), "apply writes the rule only: no resize, no timer, no re-apply")
  check(bridge.heal() == "3", "heal defaults to the active workspace")
  local healed = slurp(tmp .. "/dispatch.log")
  -- The fake registers no layout, so heal falls back to the plain nudge; the
  -- source itself must carry the jiggle logic.
  check(healed:find("resize x=0"), "heal nudges: " .. healed)
  local hsrc = bridge.heal_source(8)
  check(hsrc:find("__st.jiggle = 8", 1, true) and hsrc:find("timeout = 120", 1, true) and hsrc:find("__st.jiggle = false", 1, true), "heal_source jiggles workspace 8 on, then off after 120ms")
  local persisted = slurp(tmp .. "/workspace-rules/3.lua")
  check(persisted:find('workspace = "3", layout = "lua:ultrawide", gaps_in = hl.get_config', 1, true), "apply persists a workspace_rule with gutters: " .. persisted)
  os.execute("mkdir -p '" .. tmp .. "/workspace-layouts'")
  local legacy = assert(io.open(tmp .. "/workspace-layouts/3.lua", "w")); legacy:write('hl.workspace_rule({ workspace = "3", layout = "dwindle" })\n'); legacy:close()
  bridge.apply("ultrawide", 3)
  check(not exists(tmp .. "/workspace-layouts/3.lua"), "apply removes Omarchy's file for the workspace so it cannot override ours at reload")
  bridge.save("gappy", gapped)
  bridge.apply("gappy", 4)
  local persisted4 = slurp(tmp .. "/workspace-rules/4.lua")
  check(persisted4:find("gaps_in = 0, gaps_out = 24, border_size = 0", 1, true), "apply of a saved layout carries its gaps: " .. persisted4)
  bridge.remove("gappy")
  local live, live_id = bridge.apply("quad", 5, { persist = false })
  check(live == "lua:quad" and live_id == "5" and not exists(tmp .. "/workspace-rules/5.lua"), "apply with persist = false writes no rule file")

  -- Unknown layouts and unsafe names never reach the compositor or the disk.
  local missing, merr = bridge.apply("typo", 9)
  check(missing == nil and tostring(merr):find("no layout named typo", 1, true) and not exists(tmp .. "/workspace-rules/9.lua"), "apply of an unknown layout fails without writing a rule: " .. tostring(merr))
  local badws, bwerr = bridge.apply("quad", "../x")
  check(badws == nil and tostring(bwerr):find("invalid workspace id", 1, true), "apply refuses a non-numeric workspace id: " .. tostring(bwerr))
  local badrm, brerr = bridge.remove("../x")
  check(badrm == nil and tostring(brerr):find("invalid layout name", 1, true), "remove refuses a name with path characters: " .. tostring(brerr))
  local badrn, brnerr = bridge.rename("quad", "../x")
  check(badrn == nil and tostring(brnerr):find("invalid layout name", 1, true), "rename refuses a name with path characters: " .. tostring(brnerr))
  local badpath, bperr = bridge.layout_path("a/b")
  check(badpath == nil and tostring(bperr):find("invalid layout name", 1, true), "layout_path refuses a name with a slash")

  -- The name the shell shows, and the SUPER+L cycle.
  check(bridge.display_name("lua:columns") == "columns" and bridge.display_name("dwindle") == "Dwindle" and bridge.display_name("") == "", "display_name strips lua: and capitalises built-ins")
  local names = { "a", "b" }
  check(bridge.cycle_target("lua:a", names) == "lua:b" and bridge.cycle_target("lua:b", names) == "dwindle" and bridge.cycle_target("dwindle", names) == "lua:a", "cycle_target walks layouts then dwindle and wraps")
  check(bridge.cycle_target("lua:a", names, true) == "dwindle" and bridge.cycle_target("dwindle", names, true) == "lua:b", "cycle_target --reverse walks back")
  check(bridge.cycle_target("scrolling", names) == "lua:a" and bridge.cycle_target("scrolling", names, true) == "dwindle", "a layout outside the cycle starts it over")

  -- A burst of presses builds one request; only the last press applies it.
  bridge.paths.runtime = tmp .. "/runtime"
  local on_disk = bridge.cycle_names()
  local t1, s1 = bridge.cycle_request("3", "dwindle", false)
  local t2, s2 = bridge.cycle_request("3", "dwindle", false)
  check(t1 == bridge.cycle_target("dwindle", on_disk) and s1 == 1, "the first press targets the next layout: " .. tostring(t1))
  check(t2 == bridge.cycle_target(t1, on_disk) and s2 == 2, "the second press steps on from the pending target: " .. tostring(t2))
  local rules_before = slurp(tmp .. "/rule.log")
  check(bridge.cycle_commit("3", 1) == false and slurp(tmp .. "/rule.log") == rules_before, "a superseded press applies nothing")
  local applied = bridge.cycle_commit("3", 2)
  check(applied == t2 and slurp(tmp .. "/rule.log"):sub(#rules_before + 1):find("3 " .. t2, 1, true), "the last press applies its target: " .. tostring(applied))
  check(bridge.cycle_pending("3") == nil and bridge.cycle_commit("3", 2) == false, "the request is cleared once applied")

  -- The word to the shell: OSD only when asked, the bar refresh always.
  local fake_shell = tmp .. "/fake-shell"
  local sf = assert(io.open(fake_shell, "w"))
  sf:write("#!/usr/bin/env bash\necho \"$*\" >> '" .. tmp .. "/shell.log'\n")
  sf:close()
  os.execute("chmod +x '" .. fake_shell .. "'")
  bridge.shell_bin = fake_shell
  bridge.notify_shell("lua:quad", true)
  bridge.notify_shell("dwindle", false)
  local shell_log = slurp(tmp .. "/shell.log")
  check(shell_log:find('osd show {"duration": 1200, "icon": "\u{F1CAC}", "message": "quad"}', 1, true) or shell_log:find('"message": "quad"', 1, true), "notify_shell flashes the display name in the OSD: " .. shell_log)
  check(not shell_log:find('"message": "Dwindle"', 1, true), "notify_shell keeps quiet without osd")
  check(select(2, shell_log:gsub("hypertile%-bar refresh", "")) == 2, "notify_shell refreshes the bar widget on every switch: " .. shell_log)

  local wins = bridge.windows()
  check(wins and #wins == 2 and wins[1].class == "chromium" and wins[1].workspace == 1 and wins[2].floating == true, "windows() parses the compositor answer")
  check(wins and wins[1].title == "Docs tab", "windows() flattens tabs in titles: " .. tostring(wins and wins[1].title))
  local wss = bridge.workspaces()
  check(wss and #wss == 2 and wss[1].id == 1 and wss[2].id == 3 and wss[2].active and wss[2].monitor == "DP-1", "workspaces() sorted by id with monitor and active flag")

  -- default layout: read and replace general.layout in a temp looknfeel.lua
  local lf = assert(io.open(bridge.looknfeel_path, "w"))
  lf:write('-- comment\nhl.config({\n  general = {\n    layout = "lua:quad",\n    gaps_in = 5,\n  },\n})\n')
  lf:close()
  check(bridge.default_layout() == "lua:quad", "default_layout reads general.layout")
  check(bridge.set_default_layout("ultrawide") == "lua:ultrawide", "set_default_layout adds the lua: prefix")
  check(bridge.default_layout() == "lua:ultrawide", "set_default_layout replaced the value in place")
  local after = slurp(bridge.looknfeel_path)
  check(after:find("gaps_in = 5", 1, true) and after:find("-- comment", 1, true), "everything else in looknfeel.lua is untouched")
  check(slurp(bridge.looknfeel_path .. ".bak"):find('layout = "lua:quad"', 1, true), "set_default_layout keeps the previous text as .bak")
  check(bridge.set_default_layout("dwindle") == "dwindle", "built-in layout names pass through")

  -- remove honours references: the default is protected, workspace rules
  -- block unless forced, and forcing drops the rules.
  bridge.save("doomed", quad_spec)
  bridge.set_default_layout("doomed")
  local blocked, why = bridge.remove("doomed")
  check(blocked == nil and why:find("default", 1, true), "remove refuses the default layout: " .. tostring(why))
  bridge.set_default_layout("dwindle")
  os.execute("mkdir -p '" .. tmp .. "/workspace-rules'")
  local wf = assert(io.open(tmp .. "/workspace-rules/7.lua", "w"))
  wf:write('hl.workspace_rule({ workspace = "7", layout = "lua:doomed", gaps_in = 2 })\n')
  wf:close()
  local refs = bridge.references("doomed")
  check(#refs.workspaces == 1 and refs.workspaces[1] == "7" and not refs.default, "references lists the workspace rule that uses a layout")
  blocked, why = bridge.remove("doomed")
  check(blocked == nil and why:find("workspace 7", 1, true), "remove refuses a layout a workspace rule uses: " .. tostring(why))
  local gone, dropped = bridge.remove("doomed", true)
  check(gone and dropped[1] == "7" and not exists(tmp .. "/workspace-rules/7.lua") and not bridge.load("doomed"), "forced remove drops the rule and the file")

  -- rename carries workspace rules and the default along.
  bridge.save("old-name", quad_spec)
  bridge.set_default_layout("old-name")
  local wf2 = assert(io.open(tmp .. "/workspace-rules/8.lua", "w"))
  wf2:write('hl.workspace_rule({ workspace = "8", layout = "lua:old-name", gaps_in = 2 })\n')
  wf2:close()
  local rpath, rrefs = bridge.rename("old-name", "new-name")
  check(rpath == tmp .. "/layouts/new-name.lua" and rrefs.default and rrefs.workspaces[1] == "8", "rename writes the new file and reports what followed: " .. tostring(rrefs))
  check(not bridge.load("old-name") and bridge.load("new-name"), "rename removes the old file and the new one loads")
  check(slurp(tmp .. "/workspace-rules/8.lua"):find('layout = "lua:new-name"', 1, true), "rename retargets the workspace rule")
  check(bridge.default_layout() == "lua:new-name", "rename retargets the default")
  local dup, derr = bridge.rename("new-name", "quad")
  check(dup == nil and derr:find("already exists", 1, true), "rename refuses an existing name")
  check(bridge.rename("nope", "x") == nil, "rename of a missing layout fails")
  bridge.set_default_layout("dwindle")
  bridge.remove("new-name", true)
  layout = bridge.apply("dwindle", 5)
  check(layout == "dwindle", "apply passes built-in layouts through unchanged")
  check(bridge.reload() == true, "reload succeeds with no config errors")
end

---------------------------------------------------------------------------
-- 7. CLI smoke test through the real script
---------------------------------------------------------------------------
do
  -- Everything the CLI could touch is pointed into tmp: HOME and the XDG
  -- dirs get fake homes here, the fake hyprctl from section 6 stands in for
  -- the compositor, and the fake shell swallows notifications.
  local home = tmp .. "/home"
  local config_home, state_home = home .. "/.config", home .. "/.local/state"
  os.execute("mkdir -p '" .. config_home .. "/hypr' '" .. state_home .. "/omarchy/workspace-layouts'")
  local lf = assert(io.open(config_home .. "/hypr/looknfeel.lua", "w"))
  lf:write('hl.config({\n  general = {\n    layout = "dwindle",\n  },\n})\n')
  lf:close()
  -- `env` adds or overrides variables; the cycle debounce is off unless a
  -- test turns it on.
  local function run(args, stdin, env)
    local cmd = string.format(
      "(cd '%s' && HOME='%s' XDG_CONFIG_HOME='%s' XDG_STATE_HOME='%s' XDG_RUNTIME_DIR='%s/runtime' HYPERTILE_SRC='%s'"
        .. " HYPERTILE_LAYOUTS_DIR='%s/layouts' HYPERTILE_RULES_DIR='%s/workspace-rules'"
        .. " HYPERTILE_HYPRCTL_BIN='%s/fake-hyprctl' HYPERTILE_SHELL_BIN='%s/fake-shell' HYPERTILE_CYCLE_DEBOUNCE_MS=0 %s lua bin/hypertile-ctl %s)",
      root, home, config_home, state_home, tmp, root, tmp, tmp, tmp, tmp, env or "", args
    )
    if stdin then
      cmd = "printf '%s' '" .. stdin:gsub("'", "'\\''") .. "' | " .. cmd
    else
      cmd = cmd .. " < /dev/null"
    end
    local p = io.popen(cmd .. " 2>&1; echo \"exit=$?\"")
    local out = p:read("a")
    p:close()
    local code = tonumber(out:match("exit=(%d+)%s*$"))
    return out:gsub("exit=%d+%s*$", ""), code
  end

  local out, code = run("dump quad")
  check(code == 0 and out:find('"name": "quad"'), "cli dump prints JSON: " .. out:sub(1, 80))
  local _, vcode = run("validate -", out)
  check(vcode == 0, "cli validate accepts dump output")
  local bad_out, bad_code = run("validate -", '{"name": "q", "spec": {"columns": [{"name": "a"}], "fill": ["nope"]}}')
  check(bad_code ~= 0 and bad_out:find("unknown slot"), "cli validate rejects bad spec: " .. bad_out)
  local demo = '{"name": "demo", "spec": {"columns": [{"name": "a", "w": 1}, {"name": "b", "w": 2}], "fill": ["b", "a"]}}'
  local sout, scode = run("save - --no-reload", demo)
  check(scode == 0 and sout:find("layouts/demo.lua"), "cli save writes the file: " .. sout)
  local lout = run("list")
  check(lout:find("demo") and lout:find("quad"), "cli list shows saved layouts")
  local jout = run("list --json")
  check(jout:find('"fill"') and jout:find('"name": "demo"'), "cli list --json includes specs")
  local pout = run("path demo")
  check(pout:find("layouts/demo.lua"), "cli path prints the file path")
  os.remove(tmp .. "/shell.log")
  local aout, acode = run("apply demo --workspace 3")
  check(acode == 0 and aout:find("workspace 3 -> lua:demo", 1, true), "cli apply reports the switch: " .. aout)
  local alog = slurp(tmp .. "/shell.log")
  check(alog:find('"message": "demo"', 1, true) and alog:find("hypertile-bar refresh", 1, true), "cli apply on the active workspace flashes the OSD and refreshes the bar: " .. alog)
  os.remove(tmp .. "/shell.log")
  run("apply demo --workspace 1")
  alog = slurp(tmp .. "/shell.log")
  check(not alog:find("osd", 1, true) and alog:find("hypertile-bar refresh", 1, true), "cli apply elsewhere only refreshes the bar: " .. alog)
  local nout, ncode = run("apply demo --workspace 6 --no-persist --quiet")
  check(ncode == 0 and nout:find("(not persisted)", 1, true) and not exists(tmp .. "/workspace-rules/6.lua"), "cli apply --no-persist leaves the rules directory alone: " .. nout)
  -- Bad input is refused before anything is written or removed.
  local omarchy_file = state_home .. "/omarchy/workspace-layouts/9.lua"
  local of = assert(io.open(omarchy_file, "w")); of:write('hl.workspace_rule({ workspace = "9", layout = "dwindle" })\n'); of:close()
  local tout, tcode = run("apply typo --workspace 9")
  check(tcode ~= 0 and tout:find("no layout named typo", 1, true), "cli apply of an unknown layout fails: " .. tout)
  check(not exists(tmp .. "/workspace-rules/9.lua") and exists(omarchy_file), "cli apply of an unknown layout writes no rule and removes nothing")
  local wout, wcode = run("apply quad --workspace ../x")
  check(wcode ~= 0 and wout:find("invalid workspace id", 1, true), "cli apply refuses a non-numeric workspace: " .. wout)
  local xout, xcode = run("remove ../x --no-reload")
  check(xcode ~= 0 and xout:find("invalid layout name", 1, true), "cli remove refuses a name with path characters: " .. xout)
  local vout, vcode2 = run("apply quad --workspace")
  check(vcode2 ~= 0 and vout:find("--workspace needs a value", 1, true), "cli --workspace without a value is an error: " .. vout)
  local wsout, wscode = run("apply demo --workspace=6 --no-persist --quiet")
  check(wscode == 0 and wsout:find("workspace 6 -> lua:demo", 1, true), "cli --workspace=N form still works: " .. wsout)
  os.remove(tmp .. "/shell.log")
  run("apply demo --quiet")
  alog = slurp(tmp .. "/shell.log")
  check(not alog:find("osd", 1, true), "cli apply --quiet skips the OSD: " .. alog)
  -- The fake's active workspace (3) reports lua:quad whatever was applied,
  -- so both directions step from quad through whatever is on disk.
  local on_disk = bridge.cycle_names()
  run("save - --no-reload", '{"name": "aside", "spec": {"columns": [{"name": "a"}], "in_cycle": false}}')
  local names_after = bridge.cycle_names()
  local aside_listed = false
  for _, n in ipairs(names_after) do if n == "aside" then aside_listed = true end end
  check(not aside_listed and #names_after == #on_disk, "a layout saved with in_cycle = false stays out of the cycle")
  check(slurp(tmp .. "/layouts/aside.lua"):find("in_cycle = false", 1, true), "in_cycle is written to the layout file")
  run("remove aside --no-reload")
  local cout, ccode = run("cycle")
  check(ccode == 0 and cout:find("workspace 3 -> " .. bridge.cycle_target("lua:quad", on_disk), 1, true), "cli cycle applies the next layout in the cycle: " .. cout)
  local rvout = run("cycle --reverse")
  check(rvout:find("workspace 3 -> " .. bridge.cycle_target("lua:quad", on_disk, true), 1, true), "cli cycle --reverse applies the previous one: " .. rvout)

  -- Two presses inside the debounce window: one switch, to the second target.
  -- Workspace-rule lines for workspace 3 (window-rule lines start with "window").
  local function rule_lines(text)
    local n = 0
    for _ in ("\n" .. text):gmatch("\n3 ") do n = n + 1 end
    return n
  end
  -- The window has to outlast two CLI start-ups, which take tens of ms each.
  local before = slurp(tmp .. "/rule.log")
  local p1 = run("cycle --quiet", nil, "HYPERTILE_CYCLE_DEBOUNCE_MS=400")
  local p2 = run("cycle --quiet", nil, "HYPERTILE_CYCLE_DEBOUNCE_MS=400")
  local second = bridge.cycle_target(bridge.cycle_target("lua:quad", on_disk), on_disk)
  check(p1:find("(pending)", 1, true) and p2:find("-> " .. second .. " (pending)", 1, true) and slurp(tmp .. "/rule.log") == before,
    "debounced presses report their target as pending and apply nothing yet: " .. p2)
  os.execute("sleep 1")
  local after = slurp(tmp .. "/rule.log")
  local added = after:sub(#before + 1)
  check(rule_lines(added) == 1 and added:find("3 " .. second, 1, true), "the burst becomes one switch to the layout landed on: " .. added)
  check(not exists(tmp .. "/runtime/hypertile/cycle-3.json"), "the pending request is cleared once applied")
  local now = run("cycle --now --quiet", nil, "HYPERTILE_CYCLE_DEBOUNCE_MS=400")
  check(now:find("workspace 3 -> ", 1, true) and not now:find("pending", 1, true), "cycle --now switches at once: " .. now)
  -- Point the rules the applies above wrote elsewhere so demo can go.
  run("apply dwindle --workspace 1 --quiet")
  run("apply dwindle --workspace 3 --quiet")
  local rout, rcode = run("remove demo --no-reload")
  check(rcode == 0 and rout:find("removed"), "cli remove deletes: " .. rout)
  local hout, hcode = run("help")
  check(hcode == 0 and hout:find("preview") and hout:find("dwindle|scrolling|master", 1, true), "cli help prints usage with the built-in layouts")
  check(not hout:find("discard", 1, true) and not hout:find("relayout", 1, true), "cli help no longer lists removed commands")
  local _, dcode = run("relayout")
  check(dcode == 2, "cli relayout is gone")
  local _, ucode = run("bogus")
  check(ucode == 2, "cli unknown command exits 2")
end

print(string.format("%d checks, %d failures", checks, failures))
os.execute("rm -rf '" .. tmp .. "'")
os.exit(failures == 0 and 0 or 1)
