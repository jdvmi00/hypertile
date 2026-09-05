# Milestone A1 implementation checks

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
- Relative-input HiDPI behavior, modifier shortcuts, clipboard, audio routing,
  Teams camera/microphone use and virtual displays.
- End-to-end latency, dropped-frame and sustained presentation measurements.
  `window-ready` and decoder initialization deliberately do not claim verified
  frame presentation.

One fill zone must remain available for local windows. The background test used
an actual local window: Hyprland can remove a transient empty workspace when a
startup window disappears. The Mac display adapter currently uses an approved
SSH multiplex session; future connections need that session or independently
configured noninteractive SSH authentication. The active stream does not require
continuous SSH connectivity to keep rendering.
