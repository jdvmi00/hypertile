# Carrying the mirror fixes to Hyprland 0.57.2

Omarchy's update replaced the local `hyprland 0.57.1-2.1` with its own
`hyprland 0.57.2-2`, which has neither Hypertile backport. Between 0.57.1 and
0.57.2, `Monitor.cpp`, `Monitor.hpp` and `ProtocolManager.cpp` are unchanged:

| Backport | 0.57.2 | Action |
|---|---|---|
| [mirror-outputs](../mirror-outputs/README.md) | Not fixed. The monitor-added handler still returns for mirrors before registering `modeChanged`. | Carried unchanged |
| [mirror-disconnect](../mirror-disconnect/README.md) | Not fixed. `onDisconnect()` is identical to 0.57.0. | Carried unchanged |

Both `hyprland-0.57.0.patch` files apply to 0.57.2 with zero fuzz, after
Omarchy's three patches; the last mirror-disconnect hunk moves two lines.

## Recipe

The [PKGBUILD](PKGBUILD) is the [0.57.1 recipe](../hyprland-0.57.1/README.md)
moved to Omarchy's `0.57.2-2` (omacom/omarchy-pkgs commit `781dfa36`). It
produces `hyprland 0.57.2-2.1`. Omarchy changed only the version and source
hash; its three patches are still byte-identical to the copies in
`../hyprland-0.57.0/`. As before, the recipe drops the `hyprpm` split package,
and Omarchy's next release replaces this build, so `hypertile-backport-status`
asks for review again.

In a fresh build directory, copy this PKGBUILD, the three Omarchy patches
from `../hyprland-0.57.0/`, `../mirror-outputs/hyprland-0.57.0.patch` renamed
`mirror-outputs.patch`, and `../mirror-disconnect/hyprland-0.57.0.patch`
renamed `mirror-disconnect.patch`. Run `makepkg --log` as the normal user.
Then run the mirror regression against the staged binary before installing.

## Validation

Against Omarchy's stock `0.57.2-2`, `test/mirror_outputs_integration.py`
passes in its default mode: Hypertile refuses the unpatched promotion, and a
direct unguarded handoff leaves zero `wl_output` globals.

Against the staged `0.57.2-2.1` binary, `--fixed` passes all four checks:
startup mirror, handoffs, reload, reconnect and promotion; disabled mirror
then source disconnect; null mirror reference; and promotion of both mirrors.
The package carries both markers at `0.57.2-2.1`, and its dynamic libraries
resolve. A physical Dell power or input cycle still validates the hardware
path.
