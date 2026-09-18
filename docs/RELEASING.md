# Releases and marketplace approval

## Current release state

- Prepared version: **1.4.0** (this manifest). After the authorized promotion
  to `main`, record the merge SHA here, tag it `v1.4.0`, publish the GitHub
  release, and request marketplace update verification through the verify
  form. Until a maintainer approves that request, the listing keeps its current
  snapshot and may read "Update unverified".
- Previous published version: **1.3.0**, tag `v1.3.0`, at
  `20ee1c30823bdc967a7c04402699e58bc744f6eb` (merge of PR #23 into `main` on
  2026-09-15), with a GitHub release. Its marketplace update verification
  [#7073](https://github.com/omacom/omarchy-plugin-marketplace/issues/7073)
  was validated by the bots the same day and was still awaiting maintainer
  approval when 1.4.0 was prepared, so **1.2.0** (tag `v1.2.0`, at
  `2c02a8210780bf503e2d96fafe8e7df0ced753a1`, verified and published on
  2026-09-13 through
  [#6562](https://github.com/omacom/omarchy-plugin-marketplace/issues/6562)
  with no findings) remains the listed snapshot.
- Earlier verifications, kept as historical records: **1.1.2** through
  [#6233](https://github.com/omacom/omarchy-plugin-marketplace/issues/6233)
  on 2026-09-11 (maintainer acceptance of the `installer` capability), and
  the initial submission #5181.
- `main` is the default branch and is locked including for administrators.
  Unlock only for the authorized promotion, then lock it again immediately.
  Keep it fixed while the marketplace reviews and publishes that exact commit.
- Preserve published tags, including `v1.4.0`, `v1.3.0`, `v1.2.0`, `v1.1.2`, `v1.1.1`, `v1.1.0`,
  `v1.0.1`, and `marketplace-1ba0f8a`. Keep agent instructions outside the repository and
  installed plugin contents. CI rejects tracked instruction files; an ignore
  rule alone does not remove local files from a linked installation.

The recorded development environment is Omarchy `4.0.3-1` with the separately
installed Hyprland `0.56.2-2.1` size-ack backport. Its rebuild and isolated
validation are documented under `docs/diagnostics/size-acks/`; release preparation
does not install or rebuild the compositor. Saved scene definitions remain
individual files under `$XDG_CONFIG_HOME/hypertile/scenes/`, not `scenes.json`.

## Development

1. Create a feature branch from current `develop`, preserving existing work.
2. Implement and run relevant tests from `.github/workflows/test.yml`.
3. Push the feature branch and open a PR targeting `develop`.
4. Wait for `test` and `windows-display-policy` to pass, then merge the PR.

The `windows-display-policy` job runs the extracted policy suite from an immutable
Remote Desktops commit on Windows; host code is no longer duplicated here.

Both integration branches require passing checks on an up-to-date PR; no
additional reviewer is required for this solo-maintainer repository. Force
pushes and deletion are disabled. The extra lock on `main` prevents even a
passing development PR from changing the candidate accidentally.

## Promote the prepared release

1. Obtain an explicit release instruction. Prepare the complete release on
   a branch from `develop`: bump the manifest version beyond the latest published
   version, finish changelog/README/dependency and installer disclosures, and pass
   all CI.
2. Merge the preparation into `develop`; open the release PR into `main`.
   Review the complete diff and wait for both required checks on the current
   revision. Do not include unfinished development features.
3. For the authorized promotion only, unlock `main` through branch protection,
   retaining required PRs, status checks, admin enforcement, and force-push/
   deletion restrictions. Merge the release PR, immediately lock `main`
   again, and read back its full resulting SHA and protection settings.
   If promotion fails, restore the lock before doing anything else.
4. Confirm CI on the resulting `main` SHA passes. Tag that exact SHA with the
   matching new version and publish matching GitHub release notes. Never move
   an existing release tag. Do not call the release marketplace-verified yet.
5. For this already listed plugin, use the marketplace's Plugin verification
   form, action **Verify and publish a newer upstream commit**, plugin ID
   `jmartin.hypertile`, repository root URL, and full current `main` SHA.
   Keep the closed initial submission #5181 as historical evidence.
6. Wait for fresh compatibility and baseline reports, then maintainer approval
   and successful publication, all covering that same SHA. Keep `main` frozen
   throughout; continue development elsewhere.

Moving `main` can show `Update unverified` until the new snapshot is approved.
Omarchy's mutable upstream installation command is not bound to marketplace
verification. Tags do not change which commit that command installs.

## References

- https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md
- https://github.com/omacom/omarchy-plugin-marketplace/blob/main/VERIFICATION.md

Recheck these policies before each release; the marketplace workflow can change.
