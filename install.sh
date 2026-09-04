#!/usr/bin/env bash
# Install hypertile into an Omarchy system.
#
# The Omarchy shell loads the overlay and the bar widget straight from this
# directory (the plugin). Everything else has to be put where Hyprland and the
# shell expect it, which is this script's job:
#
#   ~/.config/hypr/hypertile.lua           engine
#   ~/.config/hypr/hypertile-json.lua      JSON module (bridge)
#   ~/.config/hypr/hypertile-bridge.lua    bridge library
#   ~/.config/hypr/hypertile-layouts.lua   loader for layouts/*.lua
#   ~/.config/hypr/layouts/<name>.lua      one file per layout (only if missing)
#   ~/.local/bin/hypertile-ctl             CLI
#   ~/.config/omarchy/plugins/jmartin.hypertile/
#                                          the shell plugin: a copy of manifest.json
#                                          and plugin/ when this is a development
#                                          checkout somewhere else; nothing when this
#                                          script already runs from that directory
#                                          (omarchy plugin add put it there)
#   + the bar widget after the workspaces (only if not already on the bar)
#   + a "Layouts" menu entry and keybinds (only if absent; see --no-menu, --no-keybinds)
#
# Then makes sure hyprland.lua requires the loader, reloads, and checks for
# config errors. Every config file it edits is first copied to
# <file>.hypertile.bak. Existing layout files are never overwritten. Safe to
# run again after `omarchy plugin update jmartin.hypertile` or a git pull.
#
# Usage: ./install.sh [--no-keybinds] [--no-menu]

set -euo pipefail

want_keybinds=1
want_menu=1
for arg in "$@"; do
  case "$arg" in
  --no-keybinds) want_keybinds=0 ;;
  --no-menu) want_menu=0 ;;
  -h | --help)
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "install.sh: unknown option: $arg" >&2
    exit 2
    ;;
  esac
done

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
config="${XDG_CONFIG_HOME:-$HOME/.config}"
hypr="$config/hypr"
bin="$HOME/.local/bin"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hypertile"

for tool in lua jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "install.sh: $tool is required" >&2; exit 1; }
done
[[ -e "$hypr/hyprland.lua" ]] || { echo "install.sh: $hypr/hyprland.lua not found; is this an Omarchy 4 (Lua config) system?" >&2; exit 1; }

mkdir -p "$hypr/layouts" "$bin" "$state"

# One backup per edited config file, overwritten on each edit.
backup() {
  cp "$1" "$1.hypertile.bak"
}

for f in hypertile.lua hypertile-json.lua hypertile-bridge.lua hypertile-layouts.lua; do
  install -m 0644 "$src/$f" "$hypr/$f"
done
install -m 0755 "$src/bin/hypertile-ctl" "$bin/hypertile-ctl"

for f in "$src"/layouts/*.lua; do
  name="$(basename "$f")"
  if [[ ! -e "$hypr/layouts/$name" ]]; then
    install -m 0644 "$f" "$hypr/layouts/$name"
    echo "added layout $name"
  fi
done

# ---------------------------------------------------------------- shell plugin
plugin_id="jmartin.hypertile"
plugin_dst="$config/omarchy/plugins/$plugin_id"

if [[ -d "$plugin_dst" && "$(cd "$plugin_dst" && pwd -P)" == "$src" ]]; then
  # Running from the installed plugin itself (omarchy plugin add, or a clone
  # straight into the plugins directory). The shell reads it in place.
  echo "shell plugin runs from $plugin_dst"
elif [[ -d "$plugin_dst/.git" ]]; then
  echo "install.sh: $plugin_dst is a git checkout managed by omarchy plugin;" >&2
  echo "  update it with: omarchy plugin update $plugin_id" >&2
  echo "  then run: $plugin_dst/install.sh" >&2
  exit 1
else
  # A development checkout elsewhere: copy what the shell loads.
  mkdir -p "$plugin_dst/plugin"
  install -m 0644 "$src/manifest.json" "$plugin_dst/manifest.json"
  for path in "$src"/plugin/*; do
    install -m 0644 "$path" "$plugin_dst/plugin/$(basename "$path")"
  done
  find "$plugin_dst/plugin" -maxdepth 1 -type f | while read -r installed; do
    [[ -e "$src/plugin/$(basename "$installed")" ]] || rm -f "$installed"
  done
  echo "copied shell plugin to $plugin_dst"
fi

if command -v omarchy-plugin-validate >/dev/null 2>&1; then
  omarchy-plugin-validate "$plugin_dst" >/dev/null || echo "warning: plugin manifest did not validate" >&2
fi

shell_up=0
if command -v omarchy-shell >/dev/null 2>&1 && omarchy-shell -q shell ping 2>/dev/null; then
  shell_up=1
  # The shell only learns about a new plugin directory after a rescan.
  omarchy-shell -q shell rescanPlugins || true
fi

# The shell tracks a plugin by one entry: in the bar layout (which also
# enables the overlay) or in the plain plugins list. A plugin already listed
# there is enabled without a bar slot, so the entry is dropped and the plugin
# re-enabled with a placement. That happens only while the widget is off the
# bar; one the user has moved stays where they put it.
shell_json="$config/omarchy/shell.json"
if (( shell_up )) && command -v omarchy-plugin-enable >/dev/null 2>&1; then
  if [[ -e "$shell_json" ]] &&
     ! jq -e --arg id "$plugin_id" '[.bar.layout // {} | .[] | .[]? | .id] | index($id)' "$shell_json" >/dev/null 2>&1; then
    omarchy-plugin-disable "$plugin_id" >/dev/null 2>&1 || true
    if omarchy-plugin-enable "$plugin_id" --section left --after omarchy.workspaces >/dev/null; then
      echo "added the layout widget to the bar after the workspaces"
    else
      echo "warning: could not enable $plugin_id (run: omarchy plugin enable $plugin_id --section left)" >&2
    fi
  else
    omarchy-plugin-enable "$plugin_id" >/dev/null || echo "warning: could not enable $plugin_id (run: omarchy plugin enable $plugin_id)" >&2
  fi
elif (( ! shell_up )); then
  echo "shell not running; enable the plugin later with: omarchy plugin enable $plugin_id --section left --after omarchy.workspaces"
fi

# The shell caches compiled QML for on-demand panels; a rescan does not
# refresh it, so changed overlay code needs a shell restart to take effect.
# A hash of the plugin files, kept in the state directory, says whether
# anything changed since the last install.
plugin_hash="$(cat "$src/manifest.json" "$src"/plugin/* | sha256sum | cut -d' ' -f1)"
hash_file="$state/installed-plugin.sha256"
if [[ ! -e "$hash_file" || "$(cat "$hash_file")" != "$plugin_hash" ]]; then
  if (( shell_up )); then
    omarchy restart shell >/dev/null 2>&1 || true
    echo "restarted the shell to load the updated plugin"
  fi
  echo "$plugin_hash" >"$hash_file"
fi
echo "installed shell plugin $plugin_id (toggle: omarchy-shell shell toggle $plugin_id)"

# ------------------------------------------------------------- menu entry
# SUPER+SPACE > Layouts.
menu_ext="$config/omarchy/extensions/omarchy-menu.jsonc"
if (( want_menu )) && [[ ! -e "$menu_ext" ]]; then
  echo "note: $menu_ext does not exist, skipped the menu entry"
elif (( want_menu )) && ! grep -q "\"layouts\":.*$plugin_id" "$menu_ext"; then
  if command -v python3 >/dev/null 2>&1; then
    backup "$menu_ext"
    python3 - "$menu_ext" "$plugin_id" <<'PY'
import sys
path, pid = sys.argv[1], sys.argv[2]
text = open(path).read().rstrip()
entry = '  "layouts": {"icon":"󱂬","label":"Layouts","description":"Show and switch tiling layouts","action":"omarchy-shell shell toggle %s"}' % pid
close = text.rfind("}")
if close == -1:
    sys.exit(0)
head = text[:close].rstrip()
# Add a comma if the previous significant line is an entry rather than "{" or a comment.
lines = [l for l in head.splitlines() if l.strip() and not l.strip().startswith("//")]
prev = lines[-1].rstrip() if lines else "{"
if not (prev.endswith("{") or prev.endswith(",")):
    head += ","
open(path, "w").write(head + "\n" + entry + "\n}\n")
PY
    echo "added Layouts to the Omarchy menu"
  else
    echo "note: python3 not found, skipped the menu entry (add one to $menu_ext by hand)"
  fi
fi

# --------------------------------------------------------------- keybinds
# Each skipped if already present. SUPER+ALT+L toggles the overlay; SUPER+L
# cycles the workspace's layout, replacing Omarchy's dwindle/scrolling toggle,
# which cannot return to a hypertile layout; SUPER+SHIFT+L cycles the other
# way. Every block starts with a "-- hypertile" comment so uninstall.sh can
# find it again.
bindings="$hypr/bindings.lua"
if (( want_keybinds )) && [[ -e "$bindings" ]]; then
  if ! grep -q "Layouts overlay" "$bindings"; then
    backup "$bindings"
    cat >>"$bindings" <<LUA

-- hypertile: fullscreen layout overlay (browse with arrows, Enter uses and closes).
o.bind("SUPER + ALT + L", "Layouts overlay", "omarchy-shell shell toggle $plugin_id")
LUA
    echo "bound SUPER+ALT+L to the overlay"
  fi
  if grep -q "Toggle workspace layout" "$bindings" && ! grep -q "hypertile-ctl cycle" "$bindings"; then
    echo "SUPER+L is already bound in bindings.lua, left alone"
  elif ! grep -q "hypertile-ctl cycle" "$bindings"; then
    backup "$bindings"
    cat >>"$bindings" <<'LUA'

-- hypertile: cycle the workspace through every saved layout, then dwindle.
-- The shell flashes the new layout's name.
hl.unbind("SUPER + L")
o.bind("SUPER + L", "Toggle workspace layout", "hypertile-ctl cycle")
LUA
    echo "bound SUPER+L to cycle layouts"
  fi
  if ! grep -q "hypertile-ctl cycle --reverse" "$bindings"; then
    backup "$bindings"
    cat >>"$bindings" <<'LUA'

-- hypertile: cycle the other way.
o.bind("SUPER + SHIFT + L", "Toggle workspace layout (back)", "hypertile-ctl cycle --reverse")
LUA
    echo "bound SUPER+SHIFT+L to cycle layouts backwards"
  fi
fi

# ------------------------------------------------------------ hyprland.lua
main="$hypr/hyprland.lua"
if ! grep -q 'require("hypr.hypertile-layouts")' "$main"; then
  backup "$main"
  # Insert after the bindings require so layouts load before looknfeel.
  sed -i 's|^require("hypr.bindings")$|require("hypr.bindings")\nrequire("hypr.hypertile-layouts")|' "$main"
  grep -q 'require("hypr.hypertile-layouts")' "$main" || echo 'require("hypr.hypertile-layouts")' >>"$main"
  echo "hyprland.lua now requires hypr.hypertile-layouts"
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
else
  echo "Hyprland is not running; the config changes take effect at the next start"
fi

echo "installed. try: hypertile-ctl list"
