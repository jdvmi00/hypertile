#!/usr/bin/env bash
# Completely remove Hypertile, including settings and the installed plugin.
# By default, archive settings in ~/Backups/hypertile-uninstall-<timestamp>/.
# --archive DIR chooses a new archive directory; --purge skips the archive.
# Unrelated desktop settings and development symlink targets are preserved.
# Usage: ./uninstall.sh [--archive DIR | --purge]

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

archive=""
purge=0
while (( $# )); do
  case "$1" in
  --purge) purge=1; shift ;;
  --archive)
    [[ $# -ge 2 && -n "$2" ]] || { echo "--archive requires a directory" >&2; exit 2; }
    archive="$2"; shift 2 ;;
  -h | --help)
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
  *) echo "uninstall.sh: unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ $purge == 0 || -z "$archive" ]] || { echo "--archive and --purge are mutually exclusive" >&2; exit 2; }

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
config="${XDG_CONFIG_HOME:-$HOME/.config}"
hypr="$config/hypr"
bin="$HOME/.local/bin"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hypertile"
plugin_id="jmartin.hypertile"
plugin_dst="$config/omarchy/plugins/$plugin_id"

PYTHONPATH="$src/session" python3 - "$state" "$config/omarchy/shell.json" <<'PY_PREFLIGHT'
from pathlib import Path
from upgrade import check_legacy
import sys
check_legacy(Path(sys.argv[1]))
# Validate before removal even when the shell is offline.
import json
shell = Path(sys.argv[2])
if shell.exists():
    value = json.loads(shell.read_text())
    if not isinstance(value, dict):
        sys.exit("uninstall.sh: shell.json must contain an object")
PY_PREFLIGHT

# Wait for any setup already in progress, then disable the service before
# removing runtime files. An enabled service would reinstall them on reload.
mkdir -p "$state"
exec 8>"$state/install.lock"
flock -x 8
# Preserve shell placement/preferences before disabling the plugin.
if (( ! purge )) && [[ -f "$config/omarchy/shell.json" ]]; then
  cp "$config/omarchy/shell.json" "$state/uninstall-shell.json"
fi
shell_up=0
if command -v omarchy-shell >/dev/null 2>&1 && omarchy-shell -q shell ping 2>/dev/null; then
  shell_up=1
  omarchy-plugin-disable "$plugin_id" >/dev/null
fi

# Stop writers before archiving or removing their data. An offline service
# may reject stop; writer locks below prove that it has actually exited.
if [[ -x "$bin/hypertile-displays" ]]; then
  "$bin/hypertile-displays" stop >/dev/null
fi
if [[ -x "$bin/hypertile-session" ]]; then
  "$bin/hypertile-session" stop >/dev/null 2>&1 || true
fi
if [[ -x "$bin/hypertile-stream" ]]; then
  "$bin/hypertile-stream" stop >/dev/null 2>&1 || true
fi

if [[ -x "$bin/hypertile-scenes" ]]; then
  "$bin/hypertile-scenes" stop >/dev/null 2>&1 || true
fi

mkdir -p "$state/displays"
exec 7>"$state/displays/daemon.lock"
flock -x -w 5 7 || { echo "uninstall.sh: display service is still running" >&2; exit 1; }

# Keep pending host recovery tools intact and prevent legacy writer restarts.
mkdir -p "$state/streams"
exec 9>"$state/streams/writer.lock"
flock -sn 9 || { echo "uninstall.sh: legacy controller is still running" >&2; exit 1; }
PYTHONPATH="$src/session" python3 - "$state" <<'PY_CHECK'
from pathlib import Path
from upgrade import check_legacy
import sys
check_legacy(Path(sys.argv[1]))
PY_CHECK

# Stop requests can return before the daemon exits. Hold every writer lock
# through archive and removal; a failed stop must never erase live state.
mkdir -p "$state/sessions" "$state/scenes"
exec 5>"$state/sessions/writer.lock"
flock -x -w 5 5 || { echo "uninstall.sh: session service is still running" >&2; exit 1; }
exec 6>"$state/scenes/writer.lock"
flock -x -w 5 6 || { echo "uninstall.sh: scenes service is still running" >&2; exit 1; }

# Copy and verify stopped services before removing files. Archive failure
# leaves the installation on disk, with services stopped/disabled.
if (( ! purge )); then
  python3 - "$archive" "$config" "$state" "$plugin_dst" <<'PY_ARCHIVE'
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import sys

requested, config, state, plugin = sys.argv[1:]
config, state, plugin = map(Path, (config, state, plugin))
data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "hypertile"
sources = {"layouts": config / "hypr/layouts", "settings": config / "hypertile",
           "state": state, "runtime-code": data, "plugin": plugin}
for name in ("hyprland.lua", "bindings.lua", "looknfeel.lua", "monitors.lua"):
    sources["desktop/" + name] = config / "hypr" / name
for name in ("shell.json", "extensions/omarchy-menu.jsonc"):
    sources["desktop/omarchy/" + name] = config / "omarchy" / name
if (state / "uninstall-shell.json").exists():
    sources["desktop/omarchy/shell.json"] = state / "uninstall-shell.json"
for directory in (config / "hypr", config / "omarchy/extensions"):
    for path in directory.glob("*.hypertile.bak"):
        sources["installer-backups/" + str(path.relative_to(config))] = path
if requested:
    destination = Path(requested).expanduser().absolute()
else:
    parent = Path.home() / "Backups"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / ("hypertile-uninstall-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
for source in sources.values():
    if destination.resolve().is_relative_to(source.resolve()):
        sys.exit("Archive must be outside the installation and settings directories")
destination.parent.mkdir(parents=True, exist_ok=True)
destination.mkdir(mode=0o700)
checks = {}
for name, source in sources.items():
    if not source.exists():
        continue
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
        files = [p for p in source.rglob("*") if p.is_file() and not p.is_symlink()]
    else:
        shutil.copy2(source, target)
        files = [source]
    for original in files:
        copied = target / original.relative_to(source) if source.is_dir() else target
        def digest(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        expected = digest(original)
        if digest(copied) != expected:
            sys.exit("Archive verification failed: " + str(original))
        checks[str(copied.relative_to(destination))] = expected
(destination / "checksums.json").write_text(json.dumps(checks, indent=2) + "\n")
(destination / "README.txt").write_text(
    "Hypertile settings archived before uninstall.\n"
    "After reinstalling, copy layouts/ contents into $XDG_CONFIG_HOME/hypr/layouts/ "
    "(normally ~/.config/hypr/layouts/), then run hyprctl reload.\n"
    "settings/ contains scenes and preferences; state/ contains workspace rules and recovery data.\n"
    "Restore selectively after stopping the relevant services. Do not restore old state for a clean-install test.\n"
    "desktop/ and installer-backups/ are reference copies; do not overwrite current desktop configuration blindly.\n")
print("Verified archive: " + str(destination), flush=True)
PY_ARCHIVE
fi

# Preserve the original pre-install backup, including on repeated uninstalls.
backup() {
  if [[ ! -e "$1.hypertile.bak" ]]; then
    cp "$1" "$1.hypertile.bak"
  fi
}

# The default layout may point at a hypertile layout; put it back on dwindle
# before the engine goes away, or the next reload has a layout it cannot find.
looknfeel="$hypr/looknfeel.lua"
if [[ -e "$looknfeel" ]] && grep -qE '^\s*layout\s*=\s*"lua:' "$looknfeel"; then
  backup "$looknfeel"
  sed -i -E 's|^(\s*layout\s*=\s*)"lua:[^"]*"|\1"dwindle"|' "$looknfeel"
  echo "default layout in looknfeel.lua set back to dwindle"
fi

# The loader require line.
main="$hypr/hyprland.lua"
if [[ -e "$main" ]] && grep -q 'require("hypr.hypertile-layouts")' "$main"; then
  backup "$main"
  sed -i '/^require("hypr.hypertile-layouts")$/d' "$main"
  echo "removed the loader require from hyprland.lua"
fi

# Remove marked blocks and the known blocks written by older installers.
bindings="$hypr/bindings.lua"
if [[ -e "$bindings" ]] && grep -q '^-- hypertile' "$bindings"; then
  backup "$bindings"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$bindings" <<'PY'
import sys
import re
path = sys.argv[1]
text = open(path).read()
text = re.sub(r'^-- hypertile: begin [^\n]+\n(?:(?!^-- hypertile: begin ).)*?'
              r'^-- hypertile: end[^\S\n]*(?:\n|$)',
              '', text, flags=re.M | re.S)
# Match only the original installer-owned lines, allowing blank lines within
# each block. A user line after a block must survive even without a separator.
legacy = [
    ['-- hypertile: swap across gaps, replacing Omarchy\'s directional swap bindings.',
     'require("hypr.hypertile-navigation").bind()'],
    ['-- hypertile: focus and swap across gaps, replacing Omarchy\'s directional bindings.',
     'require("hypr.hypertile-navigation").bind()'],
    ['-- hypertile: fullscreen layout overlay (browse with arrows, Enter uses and closes).',
     'o.bind("SUPER + ALT + L", "Layouts overlay", "omarchy-shell shell toggle jmartin.hypertile")'],
    ['-- hypertile: cycle the workspace through every saved layout, then dwindle.',
     "-- The shell flashes the new layout's name.", 'hl.unbind("SUPER + L")',
     'o.bind("SUPER + L", "Toggle workspace layout", "hypertile-ctl cycle")'],
    ['-- hypertile: cycle the other way.',
     'o.bind("SUPER + SHIFT + L", "Toggle workspace layout (back)", "hypertile-ctl cycle --reverse")'],
]
for block in legacy:
    pattern = r'\n(?:[ \t]*\n)*'.join(re.escape(line) for line in block)
    text = re.sub('^' + pattern + r'(?:\n|$)', '', text, flags=re.M)
open(path, "w").write(text)
PY
    echo "removed the hypertile keybinds from bindings.lua (Omarchy's SUPER+L is back)"
  else
    echo "note: python3 not found; remove the '-- hypertile' blocks from $bindings by hand"
  fi
fi

# Keep the module and its dependencies if an edited or custom binding still
# refers to it. Removing the runtime would break subsequent config reloads.
if [[ -e "$bindings" ]] && grep -q 'hypertile-navigation' "$bindings"; then
  echo "uninstall.sh: $bindings still references hypertile-navigation; runtime files retained." >&2
  echo "Remove that reference and run uninstall.sh again." >&2
  exit 1
fi

# Menu entry.
menu_ext="$config/omarchy/extensions/omarchy-menu.jsonc"
if [[ -e "$menu_ext" ]] && grep -qE "\"layouts\":.*$plugin_id|hypertile-ctl session (logout|reboot|shutdown)" "$menu_ext"; then
  backup "$menu_ext"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$menu_ext" "$plugin_id" <<'PY'
import json
import sys
path, pid = sys.argv[1], sys.argv[2]
lines = open(path).read().split("\n")
lines = [l for l in lines if not (l.lstrip().startswith('"layouts"') and pid in l)]
def owned_power_entry(line):
    try:
        row = json.loads("{" + line.strip().removesuffix(",") + "}")
    except ValueError:
        return False
    for action, icon, label in (("logout", "󰍃", "Logout"),
                                ("reboot", "󰜉", "Reboot"),
                                ("shutdown", "󰐥", "Shutdown")):
        command = "hypertile-ctl session " + action
        # Remove both the legacy action-only form and complete stock entries.
        # User-customized entries are kept.
        if row in ({"system." + action: {"action": command}},
                   {"system." + action: {"icon": icon, "label": label, "action": command}}):
            return True
    return False
lines = [line for line in lines if not owned_power_entry(line)]
# The entry before it may now be the last one and must lose its comma.
body = [i for i, l in enumerate(lines) if l.strip() and not l.strip().startswith("//")]
if len(body) >= 2:
    last, prev = body[-1], body[-2]
    if lines[last].strip() == "}" and lines[prev].rstrip().endswith(","):
        lines[prev] = lines[prev].rstrip()[:-1]
open(path, "w").write("\n".join(lines))
PY
    echo "removed Layouts from the Omarchy menu"
  else
    echo "note: python3 not found; remove the \"layouts\" entry from $menu_ext by hand"
  fi
fi

# Files.
for f in hypertile.lua hypertile-json.lua hypertile-bridge.lua hypertile-layouts.lua hypertile-navigation.lua hypertile-session.lua; do
  rm -f "$hypr/$f"
done
rm -f "$bin/hypertile-ctl"
PYTHONPATH="$src/session" python3 - "$bin" "${XDG_DATA_HOME:-$HOME/.local/share}" <<'PY_CLEANUP'
from pathlib import Path
from upgrade import cleanup
import sys
cleanup(Path(sys.argv[1]), Path(sys.argv[2]))
PY_CLEANUP
rm -f "$bin/hypertile-session" "$bin/hypertile-scenes" "$bin/hypertile-displays"
for module in service scene_recovery display_recovery upgrade; do
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile/session/$module.py"
done
for module in scene_service apps ipc scenes browse; do
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile/scenes/$module.py"
done
for source in "$src"/displays/*.py; do
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile/displays/$(basename "$source")"
done
echo "removed the engine files and hypertile-ctl"

# Remove full application-owned trees, including obsolete settings/modules.
# rm removes a development symlink itself, never its source checkout.
rm -rf "$hypr/layouts" "$state" "$config/hypertile" "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile"
# The caller may have cd'd into the installed checkout. Keep subsequent
# Python invocations out of a directory we are about to delete.
cd "$HOME"
rm -rf "$plugin_dst"
python3 - "$config" <<'PY_CLEAN'
from pathlib import Path
import json
import os
import shutil
import sys
config = Path(sys.argv[1])
shell = config / "omarchy/shell.json"
if shell.exists():
    value = json.loads(shell.read_text())
    def clean(value):
        if isinstance(value, list):
            return [clean(item) for item in value if item != "jmartin.hypertile"
                    and not (isinstance(item, dict) and item.get("id") == "jmartin.hypertile")]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key != "jmartin.hypertile"}
        return value
    updated = clean(value)
    if updated != value:
        shell.write_text(json.dumps(updated, indent=2) + "\n")
for directory in (config / "hypr", config / "omarchy/extensions"):
    for path in directory.glob("*.hypertile.bak"):
        path.unlink()
runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
for name in ("hypertile", "hypertile-scenes", "hypertile-session", "hypertile-tile-drag.json"):
    path = runtime / name
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
PY_CLEAN
echo "removed layouts, settings, state, runtime files, installer backups, and shell plugin"

# A rescan retains compiled QML for this plugin URL. Restart after removal,
# otherwise its enabled service can reinstall the runtime.
if (( shell_up )); then
  omarchy restart shell 5>&- 6>&- 7>&- 8>&- 9>&-
  echo "restarted the shell to clear cached plugin UI"
fi

if command -v hyprctl >/dev/null 2>&1 && hyprctl version >/dev/null 2>&1; then
  hyprctl reload >/dev/null || { echo "hyprctl reload failed" >&2; exit 1; }
  errors="$(hyprctl configerrors | sed '/^\s*$/d' || true)"
  if [[ -n "$errors" ]]; then
    echo "hyprctl configerrors:" >&2
    echo "$errors" >&2
    exit 1
  fi
  echo "reloaded Hyprland, no config errors"
fi

echo "uninstalled."
