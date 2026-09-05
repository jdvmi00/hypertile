# Scenes and content

A scene saves a workspace's layout and the content assigned to its zones. It can
combine local windows, paired remote desktops with named profiles, and Empty.
The stream controller applies the scene, owns its connections, and records
unfinished work for recovery. See [remote desktop setup](STREAMS.md) first to
configure and pair computers.

## Overlay

Open **Super+Alt+L** and switch the rail to its **Scenes** tab. The header
names the workspace's scene (or *No scene*) with its state; **Save scene…**
stores the current layout and content under a name, and **Restore previous**
puts back what the workspace had before the scene. **Saved scenes** lists every
scene with **Apply**; the applied one reads *Applied*, and ✕ deletes a saved
definition after a confirmation (nothing on the workspace changes).

**Content** lists the zones in fill order with what each one holds: local
windows by fill order, *Empty*, one app, or a computer and profile with its
state. Click a row or a zone on the screen, or move with Tab and the arrows.
The **Zone** section shows the selected zone; for a remote desktop it offers
Focus, Disconnect and Reconnect (Retry and Restore display when they apply),
and **More controls** holds capture toggling, clipboard typing where supported,
Moonlight statistics, focusing a local window, the Performance panel and the
raw status. **Change to** puts something else in the zone: Local windows,
Empty, a computer's profile (its non-default traits are shown beside it), or an
open app. Choosing a computer already on this workspace moves its assignment.
Choosing another profile reconnects that computer after restoring the old
profile's managed display settings.

Local app assignments use one matching tiled window on that workspace. Open the
app and Retry if none exists. If several match, resolve the ambiguity first;
Hypertile does not guess, launch another copy, or move a window from elsewhere.
Unassigned zones continue to use the layout's normal fill and application rules.
At least one fill/cycle zone must remain available for local windows.

Changes and source swaps mark the current scene modified; saved definitions
change only when explicitly saved (**Save** writes a named scene back). Restore
previous returns to the layout and content from before the first scene
application in this sequence. A later scene replaces pending work from the
earlier one; compatible ready streams retain their client process. Failed
sources remain visible while local content can finish applying.

Browsing under the Layouts tab moves the live windows, including connected
remote desktops. Scene assignments stay on the committed layout while the
other layout is previewed. Closing the overlay or returning to Scenes restores
that layout without reconnecting streams or changing saved scenes. An abandoned
preview expires after ten seconds without its overlay heartbeat; restarting the
controller also restores it. Session recovery retains its last committed
checkpoint while a preview is active. Using another layout there asks first:
the assignments are replaced with local content on the chosen layout (streams
disconnect, local apps stay open). Layout editing takes effect on Save. Deleted
referenced zones require choosing replacements; they are not reassigned by
their position in the layout.

Ordinary scene changes do not take focus. Focus, clipboard, statistics, and
capture controls are explicit interactions with the selected remote desktop and
close the overlay.

## CLI

```bash
hypertile-ctl scene content --zone right --type stream --computer macbook --profile desktop
hypertile-ctl scene content --zone left --type empty
hypertile-ctl scene content --zone center --type local --app-class org.example.Editor
hypertile-ctl scene save work
hypertile-ctl scene list --json
hypertile-ctl scene apply work --workspace 1
hypertile-ctl scene current --workspace 1 --json
hypertile-ctl scene retry --workspace 1
hypertile-ctl scene restore --workspace 1
```

Use names from your actual layout and app classes from `hypertile-ctl windows
--json`. Scenes currently target existing numbered workspaces. Omit
`--workspace` to use the active workspace. A computer can occupy one zone only;
explicitly disconnect it before assigning it on another workspace.

`apply` accepts work asynchronously. Check `current` for ready, connecting,
partial, or needs-attention. Retry rechecks pending content. An explicit stream
Disconnect suppresses further automatic reconnects from that scene. Apply the
scene again to request those connections again. `cancel` is an alias for
`restore`. `remove NAME` removes a saved definition without stopping its active
connections. `scene layout NAME` starts a scene containing local windows using
that layout.

Switch a connected computer's profile without manually sequencing teardown:

```bash
hypertile-ctl stream profile macbook --profile desktop-capture
hypertile-ctl stream stats macbook
hypertile-ctl stream input-release macbook
hypertile-ctl stream clipboard work-laptop
```

`input-release` toggles Moonlight's capture; it is not an idempotent release.
For Mac Command shortcuts, select a `system_keys: always` profile, focus the
stream, then enter it with the pointer or activate Toggle capture. Focusing a
newly opened client alone may leave capture inactive.
Clipboard typing sends the local text clipboard into the host's focused app.
It is neither clipboard synchronization nor file transfer. Hypertile sends the
stock Moonlight shortcut without reading or journaling clipboard contents.
**Stock Sunshine on macOS does not implement this text-input path**; the action
is disabled for configured Mac hosts. Other hosts still need a live input check.
[Moonlight's implementation](https://github.com/moonlight-stream/moonlight-qt/blob/v6.1.0/app/streaming/input/keyboard.cpp)
and [the tested Sunshine Mac implementation](https://github.com/LizardByte/Sunshine/blob/v2026.516.143833/src/platform/macos/input.cpp)
explain the distinction.

## Format and stable references

Saved definitions live in `~/.config/hypertile/scenes/NAME.json`, mode 0600.
This input example can be saved using `scene save work --file scene.json` after
substituting your layout, zone and configured computer names:

```json
{
  "version": 1,
  "layout": "my-layout",
  "sources": {
    "right": { "type": "stream", "computer": "macbook", "profile": "desktop" },
    "left": { "type": "empty" },
    "center": { "type": "local", "app_class": "org.example.Editor" }
  }
}
```

On first save, Hypertile adds a persistent `layout_id` and leaf `id` fields to
that layout without changing its geometry. The saved scene includes `layout_id`
and keys `sources` by leaf ID; each source's `zone` field is a readable name hint.
Use `scene show work` to inspect the normalized document and `scene validate
--file scene.json` for a read-only check. Name-based imports are allowed only
when the input omits `layout_id`.

Renaming or reordering zones preserves their identities. Splitting retains the
original ID on the original half and gives the new half a new ID. A copied
layout receives new identities. Deletion invalidates references; reusing a name
does not revive the old ID. Layout renames resolve through `layout_id`; missing
or duplicated identities produce an actionable error. Manually copied layout
files must receive fresh identities before being used as different scenes.

Scene sources stay outside layout geometry. Empty reservations are scoped to a
workspace. No monitor-input source is enabled until a hardware profile has been
validated; local and streamed scenes work without Dell/DDC support.

## Recovery and limits

Scene intent, its pre-scene baseline, progress, and source restoration journals
live in the existing private stream state file. The single controller serializes
scene and stream operations. Host restoration pending on an offline computer
blocks that computer's replacement profile, while local content can continue.
Session checkpoints include scene definitions and source references, excluding
transient compositor scene state. Restoring an older checkpoint does not undo an
explicit disconnect recorded by the controller.

App pins are restored only when the same window still has the scene-owned pin;
manually changed pins are preserved. Live compositor addresses are never used
as saved scene identities. Selecting a different layout directly through other
CLI/keybindings leaves the scene needing attention; apply or restore it to
reconcile content.

Meeting profiles and system-key capture are described in [STREAMS.md](STREAMS.md).
The [validation record](STREAMS-VALIDATION.md) distinguishes automated recovery
checks, live desktop checks, and hardware/call features still unverified.

The [Performance panel](STREAM-QUALITY.md) adds measured reconnect timing,
completed decoder statistics and readability assessments. Scheduled collection
uses the same stream controller and is cancelled by superseding scene work.
