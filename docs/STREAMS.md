# Remote desktops

Hypertile manages paired Sunshine desktops as Moonlight windows in named zones.
The user-session controller owns launching, placement, retries and host display
restoration. The layout engine only consumes workspace-specific reservations.

Install with `./install.sh`, or update a development installation with
`./dev apply`. Python 3, Moonlight Qt, and the current Hyprland Lua API are
required. The loader starts one controller per user; commands also start it on
demand. No root service or persistent remote agent is installed.

## Configure computers

Copy [computers.example.json](computers.example.json) to
`~/.config/hypertile/computers.json` and replace the example identities. XDG config,
data, runtime, and state directories are supported. Configuration is version 1.
Pair each host in Moonlight first. Obtain its UUID from Moonlight's `hosts`
section in `~/.config/Moonlight Game Streaming Project/Moonlight.conf`; leave
certificates and keys there. No credentials belong in `computers.json`.

`host` is the preferred address used to check reachability. Launches select the
paired UUID: Moonlight owns certificate verification, discovery and media-path
selection, using its saved addresses. Hypertile does not claim the media traveled
over Tailscale simply because a Tailscale hostname was configured.

Set `title` to the exact final title, such as `MacBook - Moonlight`. The controller
requires that title, Moonlight's class, its owned process and the compositor's
window identity. It does not adopt a manually launched stream. Close that view
before the first managed connection.

For automatic Mac preparation, BetterDisplay must already be running with CLI
integration enabled, and Sunshine must already have screen recording and input
permissions. Configure an approved SSH account with existing host-key trust and
noninteractive authentication. An optional absolute `ssh.control_path` uses an
already authenticated multiplex connection; once it expires the adapter reports
SSH unavailable. SSH passwords and Sunshine admin credentials are not stored.

Find the physical display UUID on the Mac:

```bash
/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay \
  get -type=Display -name='Your display' -identifiers
```

Preflight authenticates an app-list request through Moonlight. The Mac adapter
also checks Sunshine's stored computer UUID over the approved SSH connection
before any display operation. It resolves the display UUID to the current
CoreGraphics display ID and checks that it is active. It verifies the advertised
mode and, when `require_ac` is true,
AC power. `output_name` in `~/.config/sunshine/sunshine.conf` is mapped to that ID;
changing it restarts Sunshine. Display groups and virtual displays are excluded.
The BetterDisplay `connected` getter is not required: physical activity is read
through CoreGraphics. Permission status is reported as unknown until tested in
the stream. No lid/sleep settings are modified.

The three sizes are separate. `display.mode.resolution` is the logical desktop;
`hidpi: true` renders twice as many pixels per dimension. `stream_resolution` is
the encoded video size. Probe and status expose the resolved host mode. For
example, a 1920×1080 HiDPI desktop renders at 3840×2160 and streams at 2560×1440.

Sunshine 2026.516.143833 on the tested Mac produced a 2× absolute-pointer offset
with HiDPI capture. The example uses HiDPI off to keep ordinary absolute clicks
correct while retaining the same logical desktop size. For HiDPI, explicitly
choose `input: relative` and validate captured-pointer behavior; use
Ctrl+Alt+Shift+Z to release capture. `input: absolute` is the default. This is a
host/client compatibility limit, not a reason to silently select another display.

Use `display.adapter: external` for Windows or any host whose display settings
are managed elsewhere. Hypertile reports this explicitly and changes no host
settings. Preparation and restoration are available only with the Mac adapter.

## Use a named zone

```bash
hypertile-ctl computers --json
hypertile-ctl stream probe macbook --profile desktop --json
hypertile-ctl stream connect macbook --profile desktop --zone right --workspace 1
hypertile-ctl stream status macbook --json
hypertile-ctl stream focus macbook
hypertile-ctl stream disconnect macbook
```

Use an existing workspace with a Hypertile layout and an existing, non-spacer
zone name. Omitting `--workspace` uses the active workspace. One fill/cycle zone
must remain available for local windows; the first release rejects assignments
that reserve every fill zone. Reserved zones remain empty while a source is
offline, even with an `empty = "collapse"` layout. Ordinary local overflow,
application rules and pins cannot fill them. Explicit disconnect releases them.

`connect` returns an operation ID and desired state immediately after validation.
It accepts work, which may subsequently fail; inspect `status` for the result.
Repeated connects with the same profile and assignment reuse the operation or
focus its ready window. Use the [Content picker or scene commands](SCENES.md) to move an assignment
or `stream profile COMPUTER --profile NAME` to switch profiles with managed
teardown. A different assignment/profile passed directly to `connect` still
requires disconnect first. Conflicting computers or zone owners are rejected.

**Super+Shift+Arrow** swaps a ready stream with the neighboring window, including
another stream. This updates the reserved zone and saved source assignment while
keeping the same connection, profile and host restoration journal. A local window
exchanged with a stream takes the vacated zone and can be swapped again normally.
Swaps currently require one window in each participating zone; a stacked target,
changed layout, or closed window produces a notification without restarting the
stream. The same shortcut continues to handle ordinary local windows.

Launch rules keep startup windows on the requested workspace without initial
focus or fullscreen activation. Placement targets the final window and never
focuses it; `focus` and repeating a completed `connect` are explicit focus actions.
The stream continues across workspace switches. Small zone changes resize the
local view and do not change the host mode.

`window-ready` means the final window was found and placed. The stock Moonlight
6.1 logs expose negotiation and decoder initialization, but do not prove frame
presentation or remote input. Status therefore says `video_ready: unverified`;
check the visible desktop and keyboard/mouse before relying on it. Raw Moonlight
logs are discarded. Only typed observations (video size, decoder initialization,
termination code, quit) are retained, without request URLs or pairing material.

Moonlight shortcuts include **Ctrl+Alt+Shift+Z** to release mouse capture,
**Ctrl+Alt+Shift+Q** to disconnect, and **Ctrl+Alt+Shift+S** for statistics. System
key capture defaults to `never` so Omarchy shortcuts remain local. A profile can
set `system_keys: always` to forward Command/Windows keys while captured, or
`fullscreen` to enable this only in fullscreen. Toggle capture to use local
shortcuts again. Enter the stream with the pointer or use Toggle capture to
activate capture; focus alone may not activate a newly opened client. A Mac desktop profile with `never` cannot send Command-key
shortcuts through stock Moonlight. Set the computer’s `platform` to `macos`,
`windows`, or `linux` to report platform limits even with external display
management; BetterDisplay profiles also identify a Mac. All launches use
`--no-quit-after`, so disconnecting leaves the host applications running.

## Profiles and lifetime

- `audio: focus` mutes the client when its window loses focus (the default).
- `audio: continuous` keeps client audio playing in the background.
- `audio: host` retains playback on the host and mutes only the owned Moonlight
  process’s local PulseAudio/PipeWire-Pulse sink inputs using `pactl`. Missing
  `pactl` or unrecognized outputs are reported by `audio_health`; absent audio
  streams remain waiting-for-audio. New outputs are checked every five seconds,
  so brief startup playback can precede muting. Audible output and microphone
  routing still require a real call check.
- `keep_awake: visible` sets a targeted Hyprland idle inhibitor while a ready
  source is on a visible workspace. Omarchy's idle service respects compositor
  inhibitors. `always` also uses Moonlight's stream-wide inhibition; `never`
  requests neither. These settings never change the remote host's sleep policy.
- Video defaults are HEVC, 60 FPS, 60,000 Kbps, hardware decode, SDR and standard
  chroma. HDR, AV1, 4:4:4 and higher rates require host/client validation. The
  default aspect policy is fit; stretching is not supported.

A `meeting-headset` profile can copy the desktop settings with `audio: host`
and `keep_awake: always`. Use `audio: continuous` for a `meeting-audio` profile
when listening locally. Keep the camera and microphone attached to the host;
these profiles do not forward local devices or establish meeting readiness.

The Content picker exposes statistics, capture toggle and explicit clipboard
typing. Mac clipboard typing is unavailable with the tested stock Sunshine;
see [scene input controls](SCENES.md) and [live validation](STREAMS-VALIDATION.md).

## Performance and reconnecting

Use `stream reconnect COMPUTER` to restart a ready local view while retaining
its zone, profile and host restoration journal. `stream measure COMPUTER
--seconds 30` collects the completed decoder summary by reconnecting after the
requested interval. The Content picker's Performance panel and `stream quality
COMPUTER --json` show the results. `stream local COMPUTER` returns focus to a
local window on the same workspace. See [quality and interaction](STREAM-QUALITY.md)
for measurement scope, cancellation and capability limits.

## Recovery

Before host writes, Hypertile durably records every original/intended value in
`~/.local/state/hypertile/streams/state.json`. Display mode is a compound setting
(resolution, HiDPI, refresh), restored together. Nominal refresh timings can differ
by less than 0.15 Hz; actual timings are recorded separately from the request.
The adapter compares the current value with the expected value immediately before
writing. Remote operations share a host-side lock, including probes, so a timed-out
write cannot race with a restoration read. A partial preparation
restores changes that happened and retains any unresolved journal. Reconnects
reuse the first baseline. The journal is separate from session snapshots.

Explicit disconnect, recognized normal window close and failed preparation
restore changed settings. If the host is unreachable, the local zone is released
and status reports `restore-pending`. If a value differs from the applied value,
it is preserved as a conflict. Retry restoration or explicitly accept the current
host settings:

```bash
hypertile-ctl stream restore macbook
# Only after disconnect; deliberately forget the outstanding host journal:
hypertile-ctl stream release macbook --keep-host-settings
```

`restore` never reconnects. `release` requires the explicit flag because it gives
up automatic restoration. A new connection is refused while a journal remains.

Reachability failures retry at most three times (2, 5 and 15 seconds), retaining
the zone and original journal. Moonlight's explicit no-video-traffic termination
can retry; unknown exits, pairing/configuration failures, decoder failures and
ambiguous closes stop for attention. No scheduled retry survives a disconnect.
Use `hypertile-ctl stream retry macbook` for a source still assigned to its zone.
Individual SSH steps have a 40-second deadline; the single writer accepts the
next command between steps, so a stalled remote operation can delay a command.
Running Mac sources recheck display identity, capture output and power every
30 seconds. Losing the SSH observation channel marks the source degraded while
its view keeps running; a confirmed missing display or power prerequisite stops
the view and requests restoration.

Controller restart reconciles durable process ownership and in-progress journals.
A launch token, per-job lock and an intent check before exec prevent duplicate
launches after dispatch uncertainty. Intent changes and PID publication share a
lock, closing the gap in which a disconnect could miss a pending launch.
The PID survives exec from the launcher to
Moonlight. `hypertile-stream stop` stops only the controller for updates; views,
intent and journals survive. Start it again with `hypertile-stream daemon`.

Session checkpoints store remote references/profile/assignment independently of
mapped windows and omit managed windows from generic application launching and
matching. Optional remote restoration never blocks local recovery. Existing
controller intent wins over a snapshot, including explicit disconnects. A source
whose zone or workspace layout changed requires attention; it is never silently
assigned elsewhere. The controller supports one active compositor per user.
On compositor restart it waits up to 45 seconds for local recovery to recreate a
workspace. An unavailable restored source stays in durable state even when its
computer definition is missing. Configure it and use `retry`, or disconnect it.

CLI exit status is 0 for successful queries or accepted operations, 1 for failed
requests/prerequisites, and 2 for argument syntax errors. Accepted operations can
later fail; inspect their operation ID and observed state. Uninstall refuses to
remove the recovery code while sources or host journals remain active.

## Validation

```bash
python3 test/stream.py
lua test/stream.lua
python3 test/session.py
lua test/session.lua
lua test/harness.lua
```

The failure tests cover queued cancellation, duplicate requests, controller and
compositor-instance changes, wrong window identity, bounded retries, normal and
ambiguous exits, missing zones, partial writes, crash recovery between write and
readback, nominal refresh rounding, conflict preservation, restoration pending,
private log extraction, and session ownership. Live checks and host-specific
limitations are recorded in [the implementation report](STREAMS-VALIDATION.md);
sleep/wake, lid transitions, network disruption,
remote input, and audio require real host checks in addition to these tests.
