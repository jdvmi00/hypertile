# Hypertile

Design zone layouts for Hyprland on [Omarchy](https://omarchy.org/), then
move your windows between them. Browse and edit layouts directly over your
desktop, save app arrangements as scenes, and manage your displays from the
same overlay.

- **Layouts:** split and resize zones, choose their fill order, and tune gaps,
  corners, aspect ratios, and stacking.
- **Window movement:** move or swap windows with keyboard shortcuts, numbered
  destinations, or drag and drop.
- **Scenes:** assign apps to zones and save arrangements you can return to.
- **Displays:** arrange or mirror screens, adjust resolution and scale, and
  choose workspace placement and monitor layout defaults.
- **Session recovery:** save the desktop and restore supported apps when you
  log in again.

[![Hypertile highlights: layout switching, window swaps, live zone editing, and display arrangement](docs/demo.gif)](docs/media/hypertile-highlights.mp4)

[Watch the full 73-second demo](docs/media/hypertile-highlights.mp4).

[Install](#install) · [Everyday use](#using-it) · [Overlay](#overlay) ·
[CLI](#cli) · [Update](#update) · [Uninstall](#uninstall) ·
[Documentation](#documentation) · [Development](#development)

## Requirements

Requires Omarchy 4 with its Lua Hyprland config and Omarchy shell. Development
and local validation use Hyprland 0.56.2 / Omarchy 4.0.3, with the separately
installed `0.56.2-2.1` compositor backport described in the
[sizing diagnostics](docs/HYPRLAND-SIZING-BUG.md).

Runtime and setup use the Omarchy shell (Quickshell), Bash, `lua`, `jq`,
Python 3, coreutils, and `flock` from util-linux, included with Omarchy.
Setup runs as your user; it does not install packages or patch the compositor.

## Install

```bash
omarchy plugin add https://github.com/jdvmi00/hypertile.git --enable
```

Enabling the plugin installs its runtime automatically. The widget briefly
shows **Setting up Hypertile…** while setup finishes. A newly created layouts
directory starts with `welcome`, a four-zone layout; existing layout directories
are left untouched.

Open the overlay with `SUPER+ALT+L` or the bar widget. Choose a layout and press
`Enter` to use it, or choose **Edit** to make it your own. `SUPER+L` cycles
through saved layouts and then dwindle; `SUPER+SHIFT+L` cycles backwards.
See the [user manual](docs/MANUAL.md#your-first-layout) for a first walkthrough.

<details>
<summary>What setup changes</summary>

Setup installs the engine and bridge under `~/.config/hypr/`, the CLI commands
under `~/.local/bin/`, and the display, Scenes, and session recovery services.
It adds the layout loader to `hyprland.lua`, a bar widget, a **Layouts** menu
entry, navigation shortcuts, and guarded logout/reboot/shutdown actions that
save the session before closing apps. Custom power-menu actions are left alone.

The cycling shortcut replaces Omarchy's default dwindle/scrolling toggle;
an existing custom **Toggle workspace layout** binding is left alone.
Every config file the installer edits is first copied to
`<file>.hypertile.bak` if that backup does not exist. Later installs preserve
that first backup. The installer reloads Hyprland and checks
`hyprctl configerrors`.

For a manual install with optional integrations omitted, add the plugin
without `--enable`, then run its `install.sh` with `--no-menu` and/or
`--no-keybinds`. Automatic updates remember these choices.

</details>

## Using it

| Where | What |
|---|---|
| `SUPER+L`, `SUPER+SHIFT+L` | next or previous layout on this workspace; the name flashes in the OSD |
| `SUPER+ALT+L`, the bar widget, `SUPER+SPACE` > Layouts | open the overlay |
| `SUPER+ALT+T`, then a tile number | move the active window to that tile, swapping if occupied; `Esc` cancels |
| `SUPER+Arrow` / `SUPER+SHIFT+Arrow` | focus a window / move or swap it into the next slot |
| `SUPER` + left mouse drag | drag a tiled window to a numbered destination |
| bar widget | the layout on this monitor's workspace; scroll or middle-click cycles |
| `hypertile-ctl list` | the layouts on disk, the one in use starred |

Layouts live one per file in `~/.config/hypr/layouts/<name>.lua`. A layout
saved from the overlay joins the `SUPER+L` cycle (every layout on disk in
name order, then dwindle); one saved with `in_cycle = false` is skipped by
the cycle and still shown by the overlay. Pressing `SUPER+L` several times
quickly flashes each name and switches once, to the layout you stop on.

Each workspace remembers its explicit layout in
`~/.local/state/hypertile/workspace-rules/`. Otherwise it inherits the monitor's
default layout, falling back to `general.layout` in `looknfeel.lua`. Choose
**Follow monitor default** in the Layouts rail, or run
`hypertile-ctl apply monitor-default`, to clear a workspace override. An active
scene keeps its required layout until you confirm a replacement.

### Moving and swapping windows

`SUPER+Arrow` focuses the nearest window in that direction. `SUPER+SHIFT+Arrow`
moves to the next layout slot: an empty slot receives the active window, and an
occupied slot swaps windows. Other apps stay in their slots; spacers and scene
slots marked Empty are skipped. Moving into a collapsed slot reveals the full
layout on that workspace until the layout is reset.

`SUPER+ALT+T` shows numbered destinations for the active window. Release the
modifiers and type a tile number, or click a tile, to move there (or swap with
its occupant). `Esc` cancels; the current tile is highlighted. Numbers match
the layout's fill order, including multiple numbers for a stacked zone.
When a number is also a prefix (for example, 1 and 10), press `Enter` to select
the shorter number; `Backspace` corrects input. Spacers and scene slots marked
Empty are excluded. A zone without a fill number can still be clicked.
Outlines follow each tile's fitted window area, including aspect ratio and
scale, so unused space outside that area is not outlined.

`SUPER` + left mouse drag also shows those destinations for a tiled window.
Drop over a tile to move there (or swap if occupied); the hovered tile is
highlighted. Dropping outside the outlined tiles keeps Hyprland's normal drag
result. Destinations stay on the starting workspace and monitor. Floating
windows and other layouts keep their normal mouse behavior.

## Overlay

A fullscreen layer draws the viewed layout's zones at true scale over your
windows. Each zone carries a badge with its position in the fill order (a
slot holding several positions shows "5 · 6" and a divider per stacked
window) and chips for its size and constraints. The inspector rail holds
the layout's name, the actions, and the settings for the current mode. It
docks on the left or the right and remembers that, along with which
sections are open, in `~/.local/state/hypertile/overlay.json`.

### Layouts tab

Each tile shows its width × height in pixels beneath its fill-order number,
updating as you resize the layout.

| Key | Action |
|---|---|
| arrows or `h` `j` `k` `l`, or a click in the rail's list | browse the layouts on disk; the workspace follows |
| `SUPER+L`, `SUPER+SHIFT+L` | browse forward/backward, moving the displayed layout and windows together |
| `Enter` | use the viewed layout on this workspace and close |
| `Esc`, click outside | close; the workspace goes back to the layout it had |
| `Space` (hold) | peek: the overlay fades to hairlines |
| `e` | edit the viewed layout |
| `n` | new layout, blank or a copy of the viewed one |
| `F2` | rename (workspace rules and the default follow) |
| `d` | delete, after a confirmation |
| `r` | re-read the layouts and the workspace |
| `?` | show or hide the keys in the rail |

Browsing switches the workspace for real, without persisting: each step is
a compositor-only switch, debounced behind the keys so a held arrow lands
once, and the scrim lightens so the windows show through. A layout used as
the global or a monitor default cannot be deleted until another default is
chosen. Workspaces whose explicit layout is deleted return to inheritance. The rail's **Workspaces** section uses the viewed
layout on any workspace, on every workspace of a monitor, or as the
default, and keeps the overlay open.

### Edit mode

Edits preview live on an unmanaged workspace. When a workspace has assigned
content, preview stays off: saving an existing layout applies the changes, and
saving a new layout asks before using it and replacing those assignments.

![Edit mode with the top-left zone selected: split buttons on the zone, the Zone section in the rail](docs/screenshots/overlay-edit.jpg)

| Key | Action |
|---|---|
| click, arrows or `hjkl`, `Tab` | select a zone |
| `c`, `r` | split the selected zone into columns or rows |
| `x`, `Delete`, right-click | delete it; the neighbour absorbs the space |
| drag a divider | resize the two zones it separates |
| `Shift` + arrows | move the selected zone's edge by 1% of the screen |
| `s` | toggle spacer (an empty hole that never takes windows) |
| `f` | renumber: click zones in fill order, `Backspace` undoes, `Enter` finishes |
| `u` | undo |
| `w`, `Ctrl+S` | save (a new layout asks for a name) |
| `Esc` | leave; with unsaved changes it asks: Discard, Save, or keep editing |

The rail's **Zone** section names the selected zone (names matter in the
file and for app rules, so view mode does not show them), sets its exact
size in percent of the screen, and its options: spacer; never split (one
window at most, never an overflow target while another zone exists);
stack direction; capacity; aspect ratio (1:1, 4:3, 3:2, 16:9, 21:9) and
scale, so a 1:1 aspect ratio at 70% fits a smaller square inside the zone. **Opens here** lists the apps pinned to the zone, picked from the
windows open now; an app allowed in several zones fills them lowest number
first. **Layout** sets the gutters (the gap between windows, the gap
around the layout, the border), the window corner radius for the layout's
workspaces, the empty and lone-window policies, and whether the layout is
in the `SUPER+L` cycle.

Zones you did not click while renumbering follow the clicked ones in tree
order. Discarding an unmanaged edit previews the saved layout back onto the
workspace; nothing reloads. Discarding managed edits leaves the workspace
as it was. Gutters and rounding travel with the layout as workspace and
window rules. See [engine internals](docs/INTERNALS.md) for switch behavior.

### Scenes tab

Switch to **Scenes** to choose what each zone holds: **Local windows**, **Empty**,
an open window, or an installed app. Click a zone, press its fill number outside
the search field, or use `Tab` to select it. Type to search; app names can start
with digits. `↑`/`↓` select a match, `Enter` assigns it, and `Tab` moves to the
next zone while keeping the query. `Esc` clears a query first, then closes;
`?` shows the keys. Ordinary letters, including `hjkl`, remain search text.

With no zone selected, `↑`/`↓` browse saved scenes, `Enter` uses the selected
scene, and `Delete` asks before removing its file (`Enter` confirms, `Esc`
cancels). **Save** updates the named scene; **Save as…** stores another one.
Using a saved scene asks before replacing unsaved scene changes. **Retry**
rechecks pending content, and **Restore previous** returns to the arrangement
from before the scene. Clicking outside the zones deselects first; a second
click closes. See [Scenes and content](docs/SCENES.md) for placement, recovery,
and app identity details.

<details>
<summary>Remote desktop apps and migration</summary>

Scenes can launch or reuse installed apps in named zones, including each
computer's Remote Desktops launcher. Placement happens once; subsequent window
moves and closes stay under your control. The independent Scenes service does
not own remote connections or host display settings.

Use the overlay’s **Scenes** tab or `hypertile-ctl scene` to assign apps, local
windows, or Empty, then save the arrangement. See [scenes and content](docs/SCENES.md)
for setup, migration from legacy stream sources, and recovery behavior.
Remote connections and host recovery now belong to
[Remote Desktops](https://github.com/jdvmi00/remote-desktops). Upgrade checks
require legacy connections to be disconnected and restored before removing
their old runtime files; saved configuration and journals are preserved.

</details>

### Displays tab

Choose **Displays** to arrange or mirror screens, change resolution, refresh
rate, scale and rotation, or sleep and wake outputs. Select a display and use
**Workspace → Apply** to switch its workspace immediately; **Use this workspace at
startup** saves a starting workspace through Preview/Keep. Expand **Workspace
preferences** to assign workspaces and choose a default layout for a monitor.

**Wallpaper groups…** spans an image across selected displays while keeping
others independent. Each group can follow the theme or use a fixed custom image.
Apply wallpaper saves immediately.

Arrangement and workspace preference changes use a 15-second **Keep/Revert**
preview with an independent rollback watchdog. **Keep changes** saves adjusted
monitor fields to `~/.config/hypr/monitors.lua`, preserving unrelated and
unchanged automatic settings. Existing monitor configuration is adopted
automatically; setup does not rearrange your screens.

**Desktop text size** applies immediately to every display and is separate
from Preview and Keep. Sleep/wake is also immediate and temporary.
See [Displays and workspace placement](docs/DISPLAYS.md) for mirroring,
configuration ownership, reconnect behavior, and the shared UI/CLI workflow.

## Bar widget

An **!** badge means session saving needs attention. The tooltip explains why;
open the overlay to see unmatched windows or resume saving after a partial
restore or freeze. See [Session recovery](docs/SESSIONS.md).

The bar widget shows the layout icon and name on each monitor's active
workspace. Clicking opens the overlay; the scroll wheel or a middle-click cycles. It follows workspace
focus, workspaces moving between monitors, and config reloads on its own,
and `hypertile-ctl` pokes it after every apply, since a workspace rule
write raises no compositor event. `omarchy bar move jmartin.hypertile
--section center` moves it. The shell tracks the plugin by that one bar
entry, so `omarchy plugin disable jmartin.hypertile` drops the overlay too.

## Session recovery

Hypertile saves the desktop after changes and restores supported applications
on the next Hyprland session. It restores zone layouts, native window order,
pins, runtime sizing, workspaces, floating geometry, and focus. Applications
restore their own tabs/documents; terminal commands are not replayed.

Turn this on or off with **Startup → Save windows for startup** in the
overlay, or `hypertile-ctl session enable|disable`. The choice takes effect
immediately and persists across reboots. Enabling saves the current desktop.

Use the guarded Omarchy menu actions or `hypertile-ctl session logout`,
`reboot`, or `shutdown` so the snapshot is saved before applications close.
`hypertile-ctl session status` reports progress and unmatched windows. Apps
with no launch recipe are skipped without holding anything up. A partial
restore (an app that failed to launch or whose window never appeared) protects
the original snapshot until you retry or explicitly accept the current desktop
with `hypertile-ctl session resume`; a notification says so, and again at
logout while saving is still paused.

`hypertile-ctl session save work` saves a named session;
`hypertile-ctl session restore work` returns to it. See [session recovery](docs/SESSIONS.md) for app recipes,
shutdown integration, storage, and limits.

## Documentation

| Guide | Covers |
|---|---|
| [User manual](docs/MANUAL.md) | getting started, daily use, layout recipes, and troubleshooting |
| [Scenes](docs/SCENES.md) | app assignments, saved arrangements, and recovery |
| [Displays](docs/DISPLAYS.md) | monitor settings, mirroring, and workspace placement |
| [Session recovery](docs/SESSIONS.md) | app recipes, named sessions, and shutdown integration |
| [Development guide](docs/README.md) | working checkout, runtime updates, and verification |
| [Engine internals](docs/INTERNALS.md) | layout behavior and compositor integration |
| [Changelog](CHANGELOG.md) | release history and unreleased changes |

### Known sizing issue

**Hyprland 0.56.2 sizing bug:** after a layout switch or save, a window's
content can remain smaller than its tile. `hypertile-ctl heal` is temporary
recovery. A one-line compositor backport fixes the identified acknowledgment
bookkeeping defect. See [the sizing bug and backport guide](docs/HYPRLAND-SIZING-BUG.md)
for building/installing it, checking it after Omarchy updates, rollback, and
returning to an official package that includes the upstream correction.

## CLI

Run `hypertile-ctl help` for command syntax. The CLI can also run directly
from this checkout with `HYPERTILE_SRC=$PWD bin/hypertile-ctl help`.

### Layout commands

```text
hypertile-ctl list [--json]            layouts on disk, the one in use starred; --json includes each spec
hypertile-ctl dump <name>              layout as JSON  {"name":..., "spec":{...}}
hypertile-ctl validate [file|-]        check JSON, silent on success
hypertile-ctl save [file|-] [--no-reload]
                                       write layouts/<name>.lua, reload
hypertile-ctl rename <old> <new> [--no-reload]
                                       rename the file; workspace rules and the default follow
hypertile-ctl remove <name> [--force] [--no-reload]
                                       delete the file, reload; refuses global or monitor defaults;
                                       --force clears workspace references
hypertile-ctl preview [file|-] [--workspace N] [--no-apply]
                                       hot-swap in the compositor and re-place the workspace, no disk write
hypertile-ctl apply <name|monitor-default|dwindle|scrolling|master> [--workspace N] [--quiet] [--no-persist]
                                       workspace rule, persisted in ~/.local/state/hypertile/workspace-rules/;
                                       the shell flashes the name (unless --quiet, or the workspace is
                                       not the active one) and the bar widget refreshes; --no-persist
                                       switches the compositor only; monitor-default clears the
                                       workspace override
hypertile-ctl cycle [--reverse] [--workspace N] [--quiet] [--now]
                                       apply the next layout: every saved layout in name order
                                       (in_cycle = false skips one), then dwindle; presses within
                                       200 ms become one switch to the layout landed on (--now
                                       switches at once); while the Layouts overlay is open,
                                       cycle browses there instead (--now bypasses this)
hypertile-ctl heal [--workspace N]     manual recovery for a window drawn smaller than its tile
hypertile-ctl current [--json]         active workspace id, name, layout; --json adds monitor size,
                                       reserved edges, gaps, border, layout area
hypertile-ctl workspaces [--json]      every workspace with monitor, layout, window count
hypertile-ctl windows [--json]         open windows (class, title, workspace)
hypertile-ctl default [name|dwindle|scrolling|master] [--no-reload]
                                       show or set the default layout (looknfeel.lua)
hypertile-ctl path [name]              layouts dir or a layout's file
```

Reading a layout back executes its file with a recording stub in place of
the engine, so hand-edited files round-trip as long as they are valid Lua.

### Scenes, displays, and sessions

| Command | Purpose | Reference |
|---|---|---|
| `hypertile-ctl scene` | save and apply scenes, assign content, retry or restore | [Scenes](docs/SCENES.md#cli) |
| `hypertile-ctl display` | inspect displays, preview/keep/revert changes, identify, sleep or wake | [Displays](docs/DISPLAYS.md#cli) |
| `hypertile-ctl session` | check recovery, enable/disable saving, save/restore named sessions, guarded logout | [Sessions](docs/SESSIONS.md) |

```bash
hypertile-ctl scene list
hypertile-ctl display list --json
hypertile-ctl session status
```

### Overlay scripting

While the overlay is open, `omarchy-shell hypertile <method> [args]` drives
it:

| Method | Effect |
|---|---|
| `next`, `prev`, `view <name>` | browse |
| `use`, `apply`, `applyTo <ws>`, `applyMonitor <mon>`, `setDefault` | use the viewed layout (`use` closes) |
| `inCycle <bool>`, `rename <name>`, `deleteLayout` | layout housekeeping |
| `edit`, `newLayout`, `newBlank` | enter edit mode (copy or blank) |
| `select <zone>`, `move <dir>`, `split <zone> <columns\|rows>`, `remove <zone>` | zones |
| `nudge <w\|h> <delta>`, `size <zone> <w\|h> <fraction>`, `resize <path> <index> <ratio>` | sizes |
| `renameZone <zone> <name>`, `renumber <a,b,c>`, `zoneProp <zone> <key> <value>`, `capacity <zone> <n>` | zone settings |
| `layoutProp <key> <value>`, `gap <inner\|outer> <px>`, `addRule <class> <zone>`, `removeRule <i>` | layout settings |
| `undo`, `saveAs <name>`, `discard` | finish an edit |
| `content <bool>` | show Scenes (`true`) or Layouts (`false`); leave edit mode first |
| `displays`, `displayState` | open Displays or read its draft, preview, and error state |
| `displaySelect <index>`, `displaySet <index> <key> <value>` | select or edit a display in the draft (zero-based index) |
| `displayPreview`, `displayKeep`, `displayRevert` | preview, keep, or revert display changes |
| `displayIdentify <connector>`, `displayDiscard` | identify a display, or discard edits and close |
| `assign <local\|empty>` | set the selected zone to local fill or empty |
| `assignApp <class>` | pin an already-open window of this class to the selected zone; does not launch an app |
| `scene <action> <name>` | request a scene action on the current workspace; see actions below |
| `saveSceneAs`, `saveScene <name>`, `deleteScene <name>` | open the scene naming field, save directly, or delete directly |
| `confirmSwitch` | confirm the pending layout or scene replacement |
| `search <text>`, `pick` | set the app query, then assign the selected search match |
| `hover <index>`, `focusSearch` | preview a search match by zero-based index (`-1` clears), or focus the search field |
| `dock <left\|right>`, `keysHint <bool>`, `peek <bool>`, `refresh`, `close` | the overlay itself |
| `viewed`, `draft`, `state` | read back the viewed name, the draft, or the whole state as JSON |

For content assignments, switch to Scenes and select a zone first. `assignApp`
accepts a window class; to launch or reuse an installed app, use `search` and
`pick`. `scene` actions include `apply`, `save`, and `remove` with a scene name,
or `retry`, `restore`, and `dismiss` with an empty name argument (`""`). Use
`state` to inspect `pendingSwitch`, scene progress, or errors; `confirmSwitch`
accepts a pending replacement. `deleteScene` removes the saved definition
immediately, without the UI's confirmation prompt.

```bash
omarchy-shell hypertile content true
omarchy-shell hypertile select left
omarchy-shell hypertile search '1Password'
omarchy-shell hypertile state  # check that matches is greater than zero
omarchy-shell hypertile pick
omarchy-shell hypertile state
```

Replace `left` with a zone name from your layout. Placement may continue after
the command returns; read `state` to check its result.

## Spec

```lua
local hypertile = require("hypr.hypertile")

hypertile.layout("ultrawide", {
  columns = {
    { name = "left",   w = 0.2 },
    { name = "center", w = 0.6 },
    { name = "right",  w = 0.2, rows = { { name = "r1" }, { name = "r2", h = 2 } } },
  },
  -- leaf options: aspect = 1 (w/h), scale = 0.7, spacer = true, never_split = true, stack = "h"
  fill  = { "center", "right", "left" },   -- where the first unassigned windows go
  cycle = { "right", "left", "center" },   -- where the rest go (defaults to fill)
  rules = { { class = "^chromium$", slot = "center" }, { tag = "terminal", slot = "right" } },
  capacity = { r1 = 1 },                   -- overflow spills to the next fill slot
  gaps = { inner = 0, outer = 0 },         -- gutters, applied as workspace rules
  border = 0,                              -- border size, same
  rounding = 12,                           -- window corner radius 0..20, as a window rule
  empty  = "collapse",                     -- or "keep": empty slots leave a gap;
                                           -- any container node can override with its own `empty`
  single = "collapse",                     -- or "slot": one window stays in its slot
  stack  = "v",                            -- or "h": how windows share a slot
  in_cycle = false,                        -- leave out of the SUPER+L cycle (default true)
})
```

Use it from a workspace rule (`layout = "lua:ultrawide"`) or as the global
layout. Runtime commands go through the layout dispatcher:

```lua
hl.dsp.layout("pin center")        -- pin the active window to a slot
hl.dsp.layout("unpin")
hl.dsp.layout("grow center 0.05")  -- adjust a slot's weight
hl.dsp.layout("size center 1.0")
hl.dsp.layout("reset")
```

New installs include `welcome`: four equal zones filled top-left, top-right,
bottom-left, then bottom-right, with horizontal stacks in the top two zones
and 20-pixel rounding. The bottom zones hold one window each; empty zones
keep their space, and a lone window stays in its slot.

The repository also includes two example layouts for reference and tests; neither
is installed automatically:

- `ultrawide`: 20/60/20 columns, fill center, right, left, then cycle.
- `quad`: same columns, but the center is four quadrants filled top-left,
  top-right, bottom-left, bottom-right, then right (stacked), then left
  (stacked). Every slot keeps its place when empty, so a lone window sits
  in the top-left quadrant.

## Update

```bash
omarchy plugin update jmartin.hypertile
```

Enabled plugins apply runtime updates automatically; disabled plugins apply
them when next enabled. Shell restarts skip setup when the runtime is current.
If setup fails, the widget points to `~/.local/state/hypertile/install.log`
(`$XDG_STATE_HOME/hypertile/install.log` when set). Resolve the reported issue,
then disable and re-enable Hypertile to retry.

Development links use `./install.sh` once and `./dev apply` after edits.

## Uninstall

Uninstall with:

```bash
~/.config/omarchy/plugins/jmartin.hypertile/uninstall.sh
# Choose the archive location instead:
# .../uninstall.sh --archive ~/Backups/my-hypertile-settings
# Or permanently discard settings without an archive:
# .../uninstall.sh --purge
```

Uninstall first copies and verifies an archive in
`~/Backups/hypertile-uninstall-<timestamp>/` (or the new directory supplied
with `--archive`). It then removes layouts, all Hypertile settings, scenes,
state, runtime files and caches, installer-created `.hypertile.bak` files,
and the installed plugin checkout. Development symlinks are unlinked without
removing their source checkout. The shell restarts to clear cached plugin UI,
so reinstalling another version cannot show the old version's menus.

The archive includes `layouts/`, `settings/`, `state/`, reference copies of
desktop configuration, and the plugin checkout. Its `README.txt` explains
restoration. To restore only layouts after testing a clean install, copy the
contents of `layouts/` into `~/.config/hypr/layouts/` (or
`$XDG_CONFIG_HOME/hypr/layouts/`) and run `hyprctl reload`. Existing archive
paths are refused; if archiving fails, uninstall stops before removing files.
`--purge` explicitly skips archiving; both modes leave a clean installation.

The default layout returns to dwindle if it used Hypertile. Monitor settings
and unrelated desktop customizations remain. If a custom binding still
references `hypertile-navigation`, uninstall retains runtime files and asks
you to remove that reference before running it again. Active legacy remote
connections must also be restored before uninstalling.

## Development

For live development, keep one checkout and link the installed plugin to it:

```sh
./dev link       # preserves the existing installation, then links this checkout
./install.sh     # first-time runtime/config setup
./dev apply      # validates and applies changes; restarts affected components
./dev status
```

After setup, edit locally and run `./dev apply`. See the
[development README](docs/README.md) for component reloads, layout previews,
backup/recovery paths, and isolated testing. The regular installer also supports
an unlinked source checkout when the destination is a plain plugin copy; it
refuses to overwrite a different Git checkout.

Run the tests from the repository root:

```bash
shellcheck install.sh uninstall.sh
python3 test/dev.py && python3 test/upgrade.py   # deployment helper: preservation, restarts, failures
python3 test/install.py                          # installer and uninstaller
python3 test/displays.py && python3 test/display_configuration.py && python3 test/display_policy.py && node test/displays.js
                                                 # display transactions, failure recovery, assignment policy
python3 test/display_integration.py               # opt-in isolated compositor, from a live Wayland session
lua test/harness.lua && lua test/loader.lua      # engine: placement, rules, capacity, messages, hot swap
lua test/navigation.lua && node test/tile_picker.js  # directional and numbered moves, swaps, picker input
lua test/bridge.lua                              # bridge and CLI, against a fake hyprctl
python3 test/session.py && python3 test/scene_recovery.py && lua test/session.lua && node test/session.js
                                                 # recovery: durable writes, shutdown, restart, identity
python3 test/scenes.py && python3 test/apps.py && lua test/scenes.lua && lua test/swap.lua
node test/content.js && node test/content_keys.js  # scenes, app catalog, placement, the Scenes tab
python3 test/browse.py && node test/browse.js    # managed layout browsing
node test/wallpaper.js && python3 test/wallpaper.py # wallpaper groups and settings
node test/geometry.js                            # overlay drawing math
node test/editor.js && node test/overlay.js && node test/readability.js
                                                 # editor operations (validated by the engine), overlay, contrast
omarchy plugin validate .
```

[The CI workflow](.github/workflows/test.yml) runs the unit suites and manifest
checks. The isolated compositor integration test and `omarchy plugin validate`
are local checks requiring the corresponding environment; CI also checks the
migrated Windows display policy in the Remote Desktops repository.

The harness also checks that the `ultrawide` spec places 1 to 9 windows
where the hand-written provider in `test/fixtures/legacy-ultrawide.lua`
put them (within 1px on stacked heights, where hypertile rounds edges
instead of sizes to avoid seams). The CLI runs from a checkout without
installing: `HYPERTILE_SRC=$PWD bin/hypertile-ctl list`.

## Layout of this repository

<details>
<summary>Source files and architecture</summary>

```
manifest.json          the Omarchy plugin manifest (kinds: overlay, bar-widget, service)
plugin/                the shell plugin: Overlay.qml, Rail.qml (inspector), ZoneItem.qml,
                       Divider.qml, Thumb.qml, Card.qml, Chip.qml, Geometry.js (drawing),
                       Editor.js (edits); DisplaysPane.qml and Displays.js (display settings);
                       ContentPane.qml and Content.js (the Scenes tab);
                       TilePicker.qml and TilePicker.js (numbered tile destinations);
                       LayoutWidget.qml (bar widget); SessionStatus.qml and Session.js
                       (session status); Service.qml (automatic setup on enable and
                       update); Readability.js (text contrast)
hypertile.lua          engine: spec -> layout provider (hot-swappable)
hypertile-bridge.lua   bridge: load/serialize/JSON/save/preview/apply
hypertile-json.lua     JSON encode/decode (pure Lua)
hypertile-layouts.lua  loader: requires every ~/.config/hypr/layouts/*.lua
hypertile-navigation.lua  gap-aware focus and swap for SUPER+arrows and SUPER+SHIFT+arrows
hypertile-session.lua  compositor adapter: capture and restore window placement
session/service.py    session watcher, durable snapshots, app launch and matching
session/scene_recovery.py  checkpoint and delivery of scene assignments across restarts
session/upgrade.py    preserve daemon state while replacing installed runtime files
scenes/*.py            scenes service: saved scenes, the app catalog, one-shot placement
layouts/*.lua          starter layout: welcome; reference examples: ultrawide, quad
bin/hypertile-ctl      CLI over the bridge
bin/hypertile-session  session service entry point (also via hypertile-ctl session)
bin/hypertile-displays display service entry point (also via hypertile-ctl display)
displays/*.py          display adapter, recovery watchdog, workspace policy
bin/hypertile-scenes   scenes service entry point (also via hypertile-ctl scene)
dev                    link the checkout, check changes, and reload affected components
install.sh             puts the engine, CLI, keybinds, and menu entry in place
uninstall.sh           takes them out again
probe.lua              live probe (logs everything the API hands a layout)
docs/MANUAL.md         user manual: daily use, designing layouts, scenes, sessions, troubleshooting
docs/SCENES.md         scenes and content: placement, recovery, app identity, the scene CLI
docs/DISPLAYS.md       displays, mirroring, workspace placement, and monitor configuration
docs/SESSIONS.md       session recovery: commands, app recipes, shutdown integration, storage
docs/README.md         development workflow, testing, and backup/recovery paths
docs/INTERNALS.md      what the compositor API does and does not do, what shapes the overlay,
                       and the stale-window forensics
docs/HYPRLAND-SIZING-BUG.md  the 0.56.2 size-ack bug and the local compositor backport
docs/RELEASING.md      release and marketplace verification procedure
CHANGELOG.md           release notes
test/                  engine, bridge, CLI, geometry, and editor tests
```

The layout editor reads workspace and layout data through `hypertile-ctl current --json` and
`hypertile-ctl list --json`, previews through `hypertile-ctl preview`, and
saves through `hypertile-ctl save` then `apply`. `Overlay.qml` owns the
state, the processes, and the pointer and key handling; `Rail.qml` is the
inspector, `ZoneItem.qml` draws a zone, `Divider.qml` a boundary,
`Thumb.qml` a layout thumbnail. The chrome uses the shell's `Color` and
`Style` tokens and its `qs.Ui` controls, so it follows the active theme.
Zone math lives in `plugin/Geometry.js`; edits are pure functions in
`plugin/Editor.js`.

</details>

## License

MIT. See [LICENSE](LICENSE).
