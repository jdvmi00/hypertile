# hypertile internals

What the engine, bridge, and overlay rely on from Hyprland's Lua layout
API, the constraints that shaped the overlay, and the forensics behind the
one hard bug so far. The user guide is `README.md`.

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
has finished loading; Omarchy's file for a workspace is removed the
first time hypertile takes it over.

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
