# Missing Wayland outputs after changing the mirror source

The [validation record](VALIDATION.md) covers the tested package, deployment,
regressions, artifact hashes and activation status.

Hyprland 0.56.2 can promote a display that connected as a mirror without
advertising its `wl_output` global. Its monitor IPC still reports valid geometry.
When the previous source becomes a mirror, no output remains available to
Wayland clients: the shell's launcher and wallpaper disappear and Hypertile
cannot open normally. Restarting the shell does not fix the missing global.

## Cause and correction

In upstream commit `efb50993780079460b0cbed1363e2166a2de1d9f`, the monitor-added
callback in [`ProtocolManager.cpp`](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/managers/ProtocolManager.cpp)
returns for a mirror before registering its `modeChanged` listener. However,
`CMonitor::onConnect()` applies its mirror rule before emitting monitor-added.
Promotion emits `modeChanged` with no listener to recreate the global.

[The patch](hyprland-0.56.2.patch) registers that listener for all connected
outputs, keeping globals suppressed for mirrors. It also removes the listener
on disconnect even when that output never had a global. It preserves the
existing handling of bound resources on retired globals.

## Hypertile protection

`displays/wayland.py` opens a separate, short-lived Wayland connection and reads
connector names from core `wl_output` version 4. It requests no surfaces or
input and requires no added Python dependency or native build step. A bounded
deadline covers connection, registry enumeration and output readback.

The display adapter checks these names against the independent displays.
Transactions check their baseline, every newly applied independent output,
the complete preview, Keep, and the saved configuration reload. In particular,
the source handoff stops before moving workspaces or demoting the original
source if the promoted output is absent. The existing transaction journal
restores previous geometry, assignments, and files. Recovery checks outputs
too and retains its journal if they remain unavailable. No automatic output
disable/re-enable is used as a workaround.

## Build the local package

For source-disconnect protection as well, use the newer combined
[mirror-disconnect recipe](../mirror-disconnect/README.md).

The [PKGBUILD](PKGBUILD) builds `hyprland 0.56.2-3.2`, based on Arch's
`0.56.2-3` recipe, with both this fix and the existing size-ack backport.
It retains the separately packaged `hyprpm`, current recipe dependencies,
release optimizations, and the local builds' disabled LTO/debug packages.

Use a fresh build directory; copy this PKGBUILD, this patch as
`mirror-outputs.patch`, and `hyprland-0.56.2.patch` plus `verify.py` from
`../size-acks/`. Run `makepkg --log` as the normal user. The recipe checks
source and patch hashes, applies patches with zero fuzz, and runs the
size-ack source regression. Do not install this older version over a newer
official package without reviewing that package's source and dependencies.

Keep the previous package for rollback. Install the validated package through
pacman, then install `../size-acks/hypertile-backport-status` under
`~/.local/bin/` to extend the existing post-update and post-boot checks to both
fixes. Each fix has a package-owned patch and version marker. Official updates
can replace the local package normally; no package or library is pinned.
If an update removes the markers, inspect the exact upstream source and test
it before retiring or rebasing the patches.

Installation changes the binary for the **next desktop session**. Save your
work and log out/in when convenient; a config reload cannot activate it.

## Regression checks

From the repository root, with a live Wayland parent:

```sh
python3 test/wayland.py
python3 test/displays.py
python3 test/display_configuration.py
# Installed unpatched compositor: prove guarded rollback and the original bug.
python3 test/mirror_outputs_integration.py
# Newly built compositor: prove source handoffs and reconnects work.
python3 test/mirror_outputs_integration.py --fixed --binary /path/to/built/Hyprland
```

The integration test uses a nested compositor, private config/runtime/state,
virtual outputs, and a disposable client. It tests a display connected as a
mirror, source promotion, saved reload, repeated switches, and mirrored
disconnect/reconnect. It checks both IPC and a fresh Wayland registry and
verifies that the existing client survives. It never changes physical output
settings. Run the existing isolated compiled size-ack check against the new
binary as well before installing the combined package.
