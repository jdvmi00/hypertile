# Displays and workspace placement

Open Hypertile and choose **Displays**. The diagram uses logical desktop
coordinates: resolution, rotation, and scale all affect a screen's size. Drag a
screen to align its edges, or enter its X and Y position.

![Displays arrangement and settings](screenshots/displays.png)

Tab to a diagram
screen and use arrows to move one logical pixel, or Shift+arrows for ten.
**Identify** temporarily labels the connected screens with the diagram numbers.

Select a screen to change resolution and refresh rate, scale, rotation, or its
enabled state. The mode picker lists the modes reported by Hyprland. Saved
screens that are disconnected remain visible, with their preferences retained.
If screens report the same identity, explicitly match each connector before
applying. Hypertile does not guess which identical screen should inherit a
saved configuration.

Choose **Preview changes**, then **Keep changes** within 15 seconds. **Revert**,
closing during preview, or letting the countdown expire restores the previous
arrangement and workspace placement where possible. A separate watchdog runs
outside the overlay and display watcher. Confirmation is required even when
only workspace or layout preferences change. Unsupported modes and overlapping
screens produce an error before application; mirroring is outside this release.

## Sleep and disable

**Sleep display** turns off the output using DPMS without changing its workspace
placement. **Wake**, **Wake all**, or `hypertile-ctl display wake` powers it back
on. Sleeping the last awake output enables Hyprland's keyboard wake option, so
a key press remains a way back. Sleep is temporary and is never saved as a
disabled display.

**Disable display** removes an output from the desktop after other destinations
are enabled. Its workspaces remain accessible on another output. Disabling the
last usable output is rejected. Re-enabling uses the saved settings, subject to
hardware availability.

## Workspace preferences

Add a numbered workspace, or a named workspace using `name:research`, and choose
its preferred screen. The workspace need not exist yet. Apply moves an existing
workspace immediately; the preference also applies at startup and when the
preferred output returns. Moving a workspace normally does not rewrite this
preference or cause Hypertile to move it back continuously.

While a preferred output is absent, workspaces stay usable elsewhere. A later
manual move while it is absent suppresses automatic return until the assignment
is explicitly reapplied or a new compositor session begins. Reconnect does not
select the returning workspace or relaunch scene applications.

A display's **Initial workspace** is selected during startup. Initial choices
are coordinated with session restoration. Config reload and monitor reconnect
preserve the user's focus.

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

Hypertile leaves existing Hyprland and Omarchy configuration files intact. The
Displays view reports monitor/workspace rules found in the user's Lua config.
Review these and deliberately accept takeover before the first preview.
Confirmed runtime settings are reapplied after config reload. Unrelated monitor
properties, keyboard bindings, colors, and desktop preferences remain outside
Hypertile's display configuration.

Display state lives in `$XDG_STATE_HOME/hypertile/displays/` (normally
`~/.local/state/hypertile/displays/`):

- `confirmed.json`: versioned display and workspace preferences.
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
hypertile-ctl display preview --json - --takeover < settings.json
hypertile-ctl display keep TOKEN
hypertile-ctl display revert TOKEN
hypertile-ctl display sleep DP-1
hypertile-ctl display wake DP-1
hypertile-ctl display wake
hypertile-ctl display restore
hypertile-ctl display recover
```

`restore` reapplies confirmed preferences. `recover` rolls back an interrupted
preview. `watch` is the long-running display watcher; `stop` stops it after
recovery. `--takeover` is required when existing rules conflict and takeover has
not already been confirmed. The UI also displays per-output identify labels.

A settings document has `version: 1`, a `displays` array, and a `workspaces`
object. Start from `display list` rather than inventing display identities.
Each display has `id`, `identity`, `connector`, `enabled`, `width`, `height`,
`refresh`, `scale`, `transform`, `x`, and `y`. Optional preferences are
`default_layout`, `initial_workspace`, and `explicit_match`. Workspace entries
use selectors as keys and `{ "monitor": "saved-display-id", "layout": null }`
as values; `null` inherits, while a layout string is explicit. Custom layouts
use the `lua:` prefix. Display transforms use Hyprland's values 0–7.

See [display validation](diagnostics/displays/README.md) for the tested software,
hardware, and remaining physical verification limits.
