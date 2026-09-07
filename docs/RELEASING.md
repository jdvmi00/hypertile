# Releases and marketplace approval

## Current candidate

- Repository/default branch: `jdvmi00/hypertile`, `main`.
- Release: `1.1.1`, tagged `v1.1.1` after promotion. The tag and the
  maintainer notes on the submission record the exact promoted commit;
  do not add a commit to `main` merely to record its own SHA.
- Submission: https://github.com/omacom/omarchy-plugin-marketplace/issues/5181
  (initial listing, pending). Issue #4893 is closed and superseded.
- Previous candidate: `25552c2a0ace46d74bff91390811c0ff73671b85` (`v1.1.0`).
  Version 1.1.1 removes `AGENTS.md` from the installable tree. Preserve all
  published tags, including `v1.1.0`, `v1.0.1`, and `marketplace-1ba0f8a`.
- Keep agent instruction files outside the repository and all installed
  plugin contents. The complete repository tree is installed by the plugin
  manager; an ignore rule alone does not remove tracked or local files.

`main` is locked, including for administrators. It remains GitHub's default
branch because marketplace validation and upstream installation resolve it.
Ongoing development belongs on `develop` and feature branches. Scenes and
session recovery are part of this candidate.

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

## Finish the current submission

1. Resolve the release tag to its full SHA, verify remote `main` matches, and confirm both its
   checks passed.
2. Update the existing submission's maintainer notes to describe this exact
   tree, including session recovery, background service, application launch,
   and menu/config changes. Remove stale claims such as no background service.
   Preserve the issue form headings and checklist. Editing the issue triggers
   marketplace validation; do not open a duplicate initial submission.
3. Wait for both the marketplace compatibility report and automated security
   baseline to identify the full candidate SHA (the visible report may
   abbreviate it). Resolve reported blockers before requesting re-review.
4. Ask a marketplace maintainer to review the current evidence and apply
   `approved-and-verified`. Installer capabilities may require manual review.
5. Verify publication completed and the listing snapshot equals the candidate.
   A green local CI run, candidate tag, or retained approval label alone does
   not demonstrate publication. Leave `main` locked after publication.

Any code fix would create a different candidate. Obtain the owner's explicit
instruction before replacing this specifically selected SHA.

## Subsequent releases

1. Obtain an explicit release instruction. Prepare the complete release on
   a branch from `develop`: bump the manifest version beyond `1.0.1`, finish
   changelog/README/dependency and installer disclosures, and pass all CI.
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
5. For an already listed plugin, use the marketplace's Plugin verification
   form, action **Verify and publish a newer upstream commit**, plugin ID
   `jmartin.hypertile`, repository root URL, and full current `main` SHA.
   For an initial listing still pending, update #5181 instead.
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
