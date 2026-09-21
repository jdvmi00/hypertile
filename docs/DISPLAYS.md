# Displays and workspace placement

Open Hypertile and choose **Displays**. The diagram uses logical desktop
coordinates: resolution, rotation, and scale all affect a screen's size. Drag a
screen to align its edges, or enter its X and Y position. Changing a screen's
scale, rotation, or resolution moves the screens attached to its right and
bottom edges by the same amount, so they stay attached instead of overlapping.

![Displays arrangement and settings](screenshots/displays.png)

Screens are numbered by
position, left to right and then top to bottom, so the number on a screen says
where it stands; a mirror counts right after its source, and disconnected or
disabled displays come last. Tab to a diagram screen and use arrows to move one
logical pixel, or Shift+arrows for ten. **Identify displays** labels every
screen with its number for a few seconds, with the selected screen highlighted;
`hypertile-ctl display identify` does the same, or labels one screen when given
a connector. Closing with unsaved changes asks before discarding them; nothing is
applied until you preview.

Select a screen to change resolution and refresh rate, scale, rotation, or its
enabled state. The mode picker lists the modes reported by Hyprland. Saved
screens that are disconnected remain visible, with their preferences retained.
If screens report the same identity, explicitly match each connector before
applying. Hypertile does not guess which identical screen should inherit a
saved configuration.

Choose **Preview changes**, then **Keep changes** within 15 seconds. The
countdown starts once every display has settled on the new settings, not when
the first one starts changing. Enter keeps; Escape reverts and leaves the pane
open. **Revert**, closing during preview, or letting the countdown expire
restores the previous arrangement and workspace placement where possible. A separate watchdog runs
outside the overlay and display watcher. Confirmation is required even when
only workspace or layout preferences change. Unsupported modes and overlapping
independent screens produce an error before application.

## Mirroring

Select a display and choose **Use as → Mirror display …** to duplicate an
independent display. **Extended display** restores its separate desktop and
previous position; **Disabled** removes it from the desktop. Sleep remains a
separate temporary action.

The diagram groups mirrors with their source (for example, **1 + 2**). Select
individual physical displays from the list to change resolution and refresh.
Mirrors have no independent desktop position, initial workspace, or default
layout. Their saved workspace assignments temporarily use the source; their
independent preferences remain available when returning to Extended.

A mirror source must be connected, enabled, and independent. Multiple displays
can mirror one source, alongside other extended displays. Self-mirroring,
chains, and cycles are rejected. Different aspect ratios may stretch the image;
mirroring does not render extra detail for a higher-resolution target.

Mirroring uses the same preview countdown, Keep, and rollback as other display
changes. Keep writes the `mirror` field into the existing Lua declaration.
Returning to Extended explicitly clears that field. Recovery establishes source
displays first and keeps a remaining output usable if a source disappears.

## Sleep and disable

**Sleep display** turns off the output using DPMS without changing its workspace
placement. If the overlay is on that display it moves to another awake display
first, so its Wake button stays visible. The same button reads **Wake display**
while the output is asleep;
it follows the compositor's power state, not unsaved edits, so it is only
offered for a connected, enabled output. Sleeping displays are marked in the
diagram and the display list, and **Wake all** appears in the header only while
something is asleep. `hypertile-ctl display wake` also powers outputs back on.
Hyprland treats DPMS as one global state, so after any output sleeps its
`key_press_enables_dpms` and `mouse_move_enables_dpms` options (both on in
Omarchy) would wake every output on the next key press or mouse move. While
another output stays awake, the service holds both options off; sleeping the
last awake output instead enables keyboard wake, so a key press remains a way
back. The original values are restored once every output is awake, however it
woke, and re-asserted after a config reload. Sleep is temporary and is never
saved as a disabled display.

**Disable display** removes an output from the desktop after other destinations
are enabled. Its workspaces remain accessible on another output. Disabling the
last usable output is rejected. Re-enabling uses the saved settings, subject to
hardware availability.

## Apply a workspace

Select an extended display, then choose **Workspace → Apply** below **Use as**.
The picker lists workspaces 1–10 and existing or saved workspaces, with the current
connector beside live workspaces. **Other workspace…** accepts a new number or a
name such as `name:research`. Apply switches immediately, moving an existing
workspace and its windows to this display if necessary. The previously visible
workspace remains available. This does not change saved placement preferences.
Apply is unavailable during a display preview or for sleeping, disabled,
disconnected, or mirrored outputs.

Check **Use this workspace at startup**, then **Preview changes → Keep changes**
to save the startup preference. Uncheck it while that workspace is selected to
clear it. Startup workspaces must be unique across displays and cannot conflict
with a saved workspace assignment.

## Workspace preferences

Expand **Workspace preferences** in the selected display’s settings to adjust
optional layout defaults and workspace assignments. This section starts collapsed.

Add a numbered workspace, or a named workspace using `name:research`, and choose
its preferred screen. The Add button waits until the entry is a valid selector
and says why otherwise. The workspace need not exist yet. Apply moves an existing
workspace immediately; the preference also applies at startup and when the
preferred output returns. Moving a workspace normally does not rewrite this
preference or cause Hypertile to move it back continuously.

While a preferred output is absent, workspaces stay usable elsewhere. A later
manual move while it is absent suppresses automatic return until the assignment
is explicitly reapplied or a new compositor session begins. Reconnect does not
select the returning workspace or relaunch scene applications.

Initial workspace preferences apply at startup and are coordinated with session
restoration. Set them using the Workspace control above. Config reload and monitor reconnect preserve the user's focus.

## Layout inheritance

The **Default layout for this monitor** applies to inheriting workspaces,
including future ones. An explicit workspace layout takes precedence and follows
that workspace when moved. **Monitor default** clears the explicit override; a
monitor without a default uses the existing global layout fallback.

The Layouts rail shows both the effective layout and its source. Cycling or
choosing a layout makes the choice explicit. Existing saved workspace layouts
remain explicit on upgrade. **Use on all of …** remains a one-time assignment to
current workspaces; it does not set a persistent monitor default.

An active scene retains its required layout. To replace it with a conflicting
layout, use the Layouts view's existing replacement confirmation first. Moving
a scene workspace does not replace its layout or launch its apps again.
Renaming layouts updates display references. Deleting a monitor default is
refused until another default is chosen.

## Configuration ownership and recovery

Hypertile automatically uses the existing `~/.config/hypr/monitors.lua` as the
display configuration when installed or enabled. No takeover choice is needed,
and initial setup does not change your display arrangement. The UI starts from
the running settings. Preview changes are temporary; **Keep changes** saves the
adjusted fields into the existing monitor declarations, reloads Hyprland, and
verifies the result. A failed save or reload restores the previous file and
runtime arrangement.

Comments, unrelated fields, the general fallback rule, and unchanged expressions
such as `preferred`, `auto`, and shared scale variables are preserved. A screen
without a specific rule gets one when its settings change, inheriting fallback
expressions. Changing one screen's scale never changes a shared scale variable.
The first save keeps `monitors.lua.hypertile.bak`; each preview also journals the
exact pre-save content for crash recovery. External edits during preview cause
the save to stop and ask you to refresh, rather than overwrite them.

Configuration reloads and reconnects use Hyprland's saved monitor rules directly;
Hypertile no longer reapplies a competing geometry snapshot. Disabling or
uninstalling Hypertile leaves the saved monitor configuration usable, including
on purge. Existing saved preferences from the earlier display implementation
are migrated once on upgrade before the old replay behavior is retired.

Supported edits are literal `hl.monitor({ ... })` declarations in `monitors.lua`.
The declaration edited for an output is the one Hyprland applies: a `desc:`
selector matches a prefix of the description, and when several declarations
match one output the last one in the file wins, so a partial description rule
keeps its other fields (such as `vrr`) instead of being shadowed by a new rule.
Custom control flow, computed output selectors, duplicate declarations, or
monitor rules in other loaded user modules receive a source-specific explanation
before preview changes are applied. They are never rewritten speculatively.
Workspace policy remains separate from monitor geometry. Known connected outputs
are matched by connector automatically, including connections sharing an EDID;
reassigning a disconnected saved display still uses the explicit matching UI.

Display state lives in `$XDG_STATE_HOME/hypertile/displays/` (normally
`~/.local/state/hypertile/displays/`):

- `confirmed.json`: versioned workspace/display identity metadata and the
  configuration migration marker; geometry is informational after migration.
- `pending.json`: an unconfirmed transaction, original geometry and workspace
  placement, its token, deadline, and application progress.
- `workspace-runtime.json`: current-session reconnect and manual-move tracking.
- `recovery.json`: the most recent rollback result, including external changes,
  unavailable hardware, and fallback recovery errors.

Settings are written atomically. A pending transaction never becomes startup
intent without Keep. Session saves pause during preview. Startup restores
confirmed display intent before recovering windows and scenes. A changed
external configuration is detected during rollback and is not blindly replaced.
If hardware disappears, recovery keeps an available output usable and reports
any fallback.

Ordinary upgrades and uninstall preserve preferences and recovery state.
`uninstall.sh --purge` removes this state along with the other Hypertile user
state. Uninstall first stops display management and rolls back an active preview.

## CLI

All display commands return JSON and use the same service as the UI:

```sh
hypertile-ctl display list --json
hypertile-ctl display status
hypertile-ctl display preview --json - < settings.json
hypertile-ctl display keep TOKEN
hypertile-ctl display revert TOKEN
hypertile-ctl display show-workspace HDMI-A-1 1
hypertile-ctl display sleep DP-1
hypertile-ctl display wake DP-1
hypertile-ctl display wake
hypertile-ctl display restore
hypertile-ctl display recover
```

`restore` recovers interrupted work and reconciles workspace preferences;
monitor geometry comes from the Lua configuration. `recover` rolls back an
interrupted preview. `watch` is the long-running display watcher: it listens to
Hyprland's event socket and consults the compositor only when a workspace or
output event arrives, every five seconds as a safety net, or while an output
sleeps, and it rewrites its runtime file only when something changed. `stop`
stops it after recovery. The former `--takeover` flag remains accepted for script
compatibility and is no longer necessary. The UI also displays per-output
identify labels.

A settings document has `version: 1`, a `displays` array, and a `workspaces`
object. Start from `display list` rather than inventing display identities.
Each display has `id`, `identity`, `connector`, `enabled`, `width`, `height`,
`refresh`, `scale`, `transform`, `x`, and `y`. Optional preferences are
`default_layout`, `initial_workspace`, `explicit_match`, and `mirror_of` (a saved
display ID, or `null` for Extended). `extended_position` retains `{ "x": …,
"y": … }` for returning from mirroring. `mirror_connector` is runtime readback;
preview resolves connectors from `mirror_of` rather than trusting that field. Workspace entries
use selectors as keys and `{ "monitor": "saved-display-id", "layout": null }`
as values; `null` inherits, while a layout string is explicit. Custom layouts
use the `lua:` prefix. Display transforms use Hyprland's values 0–7.

See [display validation](diagnostics/displays/README.md) for the tested software,
hardware, and remaining physical verification limits.

## Wallpaper groups

Open **Displays → Wallpaper groups…** below the arrangement diagram. Select a
screen, check **Span wallpaper across a group**, and check the other displays
that should share that image. Group members are highlighted in the diagram.
Select a third screen and leave spanning off for an independent wallpaper.
Independent screens following the theme repeat the image on each screen.

Each group can use **the current theme wallpaper** or **Choose image…** for a
fixed image that does not change with the theme. Crop fills the screen/group;
**Fit entire image** preserves the entire image with black borders as needed.
**Apply wallpaper** saves all wallpaper edits immediately, once a spanning
group has at least two displays and a custom image has a file. This is separate
from display geometry's Preview/Keep. Unsaved wallpaper edits are retained while
selecting other monitors; closing asks before discarding them.

A display belongs to one group. Adding it to another group removes it from its
old group; a group left with one display becomes independent. Spans follow the
logical desktop arrangement, including vertical offsets and mixed scales.
Missing outputs are excluded from the visible span and rejoin on reconnect.
Connectors identify group members, so using a different port requires updating
the group. Mirrored outputs use their source's wallpaper. If a custom file is
later removed or fails to load, the renderer falls back to the theme image.

Settings live in `~/.config/omarchy/wallpaper.json` (or `$XDG_CONFIG_HOME`). The
first Apply clones `omarchy.background` using Omarchy's supported clone command
and adds group rendering to that user-owned clone. Packaged Omarchy files remain
untouched. Theme transitions and background-selection shortcuts remain available.
First-time setup and renderer updates briefly restart the shell to load the new
renderer; ordinary wallpaper changes apply live. Finish any pending display
changes before applying wallpaper.
Hypertile refuses to overwrite an existing custom clone or locally edited
renderer. Subsequent Apply operations update an unmodified managed clone when
needed. The original renderer is retained as `Background.omarchy.qml.bak`.

The clone and wallpaper preferences are independent user customizations and
remain usable if Hypertile is disabled or uninstalled. To return to stock
rendering, disable `<username>.background` through Omarchy's plugin controls;
Omarchy restores its original background plugin. Preferences remain available
for later use.

CLI: `hypertile-ctl display wallpaper` reads preferences. To apply, pass
`--json` with `{"previous": <last-read-settings>, "settings": <new-settings>}`.
Settings have `version: 1` and `groups`, whose entries contain `outputs`
(connector names), `mode` (`span` or `repeat`), `image` (absolute path or `null`
for the theme), and `fit` (`crop` or `fit`). Concurrent edits are rejected.
