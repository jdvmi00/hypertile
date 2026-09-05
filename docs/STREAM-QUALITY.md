# Stream quality and interaction

The Content picker's **Performance** panel reports connection timing, completed
Moonlight decoder statistics, and explicit readability assessments. Reconnect
and Return locally are available beside the existing stream controls.

```bash
hypertile-ctl stream quality macbook --json
hypertile-ctl stream reconnect macbook
hypertile-ctl stream measure macbook --seconds 30
hypertile-ctl stream readability macbook readable
hypertile-ctl stream local macbook
```

## Collecting evidence

An existing stream needs one reconnect after installing this version to enable
its new logger. `reconnect` gracefully closes only the owned local Moonlight
window, waits for its logger, and starts the same profile in the same zone. It
keeps the reservation and original host restoration journal. Pairing, display,
power and assignment checks still run. Host apps stay open. Repeated requests
during the reconnect reuse the operation; Disconnect or a superseding scene
cancels it. A client that ignores graceful close is terminated after a bounded
wait; its final statistics may then be unavailable.

`measure` schedules this same reconnect after 10–300 seconds of continued use.
The default is 30 seconds. It returns immediately; the controller owns the timer.
Use `quality` to inspect the result. A disconnect, profile change, client exit or
reboot cancels an outstanding collection. Restarting the controller in the same
boot preserves it. The timer never creates another connection after cancellation.

Stock Moonlight Qt 6.1 logs its FFmpeg summary when that decoder is destroyed.
**These are completed decoder-segment statistics, not a live 30-second sample.**
They include activity since that decoder started, potentially before collection
was scheduled. For a repeatable comparison, reconnect, wait for the view to be
ready, use the same document/workload and geometry, then collect. Resizing or
changing display conditions can create a new decoder segment. The report keeps
the latest complete summary, rather than averaging incompatible segments.

The parser accepts only known numeric fields in the expected summary format.
Raw logs, request URLs, clipboard text and screen content are not retained.
Unknown versions, incomplete summaries, absent measurements and invalid values
remain unavailable; they do not become zero. Collection does not toggle remote
debug logging or require a patched Moonlight/Sunshine build.

## Reading the results

| Result | Meaning |
| --- | --- |
| Window-ready time | Monotonic elapsed time from the accepted connect/reconnect request until the owned final window is placed. It does not measure first-frame presentation. |
| Stages/work | Elapsed stage boundaries and time spent doing controller work, useful for separating startup waits from host checks. |
| Decode, queue, render | Moonlight's average decoder, frame queue and rendering times for the completed segment. Rendering includes its V-sync wait. |
| Network RTT | The RTT value reported in the summary, not a capture-to-display measurement. |
| Network/jitter loss | Moonlight's separate percentages for missing network frames and frames discarded by its pacer. |
| Host processing | Reported when supplied by the host; this includes more than encoding and is not renamed “encode latency.” |
| Encoding-only/end-to-end | Unavailable from this telemetry. External testing is still required for end-to-end latency. |

See the [tested Moonlight formatter](https://github.com/moonlight-stream/moonlight-qt/blob/v6.1.0/app/streaming/video/ffmpeg.cpp)
and [Moonlight's metric definitions](https://github.com/moonlight-stream/moonlight-docs/wiki/Frequently-Asked-Questions).

Readability is an explicit assessment: `readable`, `too-small`, or `blurry`.
It applies to the recorded profile settings and view dimensions. Resizing the
window invalidates its use as a current assessment. Check ordinary document
text, code, punctuation and scrolling at your actual zone size; resolution alone
does not establish readability. The UI records your choice without reading the
remote document.

At most 20 runs per computer are kept in the private controller state, with the
latest five exposed in history. Results include requested settings, client
version, view size, observed host mode and timestamps. Completed results used
for advice must match the current settings fingerprint; reusing a profile name
for different settings does not make old results applicable. Advice uses simple
thresholds (over 0.5% loss or decoding longer than one requested frame interval)
to suggest a comparison, and never changes the profile automatically.

## Returning to local input

**Return locally** releases compositor input capture and focuses the last
observed local window on the same workspace. It validates window identity and
never takes focus away from an already focused local app. If that local window
closed, it uses another local window on that workspace. With no local window,
use the existing Toggle capture / Ctrl+Alt+Shift+Z control.

Stock Moonlight absolute input already supports leaving a window with the
pointer; its drag handling deliberately retains mouse input while buttons are
held. Relative input requires explicit capture release. Hypertile adds no global
pointer forwarding, edge polling, synthetic crossing clicks, or automatic focus
switching. The separate keyboard-capture profile remains an explicit choice for
Mac Command/Windows shortcuts. See the
[client input implementation](https://github.com/moonlight-stream/moonlight-qt/blob/v6.1.0/app/streaming/input/input.cpp).

## A3 decisions

Startup and teardown states now poll every 200 ms, while steady streams poll
once per second. This removes measured inter-stage waiting without skipping
host validation, increasing network retry rates, or changing the restoration
transaction. The existing 2/5/15-second network retry backoff and host-health
probe interval are preserved.

No quality presets or automatic profile changes were added. The initial Mac
comparison supports reducing controller wait time; it does not establish a
better codec, bitrate, host mode or meeting policy. Automatic selection would
need repeated comparisons for the relevant host, network, view size and audio
policy, plus a benefit sufficient to justify reconnecting the view. Existing
scene/profile selection stays explicit. The measured improvement uses the stock
client; no upstream patch or fork is needed for it.

The [validation record](STREAMS-VALIDATION.md) contains the live baseline,
comparison and hardware limits. Physical edge-crossing behavior in relative
capture, Windows measurements, and encoding-only/end-to-end measurements remain
separate validation work.
