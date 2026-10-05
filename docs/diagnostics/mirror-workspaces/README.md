# Workspaces restored onto a mirror after reconnect

On the tower, changing the Dell from PBP (HDMI-1 and Thunderbolt) to HDMI-2
and back left workspace 1 and three windows assigned to DP-1. DP-1 was
mirroring HDMI-A-1, which still displayed workspace 4. Moving workspace 1
onto HDMI-A-1 restored access without changing its layout or closing windows.

The failure reproduced twice in an isolated compositor using installed
Hyprland `0.56.2-4.1`, dwindle, a disposable client and no Hypertile daemon.
It also reproduced in the retained regression with the new recovery policy.
This is separate from the existing missing-output, mirror-lifetime and
NVIDIA modesetting corrections.

## Compositor correction

In `CMonitor::onConnect()` at source commit
`efb50993780079460b0cbed1363e2166a2de1d9f`, mirror setup happens before the
remembered-workspace restoration. The latter unconditionally moves the
connector's former active workspace back and makes it active on the mirror.
Selecting that workspace then fails to change the source's visible desktop.

The [patch](hyprland-0.56.2.patch) permits returning/orphaned-workspace
restoration, remembered-active-workspace restoration and fallback focus only
on independent outputs. Mirror connections retain their remembered state;
an ordinary independent reconnect still restores it. No driver, tiling,
monitor-mode or cable configuration changes are included.

## Hypertile safeguard

`displays/policy.py` examines live mirror relationships during reconciliation.
Any workspace stranded on a live mirror moves to its enabled independent
source, even without a placement preference or with suppressed automatic
return. Valid explicit placement moves take precedence. Recovery preserves
the saved document, follows runtime source changes, and checks move readback.
Named workspaces and scratchpads are included; unavailable sources and
unrelated extended outputs are left alone. Repeated idle events make no
additional move.

## Validation

The new [integration test](../../../test/mirror_workspaces_integration.py)
uses a private nested compositor, configuration, state and disposable client:

```sh
# Prove the old binary fails and the Hypertile safeguard rescues it.
python3 test/mirror_workspaces_integration.py --expect-bug --rescue
# Prove the correction works without a recovery daemon.
python3 test/mirror_workspaces_integration.py --binary /path/to/patched/Hyprland
```

Both checks pass. They verify the same client and workspace layout survive,
ordinary switching works after recovery, and reconnecting as independent
still restores the remembered workspace. The mirror fixture uses a Wayland
output for initial promotion/removal and a headless replacement to keep the
host's window resizing from overriding its mirror rule. The compiled removal
helper is loaded only into the private compositor.

Also passed: 27 workspace-policy tests; the Wayland (6), display transaction
(93), display configuration (54), display safety (42), display placement (35),
session (29) and scene recovery (10) suites; the display JavaScript suite and
Lua session adapter checks. Python compilation, shell syntax and whitespace
checks pass. ShellCheck is unavailable on the workstation.

The existing stable-mode mirror integration runner passes startup mirrors,
repeated source handoffs, saved reloads, reconnect/promotion, disabled-mirror
teardown, null mirror references and multiple-mirror promotion on the staged
binary. Physical Dell cycling on the corrected desktop and complete backend
loss remain separate validation; no logout or live input switching was done.

## Package and activation

The [recipe](PKGBUILD) builds `hyprland 0.56.2-4.2` on Arch's `0.56.2-4` base,
retaining all three previous backports and adding this fourth. For a fresh
build directory copy the recipe, this patch as `mirror-workspaces.patch`,
the sizing patch and `verify.py` from `../size-acks/`, and the output and
disconnect patches as `mirror-outputs.patch` and `mirror-disconnect.patch`.
The recipe checks every input hash and applies patches with zero fuzz.

The built package and logs are in
`/home/jmartin/Work/hyprland-backports-0.56.2-4.2/`. Package SHA-256:
`eac23481c1c27c7074a7680e9c35e5f6d02fd94ff79dae48b37511bfd6290f1c`.
Staged binary SHA-256:
`3a3fdce20af2007d771444e3b0a5e138d88c6380c2160bf5f866ba65acf5a688`.

Both fixes are prepared and tested but not installed: automatic approval
review rejected changing the installed runtime during source development.
Installation needs Jim's explicit approval for the package, recovery policy
and display-watcher restart. Preserve the previous package and policy for
rollback. The compositor correction activates only in a new login session;
a configuration reload cannot activate it. The updated backport status
checker tracks the new package marker and reports a pending session restart.

Queued for upstream review; no PR or message has been published. Refresh
current upstream source and overlapping issues/PRs before proposing the
exact patch for Jim's approval.
