# Remote desktop and scene implementation checks

Implementation and local installation: 2026-09-04. Usage and limitations are in
[STREAMS.md](STREAMS.md). This records what was exercised; the full hardware
acceptance matrix is not implied by the automated tests.

## Automated checks

- 36 Python stream tests: configuration and paired identity, serialized launch
  cancellation, repeated requests, process ownership, restart reconciliation,
  delayed workspace creation, retained unresolved sources, offline local session
  recovery, bounded retries, close/EOF ordering, display rollback and conflicts,
  nominal refresh rounding, host-health handling and private log extraction;
  source swap persistence, lost-reply recovery, cancellation, stale identities,
  two-source exchanges and rejection of old-compositor window references.
- Lua stream adapter checks: reservations, overflow, collapsed empty zones,
  workspace isolation, final-window identity, targeted placement without focus,
  temporary window rules and release; source/local and source/source swaps,
  subsequent local swaps, uncapped fill, overflow and stale-target rejection.
- Directional navigation checks include routing managed swaps through the source
  controller while retaining native swaps for ordinary unpinned local windows.
- Existing tests: 14 Python session tests, 3 development-helper tests, Lua session
  adapter, 136 engine checks, 132 bridge/CLI checks, 32 geometry checks and 110
  editor checks.
- ShellCheck on install/uninstall, Python/Lua syntax validation, plugin validation,
  and a live Hyprland reload without configuration errors.

## Live results

| Exercise | Result |
| --- | --- |
| Mac connection | Final Moonlight window in the requested zone, normal tiled state, visible desktop and keyboard input. |
| Windows connection | Paired desktop rendered in a second requested zone; external display management reported. |
| Repeated/concurrent connect | Four concurrent Mac requests returned the same operation and PID. |
| Background connection | Mac connected to workspace 1 while a local terminal remained active on workspace 2; workspace stayed 2 throughout startup and placement. |
| Controller update/reload | Repeated updates and Hyprland config reloads retained existing Mac/Windows PIDs; no duplicate streams. |
| Session capture | Both source references were saved; zero managed Moonlight windows appeared in generic app recovery. |
| Mac mode transaction | Original mode persisted before a change; requested and actual mode read back; restoration returned the original mode. |
| Manual mode change | Disconnect preserved the different mode and retained a restoration conflict. The test then returned the display to its original mode and cleared the journal through `restore`. |
| Normal window close | Both hosts disconnected and released their reservations. Mac host-mode restoration completed and cleared its journal. |
| Existing Mac launcher | Updated to call the managed controller; used to reconnect the final Mac session. |
| Pointer scaling | With HiDPI off, a measured local pointer offset mapped to the expected Mac coordinates. |
| Source swap | In the active quad layout, the Mac and local terminal exchanged zones and swapped back through the directional shortcut handler. The reservation and saved source assignment followed the Mac; all other window positions and focus remained unchanged. |
| Restart after swap | Restarting the controller while the Mac was in its new zone retained that assignment and Moonlight PID. Swapping back restored the original arrangement. No host-mode or journal change. |

The tested client is Moonlight Qt 6.1.0. The Mac runs Sunshine
2026.516.143833 and BetterDisplay 4.3.4. Its physical Dell display is connected
with AC power. The final Mac profile has a 1920×1080 logical/rendered desktop,
2560×1440 stream, HEVC, 60 FPS, 60 Mbps, SDR, standard chroma and absolute input.
The Windows profile requests 2560×1600 with the same video baseline; host display
settings are externally managed.

Two compatibility issues changed the implementation:

1. BetterDisplay UUID-only queries also returned a default display group.
   Physical display operations now explicitly include `type=Display`, and
   activity is checked with CoreGraphics. The `connected` getter failed on this
   installation and is not used.
2. Nominal 60 Hz modes sometimes read back as 59.95 Hz. Mode comparisons allow
   less than 0.15 Hz variation while recording actual values. Resolution and
   HiDPI must still match. On the tested Sunshine build, HiDPI absolute input
   produced a 2× pointer offset; the default profile keeps the same readable
   logical size with HiDPI off. A relative-input HiDPI profile is optional.

## Still requiring hardware validation

- Deliberate network interruption and recovery, host sleep/wake, and a full
  compositor logout/restart. Their controller failure/recovery paths are covered
  by controlled tests; live config reload is not the same as compositor restart.
- Opening/closing the Mac lid during a managed transaction, battery-only use,
  and removing the Dell. Earlier prototype lid-closed evidence does not establish
  those additional combinations.
- Relative-input HiDPI behavior, Windows modifier/clipboard behavior, audible
  audio routing, Teams camera/microphone use and virtual displays. Mac modifier
  and clipboard results are recorded below.
- End-to-end latency and sustained presentation measurements. A3's short Mac
  decoder summaries below provide limited frame-loss evidence.
  `window-ready` and decoder initialization deliberately do not claim verified
  frame presentation.

One fill zone must remain available for local windows. The background test used
an actual local window: Hyprland can remove a transient empty workspace when a
startup window disappears. The Mac display adapter currently uses an approved
SSH multiplex session; future connections need that session or independently
configured noninteractive SSH authentication. The active stream does not require
continuous SSH connectivity to keep rendering.

## A2 scenes and everyday controls

Implemented and installed locally on 2026-09-04. See [SCENES.md](SCENES.md).

Automated checks add 22 Python scene/input/audio tests, Lua scene adapter checks,
and JavaScript Content/identity checks. They exercise stable IDs, renamed and
missing references, queued rename handling, duplicate computer/app rejection,
Empty reservations, local app ambiguity, retained client movement, profile
switching, supersession, explicit disconnects, controller restart, offline
partial application, baseline restoration, clipboard capability gating, optional
system-key capture, and muting only the owned client's audio. All existing
stream, session, navigation, engine, bridge, editor, geometry and development
helper suites also pass. A session restoration argument-order error found during
integration is fixed and covered by a regression check. Lua scene layout changes
apply directly in the compositor; rule-file persistence runs in the controller,
avoiding recursive compositor IPC.

| Live exercise | Result |
| --- | --- |
| Save/apply current desktop | Saved `desktop` using persistent layout and leaf identities. Applying it retained the existing Mac client. |
| Directional swapping with a saved scene | Reproduced the A2 zone-ID regression, fixed assignment validation, and tested the actual keyboard swap handler down and back in the active quad layout. Both windows moved; focus, unrelated windows, client PID, host journal and saved scene contents stayed unchanged. Regression tests cover scene state, restart, and stale zone identities. |
| Content picker movement | Moved the Mac to another quad zone through overlay IPC, then applied `desktop` to restore it. The same PID and host journal were retained. |
| Empty and local app | On a temporary workspace, reserved an Empty zone and assigned its unique local terminal to another zone; the main desktop and Mac connection were unaffected. Restore removed the reservation and the temporary window was closed. |
| Controller/config updates | Reconciled scene content and retained ready client ownership across service updates and Hyprland reloads. |
| Profile switch | Switched the Mac between desktop and desktop-capture, with display restoration before relaunch, then reapplied the saved desktop scene. |
| Statistics | The overlay shortcut displayed Moonlight's statistics over the actual stream; a second invocation hid them. |
| Mac Command key | With desktop-capture and capture activated, physical Super+A selected the temporary document’s text and replacement typing replaced all of it. Merely focusing a newly opened client did not activate capture. |
| Mac ordinary modifiers | Option+Left moved by a word in a temporary TextEdit document; a physical Shift key event produced uppercase input. |
| Mac clipboard typing | Failed in a temporary document. Confirmed the installed Sunshine version's macOS Unicode input method is unimplemented. The CLI rejects the action and Content displays the reason. |
| Host-headset audio | Process-specific muting and missing-output handling tested with controlled audio objects. Candidate meeting profiles configured; audible playback and a real call remain unverified. |

Mac input checks used disposable local TextEdit documents, synthetic text, and
conditional clipboard restoration. No Teams content or call was inspected or
started. The temporary documents were removed. Automatic clipboard sharing is
not implemented.

The clipboard limitation is in the
[tested Sunshine Mac implementation](https://github.com/LizardByte/Sunshine/blob/v2026.516.143833/src/platform/macos/input.cpp).
[Moonlight's shortcut implementation](https://github.com/moonlight-stream/moonlight-qt/blob/v6.1.0/app/streaming/input/keyboard.cpp)
sends that UTF-8 text path and drops GUI/Command keys when system-key capture is
inactive. This is distinct from ordinary key input and from the client receiving
a shortcut.

A representative Teams call must still verify camera, microphone, host-headset
or continuous playback, focus changes, and echo. Windows shortcut/clipboard and
live audio-policy checks, the A1 hardware checks above, and a complete compositor
restart remain outstanding. These limitations are not inferred from desktop
video readiness or the presence of an audio stream.

## A3 interaction and quality

Implemented and installed locally on 2026-09-04. See
[STREAM-QUALITY.md](STREAM-QUALITY.md) for collection semantics and controls.

Automated coverage adds 14 Python quality/reconnect tests, Lua identity/focus
checks and JavaScript metric formatting checks. They cover typed summary
parsing, truncated/invalid output, unsupported versions, monotonic timing,
bounded history, exact profile/size matching, idempotent reconnect, cancellation,
controller restart, late logger output, compositor recovery identity, scheduled
collection and unchanged retry backoff. Existing stream, scene, session,
navigation, engine, bridge, geometry, editor and development checks pass.

| Live exercise | Result |
| --- | --- |
| Baseline reconnect | 17.56 s from accepted request to the final window being placed, using one-second transition polling. |
| Faster transition polling | Two repeats at 200 ms polling took 13.72 s and 13.79 s. Assignment, profile and original host restoration journal were retained. |
| Scheduled collection | A 30-second collection survived a controller update and completed; a second 10-second collection also completed. Each briefly reconnected only the local view. |
| Decoder summaries | Average decode 0.11 ms in both summaries; rendered 59.97 and 59.93 FPS. Network frame loss 0.27% and 0.51%; jitter loss 0% and 0.03%. RTT 3 ms in both. |
| Return locally | Focused the stream, then returned to the same local terminal with input capture released. |
| Readability | Synthetic text in a disposable Mac TextEdit document, Menlo 14 point, was legible in the current 2218×1246 tile. Recorded as readable for this profile and size; the document was removed and the previous Mac app restored. |
| Performance UI | Expanded the panel on the live Mac source and checked metric labels, wrapping, collection controls and readability choices; no QML errors. |
| Swap regression after installation | Swapped the focused local window and Mac right and back through the actual directional handler. Focus, other windows, client PID, profile and host journal were unchanged. Restored the scene's unmodified state with identical saved bytes. |

The approximately 3.8-second improvement is a small local comparison, not a
statistical guarantee or a network-recovery measurement. In the first faster
run, stages reached preflight at 0.52 s, preparing at 1.61 s, launch at 2.20 s,
connecting at 2.47 s and window-ready at 13.72 s. Paired identity, power and
display checks still ran; most remaining startup time was in Moonlight.

The decoder summaries cover activity since their decoder segment began, not
just the scheduled 10/30-second wait. Queue delay was 0.01 ms; rendering was
1.37/1.34 ms. The tested host did not supply host-processing latency. Pure
encoding and end-to-end latency remain unavailable. The second frame-loss
result suggests comparing bitrate under the same workload; it does not justify
an automatic change or a new preset.

No client fork or patch was needed. Physical pointer-edge behavior, relative
capture, Windows quality, sustained workloads, sleep/network recovery and call
hardware still need their separate checks. No Teams content or call was read
or started during this validation.

## Layout browsing with assigned content

Fixed and validated on 2026-09-05. Layouts browsing now moves the actual windows
on a workspace with scene assignments or a connected stream. The controller
holds the original layout while a temporary preview is active, so reconciliation
does not mistake the preview for a deleted stream zone. Closing the overlay or
returning to Scenes restores the committed layout; saved source references and
host settings are unchanged.

Eight Python tests cover preview/cancel, late requests, heartbeat expiry,
controller restart, superseding scenes, disconnect, checkpoint protection and
restoration failures. JavaScript tests exercise the overlay's actual managed and
ordinary browsing routes, serialization and teardown. Existing suites pass.

Live checks on the active quad layout moved both local windows and the Mac view,
kept a preview alive through heartbeats, returned through the Scenes tab, and
rapidly selected layouts before immediately closing. The exact initial window
positions returned. Focus, stream PID, assignment, operation, profile, journal,
saved scenes and workspace rule files were retained. Restarting the controller
during a live preview also restored the original layout before cleanup, retaining
the same Mac client process.

## Windows display recovery

Implemented and installed on the work laptop on 2026-09-05. The Windows console
helper owns display topology, with Sunshine's display automation disabled. The
desktop and meeting profiles use the managed Windows adapter. See
[Windows display recovery](WINDOWS-DISPLAY-RECOVERY.md) for setup and operation.

| Live exercise | Result |
| --- | --- |
| Connect and disconnect | The dedicated virtual display was the only active output during streaming at 2560×1600. Disconnect restored the built-in panel at 1920×1200, disabled the virtual output and cleared the local recovery journal. The user confirmed the panel lit. |
| Delayed cancelled preparation | Replaying a cancelled preparation was rejected with `operation-cancelled`; the physical display stayed active. |
| Recovery without the controller | Paused the Linux controller and terminated its Moonlight client. The laptop helper restored the internal panel without receiving a restore request. The Linux journal still contained the original preparation until the controller resumed and reconciled it. |
| Closed lid, then undock | Started from the Dell-only desktop with the lid closed. While streaming, the user unplugged the dock. Disconnect left recovery pending because Windows exposed no physical display. Opening the lid automatically restored the built-in panel at 1920×1200, disabled the virtual display and cleared the journal. The user confirmed the screen came back. |

Eight Python tests cover ownership, acknowledgement loss, verified restoration,
transport identity, and continued recovery after disconnect or failure. Eighteen
checks on Windows PowerShell 5.1 cover display selection, Sunshine connection
events and atomic journal replacement; the native display wrapper compiled and
its read-only console inventory succeeded. Existing stream, scene, quality,
placement and development checks pass.

The connection parser was checked against this laptop's Sunshine build
2026.516.143833. It counts connection events separately from stream-worker slots,
so an old disconnected worker does not prevent a subsequent recovery. Unknown
activity blocks restoration. Normal window-close handling is covered by the
controller tests; the live offline test exercised client termination. Pre-login,
lock-screen, sleep/wake, reboot and a physical network outage still require
separate validation.
