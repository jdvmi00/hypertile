# Hypertile user manual

How to get the most out of Hypertile on Omarchy: what the pieces are, the
daily habits that make zone layouts pay off, how to design layouts that fit
your work, and what to do when something looks wrong. The
[README](../README.md) is the reference for every key, command, and spec
field; this manual is the guided tour.

Contents

1. [What Hypertile does](#1-what-hypertile-does)
2. [Getting started](#2-getting-started)
3. [Everyday use](#3-everyday-use)
4. [Moving windows around a layout](#4-moving-windows-around-a-layout)
5. [Designing layouts](#5-designing-layouts)
6. [Layout recipes](#6-layout-recipes)
7. [Putting layouts on workspaces](#7-putting-layouts-on-workspaces)
8. [Scenes: what each zone holds](#8-scenes-what-each-zone-holds)
9. [Session recovery](#9-session-recovery)
10. [The command line and scripting](#10-the-command-line-and-scripting)
11. [Troubleshooting](#11-troubleshooting)
12. [Where everything lives](#12-where-everything-lives)
13. [Keyboard reference](#13-keyboard-reference)

## 1. What Hypertile does

Hyprland's stock layouts (dwindle, master, scrolling) decide where windows go
by splitting whatever is already open. Hypertile turns that around: you
describe the screen as **zones** first, and windows fill the zones.

A **layout** is a tree of columns and rows that ends in named zones. Each
zone has a number, its place in the **fill order**: the first window you
open lands in zone 1, the next in zone 2, and so on. When the fill order is
used up, the **cycle order** says where further windows go; windows that
share a zone are **stacked** inside it. Optional **rules** send particular
apps to particular zones, and each zone can carry constraints: a capacity, a
stack direction, an aspect ratio and scale, or a flag that keeps it a single
window or an empty spacer. Gutters, border, and corner rounding travel with
the layout.

Three more pieces build on that:

- The **overlay** (`SUPER+ALT+L`) draws the layout over your real windows at
  true scale. In view mode you browse layouts and the workspace follows; in
  edit mode you slice, drag, and renumber zones with a live preview.
- **Scenes** record what each zone of a workspace holds: an installed app,
  one open window, ordinary fill, or nothing. Using a scene launches or
  reuses the apps and places them once.
- **Session recovery** checkpoints the desktop as you work and brings
  supported apps back on the next login, in their zones.

Each workspace remembers its own layout, so one workspace can be a quad grid
for browsing while another is a wide editor with a terminal column.

## 2. Getting started

Install from a terminal inside your Hyprland session:

```bash
omarchy plugin add https://github.com/jdvmi00/hypertile.git --enable
```

Enabling sets everything up. While it runs, the bar widget's tooltip says
**Setting up Hypertile…**; after a few seconds it shows the layout of the
current workspace. Setup edits `~/.config/hypr/hyprland.lua` (one `require`
line), `bindings.lua` (the keybinds below), and the Omarchy menu extension;
every file it touches is copied to `<file>.hypertile.bak` first.

You now have:

| Key or place | Does |
|---|---|
| `SUPER+ALT+L` | open the overlay |
| `SUPER+L` / `SUPER+SHIFT+L` | next / previous layout on this workspace |
| `SUPER+Arrow` | focus the neighbouring window, across gaps |
| `SUPER+SHIFT+Arrow` | move the window to the next zone, or swap |
| `SUPER+ALT+T` | move the window to a numbered zone |
| `SUPER` + left drag | drop a window onto a zone |
| bar widget | the layout name; click opens the overlay, scroll cycles |
| `SUPER+SPACE` → Layouts | open the overlay from the menu |
| `SUPER+SPACE` → Logout / Reboot / Shutdown | the same actions, saving the session first |

`SUPER+L` replaces Omarchy's dwindle/scrolling toggle because that toggle
cannot return to a Lua layout. If you had already rebound `SUPER+L`, setup
leaves it alone and says so in the install log.

### Your first layout

A fresh install starts with an **empty** layouts directory, so `SUPER+L` has
nothing to cycle to yet. Two ways to fix that:

**Copy the examples.** The plugin ships two reference layouts, `ultrawide`
(20/60/20 columns) and `quad` (the centre split into four). Copy them and
reload:

```bash
cp ~/.config/omarchy/plugins/jmartin.hypertile/layouts/*.lua ~/.config/hypr/layouts/
hyprctl reload
```

**Or draw one.** Press `SUPER+ALT+L`, then `n` for New and `b` for Blank. You
are in edit mode with one zone covering the screen. Press `c` to split it
into columns, click the right column and press `r` to split it into rows,
drag the dividers where you want them, then `w` to save and type a name.
The layout is immediately in use on this workspace and in the `SUPER+L`
cycle. Section 5 goes through edit mode properly.

Press `SUPER+L` a few times. The layout's name flashes in the OSD and the
windows re-tile. Open a few more windows and watch them land in fill order.

## 3. Everyday use

### Switching layouts

`SUPER+L` steps through every layout on disk in name order, then dwindle,
and back to the first. `SUPER+SHIFT+L` goes the other way. Press it several
times quickly and each name flashes, but the workspace switches only once, to
the layout you stop on: fast bursts of real re-tiles are what upsets slow
clients (see the sizing note in section 11).

The bar widget shows the layout of the active workspace on its monitor. Scroll
over it or middle-click to cycle without touching the keyboard.

### Browsing in the overlay

`SUPER+ALT+L` opens the overlay: a translucent copy of the layout over your
windows, each zone carrying its fill number and pixel size, and the
**inspector rail** on one side. Now:

- **Arrows** (or `h` `j` `k` `l`, or a click in the rail's **Layouts** list)
  browse. The workspace really switches as you browse, so you see your own
  windows in each candidate, but nothing is saved yet.
- `SUPER+L` and `SUPER+SHIFT+L` work here too and keep the preview and the
  selection together.
- **Enter** keeps the viewed layout and closes. **Esc** or a click outside
  closes and puts the workspace back on the layout it had.
- Hold **Space** to peek: the overlay fades to hairlines so you can read the
  windows underneath.
- `?` shows every key in the rail.

The rail's **Fill order** section spells out the order in words ("1 top
left, 2 top right…"), which is the quickest way to understand a layout you
did not write.

### Where the rail's switches live

- **Cycle → In the SUPER+L cycle**: turn it off for layouts you only use
  through the overlay or a scene, so the everyday cycle stays short.
- **Startup → Save windows for startup**: session recovery on or off
  (section 9).
- **Workspaces**: put the viewed layout on another workspace, on every
  workspace of a monitor, or make it the default (section 7).

## 4. Moving windows around a layout

Hyprland's own keys still work: float, fullscreen, move to workspace, and
so on. A floating window leaves the layout and rejoins at the end of the
fill order when it is tiled again. Hypertile adds zone-aware moves:

- **`SUPER+Arrow`** focuses the nearest window in that direction, across
  gutters and empty zones, which Hyprland's stock directional focus does not
  cross reliably.
- **`SUPER+SHIFT+Arrow`** moves the active window into the next zone in that
  direction. An empty zone receives it; an occupied zone swaps. Other windows
  stay where they are. Spacers and zones a scene marked Empty are skipped.
  Moving into a zone that had collapsed (section 5, "Empty zones") reveals
  the full layout on that workspace until the layout is reset.
- **`SUPER+ALT+T`** shows every zone with its number. Let go of the modifiers
  and type the number (the digits of "10" need `Enter` when "1" also exists;
  `Backspace` corrects), or click the zone. The window moves there or swaps
  with the occupant. `Esc` cancels. A stacked zone shows one number per
  position.
- **`SUPER` + left mouse drag** on a tiled window shows the same numbered
  destinations. Drop on a zone to move or swap there. Drop anywhere else and
  Hyprland's normal drag result applies.

A window can also be **pinned** to a zone, which overrides rules and fill
order until it is unpinned. Pins are made through a layout message; the
easiest way to use one is a keybind in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + CTRL + P", "Pin window to center", function() hl.dsp.layout("pin center") end)
o.bind("SUPER + CTRL + U", "Unpin window",         function() hl.dsp.layout("unpin") end)
o.bind("SUPER + CTRL + R", "Reset layout sizes",   function() hl.dsp.layout("reset") end)
```

`grow <zone> 0.05` and `size <zone> 1.0` adjust a zone's weight at runtime
and `reset` forgets those adjustments and every pin. These messages reach the
focused workspace's layout. Scenes (section 8) are the durable way to keep an
app in a zone; pins are for the moment.

## 5. Designing layouts

Open the overlay on the workspace whose windows you want to design around,
view the layout to change and press `e`, or press `n` for a new one (`b`
blank, `c` a copy of the viewed layout). Edits preview live: the workspace
re-tiles as you go, and nothing is written until you save.

### The moves

| Do | With |
|---|---|
| select a zone | click it, arrows / `hjkl`, or `Tab` |
| split it into columns / rows | `c` / `r`, or the buttons on the zone |
| delete it (the neighbour takes the space) | `x`, `Delete`, or right-click |
| resize | drag a divider; `Shift+Arrow` nudges the selected zone's edge by 1% |
| set an exact size | **Zone → Size** in the rail, in percent of the screen |
| renumber | `f`, then click zones in the order windows should fill them; click a zone again to give it a second position; `Backspace` undoes a click, `Enter` finishes. Zones you skip follow at the end |
| undo | `u` |
| save | `w` or `Ctrl+S`; a new layout asks for a name |
| leave | `Esc`; with unsaved changes it offers Discard, Save, or Keep editing |

### Zone settings that change how a layout feels

All in the rail's **Zone** section for the selected zone:

- **Name.** Names are how rules, scenes, pins, and scripts refer to a zone.
  View mode hides them (the fill summary speaks in positions), but give
  important zones real names ("editor", "terms") before writing rules.
- **Spacer** (`s`). A hole that never takes a window. Split around the area
  you want to leave empty and mark the rest as spacers to place a single
  window off-centre, or to keep a strip of wallpaper visible.
- **Never split.** The zone holds one window at most and is never an
  overflow target while any other zone exists. Use it for the "main" zone
  of a layout so a fourth window never halves your editor.
- **Stack.** Vertical or horizontal for windows sharing the zone. A wide
  bottom strip stacks better horizontally.
- **Capacity.** How many windows the zone takes before overflow spills to
  the next zone in fill order. A terminal column with capacity 3 stays
  readable.
- **Aspect and Scale.** The zone fits the largest box of that ratio inside
  itself, shrinks it by the scale, and centres it. One zone with 1:1 at 70%
  is a square in the middle of the screen with nothing around it: a focus
  layout for writing or a video call.

### Layout settings

The **Layout** section applies to the whole layout and rides along as
workspace and window rules when the layout is in use:

- **Gutter** and **Edge gap**: the gap between windows and around the layout.
  Zero both, with **Border** 0, for edge-to-edge tiling.
- **Window corners**: rounding radius for windows on this layout's
  workspaces.
- **Empty zones**: *Collapse* gives an empty zone's space to its neighbours,
  so two windows on a quad layout are two halves; *Keep their place* leaves
  the gap, so windows never move as others open and close.
- **A lone window**: *Fills the area* or *Stays in its zone*. Keep it in its
  zone when the zone's size or aspect is the point of the layout.
- **In the SUPER+L cycle**: see section 3.

**Opens here** lists the apps pinned to the selected zone as rules. Pick from
the windows open right now; an app allowed in several zones fills the
lowest-numbered one first. Rules match the window class by Lua pattern, so
a rule made from a window is exact to that app.

### Habits that produce good layouts

- **Design with real windows open.** Open the apps you actually use on that
  workspace first, then edit; the preview shows the real result.
- **Fewer, larger zones beat a grid.** Most work wants one big zone and one
  or two side zones. Let the side zones stack rather than adding more.
- **Decide the overflow.** Where should the sixth window go? Put that zone
  last in the fill order, give it a capacity, and stack it. Keep at least
  one zone in the fill or cycle order that can take overflow.
- **One layout per kind of work, not per app.** Layouts are cheap; keep a
  short cycle of three or four and leave specialised ones out of the cycle.
- **Name zones before writing rules or scenes.** Renaming later keeps
  scenes working (zones carry a stable id), but rules in hand-edited files
  refer to names.

Layouts are plain Lua files in `~/.config/hypr/layouts/`. You can edit them
by hand (the README's Spec section lists every field) and they round-trip
through the overlay as long as they stay valid Lua. Save from the overlay or
run `hyprctl reload` after editing by hand.

## 6. Layout recipes

Save any of these as `~/.config/hypr/layouts/<name>.lua` and run
`hyprctl reload`, or use them as a starting point in the overlay.

### Ultrawide: 20/60/20

The classic wide-monitor split. The first window takes the centre, the next
two the sides, and everything after that stacks in the side columns.

```lua
local hypertile = require("hypr.hypertile")

hypertile.layout("ultrawide", {
  columns = {
    { name = "left", w = 0.2 },
    { name = "center", w = 0.6 },
    { name = "right", w = 0.2 },
  },
  fill = { "center", "right", "left" },
  cycle = { "right", "left", "center" },
  empty = "keep",
  single = "slot",
})
```

### Quad: four fixed quadrants with side columns

Every zone keeps its place when empty, so a lone window sits in the top-left
quadrant and the arrangement never shifts as windows come and go.

```lua
local hypertile = require("hypr.hypertile")

hypertile.layout("quad", {
  columns = {
    { name = "left", w = 0.2 },
    {
      w = 0.6,
      rows = {
        { columns = { { name = "tl" }, { name = "tr" } } },
        { columns = { { name = "bl" }, { name = "br" } } },
      },
    },
    { name = "right", w = 0.2 },
  },
  fill = { "tl", "tr", "bl", "br", "right", "right", "left", "left" },
  empty = "keep",
  single = "slot",
})
```

### Code: editor in the middle, terminals on the right

The editor zone never splits, terminals go to the right column by rule and
stack up to three deep, and the browser is sent left. Gutters are tight and
the layout stays out of the everyday cycle because a scene (section 8)
opens it.

```lua
local hypertile = require("hypr.hypertile")

hypertile.layout("code", {
  columns = {
    { name = "browser", w = 0.25 },
    { name = "editor", w = 0.5, never_split = true },
    { name = "terms", w = 0.25, stack = "v" },
  },
  fill = { "editor", "terms", "browser" },
  cycle = { "terms", "browser" },
  rules = {
    { class = "^Alacritty$", slot = "terms" },
    { class = "^com%.mitchellh%.ghostty$", slot = "terms" },
    { class = "^chromium$", slot = "browser" },
  },
  capacity = { terms = 3 },
  gaps = { inner = 4, outer = 4 },
  in_cycle = false,
})
```

`class` and `title` are Lua patterns: anchor them with `^` and `$`, and
escape dots as `%.`. Find a window's class with `hypertile-ctl windows`.

### Focus: one window, centred, with breathing room

A single zone with a 16:9 box at 80% of the screen. A second window stacks
inside the box; switch **A lone window** to *Fills the area* if you would
rather it grew.

```lua
local hypertile = require("hypr.hypertile")

hypertile.layout("focus", {
  columns = { { name = "stage", aspect = 16 / 9, scale = 0.8 } },
  single = "slot",
  gaps = { inner = 0, outer = 0 },
  border = 0,
  in_cycle = false,
})
```

### Reference: a wide reader with a notes strip underneath

A horizontal bottom strip for chat, music, or a scratch terminal. Windows in
the strip sit side by side.

```lua
local hypertile = require("hypr.hypertile")

hypertile.layout("reader", {
  rows = {
    { name = "page", h = 0.75, never_split = true },
    { name = "strip", h = 0.25, stack = "h" },
  },
  fill = { "page", "strip" },
  cycle = { "strip" },
  rounding = 8,
})
```

## 7. Putting layouts on workspaces

Every workspace has its own layout, remembered across reloads and logins in
`~/.local/state/hypertile/workspace-rules/`. Workspaces without a rule use
the **default** layout, which is `general.layout` in `looknfeel.lua`.

From the overlay's **Workspaces** section, with the layout you want viewed:

- click a workspace row to use the viewed layout there (the row shows how
  many windows it holds and marks the one in use);
- **Use on all of <monitor>** applies it to every workspace currently on
  that monitor (Hyprland binds layouts to workspaces, not monitors);
- the default control makes it the layout for every workspace that has no
  rule of its own;
- **Follow monitor default** drops the layout chosen for the current
  workspace so it inherits its monitor's default layout (set under
  Displays → Workspace preferences). Each row says where its layout comes
  from: chosen for the workspace, its monitor default, the default layout,
  or a scene.

The overlay stays open, so you can browse to another layout and assign it
elsewhere. From a script, `hypertile-ctl apply <name> --workspace N` does the
same, `hypertile-ctl apply dwindle --workspace N` hands a workspace back to
Hyprland, and `hypertile-ctl default <name>` sets the default.

A useful arrangement: a quad or reader layout as the default, and a code
layout on the one or two workspaces where you build things.

## 8. Scenes: what each zone holds

A layout says where windows go. A **scene** says which windows: for each
zone of a workspace, an installed app to launch or reuse, one particular
open window, ordinary local fill, or Empty (nothing goes there, and the
directional moves skip it). Using a scene launches whatever is missing,
places each app once, and then leaves you alone: move, float, or close the
app and Scenes will not pull it back or open a second copy.

### Making one

1. Open the overlay on the workspace and click the **Scenes** tab.
2. Click a zone, or press its fill number, or `Tab` through them. The
   picker under the zone lists **Local windows** and **Empty** as chips,
   then **Open here** (windows on this workspace), **Remote desktops** (if
   the Remote Desktops app is installed), and **Apps** (installed desktop
   entries).
3. Type to filter, `↑`/`↓` to pick, `Enter` to assign, `Tab` to move to the
   next zone keeping the query. Hovering a match previews it in the zone.
   Letters are always search text here, including `hjkl`.
4. Click **Save as…** and name it. **Save** later updates the same scene.

The header now names the scene and how many apps are placed. The saved
scene appears as a card in the rail with its apps drawn in their zones.

### Using one

Click the card, or with no zone selected use `↑`/`↓` and `Enter`. If the
current scene has unsaved changes you are asked first. Missing apps launch,
open ones are moved into place, and progress shows on the zone cards. A
card that needs attention (an app that did not appear within 45 seconds)
is outlined and offers **Retry**. **Restore previous** returns to the
arrangement from before the scene, leaving apps running.

Assign a scene's layout `in_cycle = false` so `SUPER+L` does not walk past
it, and give the scene a workspace of its own: scenes are per workspace, and
choosing a different layout on that workspace replaces the assignments with
plain local fill (apps keep running).

### App identity

Scenes needs to recognise an app's window. Desktop entries that declare
`StartupWMClass` work immediately; for others, an open window whose class
equals the desktop id supplies it; and anything else can be configured on
the command line with an explicit class and, when several windows share a
class, an exact title:

```bash
hypertile-ctl scene content --zone editor --type app \
  --desktop-id code.desktop --app-class Code
hypertile-ctl scene save code
```

Scenes are files in `~/.config/hypertile/scenes/<name>.json`. On the first
save Hypertile gives the layout and each zone a stable id, so renaming a
zone later keeps the scene's assignments. [SCENES.md](SCENES.md) covers the
full CLI, recovery after login, and the file format.

## 9. Session recovery

Session recovery is on by default. As you work, Hypertile checkpoints the
desktop about a second after each change: which layout each workspace uses,
the order of windows in each zone, pins and runtime size changes, floating
geometry, fullscreen state, and focus. On the next login it relaunches the
apps it knows how to launch and puts their windows back.

What comes back: Chrome and Chromium (with their own session restore and
web-app windows), apps with desktop entries, and the Ghostty, Alacritty,
Kitty, and Foot terminals as fresh shells in their saved directory.
What does not: browser tabs and editor documents belong to the app's own
restore; commands running in a terminal are not replayed, except commands
you list under `replay` in `~/.config/hypertile/session.json` (a TUI that
re-attaches to its own server is the intended case).

### The habits that make it reliable

- **Leave through the guarded actions.** Omarchy closes every window before
  it asks the compositor to exit, which would checkpoint an empty desktop.
  The `SUPER+SPACE` Logout, Reboot, and Shutdown entries, and
  `hypertile-ctl session logout|reboot|shutdown`, save first. On systemd
  desktops a shutdown inhibitor also protects `systemctl reboot` and
  `poweroff`. Put `hypertile-ctl session freeze` in front of any custom
  script that calls `omarchy system ...` directly.
- **Watch the bar.** An **!** on the layout widget means saving needs
  attention. The tooltip says why; the overlay's rail shows since when,
  **Show unmatched** lists the windows and reasons, and **Resume saving**
  accepts the desktop as it is.
- **Understand partial mode.** If a launch fails or a launched app's window
  never matches, the restore is *partial*: automatic saving pauses so the
  incomplete desktop cannot overwrite the snapshot it came from. Open the
  missing app and run `hypertile-ctl session restore` to retry, or **Resume
  saving** to accept what is there. A window that simply has no launch
  recipe does not pause anything; a notification names it and saving goes on.

### Named sessions and the past

```bash
hypertile-ctl session save deep-work       # snapshot under a name
hypertile-ctl session restore deep-work    # bring it back, keeping other windows
hypertile-ctl session restore @previous-1  # the checkpoint before the latest (-2, -3)
hypertile-ctl session status               # mode, matched and unmatched windows
```

Turn recovery off with **Startup → Save windows for startup** in the
overlay or `hypertile-ctl session disable`; snapshots are kept, nothing is
restored at login, and the guarded menu actions pass straight through to
Omarchy. Custom launch recipes for apps the service does not know go in
`session.json`; see [SESSIONS.md](SESSIONS.md) for the format and the full
list of limits.

## 10. The command line and scripting

`hypertile-ctl` does everything the overlay does, which makes layouts
scriptable from keybinds, shell aliases, and other tools.

| Task | Command |
|---|---|
| see layouts, the active one starred | `hypertile-ctl list` |
| what this workspace is doing | `hypertile-ctl current`, `hypertile-ctl workspaces` |
| find a window's class for a rule | `hypertile-ctl windows` |
| put a layout on a workspace | `hypertile-ctl apply quad --workspace 3` |
| next / previous layout | `hypertile-ctl cycle`, `hypertile-ctl cycle --reverse` |
| try a layout without persisting | `hypertile-ctl apply quad --no-persist` |
| set the default | `hypertile-ctl default quad` |
| export, edit, re-import | `hypertile-ctl dump quad > quad.json`, then `hypertile-ctl save quad.json` |
| preview a JSON layout live, no disk write | `hypertile-ctl preview quad.json --workspace 9` |
| rename or delete | `hypertile-ctl rename quad grid`, `hypertile-ctl remove grid` |
| scenes | `hypertile-ctl scene list`, `scene apply work --workspace 1`, `scene current` |
| sessions | `hypertile-ctl session status`, `save`, `restore`, `enable`, `disable` |
| fix a window drawn smaller than its tile | `hypertile-ctl heal` |

Add `--json` to `list`, `current`, `workspaces`, and `windows` for machine
output. `remove` refuses the default layout, and a layout a workspace rule
uses unless you pass `--force`.

While the overlay is open, `omarchy-shell hypertile <method>` drives it:
`next`, `prev`, `view <name>`, `use`, `edit`, `split <zone> columns`,
`saveAs <name>`, `content true`, `search <text>`, `pick`, `state`, and the
rest listed in the README's Scripting section. `state` returns the whole
overlay state as JSON, which is handy for checking what a script did.

A keybind that puts a specific layout on the current workspace:

```lua
o.bind("SUPER + CTRL + 1", "Quad layout", "hypertile-ctl apply quad")
```

## 11. Troubleshooting

**A window's content is smaller than its tile**, with wallpaper showing in
the rest, after switching or saving layouts. This is a Hyprland 0.56.2
bug in size acknowledgment bookkeeping, triggered by fast re-tiles of slow
clients. `hypertile-ctl heal` on that workspace recovers it. The permanent
fix is a one-line compositor backport, built and installed separately;
[HYPRLAND-SIZING-BUG.md](HYPRLAND-SIZING-BUG.md) explains how, how to check
it after Omarchy updates, and when to retire it.

**Setup failed** (the widget's tooltip says so). Read
`~/.local/state/hypertile/install.log`, fix what it reports (usually a
config error from an unrelated edit, shown by `hyprctl configerrors`), then
disable and re-enable the plugin to retry.

**`SUPER+L` still toggles dwindle and scrolling.** `SUPER+L` was already
rebound in `bindings.lua` when setup ran, so it was left alone. Add
`o.bind("SUPER + L", "Toggle workspace layout", "hypertile-ctl cycle")` next
to the other Hypertile lines and reload.

**A layout is missing from the cycle or the overlay.** Either it was saved
with the cycle switch off (view it in the overlay and turn **In the SUPER+L
cycle** back on), or its file does not validate: the overlay's catalog shows
the validation error on the card, and `hypertile-ctl list --json` includes
it. A broken file never stops the other layouts from loading.

**Windows keep landing in the wrong zone.** Check for a stale pin
(`hl.dsp.layout("reset")` clears pins and size changes on the focused
workspace) and for rules: **Opens here** in edit mode shows the rules of the
selected zone. Remember that a floating window rejoins the layout at the end
of the fill order.

**The overlay shows a different layout from the windows.** Press `r` to
re-read the layouts and the workspace. If a layout preview was left behind
by a crash, the bar shows **!** and closing the overlay restores the
committed layout.

**The "!" badge will not go away.** Open the overlay and read the rail's
session notice. A partial restore wants either a retry or **Resume saving**;
a scene waiting for recovery offers **Retry** or **Dismiss**;
`hypertile-ctl session status` prints the same information.

**Something else changed in my Hyprland config.** Every file setup edits has
a `<file>.hypertile.bak` copy from before the first install, and it is never
overwritten by later installs or uninstalls.

**Starting over.** Run the uninstaller, then remove the plugin:

```bash
~/.config/omarchy/plugins/jmartin.hypertile/uninstall.sh   # add --purge to drop layouts, state, and scenes
omarchy plugin remove jmartin.hypertile
```

Without `--purge` your layouts, workspace rules, scenes, and snapshots are
kept for the next install.

## 12. Where everything lives

| What | Where |
|---|---|
| layouts, one Lua file each | `~/.config/hypr/layouts/<name>.lua` |
| the default layout | `general.layout` in `~/.config/hypr/looknfeel.lua` |
| each workspace's layout | `~/.local/state/hypertile/workspace-rules/` |
| overlay preferences (dock side, open sections) | `~/.local/state/hypertile/overlay.json` |
| saved scenes | `~/.config/hypertile/scenes/<name>.json` |
| session settings and app recipes | `~/.config/hypertile/session.json` |
| session snapshots and named sessions | `~/.local/state/hypertile/sessions/` |
| setup log | `~/.local/state/hypertile/install.log` |
| config backups | `~/.config/hypr/*.hypertile.bak`, `~/.config/omarchy/extensions/omarchy-menu.jsonc.hypertile.bak` |
| the plugin itself | `~/.config/omarchy/plugins/jmartin.hypertile/` |
| the CLI | `~/.local/bin/hypertile-ctl` |

`$XDG_CONFIG_HOME` and `$XDG_STATE_HOME` are honoured when set.

## 13. Keyboard reference

### Desktop

| Key | Action |
|---|---|
| `SUPER+L` / `SUPER+SHIFT+L` | next / previous layout on this workspace |
| `SUPER+ALT+L` | open or close the overlay |
| `SUPER+Arrow` | focus the neighbouring window |
| `SUPER+SHIFT+Arrow` | move the window to the next zone, or swap |
| `SUPER+ALT+T`, then a number | move the window to that zone; `Enter` for a prefix number, `Backspace` corrects, `Esc` cancels |
| `SUPER` + left drag | drop the window on a zone |

### Overlay, Layouts tab

| Key | Action |
|---|---|
| arrows, `hjkl`, click in the list | browse; the workspace follows |
| `Enter` | use the viewed layout and close |
| `Esc`, click outside | close and revert |
| `Space` (hold) | peek through the overlay |
| `e` | edit the viewed layout |
| `n`, then `b` or `c` | new layout: blank, or a copy |
| `F2` | rename |
| `d` | delete (confirms) |
| `r` | re-read layouts and the workspace |
| `?` | show the keys |

### Overlay, edit mode

| Key | Action |
|---|---|
| click, arrows, `hjkl`, `Tab` | select a zone |
| `c` / `r` | split into columns / rows |
| `x`, `Delete`, right-click | delete the zone |
| drag a divider, `Shift+Arrow` | resize; nudge an edge by 1% |
| `s` | toggle spacer |
| `f` | renumber by clicking; `Backspace` undoes a click, `Enter` finishes |
| `u` | undo |
| `w`, `Ctrl+S` | save |
| `Esc` | leave; `d` discard, `w` save, `Enter` keep editing when asked |

### Overlay, Scenes tab

| Key | Action |
|---|---|
| click a zone, its fill number, `Tab` | select a zone |
| type | search apps and windows |
| `↑` / `↓`, `Enter` | pick a match and assign it |
| `Tab` | next zone, keeping the query |
| `Esc` | clear the search, then close |
| with no zone selected: `↑` / `↓`, `Enter`, `Delete` | select, use, or delete a saved scene |
| `?` | show the keys |

## Displays and workspace placement

The **Displays** view arranges monitors, controls power, and assigns workspaces
and inherited layouts. See the [Displays guide](DISPLAYS.md) for the complete
workflow, keyboard controls, recovery, and configuration ownership.
