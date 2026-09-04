# Backport validation, 2026-09-04

Built and installed `hyprland 0.56.2-1.1` on the development Omarchy machine,
replacing official `0.56.2-1`. The currently running desktop was deliberately
left on its original executable; a new desktop session is required to activate
the installed backport there.

Evidence:

- The original 0.56.2 release archive matched Arch's recorded SHA-256.
- The patch applied with no fuzz to source commit
  `efb50993780079460b0cbed1363e2166a2de1d9f`.
- Source-extracted regression: original handler failed 1,189/4,950 checks;
  patched handler failed 0/4,950.
- Release build and package assembly completed successfully.
- An isolated compositor using the packaged binary started, mapped a real
  Wayland `foot` client on a headless output, and passed the compiled-handler
  regression through the temporary diagnostic plugin. Both future records
  were retained and final acknowledgment was 2218 × 1246. The plugin restored
  its touched state and unloaded; the test compositor and client exited.
- The tested staged executable, executable extracted from the final package,
  and installed `/usr/bin/Hyprland` have identical SHA-256 values.
- After installation, `pacman -Qkk hyprland` reported 644 files, zero altered.
- `hypertile-backport-status` found the package marker and matching tracked
  libraries, and reported the expected pending desktop restart. The same tool
  correctly reported an absent backport before installation.
- Omarchy post-update and post-boot reminder hooks are installed in the user's
  configuration. No package pin or `IgnorePkg` entry was introduced.
- The original rollback package's detached signature was verified against
  the system pacman keyring (Caleb Maclennan).

Artifact hashes for this build, not promised bit-for-bit results on other hosts:

```text
hyprland-0.56.2-1.1-x86_64.pkg.tar.zst
7e066d5488ca9f435b93b0f3cd3d46c7fe29af99b9f051038edf46ad0ce05434

usr/bin/Hyprland
f3e9c9cbf11114efe5ffe18bd4e668b1f35cd8d9b2f6d9325937020ca894667a
```

Local build artifacts and logs are retained under
`~/.local/state/hypertile/backport/`: `build/build.log`,
`build/repackage.log`, `headless-check.log`, the local package in `build/`,
and the original package plus detached signature in `rollback/`. The final
repackaging added the dependency record; it did not change the tested binary.

The deterministic compiled-handler check does not reproduce the full visual
Chrome save/reload race. After starting the normal desktop with the new binary,
repeat that workflow and check for recurrence. Follow the
[operations guide](../../HYPRLAND-SIZING-BUG.md) for updates and retirement.
