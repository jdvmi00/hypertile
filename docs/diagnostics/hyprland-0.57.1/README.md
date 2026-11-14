# Carrying the mirror fixes to Hyprland 0.57.1

Omarchy's update replaced the local `hyprland 0.57.0-2.1` with its own
`hyprland 0.57.1-2`, which has neither Hypertile backport. Between 0.57.0 and
0.57.1, `Monitor.cpp` gains only a max-bpc line in `applyMonitorRule()`, and
`ProtocolManager.cpp` is unchanged:

| Backport | 0.57.1 | Action |
|---|---|---|
| [mirror-outputs](../mirror-outputs/README.md) | Not fixed. The monitor-added handler still returns for mirrors before registering `modeChanged`. | Carried unchanged |
| [mirror-disconnect](../mirror-disconnect/README.md) | Not fixed. `onDisconnect()` is identical to 0.57.0. | Carried unchanged |

Both `hyprland-0.57.0.patch` files apply to 0.57.1 with zero fuzz, after
Omarchy's three patches; the last mirror-disconnect hunk moves two lines.

## Recipe

The [PKGBUILD](PKGBUILD) is the [0.57.0 recipe](../hyprland-0.57.0/README.md)
moved to Omarchy's `0.57.1-2` (omacom/omarchy-pkgs commit `0c7102d`). It
produces `hyprland 0.57.1-2.1`. Omarchy's three patches are byte-identical to
the 0.57.0 copies, so they stay in `../hyprland-0.57.0/`. As before, the
recipe drops the `hyprpm` split package, and Omarchy's next release replaces
this build, so `hypertile-backport-status` asks for review again.

In a fresh build directory, copy this PKGBUILD, the three Omarchy patches
from `../hyprland-0.57.0/`, `../mirror-outputs/hyprland-0.57.0.patch` renamed
`mirror-outputs.patch`, and `../mirror-disconnect/hyprland-0.57.0.patch`
renamed `mirror-disconnect.patch`. Run `makepkg --log` as the normal user.
Then run the mirror regression against the staged binary before installing.

## Validation

Against Omarchy's stock `0.57.1-2`, `test/mirror_outputs_integration.py`
passes in its default mode: Hypertile refuses the unpatched promotion, and a
direct unguarded handoff leaves zero `wl_output` globals.

Against the staged `0.57.1-2.1` binary, `--fixed` passes all four checks:
startup mirror, handoffs, reload, reconnect and promotion; disabled mirror
then source disconnect; null mirror reference; and promotion of both mirrors.
The package carries both markers at `0.57.1-2.1`, and its dynamic libraries
resolve. A physical Dell power or input cycle still validates the hardware
path.
