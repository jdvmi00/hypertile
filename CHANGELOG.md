# Changelog

## Unreleased

- Displays: the preview countdown starts after every output has settled;
  Escape reverts a preview in place instead of closing; sleeping the display
  that shows the overlay moves the overlay to an awake display first; the
  selection survives a catalog refresh; changing scale, rotation, or
  resolution keeps attached screens attached; the workspace Add field and the
  wallpaper Apply button validate before, not after, the request.
- Displays: `monitors.lua` edits pick the declaration Hyprland applies
  (`desc:` prefix matching, last match wins) instead of shadowing a partial
  description rule with a new connector rule. Keep no longer rewrites
  inherited workspace rules that already cache the effective layout, and
  every renderer patch point is checked before a wallpaper clone is written.
  Readback after each display change waits up to five seconds instead of
  1.5 before declaring a failure and reverting.
- Displays: a saved scale that does not divide the mode into whole logical
  pixels (for example 1.4 on 6144×2560) is snapped to the nearest clean 1/120
  step the way Hyprland does, instead of failing readback and reverting.
- Displays: the watcher is driven by Hyprland's event socket with a slow
  safety poll and skips unchanged runtime writes, instead of spawning five
  processes and fsyncing a file twice a second on an idle desktop.

- Keep dwindle available in the Layouts picker and its Super+L browsing cycle,
  including preview/cancel, defaults, and switching from scene assignments.

- New marketplace preview image and a benefit-led manifest description; the
  GitHub social preview matches.

## 1.4.1 (2026-09-18)

- Resolve inherited default layouts when `looknfeel.lua` has no layout override,
  and allow saving the first override without editing the file by hand (#31).
- Preserve previewed display arrangements across Keep and reload by saving
  explicit positions for dependent automatically positioned outputs (#32).

## 1.4.0 (2026-09-17)

Hypertile 1.4.0 adds a Displays view for arranging monitors and choosing
which workspaces and layouts belong on each screen.

- New **Displays** view alongside Layouts and Scenes: a scaled arrangement
  diagram with edge snapping and exact coordinates, mode, scale, and rotation
  controls, identify labels, and full keyboard access. Screens are numbered by
  position (left to right, then top to bottom; mirrors after their source,
  absent displays last) in the diagram, the display chips, mirror options, and
  identify labels. **Identify displays** sits in the header and labels every
  screen, highlighting the selected one.
- Display changes are confirmed through a 15-second **Keep changes / Revert**
  preview backed by an independent rollback watchdog, atomic confirmed
  preferences, startup recovery, and a shared display CLI. Temporary display
  sleep and wake are separate from disabling an output, and the final usable
  output is protected.
- Existing monitor configuration is adopted automatically; there is no
  takeover step. Keep writes only the changed fields to `monitors.lua`,
  preserves automatic settings and comments, verifies a config reload, and
  recovers failed or interrupted saves. Manual config edits are respected
  instead of being overwritten by saved geometry.
- Per-display mirroring, with grouped arrangement labels, retained extended
  positions and workspace preferences, source selection, source-preserving
  Lua saves, and preview and recovery support.
- Saved workspace monitor preferences, startup workspace choices, monitor
  layout defaults, explicit overrides, and a reconnect and manual-move policy.
  Optional workspace preferences are collapsed and the initial-workspace
  control is gone from the UI; saved preferences are preserved. Display
  previews coordinate with session saving and scene layout ownership.
- The desktop text-size slider has its own group under the diagram, labelled
  as immediate and not part of Preview and Keep; the footer's primary action
  sits last and the tabs match the rail's tabs.
- Workspace rows in the rail say where their layout comes from (chosen for
  the workspace, monitor default, default layout, or a scene), mark **In use**
  by the layout actually in effect, and the monitor-default button is
  **Follow monitor default** with a line saying what it does to the current
  workspace, disabled when there is nothing to drop.
- Closing the overlay with unsaved edits (a click outside, the shell close
  request) now asks to discard, save, or keep editing, like `Esc`; hiding it
  with `SUPER+ALT+L` puts the saved layout back instead of leaving the unsaved
  preview live on the workspace.
- **Startup → Save windows for startup** moves below the per-layout sections
  and is shown only in the Layouts view; session notices still appear on top.
- The Scenes header no longer keeps saying "Previous arrangement restored";
  the restore's own feedback says so, and the header describes the workspace.
  An empty Scenes list explains how to save the first scene.
- A fresh install seeds `~/.config/hypr/layouts/` with a **welcome** layout so
  `SUPER+L` has something to cycle to; existing layouts directories are left
  untouched on updates, including edits and deletions.
- Uninstall now archives settings by default (`--archive DIR` chooses a
  location; `--purge` skips archiving), wipes all Hypertile settings and
  runtime data, removes the installed plugin, and restarts the shell so cached
  development UI cannot survive a clean reinstall. It recognizes the older
  swap-navigation binding. Display settings survive ordinary upgrades and
  uninstalls and are removed on purge.
- README showcase rewritten with a smaller demo GIF and a highlights video;
  the manual covers the welcome layout.

## 1.3.0 (2026-09-15)

- `SUPER+ALT+T` opens a numbered tile picker for moving the active window to an
  empty layout tile or swapping with an occupied one. The picker supports
  clicks, multi-digit fill numbers, and cancellation, highlights the current
  tile, and rejects stale window or layout selections.
- `SUPER` + left mouse drag shows the same numbered destinations for a tiled
  window and places it into the tile under the pointer on release; dropping
  elsewhere keeps Hyprland's normal drag result.
- Tile-picker outlines honor aspect ratio and scale, showing only the fitted
  window area instead of its larger layout slot.
- `uninstall.sh --purge` removes the saved scenes directory
  (`~/.config/hypertile/scenes/`); it previously only looked for a
  `scenes.json` file that Scenes never wrote.
- New user manual at `docs/MANUAL.md`. Documentation refreshed for the 1.2.0
  release state, the plugin's service kind, the saved scenes directory, and
  the full test list.

## 1.2.0 (2026-09-12)

- Enabling the plugin installs its runtime automatically. Enabled updates
  refresh it without a separate install command, skip unchanged runtime files,
  and report setup failures in the widget and overlay. Setup preserves user
  layouts, shell placement, and manual menu/keybinding opt-outs. Development
  links continue to use `dev apply`.
- The overlay adds **Startup → Save windows for startup**, with matching
  `hypertile-ctl session enable` and `disable` commands. The choice takes
  effect immediately and persists across reboots. Disabling stops automatic
  saving and recovery while keeping snapshots; enabling saves the current
  desktop without reopening an older snapshot. Reinstallation stops a live
  disabled writer before replacing its runtime.
- `SUPER+L` and `SUPER+SHIFT+L` browse through the open Layouts overlay, keeping
  its selected layout and preview together. Enter keeps the selection; Esc
  restores the previous layout. Dialogs consume cycling shortcuts so they
  cannot change the layout behind the overlay.
- Layout tiles display their width and height in pixels beneath their
  fill-order numbers.
- Fresh installations start with an empty layouts directory. The repository's
  `quad` and `ultrawide` examples remain available for reference and tests;
  existing user layouts are preserved.
- Guarded power menu entries retain their stock icons and labels. Uninstall
  recognizes both old and current owned entries, preserves customizations,
  and disables automatic setup before removing runtime files.
- Regression coverage includes automatic setup through Quickshell, repeated
  and concurrent installation, disabled writers, persistent session toggles,
  interrupted enabling, and layout cycling through the overlay.

## 1.1.2 (2026-09-10)

- Refresh the local Hyprland size-ack backport recipe for Arch's 0.56.2-2
  packaging and Omarchy 4.0.3. The documented 0.56.2-2.1 rebuild preserves the
  Glaze compatibility change and records source, package, and isolated runtime
  verification. Hypertile's installer does not install this compositor backport.
- Overlay panels, badges, and zone labels use opaque text backgrounds. Neutral
  text colors adjust to the theme for readable contrast, and thumbnail numbers
  keep the caption size or hide when they cannot fit. Keyboard help wraps within
  the rail and includes arrow/vi browsing keys and Ctrl+S.
- The README covers the Scenes tab, placement and replacement behavior, and all
  overlay scripting methods, including app search and scene confirmation.
- Using a saved scene asks before replacing unsaved scene changes. Cancel
  keeps the arrangement; confirmation uses the originally selected scene.
  Clicking outside the zones deselects first, then closes Scenes.
- Layout controls fit on one row: the header's status line says when the
  layout is in use, Use reads as the default action, and workspace rows show
  In use as a chip. Workspace rows keep window counts visible, single-slot fill
  order has clear wording, and large zone numerals have an opaque backing.
  Header status badges no longer overlap the tabs, and long monitor controls
  fit within the rail.
- Rail polish: the session-saving notice is one tinted card with a short
  "Paused since" time; slider overrides reset with a Reset button; aspect
  presets wrap instead of running off the rail; Delete zone sits at the end of
  the zone form as a quiet destructive action; section details read as
  information rather than links; the keys panel gives wide shortcuts room.
- Saved scenes support arrow-key selection, Enter to use, and Delete with
  confirmation. The selected card exposes its delete control and scrolls into
  view. App searches accept leading digits, keep the query between zones, and
  forward `?` to keyboard help.
- Scenes use consistent Use/In use wording and report action progress and
  completion. Placement feedback follows the acknowledged operation and cannot
  mistake a stale catalog result or a pending app for completed placement.
- Renaming a scene zone preserves eligible app pins by stable zone identity,
  without another launch or move. Manual departures remain untouched, and
  checkpoints retain assignments while the rename is being reconciled.
- Invalid or unreadable scene files no longer break the rest of the catalog;
  scenes also exclude layouts that failed compilation. Session app recipes
  are validated before startup, and scene auto-start reports the daemon's
  actual error instead of just a missing socket.
- Scene pin recovery history is deduplicated, drops departed window identities,
  and retains at most 512 entries. Completed restores start a fresh history.
  Removed obsolete reservation-owner handling and unreachable CLI/engine code.
- Scene recovery requests are queued durably and retried until acknowledged.
  Undelivered assignments remain in checkpoints, including after a session
  service restart; Freeze pauses delivery and Resume re-enables it.
- An abandoned layout preview no longer silently prevents session checkpoints.
  After its lease expires, capture uses the committed layout and eligible
  original pins, preserves unrelated changes, and reports the remaining
  on-screen preview. Heartbeats now publish their renewed deadline on disk.
- The bar marks session-saving problems with an attention badge. The overlay
  shows the pause time, unmatched windows, and Resume saving; it also reports
  pending scene delivery, expired previews, and an unavailable session service.
  Capture errors stay visible until a checkpoint succeeds.
- Scenes waiting for session recovery time out after 45 seconds with Retry and
  Dismiss actions. Waiting no longer blocks layout browsing. Dismiss releases
  assignments while keeping the layout and open apps; late recovery messages
  cannot recreate the record during the same login. The overlay marks deleted
  scene definitions and explains which apps Retry may open or reuse.
- Stopping the Scenes service, including SIGTERM, attempts to restore active
  layout previews. A compositor failure no longer keeps the writer lock held;
  unsuccessful restorations remain on disk for the next writer to recover.
- The Scenes service survives a compositor error during its periodic check
  (it previously exited with an internal error); `scene status` reports the
  last failure until a check succeeds.
- Copying a layout cannot overwrite its source under the same name. Saving a
  new layout on assigned content asks before using it; discarding managed
  edits leaves the workspace untouched.
- Overlay refreshes preserve queued browsing, dismissal cancels it immediately,
  and scene updates cannot mark a leased preview as the saved layout. Failed
  or unreadable catalogs release browsing promptly; hung requests time out
  after five seconds with a visible error and Retry action.
- Successful command warnings no longer become errors. Errors include context,
  wrap to fit the screen, expire after six seconds, and clear on successful
  actions. Headers describe managed edits and previews accurately; losing
  keyboard focus clears peek mode, and slider clicks/wheel changes support undo.
- Layout cycling handles CLI paths with spaces or apostrophes and serializes
  concurrent requests and commits per workspace. Atomic writes use separate
  temporary files so overlapping writers cannot publish each other's data.
- Invalid saved layouts show their validation errors in the catalog, stay out
  of the cycle, and cannot be applied. A broken layout file no longer aborts
  the rest of the compositor config. Fill/cycle lists and rule patterns are
  validated before window placement.
- Reading or changing the default layout handles nested tables, comments,
  and quoted strings in `general`; computed layout expressions remain manual.
  Directional navigation handles missing fullscreen fields and reports a
  failed move into an empty slot without throwing out of the key callback.
- Install and uninstall preserve the first config backups. Keybind removal
  handles blank lines and older installations, and retains the runtime if a
  custom navigation reference remains. Updates finish copying the daemon
  runtime before Lua changes can restart it; `uninstall.sh --purge` also
  removes saved scenes and Python caches.
- Session recovery no longer pauses saving after every login because a window
  had no launch recipe. Such windows could never be restored, so the restore
  completes, saving resumes, a low-priority notification names the apps that
  were not reopened, and `session status` keeps listing them. A failed launch
  or an unmatched window still ends in `partial` mode.
- The guarded logout, reboot and shutdown actions proceed when
  `~/.config/hypertile/session.json` is malformed instead of exiting before
  handing over to Omarchy.
- The overlay keeps the latest layout selection while the scene catalog is
  still loading and previews it once the catalog has loaded or failed, instead
  of dropping arrow presses made in the first moments after opening.

## 1.1.1 (2026-09-07)

- Remove repository agent instructions from the installable plugin tree in
  response to marketplace review. Maintainer instructions are kept outside
  the plugin checkout. Runtime behavior is unchanged.

## 1.1.0 (2026-09-06)

- Scenes: save a workspace's layout together with what each zone holds: an
  installed app, one open window, local windows in fill order, or Empty.
  Applying a scene launches or reuses each app and places it once; you can
  then move or close it freely. Scenes live in `~/.config/hypertile/scenes/`
  and are managed from the overlay's Scenes tab or `hypertile-ctl scene`; an
  independent `hypertile-scenes` service owns placement. See
  [scenes and content](docs/SCENES.md).

- Scenes tab redesign. The header names the workspace until a scene is
  applied, then the scene with how many apps are placed. Saved scenes are
  cards like the layout list, with the apps drawn in their zones; the row
  applies. One zone list replaces CONTENT, ZONE and CHANGE TO; the picker
  under the selected zone filters as you type, shows app icons, and groups
  open windows (with titles), remote desktops, and installed apps. Zone
  cards show what they hold with icon, name, and state, plus Change… and
  Clear; a card that needs attention is outlined and offers Retry. Digits
  select zones by fill number, hovering a match previews it in the card, and
  zones are listed by position ("Top left"). The catalog lists each app's
  icon and each saved scene's sources, and skips placeholder window classes.

- Remote desktops: each computer's launcher from
  [Remote Desktops](https://github.com/jdvmi00/remote-desktops) is an ordinary
  app for Scenes and session recovery. Hypertile does not manage connections
  or host displays. Upgrade checks preserve unresolved host recovery and user
  configuration.

- `SUPER+SHIFT+arrows` move a window into an empty slot of the layout as well
  as swapping with a neighbour, so a lone app can travel around a sparse
  layout. Explicit moves reveal collapsed slots until the layout is reset.

- Session recovery: batched automatic checkpoints with durable publication and
  previous generations; named sessions; protected partial restores; supported
  app relaunch; workspace/layout, native window order, pins, sizing, floating
  geometry, and focus restoration. The Omarchy menu saves before shutdown
  closes applications and never blocks them; notifications report an
  unsaved session. See [session recovery](docs/SESSIONS.md) for app support
  and remaining limits.

## 1.0.1 (2026-09-04)

- `hypertile-ctl cycle` debounces: presses within 200 ms become one switch
  to the layout landed on, with the OSD still flashing every name. A fast
  run of real switches could leave a slow client drawn smaller than its
  tile; `--now` bypasses the debounce.

## 1.0.0 (2026-09-04)

First public release, packaged as an Omarchy shell plugin.

- Engine: `hypertile.lua` turns a zone spec into a Hyprland Lua layout
  provider. Trees of columns and rows, fill and cycle order, app rules,
  capacity, per-slot stack direction, aspect and scale, spacers, never-split
  slots, per-layout gaps, border, and rounding. Specs hot-swap in place.
- Bridge and CLI: `hypertile-ctl` lists, dumps, validates, saves, renames,
  removes, previews, applies, and cycles layouts. Layouts live one per file
  in `~/.config/hypr/layouts/`; workspace rules persist in
  `~/.local/state/hypertile/workspace-rules/` and are read without a
  config reload.
- Overlay: a fullscreen layer draws the layout's zones at true scale over
  the workspace. View mode browses layouts live and reverts on close; edit
  mode splits, resizes, deletes, renumbers, and sets zone and layout
  options with a live preview and undo. An inspector rail carries the
  layout list with thumbnails, workspace assignment, and every setting.
- Bar widget: the layout on this monitor's active workspace; click opens
  the overlay, scroll or middle-click cycles.
- Installer: `install.sh` puts the engine, CLI, layouts, keybinds, and
  menu entry in place from the plugin checkout; `uninstall.sh` removes
  them.
