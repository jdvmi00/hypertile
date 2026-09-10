#!/usr/bin/env bash
# Undo install.sh: the engine files and the loader require line in
# ~/.config/hypr, the CLI, the keybinds and the menu entry it added, and the
# shell plugin's bar entry. Workspaces fall back to Hyprland's default layout.
# Config backups at <file>.hypertile.bak are created only when absent.
#
# Kept unless --purge is given: your layouts (~/.config/hypr/layouts/) and
# hypertile's state (~/.local/state/hypertile/: workspace rules, overlay
# preferences), and saved scenes (~/.config/hypertile/scenes.json).
#
# The plugin directory itself is removed only when it is a plain copy made by
# install.sh. A git checkout made by `omarchy plugin add` is left for
# `omarchy plugin remove jmartin.hypertile`, which also works when this script
# is run from inside it.
#
# Usage: ./uninstall.sh [--purge]

set -euo pipefail

purge=0
for arg in "$@"; do
  case "$arg" in
  --purge) purge=1 ;;
  -h | --help)
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "uninstall.sh: unknown option: $arg" >&2
    exit 2
    ;;
  esac
done

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
config="${XDG_CONFIG_HOME:-$HOME/.config}"
hypr="$config/hypr"
bin="$HOME/.local/bin"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hypertile"
plugin_id="jmartin.hypertile"
plugin_dst="$config/omarchy/plugins/$plugin_id"

PYTHONPATH="$src/session" python3 - "$state" <<'PY_PREFLIGHT'
from pathlib import Path
from upgrade import check_legacy
import sys
check_legacy(Path(sys.argv[1]))
PY_PREFLIGHT

# Stop the writer before removing its code; retain recovery snapshots unless
# --purge was requested. A missing/stopped service is harmless.
if [[ -x "$bin/hypertile-session" ]]; then
  "$bin/hypertile-session" stop >/dev/null 2>&1 || true
fi
if [[ -x "$bin/hypertile-stream" ]]; then
  "$bin/hypertile-stream" stop >/dev/null 2>&1 || true
fi

if [[ -x "$bin/hypertile-scenes" ]]; then
  "$bin/hypertile-scenes" stop >/dev/null 2>&1 || true
fi

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
import sys
path, pid = sys.argv[1], sys.argv[2]
lines = open(path).read().split("\n")
lines = [l for l in lines if not (l.lstrip().startswith('"layouts"') and pid in l)]
lines = [l for l in lines if not any(
    l.strip() == '"system.%s": {"action":"hypertile-ctl session %s"}%s' % (a, a, comma)
    for a in ("logout", "reboot", "shutdown") for comma in ("", ","))]
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
rm -f "$bin/hypertile-session" "$bin/hypertile-scenes"
for module in service scene_recovery upgrade; do
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile/session/$module.py"
done
for module in scene_service apps ipc scenes browse; do
  rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile/scenes/$module.py"
done
echo "removed the engine files and hypertile-ctl"

if (( purge )); then
  rm -rf "$hypr/layouts" "$state"
  rm -f "$config/hypertile/scenes.json"
  for service in session scenes; do
    rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/hypertile/$service/__pycache__"
  done
  echo "removed layouts, state, saved scenes, and Python caches"
else
  echo "kept layouts, state, and saved scenes (use --purge to remove them)"
fi

# Shell plugin.
shell_up=0
if command -v omarchy-shell >/dev/null 2>&1 && omarchy-shell -q shell ping 2>/dev/null; then
  shell_up=1
  omarchy-plugin-disable "$plugin_id" >/dev/null 2>&1 || true
fi
if [[ -d "$plugin_dst" && ! -d "$plugin_dst/.git" && "$(cd "$plugin_dst" && pwd -P)" != "$src" ]]; then
  rm -rf "$plugin_dst"
  echo "removed the shell plugin copy at $plugin_dst"
elif [[ -d "$plugin_dst/.git" ]]; then
  echo "disabled the shell plugin; remove the checkout with: omarchy plugin remove $plugin_id"
elif [[ -d "$plugin_dst" ]]; then
  echo "disabled the shell plugin; remove $plugin_dst by hand"
fi
(( shell_up )) && { omarchy-shell -q shell rescanPlugins || true; }

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
