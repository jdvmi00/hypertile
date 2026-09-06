# Changelog

## Unreleased

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

- Remote connections now belong to Remote Desktops. Remove Hypertile's legacy
  controller, host adapters, display scripts, and remote controls. Scenes and
  session recovery use ordinary installed apps; pinned swaps remain generic.
  Upgrade checks preserve unresolved host recovery and user configuration.

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
