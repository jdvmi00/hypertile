# hypertile internals

What the engine, bridge, and overlay rely on from Hyprland's Lua layout
API, the constraints that shaped the overlay, and the forensics behind the
one hard bug so far. The user guide is `MANUAL.md`; `README.md` is the
reference.

## What the live probe established (Hyprland 0.56.2)

- **Registration.** `hl.layout.register(name, { recalculate, layout_msg })`
  from any Lua that runs in the compositor, including `hyprctl eval`.
  Workspace rules select it as `lua:<name>`. A `hyprctl reload` re-runs the
  config and drops anything added through eval, so layouts and rules must
  live in config files.
- **Runtime.** Plain Lua 5.5, no JIT. `io` and `os` are available. The
  system `lua` binary is the same version, so the harness is representative.
- **Context.** `ctx.area` is a float box that already excludes the bar's
  reserved area and `gaps_out`. `ctx.targets` are userdata with `index`,
  `window`, `box`, `place`, `set_box`. Helpers `grid_cell`, `column`, `row`,
  `split` exist on the context.
- **Target order is compositor-owned and mutable.** `swapwindow` reorders
  `ctx.targets`; the layout sees the new order on the next recalculate. So
  fill-order semantics respond to the stock swap keybinds for free.
- **Floating windows leave the target list** and rejoin at the end when
  re-tiled. Fullscreen windows still appear (fullscreen = 0 field on the
  window) and were not tested further.
- **Window fields** available on `target.window`: `address` (stable, good
  as a pin key), `class`, `title`, `floating`, `fullscreen`, `pinned`,
  `mapped`, `workspace`, `tags`. Static tags arrive with a `*` suffix
  (`"terminal*"`); the library matches with or without it.
- **layout_msg works.** `hl.dsp.layout("...")` calls the provider's
  `layout_msg(ctx, msg)`, and the compositor recalculates immediately after
  it returns. Returning a string makes the dispatch fail with that message,
  which is a clean way to report bad commands.
- **Keyboard resize is not routed to the layout.** `window.resize` only
  triggers a recalculate; the layout's placement wins, so the window snaps
  back. Resizing in a custom layout therefore has to be a layout message
  bound to keys, as in `layouts/ultrawide.lua`. Mouse drag-resize was not
  tested and will most likely behave the same.
- **Recalculate frequency.** Fires on window open, close, float toggle,
  swap, workspace focus, and after every layout message, often twice per
  action. Placement must be cheap and idempotent.
- **Events.** `hl.on("window.open" | "window.close" | "window.active" |
  "workspace.active", cb)` deliver `HL.Window` / `HL.Workspace` userdata;
  useful for scene restore later, not needed for placement.
- **A name cannot be registered twice.** `hl.layout.register` errors with
  "already registered" from eval; reload works because the compositor
  clears Lua layouts first. The engine therefore hot-swaps: calling
  `hypertile.layout(name, spec)` again replaces the spec inside the live
  provider.
- **Relayout after a swap.** Nothing recalculates on its own. Re-applying
  the workspace rule does nothing. A layout message recalculates only the
  focused workspace. A zero-size relative `window.resize` on any tiled
  window of the workspace recalculates it without changing focus or
  window order; the bridge uses that. Toggling float also works but
  reorders windows.
- **`hyprctl activeworkspace -j` reports a stale `tiledLayout`** after a
  rule change; `hl.get_active_workspace().tiled_layout` is correct. The
  bridge asks the compositor through eval and an answer file.

## Stale windows

**Root cause established 2026-09-04:** Hyprland 0.56.2's `CWindow::onAck`
uses an iterator into its pending-size vector as an erase cutoff while the
erase compacts that vector. This can delete the final size for a newer,
coalesced configure serial, leaving the compositor's acknowledged size
incorrect even though the client supplied the correct buffer. The
[investigation and executable regression](diagnostics/size-acks/README.md)
include a minimal compositor backport. Upstream's newer acknowledgment
tracker already captures the cutoff by value. The switching and reload
behavior described below can trigger the defect; suppressing those sequences
does not correct the compositor bug.

Symptom: after cycling layouts quickly a window sits at the right box
but only its top-left part is drawn, at its natural scale, and the rest
of the tile shows the wallpaper. Measured live (Hyprland 0.56.2): a
1814x1257 tile showed 1078x631 of content, which is 1815x1258 (the
client's real buffer) scaled by 1814/3053 and 1257/2506, the size the
window had two layouts earlier. Hyprland draws a surface scaled by
current size over the size it believes the client last acknowledged,
and that acknowledged size had gone stale. Because Hyprland also
believed the current size was already sent, it never sent it again: a
zero-size resize changes nothing; only a real size change
(`hypertile-ctl heal`) clears it.

The trigger was an earlier design of hypertile's apply. It started a
three second settle phase (thirty zero-size nudges, the workspace rule
re-applied at one and three seconds, a 1px shrink and restore at three
seconds) and the overlay added another on close. With SUPER+L pressed a
few times in a row those phases overlapped and each one re-applied its
own layout, so the workspace flipped between layouts for seconds after
the last press: a Wayland trace of a foot window showed configures of
quad, ultrawide, quad, ultrawide, dwindle, quad, ultrawide sizes within
six seconds, an order no key sequence produces. Heavy clients (a busy
Chromium page) acknowledge slowly, and under that storm the
compositor's acknowledged-size bookkeeping is what went stale. Scripted,
paced switches never reproduced it, keyboard bursts did.

A second storm hid underneath: apply persisted the rule into Omarchy's
`~/.local/state/omarchy/workspace-layouts/`, which Omarchy's config
requires, and Hyprland watches every file its config required. Each
write there reloaded the whole config, which unregisters and
re-registers every Lua layout and, in between, places every window on
every workspace with dwindle before putting it back. That is where the
"a second apply fixes it" folklore came from. hypertile keeps its
rules in `~/.local/state/hypertile/workspace-rules/`, which the loader
reads with `io.open` (so nothing watches it) and applies once the config
has finished loading. Apply removes Omarchy's file for a workspace when
hypertile takes it over (see Omarchy workspace modes).

The fix is to not generate either storm: a switch is one workspace rule
write and nothing else, and a Wayland trace of a four-press burst shows
exactly one configure per window per press.

That is still one real re-placement per press, and a fast burst of those
on a workspace with slow clients reproduced the symptom on its own (three
switches 0.8 s apart with a terminal, a browser, and an Electron app on
the workspace). So `hypertile-ctl cycle` debounces: each press records
its target in `$XDG_RUNTIME_DIR/hypertile/cycle-<ws>.json` and flashes
the OSD, and a detached `cycle-commit` applies the request 200 ms later
unless a newer press superseded it. A burst is one switch, to the layout
landed on. `HYPERTILE_CYCLE_DEBOUNCE_MS` tunes it, `--now` bypasses it.
`heal` stays as the manual recovery for the compositor-side condition.

## Omarchy workspace modes

Omarchy's layout toggle (`omarchy-hyprland-workspace-layout-toggle`, behind
the bar's workspace glyph) cycles a workspace through dwindle, scrolling, and
floating. It runs `o.workspace_mode({ workspace, mode })` through `hyprctl
eval` and saves the same line as
`~/.local/state/omarchy/workspace-layouts/<id>.lua`. Floating is not a
Hyprland layout. Omarchy floats the windows itself, tags the ones it floated
`omarchy-mode-floated`, and leaves the tiled layout in place, so
`tiled_layout` keeps naming the layout underneath.

`hypertile-modes.lua` holds the rules both sides follow:

- **One saved choice per workspace.** Each side keeps its own file, and the
  latest pick removes the other side's file. The bridge and the scene
  service remove Omarchy's file when they save a rule. A wrapper around
  `o.workspace_mode` removes hypertile's rule when Omarchy's toggle runs.
  With neither file, the workspace follows Omarchy's `default.lua` or
  `general.layout`.
- **A pair of files is not a pick.** `omarchy-hyprland-workspace-layout-default`
  writes a file for every busy workspace when the default changes, without
  calling `o.workspace_mode`, so the wrapper never sees it. For a hypertile
  workspace that file names `lua:<layout>`, or the old default when
  `default.lua` already existed. Hypertile's rule stays in charge of such a
  pair. Only the first load with this version treats a pair as a pick: before
  the wrapper existed, Omarchy's toggle left hypertile's rule behind, and the
  newer file was the user's choice. `omarchy-modes-migrated` in hypertile's
  state directory records that the first load ran.
- **Floating is its own fact.** The module mirrors Omarchy's private
  `modes` table. It reads the mode each of Omarchy's saved files passes to
  `o.workspace_mode`, then follows the wrapper and hypertile's own picks. `hypertile-ctl current`, `workspaces --json`,
  and the bar widget read `floating` from it.
- **Only a pick ends floating.** A pick is a persisted apply, a scene, or a
  saved rule applied at load. It calls Omarchy's unwrapped `o.workspace_mode`
  with the layout, which tiles the floated windows and records the mode.
  Transient writes set the workspace rule directly and leave a floating
  workspace floating. Those are `--no-persist`, previews, overlay browsing,
  display policy reapplies, and session restore. Routed through Omarchy, a
  transient write un-floats the workspace, so browsing in the overlay and
  reverting, or a display reapply under a floating default, would end
  floating mode.
- **Restore leaves floating to Omarchy.** Omarchy floats and tags a window
  that arrives on a floating workspace. Session restore used to float such a
  window first, which left it untagged and floating after the mode ended.

The nested probe behind `test/omarchy_modes_integration.py` established
these facts on Hyprland 0.56.2:

- `o.workspace_mode` does not exist while `hypertile-layouts.lua` runs,
  because Omarchy's loader comes later, from `default.hypr.toggles`. It
  exists when the loader's 1 ms timer fires. The timer attaches the module,
  then applies hypertile's saved rules.
- A reload builds a fresh Lua state. Omarchy defines `o.workspace_mode`
  again, and the timer wraps the new function once.
- Rewriting or deleting an Omarchy file that the last load required reloads
  the whole config. Creating a new file there does not. Hyprland watches
  each required file and reloads on any event from that watch. Removing
  hypertile's rule from the wrapper never reloads, since nothing watches it.
- A `require` that loads a file at runtime goes through Hyprland's hook on
  the Lua file searcher. `test/display_integration.py` failed 3 of 3 runs
  while every compositor query loaded `hypertile-modes.lua` that way, and
  passed again when the queries stopped. The bridge's queries therefore
  read `package.loaded`, which only has the module once the loader attached
  it.

## What shapes the overlay

- **Gaps are the compositor's.** `gaps_in` is applied around every placed
  box and `gaps_out` is already removed from `ctx.area`: a box of
  (1235,36 3674x2514) became a window at 1242,38 sized 3660x2510 with
  `gaps_in` 5 and `border_size` 2. Both are per-workspace rule fields, so
  per-layout gutters are a workspace-rule concern, not placement math.
- **Coordinates.** The overlay window covers the whole monitor
  (`ExclusionMode.Ignore`) and works in monitor-local logical pixels. The
  bridge's `current --json` area already subtracts the bar's reserved edge
  and the outer gap, so drawn zones line up with real windows to the pixel.
- **The shell caches compiled QML** for on-demand panels. After editing
  the overlay, `rescanPlugins` is not enough; `omarchy restart shell` loads
  the new code. `install.sh` restarts the shell when the plugin files
  changed.
- **One pointer handler.** With an array model, any change recreates
  Repeater delegates, and a MouseArea mid-drag dies with them. Dividers
  are therefore visual only; one MouseArea over the whole area does its
  own hit-testing (`Editor.dividerAt`, `Editor.leafAt`).
- **Quickshell's FileView skips identical writes** and never emits `saved`
  for them. The overlay's preview and save wait for `saved`, so every
  document carries a `stamp` field the bridge ignores.
- **A layout message reaches only the focused workspace,** and re-applying
  a workspace rule does nothing after a hot swap. Preview therefore
  re-places the target workspace with a zero-size relative resize on one
  of its tiled windows, which recalculates without changing focus or
  order.
