#!/usr/bin/env bash
# Undo install.sh: the engine files and the loader require line in
# ~/.config/hypr, the CLI, the keybinds and the menu entry it added, and the
# shell plugin's bar entry. Workspaces fall back to Hyprland's default layout.
# Every config file it edits is first copied to <file>.hypertile.bak.
#
# Kept unless --purge is given: your layouts (~/.config/hypr/layouts/) and
# hypertile's state (~/.local/state/hypertile/: workspace rules, overlay
# preferences).
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

# One backup per edited config file, overwritten on each edit.
backup() {
  cp "$1" "$1.hypertile.bak"
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

# Keybind blocks: each is a paragraph whose first line starts with
# "-- hypertile" (see install.sh).
bindings="$hypr/bindings.lua"
if [[ -e "$bindings" ]] && grep -q '^-- hypertile' "$bindings"; then
  backup "$bindings"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$bindings" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
paras = text.split("\n\n")
kept = [p for p in paras if not p.lstrip("\n").startswith("-- hypertile")]
out = "\n\n".join(kept).rstrip("\n") + "\n"
open(path, "w").write(out)
PY
    echo "removed the hypertile keybinds from bindings.lua (Omarchy's SUPER+L is back)"
  else
    echo "note: python3 not found; remove the '-- hypertile' blocks from $bindings by hand"
  fi
fi

# Menu entry.
menu_ext="$config/omarchy/extensions/omarchy-menu.jsonc"
if [[ -e "$menu_ext" ]] && grep -q "\"layouts\":.*$plugin_id" "$menu_ext"; then
  backup "$menu_ext"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$menu_ext" "$plugin_id" <<'PY'
import sys
path, pid = sys.argv[1], sys.argv[2]
lines = open(path).read().split("\n")
lines = [l for l in lines if not (l.lstrip().startswith('"layouts"') and pid in l)]
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
for f in hypertile.lua hypertile-json.lua hypertile-bridge.lua hypertile-layouts.lua hypertile-navigation.lua; do
  rm -f "$hypr/$f"
done
rm -f "$bin/hypertile-ctl"
echo "removed the engine files and hypertile-ctl"

if (( purge )); then
  rm -rf "$hypr/layouts" "$state"
  echo "removed $hypr/layouts and $state"
else
  echo "kept $hypr/layouts and $state (use --purge to remove them)"
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
