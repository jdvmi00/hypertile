# Repository workflow

Read [docs/RELEASING.md](docs/RELEASING.md) before changing branches, CI,
release metadata, tags, GitHub settings, or marketplace submissions.

## Branches and preservation

- `main` is the default, stable installation branch. It is frozen at
  `1ba0f8a30526f2148ff46885d67991862ae90f00` for marketplace issue #4893.
  Do not push, merge, rebase, reset remotely, or add even documentation to it.
- Work on feature branches based on `develop`; target pull requests at `develop`.
  Before editing, inspect `git status` and preserve existing uncommitted work.
  Stage only your changes; never discard or commit unrelated user changes.
- Never force-push `main` or `develop`, move published tags, change the default
  branch, disable protection, or bypass CI as a routine fix.
- Moving `main` or removing its freeze requires an explicit release instruction
  from the owner. Ordinary implementation requests authorize development work,
  not a release. Keep `main` locked between releases and throughout review.

## CI and delivery

- `.github/workflows/test.yml` defines the test commands. Keep CI running on
  pushes to `develop` and `main`, and on pull requests.
- Run the relevant suites locally. Before merging, both GitHub checks `test`
  and `windows-display-policy` must pass on the current PR revision. Fix
  failures without weakening or skipping checks. Do not claim an unavailable
  local platform check passed; use its GitHub runner.
- Local runtime installation (`./dev apply`, `./install.sh`) is separate from CI
  and release publication. Do not run these merely to test a workflow change.
- Development CI must never automatically push to `main`, publish a release,
  edit a marketplace issue, or install the plugin on the user's desktop.
- For an explicitly requested release, follow docs/RELEASING.md: prepare all
  content and version changes first, promote once, record the resulting full
  SHA, immediately freeze `main`, and obtain marketplace reports for that SHA.
  A successful GitHub test run is not marketplace approval.
- After approval, keep developing on `develop`. A new `main` commit needs the
  marketplace update process; an existing approval does not cover it.

This file lives on `develop` because adding it to the currently frozen release
would change the exact commit the owner selected. GitHub protection enforces
the freeze independently of this file.
