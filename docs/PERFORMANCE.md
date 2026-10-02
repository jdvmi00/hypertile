# Performance audit

Evaluated `develop` at `35e5294` and the local optimizations based on it on
omarchy-tower (Ryzen 9 5950X), with Lua 5.5.1 and Hyprland 0.56.2. The installed
runtime matched that revision before testing. The desktop had one active
display, two workspaces, and four application windows.

## Runtime baseline

A 30-second quiet-desktop sample from `/proc` showed:

| Process | CPU, percent of one core | Resident memory | Disk bytes written |
| --- | ---: | ---: | ---: |
| Hypertile displays | 0.100% | 22.46 MiB | 0 |
| Hypertile scenes | 0.033% | 17.77 MiB | 0 |
| Hypertile session | 0.033% | 18.82 MiB | 0 |

The services were already inexpensive at idle. These CPU counters exclude
short-lived child processes. The compositor and shell are shared with the
rest of the desktop: their CPU/RSS cannot be attributed entirely to Hypertile.
No long-duration leak or end-to-end frame-pacing conclusion follows from this
short sample.

After applying the changes and closing the verification overlay, a second
30-second sample measured the three daemons at approximately **0.07% of one
core and 58.4 MiB combined**, again with no disk reads or writes. At this low
CPU usage, counter granularity and sampling noise are substantial; use the
repeatable provider benchmarks below to assess the optimization, not the
difference between two idle samples.

## Changes

1. **Repeated tree scans in layout placement.** With a deeply nested layout
   and occupancy near the bottom, each ancestor scanned the same descendants
   again. Occupancy is now memoized for one traversal, so these scans are
   linear in tree size. Each placement gets fresh occupancy.
2. **Unchanged destination geometry.** Every provider recalculation also
   rebuilt all uncollapsed navigation boxes. These now remain cached per
   workspace until area, size overrides, or the compiled spec changes.
   In-place weight edits, deletions, reset, hot swap, and workspace cleanup
   are covered by regression tests. Actual window placement still runs on
   every callback, and the cache contains no compositor-owned userdata.
3. **Closed-window pins retained for the whole login.** Session snapshots now
   remove pins and exclusive pins whose windows no longer exist, including
   entries on inactive layouts. Live windows retain their pins across layout
   and workspace changes. Cleanup runs when snapshots run; disabling all
   snapshot consumers also disables this periodic cleanup.
4. **Unneeded preference resolution for the bar.** The bar now requests
   `hypertile-ctl workspaces --json --live`, which returns compositor fields
   without reading/resolving saved layout sources. The normal command retains
   its existing metadata. This avoids launching the display catalog merely
   to resolve inherited preferences that the bar does not display.
5. **Duplicate display queries.** Policy reconciliation now uses one fresh
   monitor snapshot for both topology and identity resolution. An empty
   display policy performs no compositor query. The snapshot stays local to
   the reconciliation; later transactions query again. An unused scene-state
   read was also removed. Full slots are checked before evaluating match
   patterns in the placement loop.

## Measurements

`lua test/performance.lua [source-directory]` benchmarks the provider with
table-based compositor targets. Results below are medians of five batches,
using the same workload against the original and modified engine. GC remains
enabled. These are Lua CPU costs, not application resize or rendered-frame
latencies.

| Workload | Before | After | CPU time reduction |
| --- | ---: | ---: | ---: |
| Welcome, 4 windows | 18.25 µs | 14.68 µs | 20% |
| Ultrawide, 4 windows | 14.92 µs | 12.27 µs | 18% |
| Quad, 4 windows | 22.98 µs | 16.45 µs | 28% |
| Quad, 64 windows | 92.74 µs | 83.92 µs | 10% |
| 150-level sparse tree, 1 window | 2167.15 µs | 203.05 µs | 91% |

The sparse-tree case is deliberately adversarial. Normal layouts were already
measured in tens of microseconds; the improvement does not imply a comparable
increase in desktop FPS.

On the live desktop, 25 workspace-query samples gave approximately 12.8 ms
for the full query and 12.0 ms for `--live`. With temporary saved preferences
that exercise monitor inheritance, 15 samples gave medians of 81.7 ms and
12.4 ms respectively. That test changed only temporary preference files, not
the desktop's saved layout or display configuration.

## Resolved follow-up findings

**Pathological placement rules:** native `string.find` could block the
compositor. The original `a*a*a*a*b` pattern against 128 `a` characters exceeded
a two-second timeout. Placement now uses `hypertile-pattern.lua`, an explicit
matcher with bounded backtracking, scanning, and capture comparisons. It
retains Lua pattern syntax, including captures, backreferences, frontiers, and
balanced pairs. Literal rules use a native plain-string fast path. Patterns
compile once per layout, with repeated patterns sharing the compiled form.

Each field match receives at most 8,192 work units, and all matches in one
assignment share 32,768 units. Patterns are limited to 1,024 bytes and subjects
to 8,192 bytes. Exceeding a limit skips that match; unmatched windows still
receive normal placement. A warning identifies the pattern once per compiled
layout. The next assignment gets a fresh budget; pins retain precedence.
These are deterministic work limits, not a real-time scheduling guarantee.
The formerly hanging 128-byte case now returns in about **0.92 ms**; assignment
of 64 adversarial windows takes about **3.72 ms** total (medians of five batches).
Normal four-window provider costs remain approximately 12–17 µs.

**Installed Omarchy wallpaper compatibility:** the original adapter rejected
the newer `BackgroundMedia` and native-image-size renderer. The adapter now
supports it while retaining asynchronous decoding, native-size caps, prepared
theme transitions, and custom-image failure fallback. Spans decode for their
whole logical area and screen scale. Inactive old/incoming frames have empty
sources, and fixed custom images release transition frames when a theme reveal
finishes. Unknown upstream integration points still fail before activation;
locally edited clones remain protected.

## Additional tuning considerations

- **Status polling scales with monitor count.** Each bar creates a
  `SessionStatus` reader, launching the CLI every five seconds. Sharing one
  reader through the plugin service could avoid duplicate processes on
  multi-monitor setups. The measured single-monitor idle load does not
  justify redesigning the status transport in this change.
- **Background safety polls and catalog refreshes still have a cost.** The
  session takes a reconciliation snapshot every five seconds; the display
  watcher polls every five seconds and faster while guarding display sleep.
  The open overlay polls its scene catalog every two seconds. Preserve
  recovery, preview leases, and wake safety when changing these intervals.
  Benchmark multi-scene/multi-monitor workloads before consolidating them.
- **Do not reintroduce resize/reload storms.** Keep the existing cycle and
  preview debounce, unchanged-write suppression, and unwatched workspace-rule
  storage. Synchronous child processes or durable writes do not belong in
  the layout recalculation callback.

Correctness checks include engine geometry, cache invalidation, navigation,
bridge/CLI output, display policy, session/scene recovery, and an isolated
real-compositor drag and workspace test. See the
[root README](../README.md#development) for the complete test commands and
`test/performance.lua` for repeatable measurements.

The changes were applied with `./dev apply`. Hyprland reported no configuration
errors, all nine loaded layouts had the new cache, the session service was
watching without errors, and the live overlay displayed the current layout
correctly. The overlay was closed again after verification.

The wallpaper compatibility failure originally reproduced on unmodified
`35e5294` is covered by the follow-up fix. `test/pattern.lua` compares over
10,000 small inputs against native Lua and exercises shared-budget exhaustion;
the engine harness checks safe placement after exhaustion. Wallpaper tests
cover both renderer generations and managed-clone upgrades. The opt-in
`test/wallpaper_integration.py` exercises the installed renderer in an isolated
compositor, including decode sizing, fit/span, transitions and broken images.
ShellCheck runs through an isolated `shellcheck-py` tool because the system has
no `shellcheck` executable. The Windows-only Remote Desktops CI job was not run
on this Linux host.

Follow-up validation passed all 32 Lua, JavaScript and Python regression suites,
plus the isolated native-drag and two-output wallpaper tests. The updated
runtime was applied locally; all nine live layouts use compiled matchers and
the compositor returned a bounded failure for the adversarial pattern without
configuration errors. The session service remains watching. The existing
custom background clone is disabled, so it was left disabled; the updated
adapter regenerates it on the next Apply wallpaper action.
