# Changelog

## Unreleased

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
- Session recovery no longer pauses saving after every login because a window
  had no launch recipe. Such windows could never be restored, so the restore
  completes, saving resumes, a low-priority notification names the apps that
  were not reopened, and `session status` keeps listing them. A failed launch
  or an unmatched window still ends in `partial` mode.
- The guarded logout, reboot and shutdown actions proceed when
  `~/.config/hypertile/session.json` is malformed instead of exiting before
  handing over to Omarchy.
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
