# Releases and marketplace approval

## Current release preparation

- Prepared version: **1.1.2**, a fixes release covering the September 10 review.
  Scene recovery, session saving, layout validation/browsing, installer backups,
  overlay input/feedback/readability, and documentation are included. The feature
  proposals from the review are deferred; none is included in this release.
- Published version: **1.1.1**, tag `v1.1.1`, at
  `7e1171579fccbf3ae5493742d843028f4e60b1da`. Remote `main` still points there
  and remains the default branch, locked including for administrators.
- Marketplace state checked on **2026-09-10**: the registry's
  `listingValidatedCommit` is the same 1.1.1 SHA. Initial submission
  [#5181](https://github.com/omacom/omarchy-plugin-marketplace/issues/5181)
  is closed and listed; registry publication was recorded on September 8.
  Issue #4893 is superseded. The next publication is an **update verification**,
  not an edit to the initial submission.
- Prepare and review 1.1.2 on `develop` before a release PR targets `main`.
  The September 10 changelog date is the planned release date; update it before
  promotion if publication moves to another day. No 1.1.2 tag or marketplace
  snapshot exists until the promotion steps below complete.
- Preserve published tags, including `v1.1.1`, `v1.1.0`, `v1.0.1`, and
  `marketplace-1ba0f8a`. Keep agent instructions outside the repository and
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
