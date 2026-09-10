# Scenes and content

A scene saves a workspace's layout and the apps assigned to its zones. Choose
an installed app, an already open local window, normal fill order, or Empty.
Scenes launches or reuses an app window and places it once. You can then move,
resize, float, fullscreen, or close it without Scenes pulling it back or
opening another copy.

Remote Desktops is an ordinary app in this model. It owns Moonlight/Sunshine,
connection profiles, reconnects, and host display restoration. Hypertile owns
layout and initial placement. No stream controller or computers.json is needed
for app scenes.

## Overlay

Open **Super+Alt+L** and switch to **Scenes**. Each zone card on the screen
shows what it holds: the app's icon and name with its state, or *Local
windows · fill order*. Click a card (or a row under **Zones**, or press its
fill number) and the picker below takes the keys: type to search, ↑ ↓ pick a
match, Enter assigns it, Esc clears the search. Hovering a match previews it
in the selected card. Zones are listed by where they sit ("Top left"), with
the layout's own name where positions would collide. **Local windows** and **Empty** are the two chips above the
list. **Open here** lists the windows already on this workspace with their
titles; choosing one pins that window without launching anything. **Remote
desktops** lists each computer's Remote Desktops launcher (install it there
first; it uses that computer's default profile). **Apps** lists installed
desktop entries with a known window identity; entries whose window class is
a packaging placeholder are left out. A card's **Change…** and **Clear** do
the same from the screen, and a card that needs attention is outlined and
offers **Retry**.

While the search has focus, digits are ordinary text (for example, `1Password`).
Tab selects the next zone and keeps the query; `?` toggles keyboard help.
With no zone selected, ↑ ↓ select a saved scene, Enter uses it, and Delete
asks before removing its file. The selected scene scrolls into view and shows
its delete control. Progress messages follow the controller until content is
placed or needs attention.

Applications declaring `StartupWMClass` are available immediately. For other
apps, an open window whose class equals the desktop ID without `.desktop`
provides the identity. Apps without either can be configured through the CLI
with an explicit class and optional exact title.

The header names the workspace until a scene is in use, then the scene, with
the layout, the workspace, and how many apps are placed. **Scenes** lists the
saved scenes as cards: the layout with the apps it places drawn in their
zones, and what it holds. Click a card to use it; the delete appears on hover
or keyboard selection and confirms inline. Using another scene, or reusing its
saved definition, asks first if the current scene has unsaved changes. Cancel
to save those changes, or confirm **Use** to replace the arrangement.
Click outside the zones once to deselect a zone; with no zone selected, clicking
outside closes the overlay.

**Save as…** stores the current definition. Using a saved scene requests its
arrangement, including apps you moved or closed. **Retry** explicitly
rechecks placement and may retry a failed/timed-out launch. Closing an app or
moving it yourself leaves its source marked *Closed* or *Moved*. Changes to the
saved definition happen only when you save.

Renaming a zone keeps its stable identity and remaps apps that are still placed
there. It does not launch them again or pull back apps you moved, floated,
unpinned, or closed. Invalid or unreadable saved scenes appear as individual
invalid cards; the rest of the catalog remains available.

**Restore previous** restores the prior layout/content and eligible app pins.
It leaves apps open and does not move departed windows back to their original
workspace. Changing scenes or cancelling an in-progress scene stops pending
placement; an app already launched may still open normally. Empty/fill behavior
and the layout's application rules continue to apply to other windows.

If session recovery does not arrive within 45 seconds after login, the scene
shows **Needs attention** and offers **Retry** or **Dismiss**. Waiting for
session recovery does not block layout browsing. The header marks a missing
saved definition as **Deleted scene** and explains which apps Retry may open
or reuse from the retained definition.

**Dismiss** forgets a waiting or failed scene and releases its zone assignments.
It keeps the current layout and leaves apps open. A late session recovery
message cannot bring that record back during the same login; saved scene files
are kept, so you can choose one again later.

Layout browsing previews the geometry and restores the committed layout when
you leave the preview. The lease expires after ten seconds without a heartbeat.
Session capture waits until the preview ends or expires. After a writer crash,
expired previews are checkpointed using their committed layout, with a warning
in the bar and overlay until the on-screen preview is cleaned up. Choosing a different layout
replaces the assignments with local content; open apps keep running.

## CLI

```bash
hypertile-ctl scene catalog --json
hypertile-ctl scene content --zone right --type app --desktop-id remote-desktops-macbook.desktop
hypertile-ctl scene content --zone left --type empty
hypertile-ctl scene content --zone center --type local --app-class org.example.Editor
hypertile-ctl scene save work
hypertile-ctl scene apply work --workspace 1
hypertile-ctl scene current --workspace 1 --json
hypertile-ctl scene retry --workspace 1
hypertile-ctl scene restore --workspace 1
hypertile-ctl scene dismiss --workspace 1
```

For an app without declared identity, add `--app-class org.example.App` and,
when its class is shared, `--app-title 'Exact window title'`. Classes and titles
are literal strings, not regexes. Use `hypertile-ctl windows --json` to inspect
windows. Desktop IDs resolve through the XDG application directories, with
user entries taking precedence. Arbitrary desktop paths and stored shell
commands are not accepted. `gio launch` handles the installed desktop file.

Scenes uses existing numbered workspaces. Omit `--workspace` for the current
one. An explicit assignment elsewhere supersedes an older pending assignment
of the same app. Applying a scene accepts work asynchronously; inspect `current`
for progress. A missing app window times out after 45 seconds. Ambiguous matches
require closing extras or narrowing the title; no arbitrary window is selected.
An interrupted launch is not automatically submitted again after service restart.

`cancel` aliases `restore`. `remove NAME` deletes only the saved definition.
`layout NAME` applies a layout with normal local fill. Placement itself does not
change focus; the app's own launcher may activate its window.

## Format and stable references

Definitions live in `~/.config/hypertile/scenes/NAME.json`, mode 0600. Save this
input using `scene save work --file scene.json`, substituting your layout/zones:

```json
{
  "version": 1,
  "layout": "my-layout",
  "sources": {
    "right": {
      "type": "app",
      "desktop_id": "remote-desktops-macbook.desktop",
      "app_class": "com.moonlight_stream.Moonlight",
      "app_title": "MacBook - Moonlight"
    },
    "left": { "type": "empty" },
    "center": { "type": "local", "app_class": "org.example.Editor" }
  }
}
```

Remote Desktops publishes `X-RemoteDesktops-WindowClass` and
`X-RemoteDesktops-WindowTitle` in each launcher. Scenes reads those optional
metadata fields and preserves their exact match. This distinguishes computers
whose Moonlight windows share a class. Ordinary apps use the same placement
path. Overlapping app matches within a scene are rejected.

On first save, Hypertile adds a persistent `layout_id` and leaf `id` fields to
the layout without changing geometry. Saved sources use leaf IDs, with `zone`
as a readable hint. `scene show NAME` shows the normalized document;
`scene validate --file FILE` checks it without applying changes. Name-based
imports are allowed only when the input omits `layout_id`.

Renaming/reordering zones preserves IDs. Splitting retains the original ID on
one half and gives the other a new ID. Copied layouts get new IDs. Deleted or
ambiguous identities require choosing replacements; reusing a name does not
revive a deleted zone. Keep one fill/cycle zone available for local overflow.
No monitor-input source is enabled without a validated hardware profile.

## Service and recovery

The independent `hypertile-scenes` service owns
`~/.local/state/hypertile/scenes/state.json` and
`$XDG_RUNTIME_DIR/hypertile-scenes/control.sock`. It takes its own writer lock,
so it can run alongside Remote Desktops. It does not read legacy computer
configuration or modify host display journals. The loader starts it; CLI scene
commands also start it on demand. Launch/placement intent is persisted before
effects. Work advances at 200 ms while connecting; settled scenes are checked
at 30-second intervals or when the overlay/CLI requests state. There is no
per-frame scripting in this path.

A restart in the same compositor preserves consumed launches and placements.
A new compositor waits for session recovery's checkpoint before applying scene
references. Scene-managed app windows are excluded from ordinary app recovery
so there is one launch owner. Checkpoints omit app assignments that the user
moved/closed; moved windows use normal session recovery, including the exact
computer launcher where available. Saved scene files retain their defaults.
Missing scene service/invalid legacy references produce recovery warnings.

Pins are restored only when the same window still has the scene-owned pin on
the same workspace. Identity checks include compositor address, stable ID, and
PID, and happen again immediately before placement. A lost placement reply
requires explicit reapplication instead of risking an automatic second move.

## Migrating legacy remote scenes

Existing `type: "stream"` scene files and legacy host recovery journals are
preserved. They are not automatically converted: install each computer's
Remote Desktops launcher, disconnect/restore legacy Hypertile streams, and
replace those sources with `type: "app"` entries. Legacy stream scenes appear
invalid until migrated. Upgrade and uninstall refuse to remove recovery tools
while any legacy connection is desired or has a pending host journal, including
when its controller is stopped. Finish recovery with the previously installed
version before upgrading. Configuration and state files are kept.

Hypertile no longer installs `hypertile-stream`, host adapters, Windows display
scripts, connection controls, or quality measurements. The standalone Scenes
service lives under `scenes/`; it only manages layouts and app placement.
Connection, input capture, audio, and host display controls belong to
[Remote Desktops](https://github.com/jdvmi00/remote-desktops).

## Validation

On 2026-09-05, a live MacBook check used the installed desktop launcher with the
new scene service and Lua adapter on temporary workspaces. Initial zone
placement passed; a move to another workspace survived a scene-service restart;
explicit reapplication reused the same client PID and connection generation;
restoring the scene left the app running. Cleanup disconnected the test session
and completed host display restoration. The regular session watcher was paused
during the check and resumed afterward. The installed plugin was not replaced.

Automated tests cover exact/ambiguous matches, interrupted launches and placement
replies, app-only session recovery, cancelled/superseded operations, XDG launcher
precedence, socket/lock isolation, and preservation of manual moves/closes.
Both MacBook and the Windows work laptop were subsequently validated live with
Remote Desktops launchers and the saved two-app scene. Workspace movement,
launcher reuse, explicit scene reapplication, and Windows reconnection passed;
the owner confirmed video, mouse, and keyboard on both computers. These checks
preceded removal of the legacy code; removal is covered by the generic app,
scene, session, swap, preview, and upgrade regression suites.
