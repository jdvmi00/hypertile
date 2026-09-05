# Session recovery

Hypertile automatically checkpoints the desktop while it is running and
restores it when a new Hyprland session starts. Install/update with
`./install.sh`. The Python service starts from the layout loader; config
reloads do not launch a second watcher or restore the session twice.

The service saves workspace layouts (including their specs), native tiled
window order, explicit zone pins, runtime size adjustments, workspace-to-monitor
assignments, focus, floating geometry, and fullscreen state. It relaunches
supported applications and places their new windows. Application contents
belong to the application: browser tabs and editor documents require the
app's own session recovery. Terminal commands and running processes are not
replayed.

## Commands

```sh
hypertile-ctl session status          # mode, matched/unmatched windows, errors
hypertile-ctl session save work       # independent named snapshot
hypertile-ctl session restore work    # restore that snapshot, preserving other open windows
hypertile-ctl session restore         # retry incomplete recovery, or restore the latest snapshot
hypertile-ctl session restore @previous-1  # recover the preceding automatic checkpoint (also -2, -3)
hypertile-ctl session freeze          # checkpoint now, then protect it from teardown
hypertile-ctl session resume          # accept the current desktop and resume automatic saves
hypertile-ctl session logout
hypertile-ctl session reboot
hypertile-ctl session shutdown
```

`restore` starts asynchronous recovery; use `status` for its outcome. The
service gives autostart applications one second to appear, then launches
missing supported apps: applications that restore their own windows start
together, while per-window launches (terminals, web apps) go one at a time so
each new window is attributed correctly. Windows that nothing can bring back
(no recipe, or a failed launch) do not delay placement, ordering and focus;
`status` names the reason for each. It never closes unrelated windows. An incomplete
restore enters `partial` mode and stops automatic checkpointing, so a
missing app cannot destroy the source session. A desktop notification reports
the incomplete restore, and the guarded logout, reboot and shutdown commands
warn again while saving is paused, since the desktop you are leaving will not
be saved. Open the missing app and retry `restore`, add an app recipe and
restart the watcher, or use `resume` to accept the desktop as it stands. A
failed application launch is retried only on an explicit retry, not in a loop.

`freeze` persists across service restarts within the same compositor. If a
logout is cancelled, use `resume`. Freezing during recovery preserves the
original recovery source and stops restoration.

## Shutdown integration

The installer overrides the stock Omarchy menu's logout, reboot and shutdown
actions with the guarded commands above. Existing custom actions are left
alone; `--no-menu` skips these overrides. Uninstall removes only the entries
Hypertile owns. Packaged Omarchy files are never changed. The guard never
blocks the action: if the service is not running or cannot save, a critical
notification says the session was not saved and Omarchy proceeds anyway.

**Omarchy closes windows before it asks the desktop to exit.** Use the guarded
menu actions or `hypertile-ctl session logout|reboot|shutdown`. Direct
`omarchy system ...` commands bypass that early guard; put `hypertile-ctl
session freeze` before them in custom scripts and bindings.

On systemd desktops, the service also requests a shutdown delay inhibitor
and listens for logind's `PrepareForShutdown`. This protects direct
`systemctl reboot` and `systemctl poweroff` when the user is permitted to take
that inhibitor. It cannot retroactively protect applications already closed
by an unguarded logout script. Compositor disconnection and service termination
never trigger a final query of the disappearing desktop.

## Application launching and identity

Chrome/Chromium launch with their session restore option and saved profile
selectors. Their web app windows (`--app=URL`, class `chrome-<host>…-<profile>`)
are not covered by the browser's own restore; they relaunch through
`omarchy-launch-webapp` with the URL read from the window class. Desktop
entries are matched by desktop ID or `StartupWMClass`.
General desktop applications are launched once per saved process/recipe;
apps with several windows must restore those windows themselves.

Ghostty, Alacritty, Kitty, and Foot have terminal recipes. A terminal with a
single shell child can save that shell's directory. A shared terminal server
with several shell children has no reliable per-window directory mapping;
it opens the default directory unless an explicit recipe is provided.

A terminal comes back as a plain shell. Commands running inside it are not
replayed, since that would rerun builds and scripts, with one opt-in
exception: the `replay` list names commands that are safe to start again,
typically a TUI that re-attaches to its own server. When the terminal's single
shell has such a command as its foreground job, the recipe starts the terminal
running that command, with its arguments, in the command's directory.

Configure applications in `~/.config/hypertile/session.json`:

```json
{
  "enabled": true,
  "replay": ["herdr"],
  "apps": {
    "my-terminal": {
      "argv": ["my-terminal", "--working-directory", "/home/me/project"],
      "per_window": true
    },
    "my-editor": {
      "argv": ["my-editor", "/home/me/project"],
      "per_window": false
    }
  }
}
```

`replay` holds command names (the executable's basename); the whole argument
list of the running job is replayed. `apps` keys are exact initial window
classes (falling back to the current class).
`argv` is an argument array, executed without a shell. `per_window` defaults
to false. The snapshot retains the recipe used at capture time; an explicit
current configuration overrides it, and a window the snapshot had no recipe
for is retried with the current built-in recipes. After changing configuration, run
`hypertile-ctl session stop`, then `hyprctl reload`. Set `enabled` to false
to disable the watcher on subsequent starts.
The guarded menu actions delegate directly to Omarchy while it is disabled.

Old window addresses are only usable in the same compositor instance and
with the same process/stable ID. After a restart, the service matches unique
class/title combinations and tracks newly launched individual windows.
It leaves ambiguous same-app windows unresolved instead of guessing. This
can happen when an app restores several windows with identical titles;
`status` lists the unresolved windows. Relaunching arbitrary `/proc` command
lines would run terminal jobs again, so Hypertile intentionally uses app
recipes and desktop entries instead.

Hypertile zone layouts and their native order are restored. A layout that
still exists keeps its current definition, so edits made after the snapshot
are not reverted; only a layout that no longer exists is re-registered from the
snapshot's copy of its spec. Built-in dwindle,
master, and scrolling layouts regain their workspace/layout selection, but
this feature does not reconstruct their internal trees. Hyprland tab groups
and app-internal tabs/documents are not reconstructed. Missing monitors fall
back to the available desktop; floating windows are brought onto an available
monitor. Exact geometry assumes the same monitor configuration and app sizing
constraints. An application crash while Hyprland survives looks like window
closure: previous generations or a named session can recover it, but the
service does not automatically relaunch apps merely because they close.

## Persistence and lifecycle

State lives under `$XDG_STATE_HOME/hypertile/sessions` (normally
`~/.local/state/hypertile/sessions`):

- `latest.json` and three previous generations: automatic checkpoints. A
  generation is promoted only when the outgoing latest is at least two minutes
  newer than the previous one, so the frequent title-change checkpoints, and an
  unguarded logout closing every window, cannot flush the history within
  seconds. `restore @previous-1` then loses at most two minutes of changes.
- `recovery.json`: protected source of the current/most recent restore.
- `status.json`: lifecycle and launch progress, used after a service restart.
- `saved/<name>.json`: explicitly saved sessions, never changed by autosave.

Files are private to the user. They include window titles and supported
launch metadata. Publishing uses a sibling temporary file, file `fsync`,
atomic rename, and directory `fsync`. Previous generations are copied before
the newest is published; an invalid latest generation falls back to a valid
previous one. An unreadable/unsupported recovery source is not overwritten
with an empty session. A startup failure (an unreadable status file, a missing
recovery source, a compositor query error) is reported in `status` and as a
notification; the service keeps running so checkpoints and the guarded
commands still work.

One service owns a filesystem lock and serializes all changes. Hyprland IPC
events mark the session dirty. A checkpoint is due after one second of quiet,
with a five-second maximum batching delay. A five-second reconciliation query
also catches floating geometry and layout changes that have no external IPC
event. Equal desktop state produces no snapshot writes. A crash can lose the
most recent uncheckpointed changes.

Restoration protects its source before touching the compositor, commits launch
intent before spawning apps, and persists successful matches. Restarting the
service during recovery in the same compositor does not relaunch already
attempted apps. Automatic saving resumes only after all saved windows have
matched and settled, or after an explicit `resume`.
