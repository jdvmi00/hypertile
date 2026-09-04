# Hyprland 0.56.2: content smaller than its tile

After changing or saving a layout, a window can have the correct frame but
its content occupies only the upper-left part of it. This is an identified
Hyprland size-acknowledgment bookkeeping bug, separate from directional
navigation across gaps. Changing rounding does not fix it.

The temporary recovery is `hypertile-ctl heal` on the affected workspace
(or `hypertile-ctl heal --workspace 1`). It shrinks the tiles by one pixel
and restores them 120 ms later to request a fresh size. Recovery does not
prevent recurrence.

The [investigation](diagnostics/size-acks/README.md) contains measured live
state, the root cause, source links, and the executable regression. In
0.56.2, `CWindow::onAck` reads a cutoff through an iterator while erasing
from the same vector. Vector compaction changes the cutoff and can discard
a newer size record. The [one-line backport](diagnostics/size-acks/hyprland-0.56.2.patch)
captures the acknowledgment serial by value instead.

The [2026-09-04 validation record](diagnostics/size-acks/VALIDATION.md) records
the built and installed package, regression results, isolated compositor test,
and artifact hashes. The normal desktop still needs a new session to activate
a newly installed compositor.

## Scope and upstream status

This recipe is specifically for **Hyprland 0.56.2**, commit
`efb50993780079460b0cbed1363e2166a2de1d9f`, using Arch packaging revision
`0.56.2-1`. It produces **`hyprland 0.56.2-1.1`** with no epoch, package
hold, or `IgnorePkg` entry. Official `0.56.2-2` and newer versions sort after
this local package. It does not patch Omarchy files or change layouts.

Upstream already corrected this defect as part of the
[August 17 view refactor](https://github.com/hyprwm/Hyprland/commit/af0d014cb26f536d8cb7cab2b9d5784f69767c8a).
The replacement `CWindowConfigureAckTracker::acknowledge` copies the selected
serial and size before erasing records. The correction was verified in
upstream commit `5584938a9fce2a4d6ebc236eb524c1551556815d`; this is not a claim
that a particular packaged release includes it. **Check the package's exact
source before retiring the backport.** A new package version alone is not
proof.

## Build and install the backport

Run from a Hypertile checkout on an Omarchy system using 0.56.2. First inspect
the versions; if they have advanced, follow the update section instead of
installing this older recipe over the new system.

```bash
pacman -Q hyprland
pacman -Si hyprland
hyprctl version
omarchy pkg add base-devel cmake glaze hyprland-protocols meson ninja xorgproto
```

Keep the original signed package for rollback somewhere outside pacman's
pruned cache. For this version, obtain
`hyprland-0.56.2-1-x86_64.pkg.tar.zst` and its `.sig` from your configured
repository mirror (`pacman -Sp --print-format '%l' hyprland` shows its URL),
then verify with `pacman-key --verify /path/to/package.pkg.tar.zst.sig`.
Save both under `~/.local/state/hypertile/backport/rollback/`. If the mirror
has advanced, use a trusted Arch archive rather than an arbitrary binary.

Build as your normal user, not root:

```bash
backport_dir="$HOME/.local/state/hypertile/backport/build"
mkdir -p "$backport_dir"
cp docs/diagnostics/size-acks/{PKGBUILD,hyprland-0.56.2.patch,verify.py} "$backport_dir/"
cd "$backport_dir"
makepkg --log
```

The [PKGBUILD](diagnostics/size-acks/PKGBUILD) derives from the
[Arch 0.56.2-1 recipe](https://gitlab.archlinux.org/archlinux/packaging/packages/hyprland/-/blob/0.56.2-1/PKGBUILD).
It verifies the release archive and local inputs with SHA-256, runs the
regression on the unpatched source, applies the patch with zero fuzz, and
builds the release package. It defaults to eight compilation jobs; set
`HYPERTILE_BUILD_JOBS=4 makepkg --log` on a smaller machine. This local
recipe disables split debug packages and link-time optimization to reduce
build cost; it keeps the release build and the official dependency list.

Expected handler-level regression result:

```text
0.56.2: 1189/4950 failed checks
backport: 0/4950 failed checks
```

Validate the resulting package and install it:

```bash
pacman -Qip ./hyprland-0.56.2-1.1-x86_64.pkg.tar.zst
sudo pacman -U ./hyprland-0.56.2-1.1-x86_64.pkg.tar.zst
```

This is a local package transaction, not a system upgrade. Continue using
`omarchy update` for system upgrades. Do not use `sudo make install`, install
an overriding binary in `/usr/local/bin`, or disable package integrity checks.
The local package is unsigned; pacman's normal local-package policy permits
it. The original source archive is checked against Arch's recorded checksum.

**Installing the package does not patch the running compositor.** Save your
work and log out/in or reboot to run it. `hyprctl reload` only reloads
configuration. `hyprctl version` still shows upstream 0.56.2, so use the
package marker and running-binary check below to identify this backport.

## Install the update checks

From the Hypertile checkout:

```bash
install -Dm755 docs/diagnostics/size-acks/hypertile-backport-status \
  "$HOME/.local/bin/hypertile-backport-status"
omarchy hook install post-update docs/diagnostics/size-acks/hypertile-size-acks.hook
omarchy hook install post-boot docs/diagnostics/size-acks/hypertile-size-acks.hook
hypertile-backport-status
```

The package owns three files under `/usr/share/hyprland/backports/`:
`size-acks.patch`, `size-acks.version`, and `size-acks.dependencies`. A normal
official replacement removes them automatically. The checker reports a
missing/mismatched marker, changes to the recorded Hyprland library packages,
missing dynamic libraries, and a running executable different from the
installed one. These are package checks, not proof that the visual bug
cannot recur. An unchanged recorded dependency list does not replace testing.

The hooks print the check and show a desktop notification when review is
needed. They **do not hold packages, block updates, rebuild, install, or
restart Hyprland**. Omarchy's post-update hook runs after system packages and
migrations but before AUR updates, so run the checker once more when the
whole update finishes. The post-boot check provides another reminder.

## Every time you update Omarchy

1. Run `omarchy update` normally. Keep your rollback package and this checkout.
2. When it finishes, run `hypertile-backport-status` before accepting a reboot
   or ending the desktop session. Read any update-hook warning too.
3. If the local package and tracked libraries are unchanged, keep using it.
   There is no rebuild requirement for an unrelated Omarchy update.
4. If libraries changed, review the package compatibility and rebuild against
   the updated system as needed. Missing libraries must be resolved before
   restarting the compositor. A version change is a conservative review
   trigger, not proof of an ABI break. Do not pin old libraries to keep an
   old compositor alive. See [Hyprland's build guidance](https://wiki.hypr.land/getting-started/installation/).
5. If an official Hyprland update replaced the backport, inspect that exact
   package's source for the correction described below. If fixed, retire the
   local tooling. If still affected, adapt the patch to the **new official
   package recipe**, test, build, and install it. Do not reinstall this old
   0.56.2 recipe over a newer release just to recover the marker.
6. Save your work and restart the desktop only after the package is ready.
   Verify the new session and repeat your layout-switch/save scenario.

For a rebuild of the same 0.56.2 source against updated libraries, copy the
recipe and run `makepkg --cleanbuild --force --log`, then install the result
again. Refreshing a package without recompiling (`makepkg --repackage`) does
not repair ABI incompatibilities. For a new base version/revision, update
`pkgver`/`pkgrel`, sources, checksums, dependencies, and regression coverage
together. A patch that no longer applies is a reason to inspect the source,
not to force it with fuzz or assume the bug is fixed.

## Once the official package includes the correction

Inspect the source corresponding to the installed or candidate package:

- In the older implementation, the erase cutoff must be captured as a value,
  rather than read through an iterator into `m_pendingSizeAcks` during erase.
- In the refactored implementation, inspect
  `CWindowConfigureAckTracker::acknowledge` in
  `src/desktop/view/window/WindowBackend.cpp`: both selected serial and size
  must be copied before `std::erase_if`. Confirm future records are retained.
- If using git history, ancestry of the upstream correction is helpful, but
  inspect the implementation too. A downstream package may carry an equivalent
  backport without that commit in its ancestry.

Let `omarchy update` install the corrected official package. If already on a
local package of the same upstream version, install the official package
explicitly with `sudo pacman -S hyprland` after the system update. This can
replace a locally higher package revision; inspect pacman's transaction.
Then save your work, restart the desktop, and test layout changes/saving.

After verifying the official package is fixed, remove the temporary checks:

```bash
rm -f "$HOME/.config/omarchy/hooks/post-update.d/hypertile-size-acks.hook"
rm -f "$HOME/.config/omarchy/hooks/post-boot.d/hypertile-size-acks.hook"
rm -f "$HOME/.local/bin/hypertile-backport-status"
```

Keep the investigation/patch as historical documentation; stop applying it
to corrected sources. The `heal` command can remain as manual recovery.
The Super+Arrow and Super+Shift+Arrow navigation helper addresses a separate
gap-navigation issue and should not be removed as part of retiring this fix.

## Rollback

For an immediate rollback on the same compatible library stack:

```bash
sudo pacman -U "$HOME/.local/state/hypertile/backport/rollback/hyprland-0.56.2-1-x86_64.pkg.tar.zst"
```

Save work and start a new desktop session afterward. This restores the original
bug too; use `hypertile-ctl heal` if needed. After substantial system updates,
prefer the current compatible repository package or an Omarchy system snapshot
instead of forcing an old compositor onto newer libraries. Keep the reminder
hooks until the affected package is intentionally replaced with a fixed one,
or remove them explicitly if abandoning the backport.
