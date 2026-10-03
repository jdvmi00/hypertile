# Crash when mirrored displays disappear

See the [validation record](VALIDATION.md) for installed package details,
reproductions, successful checks and remaining hardware-validation limits.

The tower's October 3 crash entered `CMonitor::setMirror()` from
`CMonitor::onDisconnect()` with a null `this` pointer. The instruction at
`setMirror+331` read offset `0x520` through zero in `r12`; the caller had passed
zero in `rdi`. The saved crash report is
`~/.cache/hyprland/hyprlandCrashReport698027.txt`. The installed package was
`hyprland 0.56.2-3.2` (source commit
`efb50993780079460b0cbed1363e2166a2de1d9f`).

This is a compositor monitor-lifetime defect. The crash does not establish a
connection to overlapping screen coordinates or the NVIDIA modesetting bug.
Hypertile's placement correction and the driver patch address different paths.
The later shutdown crash also needs separate evidence before assigning it the
same cause.

## Correction

The [patch](hyprland-0.56.2.patch) corrects mirror teardown:

- Detach a disconnected mirror from its source even when it is disabled.
  Previously the disabled-output early return skipped that cleanup.
- Traverse a snapshot of the source's mirror list. `setMirror("")` erases from
  the original vector, invalidating a loop over that vector.
- Lock each weak reference before use and promote only surviving mirrors
  still attached to this source. Clear stale entries after teardown.
- Erase by value when detaching, avoiding `erase(end())` if an entry is absent.
- Choose the replacement display after promoting mirrors, so the surviving
  display receives the disconnected source's workspaces and windows.

These changes leave the existing source-promotion and size-ack fixes in place.
They do not change Hypertile's layout settings or monitor mode selection.

## Build and validate

The [PKGBUILD](PKGBUILD) produces `hyprland 0.56.2-3.3` with all three local
corrections. In a fresh build directory, copy:

- This PKGBUILD and this patch renamed `mirror-disconnect.patch`.
- `../mirror-outputs/hyprland-0.56.2.patch` renamed `mirror-outputs.patch`.
- `../size-acks/hyprland-0.56.2.patch` and `../size-acks/verify.py`.

Run `makepkg --log` as the normal user. Source hashes, patch hashes and zero-fuzz
application are required by the recipe. Use the new recipe only for this exact
version; review newer official sources before carrying it forward.

From the Hypertile checkout, with a live Wayland parent, `g++`, `pkg-config`,
`foot`, and matching Hyprland development headers:

```sh
python3 test/mirror_outputs_integration.py --fixed --binary /path/to/Hyprland
```

The runner compiles [virtual-output-control.cpp](virtual-output-control.cpp)
inside its temporary directory and loads it only into its private nested
compositor. It rejects physical outputs and requires a test environment flag.
This is necessary because 0.56.2's `hyprctl output remove` searches only active,
independent monitors. It can reply `output not found` with a successful process
exit, which made the old mirror-removal test a no-op. Every removal now checks
that the output actually disappears.

The regression covers real mirror removal/reconnection, source handoffs,
saved reloads, disabled-mirror teardown and promotion of multiple mirrors.
The same Wayland client must survive the complete sequence. Select just one
new failure path with `--disconnect-case disabled`, `--disconnect-case expired`
or `--disconnect-case multiple`. The disabled fixture calls the compiled
`setMirror()` on an output that is already disabled, matching the observed
desktop state. The expired-reference fixture inserts a null weak reference
before destroying the source, exercising the precise failure boundary without
depending on when the backend releases the last reference.

`--fallback-cycle` additionally removes every desktop output and tries both
reconnection orders. On this machine the nested backend enters fallback but
then reports GBM buffer-allocation failures; replacement outputs fail to map
or have zero-sized modes. That broader backend check is not a passing result
of this repair. A physical Dell power/input cycle after starting the patched
desktop remains necessary to validate the full hardware path.
Also run the compiled size-ack check in `../size-acks/README.md` and the existing
`test/display_integration.py` handoff regression against the staged binary.

On package `0.56.2-3.2`, the null-reference fixture reproduced `setMirror+331`
(`Hyprland+0x731d4b`), the same instruction as the overnight crash. The disabled
fixture crashed in `IHyprRenderer::damageMirrorsWith()` after removal, before
the next source disconnect. The two-mirror test left one surviving output
without a `wl_output` global. These are separate checks of stale-reference
cleanup, null-reference handling and iterator safety.

Preserve the previous package for rollback. After validation, installation via
pacman affects the next desktop session. A configuration reload cannot activate
this change. The updated `../size-acks/hypertile-backport-status` checks the new
package-owned marker alongside the older fixes and dependency record. Official
updates remain free to replace the local package; nothing is pinned.
