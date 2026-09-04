# Developing Hypertile live

Use `~/Code/hypertile` as the authoritative checkout. Link Omarchy's plugin
directory to it, then use the repository's `dev` helper to apply uncommitted
changes to the running desktop. No push, pull, or second working tree is
needed for the edit/test loop.

## First-time setup

Run these commands in a terminal inside your Hyprland session:

```sh
cd ~/Code/hypertile
./dev link
./install.sh
./dev apply
./dev status
```

`link` validates the source and creates:

```text
~/.config/omarchy/plugins/jmartin.hypertile -> ~/Code/hypertile
```

If the plugin directory already exists, the helper moves the entire existing
installation, including `.git`, local edits, and untracked files, into a unique
directory under `~/.local/state/hypertile/dev/backups/`. It prints the exact
location. Backups live outside plugin discovery, so Omarchy does not see two
copies of the same plugin. Running `link` again is harmless. The backup is
preserved, not merged into your source checkout; bring any wanted edits across
before continuing development.

Run the normal installer once to set up the CLI, layout loader, menu actions,
and bindings. Because the installed plugin now resolves to the source checkout,
the installer accepts it. The first `dev apply` refreshes all components and
records a baseline for subsequent change detection.

While linked, manage Git branches and updates in `~/Code/hypertile`.
`omarchy plugin update` would update that same checkout through the link.

## The daily loop

```sh
# Edit source files, then:
./dev apply

# Inspect the overlay/windows and check the deployment:
./dev status

# Explicitly refresh everything, even if source files haven't changed:
./dev apply --force
```

`apply` checks Lua and Python syntax and validates the plugin manifest before
changing runtime files. If `qmlformat` is available, it also parses QML without
editing it. It does not run the test suites on every apply. QML imports and
dynamic components still need a live check: open the overlay and exercise the
changed behavior after the shell restarts.

| Changed files | What `apply` does |
|---|---|
| Root `hypertile*.lua` modules | Copies changed modules, reloads Hyprland, checks `configerrors`, restarts the session watcher |
| `bin/hypertile-ctl` | Copies the CLI; no process restart |
| `session/*.py`, `bin/hypertile-session` | Stops the old watcher, waits for its writer lock, copies changes, starts the new watcher |
| `plugin/`, `manifest.json` | Restarts the Omarchy shell to discard cached QML |
| Documentation and tests | No runtime changes |

The watcher is paused during Lua updates too, so it cannot capture a partially
updated adapter. The helper holds its writer lock until copying and reloading
finish. Hyprland's automatic config reloads are temporarily suspended during
the Lua copy, then their previous setting is restored. Files are replaced
atomically, and existing runtime files are backed up before replacement.

The shell reads linked source files directly and may notice edits before an
explicit apply. `apply` forces a fresh shell load; the link is not a staging
boundary for QML. Compositor Lua modules remain installed copies, so editing
engine source alone does not alter the running compositor.

Use a dedicated workspace with disposable application windows for layout/UI
experiments. Session recovery, process crashes, and shutdown behavior belong
in an isolated compositor with separate config, runtime, and state directories.
The helper targets the real desktop; it does not create an isolated session.
The existing [headless diagnostic runner](diagnostics/size-acks/headless-check.py)
illustrates isolation, but its assertions are specific to the sizing backport.

## Layout and CLI experiments

The helper does not overwrite your saved layouts, workspace rules, session
snapshots, menu customizations, or bindings. `layouts/*.lua` are sample layouts;
the installer only copies them when no user layout of that name exists.

Preview a JSON layout on a test workspace:

```sh
hypertile-ctl preview /path/to/layout.json --workspace 9
```

To preview a changed sample Lua layout from this checkout:

```sh
HYPERTILE_SRC="$PWD" HYPERTILE_LAYOUTS_DIR="$PWD/layouts" \
  bin/hypertile-ctl dump quad | hypertile-ctl preview - --workspace 9
```

For CLI/bridge work you can run source directly:

```sh
HYPERTILE_SRC="$PWD" bin/hypertile-ctl list
```

`HYPERTILE_SRC` selects local CLI/bridge code, not the engine already loaded in
Hyprland. `dev` clears that override for its runtime commands so its status and
restart checks address installed code.

## Status, failures, and reverting

`./dev status` shows the source revision, plugin path, pending components,
last successful apply, and whether Hyprland, the shell, and the session service
respond. Pending components compare source hashes and installed files with the
last successful apply. This is a deployment record, not inspection of code in
process memory; `--force` is useful after manual copying or restarting.

An apply is recorded only after the requested reloads/restarts succeed. A syntax
failure makes no runtime changes. A failed live reload/restart leaves the apply
pending and reports the error; the session watcher may remain stopped after a
failed Lua update. Fix the source and run `./dev apply` again. The helper never
automatically accepts an incomplete session restore or resumes a frozen session.

To revert a code change, restore the wanted version in the source checkout and
apply it again. Previous runtime files are also available at the backup path
printed by each apply. Backups and deployment records use
`$XDG_STATE_HOME/hypertile/dev` (default: `~/.local/state/hypertile/dev`).

To return to the preserved standalone installation, remove **only the plugin
symlink**, move the printed plugin backup back to that path, and run its own
installer. The development checkout remains intact.

If a terminal or agent inherited a stale compositor environment, list instances
and select the intended signature explicitly:

```sh
hyprctl instances
./dev status --instance SIGNATURE
./dev apply --instance SIGNATURE
```

The helper honors `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME` for
installed files, matching the installer. It does not install packages or modify
packaged Omarchy files.

## Verification before committing

Run the suites relevant to the change. The complete list is in the root
[development section](../README.md#development). In particular:

```sh
python3 test/dev.py     # deployment preservation, selective restarts, failed apply
lua test/harness.lua   # engine placement
lua test/bridge.lua    # bridge and CLI
node test/geometry.js  # overlay geometry
node test/editor.js    # editor operations
python3 test/session.py
lua test/session.lua
```

See also [session recovery](SESSIONS.md), [engine internals](INTERNALS.md), and
the [Hyprland sizing bug](HYPRLAND-SIZING-BUG.md).
