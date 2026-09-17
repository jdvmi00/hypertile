# Display release validation — 2026-09-17

Implementation is on `feature/displays-workspaces`. The release is **not yet
published**. The manifest remains 1.3.0 until physical acceptance is finished;
release notes are in the Unreleased section of the changelog.

## Environment

- Hyprland 0.56.2, Arch package `0.56.2-2.1`, commit
  `efb50993780079460b0cbed1363e2166a2de1d9f`, including the documented size-ack backport.
- Omarchy package `4.0.4-1`; NVIDIA rendering.
- Dell U5226KW, connected simultaneously over HDMI-A-1 and DP-1. Both inputs
  report the same EDID serial, exercising explicit connector matching.
- Baseline: 6144×2560 at approximately 120 Hz on both outputs, scale 1.3333334;
  HDMI at 0,0 and DP at 4608,0. Dell input switching used DDC/CI buses 3 and 4.
- Webcam confirmed the DisplayPort input's physical image during the rotated
  1920×1080 test. The panel itself was not physically rotated.

All temporary hardware previews were reverted. Both native modes, original
positions, workspace placement, and the Dell's HDMI input were restored. No
confirmed display preferences were left by the test. Existing session saving
was disabled before testing and remains disabled.

## Automated coverage

Run the existing suites listed in the root README and CI workflow. New suites:

```sh
python3 test/displays.py
python3 test/display_policy.py
node test/displays.js
python3 test/display_integration.py  # requires a running parent Wayland session
```

Transaction tests cover mode/geometry validation, duplicate identity matching,
offline preferences, final-output protection, application failures, independent
watchdog setup, interrupted confirmation, rollback, external changes, unavailable
hardware fallback, writer shutdown, and daemon/CLI state races.

Policy tests cover inheritance precedence, legacy explicit choices, active
scenes, retained placement preferences, manual-move suppression, initial
workspace projection into session recovery, future workspaces, and event order.
Session tests verify that neither automatic nor named snapshots save preview
placement and that restoration publishes its status under the display lock.
Deployment tests verify that an active display writer blocks file replacement.
Installer/uninstaller tests preserve user data and install every service module
before watched Lua files can reload.

The integration runner launches an isolated Hyprland using two nested Wayland
outputs, separate config/state/runtime paths, and no physical outputs. It verifies:

- Real Lua monitor APIs, rotation, compositor readback, and Revert.
- Real workspace moves and restoration of previous placement.
- DPMS sleep/wake readback with unchanged workspace placement.
- Keep and confirmed preferences surviving config reload.
- Display watcher reload handling and interrupted-operation recovery.
- SIGKILL of the display watcher during a preview: the detached 15-second
  watchdog restores geometry while retaining the previous confirmed document.
- Empty workspace inheritance, explicit layout survival through monitor moves,
  clearing an override, future named workspace placement, and manual moves
  remaining under user control without changing focus.

The headless Aquamarine backend could not allocate GBM buffers on this machine
and reported zero-sized outputs. Nested Wayland provides real compositor API
coverage instead; it is not represented as physical display compatibility.

## Physical and interface checks completed

- Enumeration and advertised mode choices for both Dell inputs.
- Duplicate identity requires explicit connector matching.
- DisplayPort: preview 1920×1080 at 60 Hz, scale 1, transform 1; compositor
  readback and webcam verification; restore native mode with zero rollback errors.
- HDMI: 1920×1080 at 60 Hz and scale 1.25 while DP stays at native resolution
  and scale 1.3333334. Diagram reflects logical bounds. Keep/Revert controls
  remain visible at the resulting 1536×864 logical resolution.
- Sleep and wake DP using the actual Lua DPMS dispatcher; workspace locations
  unchanged. Disable DP evacuates workspaces to HDMI; Revert re-enables DP and
  restores placement. Attempting to disable both outputs is rejected.
- Disable HDMI through the Displays UI: confirmation moves to DP. DDC switches
  the physical panel to DP for inspection. Revert restores both outputs and
  workspace placement with no errors.
- Restart the Omarchy shell during an actual display preview: independent timeout
  restores the prior geometry and placement with no rollback errors.
- Actual keyboard input: Tab reaches diagram screens, Right moves one logical
  pixel, and Shift+Right moves ten; Escape closes without applying the draft.
- UI screenshot review at native and 1080p fractional scale: themed controls,
  readable labels, visible inspector scrollbar, pinned confirmation, focus and
  small-diagram label handling. Screenshot: [Displays](../../screenshots/displays.png).
- Live deployment finishes with no Hyprland config errors.

Hardware testing found and corrected two gaps: the obsolete text-dispatch syntax
for workspace/DPMS operations, and cached `hyprctl workspaces` layout names.
Policy verifies layout changes through the existing Lua workspace adapter.

## Independent review and final visual pass

Three subagents independently reviewed the interface, display transaction service,
and workspace policy against the release requirements. Review fixes include:

- Keyboard focus reveals inspector actions and ownership controls; untouched
  fields do not dirty the draft or round exact fractional scales.
- Long workspace names wrap, action widths follow their labels, and ownership
  has a themed checkbox with an explicit keyboard-focus outline.
- Rollback snapshots use live Lua layout names rather than cached IPC values.
- Monitor defaults resolve stable identity even when a different display reuses
  the same connector.
- Keep journals only rules it actually changes, preserves unchanged explicit and
  scene-owned rules, syncs writes before confirmation, and recovers partial writes
  or crashes without promoting an incomplete configuration.

Final focused suites passed: 35 display transaction tests, 14 policy tests,
186 bridge checks, and the display UI helper tests. The isolated compositor suite
passed after the transaction and layout-snapshot changes. Deployment validated
Lua, Python and the plugin, then reloaded with no compositor config errors.

The final screenshot/webcam review covered native resolution, 1920×1080 at 1.25
scale, and confirmation moved to DisplayPort after disabling HDMI. Additional
keyboard-driven screenshots covered long workspace names, lower inspector
controls, and the ownership focus ring. Both the primary agent and UI reviewer
inspected the images. All previews reverted successfully. Webcam perspective
confirms physical presentation; screenshots provide the detailed text/layout
review. Local evidence is retained in
`~/.local/state/hypertile/validation/20260917-displays/` rather than publishing
images of the surrounding desktop.

## Remaining acceptance with Jim

Jim was unavailable and explicitly deferred hands-on checks until his return.
Do these before bumping/publishing the release:

1. Assign a disposable workspace to DP and unplug/replug the DisplayPort cable.
   Verify the preference remains, the workspace stays usable while absent, and
   automatic return does not steal focus or relaunch scene apps.
2. With a genuinely disconnected preferred display and another available
   destination, move its workspace manually. Verify reconnect honors suppression;
   explicitly reapply to restore its preference. A third independent screen is
   needed to exercise this physical topology fully.
3. Unplug an output during the 15-second preview. Verify fallback recovery and
   the displayed recovery explanation, then restore the original cabling.
4. Change a cable's connector where available and verify stable-identity matching;
   identical/ambiguous outputs must require explicit matching.
5. Inspect pointer crossing and drag snapping on independently visible screens,
   ideally including a physically rotated display. The two Dell inputs are two
   compositor outputs of one physical panel, not two independently visible panels.
6. Confirm a real logout/login restores the chosen initial workspaces, layouts,
   and scenes once. Automated recovery and isolated compositor restart tests pass;
   this workstation's live login session was deliberately preserved.

After these checks, follow [RELEASING.md](../../RELEASING.md) to prepare 1.4.0,
run CI on the exact candidate, and obtain release authorization before promotion.
