# Carrying the mirror fixes to Hyprland 0.57.0

Omarchy's update replaced the local `hyprland 0.56.2-4.3` with its own
`hyprland 0.57.0-2`, which has none of Hypertile's backports. Each one was
checked against the v0.57.0 source (commit
`0aa6745f705f2c4b0a5004eb019ef76e5bbdb426`):

| Backport | 0.57.0 | Action |
|---|---|---|
| [size-acks](../size-acks/README.md) | Fixed. `CWindowConfigureAckTracker::acknowledge()` copies the acknowledged serial before erasing. | Retired |
| [mirror-workspaces](../mirror-workspaces/README.md) | Fixed. Workspace restoration moved into `State::Workspace::monitorConnected()`, which `onConnect()` skips for mirrors; `applyMonitorRule()` sets the mirror first. | Retired |
| [mirror-outputs](../mirror-outputs/README.md) | Not fixed. The monitor-added handler still returns for mirrors before registering `modeChanged`. | [Carried](../mirror-outputs/hyprland-0.57.0.patch) |
| [mirror-disconnect](../mirror-disconnect/README.md) | Not fixed. `onDisconnect()` still skips mirror cleanup for disabled outputs, loops over `m_mirrors` while `setMirror("")` erases from it, dereferences unlocked weak references and erases an unchecked `find_if()`. | [Ported](../mirror-disconnect/hyprland-0.57.0.patch) |

The mirror-workspace fix also guarded two focus fallbacks in `onConnect()`.
0.57.0 leaves those unguarded; they only apply when no monitor has focus.

## Recipe

The [PKGBUILD](PKGBUILD) is Omarchy's `pkgbuilds/hyprland` recipe for
`0.57.0-2` (omacom/omarchy-pkgs commit `347f3d79`) with its three patches,
plus the two Hypertile patches. It produces `hyprland 0.57.0-2.1` and drops
the `hyprpm` split package. Keeping Omarchy's patches keeps the headers that
`omarchy-hyprland-titlebars` was built against; that plugin requires only
`hyprland=0.57.0`. Omarchy's next release has a higher `pkgrel` and replaces
this build, and `hypertile-backport-status` then asks for review.

In a fresh build directory, copy this PKGBUILD and the three Omarchy patches,
`../mirror-outputs/hyprland-0.57.0.patch` renamed `mirror-outputs.patch`,
and `../mirror-disconnect/hyprland-0.57.0.patch` renamed
`mirror-disconnect.patch`. Run `makepkg --log` as the normal user. Then run
the [mirror-disconnect regression](../mirror-disconnect/README.md) against
the staged binary before installing.

The updated `../size-acks/hypertile-backport-status` checks only the two
carried markers and the package-owned `dependencies` record.

## Validation

`test/mirror_outputs_integration.py --fixed` needs the parent session's
`HYPRLAND_INSTANCE_SIGNATURE`, `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR`.
[virtual-output-control.cpp](../mirror-disconnect/virtual-output-control.cpp)
builds against both 0.56.2's and 0.57.0's hyprctl command API.

Against Omarchy's stock `0.57.0-2` binary, the run stops at the first
promotion: `hypertile-displays use-display WAYLAND-2` reports that Hyprland
has not made WAYLAND-2 available to desktop apps. The disconnect cases run
only after that passes, so stock 0.57.0 never reaches them.

Against the staged `0.57.0-2.1` binary, all four checks pass: startup mirror,
handoffs, reload, reconnect and promotion; disabled mirror then source
disconnect; null mirror reference; and promotion of both mirrors. A physical
Dell power or input cycle still validates the hardware path.
