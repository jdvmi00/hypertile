# Window content remains smaller than its tile

Investigated 2026-09-04 on Hyprland 0.56.2, commit
`efb50993780079460b0cbed1363e2166a2de1d9f`.

For installation, update maintenance, rollback, and retiring the backport,
see the [backport operations guide](../../HYPRLAND-SIZING-BUG.md).

## Finding

`CWindow::onAck` uses an iterator into `m_pendingSizeAcks` as the erase
predicate's cutoff while `std::erase_if` compacts that same vector. A retained
entry can overwrite the element the iterator points to. The cutoff then
changes during the erase, allowing newer size records to be removed.

This is a compositor bookkeeping defect. Rounding does not participate in
Hypertile's placement math. Slower switching, resize nudges, and avoiding
reloads can change its likelihood or recover the display, but do not fix it.

## Live evidence

A temporary, ABI-matched diagnostic plugin read the following fields from the
affected Chrome window. It was unloaded immediately after the read. No sizing
fields or window placements were changed.

| Field | Width × height |
| --- | --- |
| Layout goal / current frame | 2218 × 1246 |
| Last requested size (`m_pendingReportedSize`) | 2218 × 1246 |
| Current surface / buffer size | 2219 × 1247 |
| Current acknowledged size (`m_current.ackedSize`) | 4448 × 2506 |
| Pending acknowledged size | 4448 × 2506 |

The outstanding size-acknowledgment vector was empty and the pending ack update
bit was clear. The client had supplied the appropriately sized buffer, but the
compositor associated it with the larger, intermediate size.

`CSurfacePassElement::getTexBox` treats this as a small client surface and draws
it at `surface size × current frame size / acknowledged size`. These values
produce approximately 1106.5 × 620.0 pixels inside the 2218 × 1246 frame,
matching the screenshot's upper-left content occupying roughly half the width
and height. `CWLSurface::correctSmallVec` returns zero with the default
`m_fillIgnoreSmall`, explaining the upper-left alignment. `sendWindowSize`
returns early because the final requested size is already recorded, so another
placement at the same dimensions does not repair the state.

The saved editor document and layout file both contain `rounding = 20` for
`quad_16_9`. The editor's Save command writes a watched Lua layout file and
explicitly requests a reload. Hyprland reload clears Lua layout providers;
unregistering each provider updates workspace layouts, falling back to the
default algorithm until the requested provider is available again. This
creates intermediate placements. The saved layout is then applied again by
the editor.

The exact protocol event sequence from the original screenshot was not
recorded. Save/reload is a source-confirmed way to create the required resize
sequence, and the saved files show that Save ran; whether the first visible
failure occurred during preview or after Save is not established. The live
size mismatch and the acknowledgment defect are independently verified.

## Deterministic reproduction

Several `setSize` calls before the event-loop callback runs reuse the same
configure serial. The final toplevel size is sent to the client, while the
window's pending vector can contain several entries for that serial.

Consider this queue (serial numbers are illustrative):

| Serial | Requested size | Meaning |
| --- | --- | --- |
| 100 | 900 × 600 | Older configure still awaiting acknowledgment |
| 101 | 4448 × 2506 | Intermediate resize |
| 101 | 2218 × 1246 | Final resize, coalesced into the same configure |

1. Acknowledging 100 selects the first vector element.
2. Erasing that element moves the first 101 entry into its place.
3. The predicate now reads 101 through the iterator, so it erases the second
   101 entry too, losing the final size.
4. Acknowledging 101 associates the client's final-sized buffer with
   4448 × 2506 instead of 2218 × 1246.

Run the regression against an unmodified 0.56.2 source checkout:

```sh
python3 docs/diagnostics/size-acks/verify.py /path/to/Hyprland-0.56.2
```

The runner extracts the actual `CWindow::onAck` method, compiles it against
minimal storage fixtures, and compares its behavior with the one-line
backport. It covers nondecreasing serial queues up to seven entries, duplicate
serials, sequential/skipped/repeated/old acknowledgments, and preservation of
future records. It does not launch or modify a compositor.

Observed output:

```text
0.56.2: 1 future records retained; final ack 4448x2506 (expected 2218x1246)
backport: 2 future records retained; final ack 2218x1246 (expected 2218x1246)
0.56.2: 1189/4950 failed checks
backport: 0/4950 failed checks
```

These are handler-level regression checks. A rebuilt package was also tested
on 2026-09-04 in an isolated compositor using a headless output and a real
Wayland client. The diagnostic called the actual compiled `CWindow::onAck`
with the three-record sequence above: both future records survived, and the
final acknowledged size was 2218 × 1246. It restored all touched state and was
unloaded; the isolated compositor and client then exited. This verifies the
compiled handler, not a full visual reproduction of the original Chrome
save/reload race. Activation in the normal desktop requires a new session.

The [test runner](headless-check.py) uses a private runtime directory and
disables systemd environment/notification updates. Aquamarine 0.14 obtains
its renderer through the parent Wayland connection; that output is disabled,
and the test checks that all active outputs are headless before creating its
client. The [diagnostic plugin](headless-ack-check.cpp) refuses to run without
the test environment flag or a matching compositor ABI. Do not load this
state-mutating diagnostic into your regular desktop.

To repeat against a staged package built with the recipe (from the Hypertile
checkout, within a Wayland session):

```bash
backport_dir="$HOME/.local/state/hypertile/backport/build"
staged="$backport_dir/pkg/hyprland/usr"
g++ -std=c++23 -shared -fPIC -O2 \
  -I"$staged/include" -I"$staged/include/hyprland/protocols" \
  $(pkg-config --cflags hyprland) \
  docs/diagnostics/size-acks/headless-ack-check.cpp \
  -o "$backport_dir/headless-ack-check.so"
python3 docs/diagnostics/size-acks/headless-check.py \
  "$staged/bin/Hyprland" "$backport_dir/headless-ack-check.so"
```

The test also requires `foot`. It is for this exact source/ABI, not a generic
validator for future refactored Hyprland releases.

## Root fix and upstream status

Capture the cutoff by value before vector compaction. The included
[`hyprland-0.56.2.patch`](hyprland-0.56.2.patch) uses the acknowledgment serial
already passed by value to `onAck`. This retains every future entry, including
multiple sizes sharing a future serial. It passes `git apply --check` against
the installed version's source commit.

Upstream already uses a stable cutoff in `CWindowConfigureAckTracker`, introduced
by the [August 17 view refactor](https://github.com/hyprwm/Hyprland/commit/af0d014cb26f536d8cb7cab2b9d5784f69767c8a).
The implementation copies both the selected serial and size before erasing.
This was confirmed at upstream main commit
`5584938a9fce2a4d6ebc236eb524c1551556815d`; it is absent from installed 0.56.2.
The proper resolution is a compositor build containing that correction or the
narrow backport, rather than a Hypertile timing/recovery mechanism.

Relevant upstream source:

- [0.56.2 acknowledgment handler](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/desktop/view/Window.cpp#L1514)
- [Configure coalescing](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/protocols/XDGShell.cpp#L629)
- [Surface rendering](https://github.com/hyprwm/Hyprland/blob/efb50993780079460b0cbed1363e2166a2de1d9f/src/render/pass/SurfacePassElement.cpp#L21)
- [Corrected acknowledgment tracker](https://github.com/hyprwm/Hyprland/blob/5584938a9fce2a4d6ebc236eb524c1551556815d/src/desktop/view/window/WindowBackend.cpp#L19)
