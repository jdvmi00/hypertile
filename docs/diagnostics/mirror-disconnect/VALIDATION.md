# Validation — 2026-10-03

## Installed result

Installed `hyprland 0.56.2-3.3` on omarchy-tower. It retains the size-ack and
mirror-output registration fixes and adds safe mirror teardown and workspace
transfer after source removal. The existing desktop remains on `0.56.2-3.2`
until logout/login. No live monitor settings or NVIDIA packages were changed.

`hypertile-backport-status` recognizes all three package markers and unchanged
tracked dependencies. Its only warning is the running/installed binary
difference. `pacman -Qkk hyprland` reports 644 files and zero altered files.
The live compositor reports no configuration errors.

## Evidence and checks

- Original core PID 698027: `setMirror+331` dereferences `r12+0x520` with
  `r12 == 0`; the caller is the mirror loop in `onDisconnect()`.
- The null-reference fixture reproduced that exact instruction on `3.2`
  (isolated core PID 1004719). The disabled-mirror fixture also reproduced a
  stale-reference crash, in `damageMirrorsWith()` (isolated core PID 1011405).
- A source with two mirrors left one surviving display without a `wl_output`
  global on `3.2`. The final patch promotes both correctly.
- Checking the original client's monitor exposed another problem: selecting
  the replacement before promotion left the client on monitor `-1`. Selecting
  after promotion transfers its workspace to a surviving output.
- The final packaged binary passes the mirror integration: actual mirror
  destruction/reconnection, repeated source handoffs and saved reloads,
  disabled-mirror removal, a null mirror entry, and two-mirror promotion.
  The original client survives and remains assigned to a live output.
- The final packaged binary passes the handoff integration at 1280×720 and
  960×540, including workspace/window/focus preservation, native modes,
  saved reloads, switching back, injected save failure and watchdog recovery.
- The compiled size-ack check passes against the final packaged binary:
  both future records remain and the final acknowledgment is 2218×1246.
- Python suites pass: Wayland 6, displays 93, configuration 41, safety 42,
  placement 35, policy 20, development helper 5, upgrade 2, installer 33.
  The display JavaScript suite, Python syntax, ShellCheck and shell syntax
  pass. Git whitespace checks pass outside the patch artifact, whose unified
  diff format requires spaces on blank context lines.
- The patch applies to the original 0.56.2 monitor source with zero fuzz.
  Packaging preserves every previous package path and adds only the two
  mirror-disconnect marker files. Dynamic dependencies resolve.

## Scope of validation

The optional `--fallback-cycle` test reaches the no-output fallback state but
cannot complete a full backend reconnect on this machine: the nested backend
reports GBM allocation errors and replacement outputs fail to map or have
zero-sized modes. This remains a separate validation limitation, not a passing
test or a claim that all backend recovery problems are fixed. The targeted
crash checks use the real compiled monitor methods with virtual outputs;
the disabled and null-reference cases use explicit diagnostic fixtures.

A physical Dell power/input cycle must still be checked after logging into
the patched compositor. The separate shutdown crash has not been diagnosed
or claimed fixed by this change.

## Artifacts and rollback

Build inputs, package, staged files, negative-test logs and final validation
logs are in `/home/jmartin/Work/hyprland-mirror-disconnect-20261003/`.
The previous package remains at:

```text
/home/jmartin/Work/hyprland-mirror-backport-20261002/hyprland-0.56.2-3.2-x86_64.pkg.tar.zst
```

The previous status checker is saved as `hypertile-backport-status.before`
in the new build directory. A rollback installs the previous package through
pacman and takes effect on the next desktop session.

SHA-256 of the final artifacts:

```text
package: 1e420ecb49ca7963c1f191fa19d3f67d5acc65e0dcaf0ff49a61b73cc3005389
installed binary: 11259b730199d633b1b598c03255b2b9748fa554cf2a87e1579fc71eb234d9e4
mirror-disconnect patch: de498060711d4430618786ac5fd03ab0a7eaffe4ef577f4c94228f11ad2cf65a
unchanged monitors.lua: 0c49d8f13b523ddcc31870ea6d30489ea64b55bc3a4e1b148ab4940ab051fe2e
```
