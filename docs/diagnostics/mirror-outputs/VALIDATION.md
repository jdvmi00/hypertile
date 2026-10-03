# Validation — 2026-10-02

## Installed result

Built and installed `hyprland 0.56.2-3.2` on omarchy-tower. The package includes
the existing size-ack correction and the mirror-output listener fix. The running
desktop was left untouched and still uses the previous executable until the
next logout/login. Physical display switching with the new executable therefore
remains a post-login check; the compositor regressions below used isolated
virtual outputs.

Hypertile's output checks were deployed with `./dev apply` on branch
`fix/mirror-output-registration`. Its status reports no pending components;
Hyprland, the shell, and the session watcher respond. The live Displays pane
reports DP-1, the mirror group, 4608×1920 logical desktop size, and no error.

The updated `hypertile-backport-status` recognizes both package markers and
unchanged tracked dependencies. Its only warning is that the running desktop
binary differs from the installed binary. Existing post-update and post-boot
hooks call this checker; no package or library holds were added.

## Evidence

- All four source/patch inputs passed their recipe SHA-256 checks; patches
  applied with zero fuzz.
- Size-ack source regression: original 1,189/4,950 failures; patched 0/4,950.
- Six protocol/timeout tests, 93 display transaction tests, 41 configuration
  tests, 42 display safety tests, 35 placement tests, 20 policy tests, and the
  display JavaScript suite passed.
- Development helper, upgrade and installer suites passed (5 + 2 + 28 tests).
  ShellCheck passed for the changed checker and the installer/uninstaller.
- Unpatched compositor: guarded promotion rejected before surrendering the
  original source; original app, workspace placement and config preserved.
  Direct unguarded promotion reproduced zero `wl_output` globals.
- Patched compositor: startup as a mirror, repeated guarded source switches,
  saved reloads, mirrored disconnect/reconnect, and subsequent promotion passed.
  The existing test client survived every transition.
- Broader handoff integration passed at 1280×720 and 960×540, including native
  modes, all workspaces/windows, focus, resizing, saved reload, switching back,
  injected save failure and independent watchdog recovery after process death.
- The packaged binary passed the isolated compiled size-ack check: retained
  both future records and acknowledged the expected final 2218×1246 size.
- The package retains every path from `0.56.2-3.1`, adding only the two
  mirror-output marker files. Dynamic dependencies resolve. Packaged, staged
  and installed binaries match. `pacman -Qkk hyprland`: 642 files, zero altered.

The integration setup now waits for both nested host windows to map before
floating/resizing them. This removes a test race where the second output could
still be tiled by the real desktop and change size during a transaction.

## Artifacts and rollback

Build inputs, logs, test logs, package and staged files:
`/home/jmartin/Work/hyprland-mirror-backport-20261002/`.

The previous package is preserved at
`/home/jmartin/Work/hyprland-sizing-backport-20260920/hyprland-0.56.2-3.1-x86_64.pkg.tar.zst`.
Its executable was verified byte-for-byte against the installed binary before
the upgrade. The previous status checker is saved as
`hypertile-backport-status.before` in the new build directory.

SHA-256:

```text
package: fe2ce29cf2e7e3dfd73175840b970fefc0f2d6f0f8c98109efceab1a85ed41d3
installed /usr/bin/Hyprland: d8bb777922939924e734450fdb3c0afa52b87b8acc624aa71cf0a1738b7e9d45
mirror patch: 7e64443a703fabb0c6197ba96b10e3315f585f1575adacc7a912e144cb3b6729
```
