# Windows display recovery

The `windows` adapter owns the work laptop's display topology. Sunshine captures
the configured virtual display and encodes video; its `dd_configuration_option`
is disabled so two components cannot race to restore different monitor layouts.
Existing resolution/refresh settings on the virtual display are retained. This
adapter currently manages topology, not arbitrary mode/HDR/scaling changes.

Before connecting, Hypertile records an ownership token locally. A helper in the
Windows console session saves the physical display configuration before making
the capture display the only active output. Reconnects reuse that baseline.
The helper reads back the active display identity before Moonlight launches.

Disconnect and recognized normal window close send a cancellation to the helper.
Restoration keeps any currently active physical screens, removes the owned virtual
screen, or restores the saved physical configuration if its devices are available.
If docking changes invalidate that configuration, it selects an available physical
screen, preferring the built-in panel. With no physical screen available, it keeps
recovery pending and retries every two seconds, including when the lid opens.
It never deliberately applies an empty display configuration.

The helper runs on the laptop independently of SSH. It observes Sunshine's
connection events and waits for all observed clients to leave before restoring.
A connection has 45 seconds to start; an unexpected disconnection has a 15-second
grace period for reconnects. An explicit disconnect requests earlier recovery.
Unknown connection state blocks automatic recovery. An active stream is never
ended solely because an SSH status check fails. The connection-event parser
requires Sunshine's info logging; changing the capture output or re-enabling its
display automation is reported as an ownership conflict.

Only a fresh readback with at least one physical display active and the owned
virtual display inactive clears the Linux recovery journal. While disconnected,
Hypertile polls pending recovery without reconnecting the source. A physical
monitor activated during streaming is reported as a display conflict rather than
silently moving applications to an unseen desktop.

## Setup

Use an already paired Sunshine host and an approved, strict-host-key SSH alias.
The account must be able to install the helper and must have an active console
session. Start with a working physical desktop and no active stream.

```sh
python3 stream/windows_display.py --ssh work-laptop \
  --pairing-uuid PAIRED-SUNSHINE-UUID \
  --output-uuid SUNSHINE-OUTPUT-UUID \
  --capture-hardware MTT1337
```

Setup verifies the Sunshine pairing/capture identities, runs 18 recovery-policy,
connection-event and atomic-journal checks, runs a read-only native display probe
in the console session, and backs up
`sunshine.conf` before disabling Sunshine's display automation. A failed setup
restores that setting if nobody has changed it in the meantime. No SSH, firewall,
VPN, power, or execution-policy settings are changed.

The helper lives in `C:\ProgramData\Hypertile\display`. The scheduled task
**Hypertile Display Recovery** runs as the configured interactive user without
elevation, starts at logon, and also runs on battery. Private requests accept only
`probe`, `status`, `prepare`, and `restore`, with identity checks, expiration,
monotonic sequence numbers and cancellation tombstones. They cannot specify code
or arbitrary commands. `state.json` retains the original snapshot and recovery
state; `status.json` is the current readback. Setup refuses to overwrite an
existing installation; upgrades must first reconcile its journal.

Use the returned `device_id` in each managed profile:

```json
{
  "platform": "windows",
  "ssh": {"alias": "work-laptop"},
  "profiles": {
    "desktop": {
      "display": {"adapter": "windows", "device_id": "EXACT-ID-RETURNED-BY-SETUP"}
    }
  }
}
```

This fragment supplements the existing computer/profile settings. It does not
replace the pairing, title or stream-quality configuration.

## Recovery and removal

`hypertile-ctl stream restore work-laptop` retries an outstanding recovery. The
helper can finish an already-armed recovery without Linux or SSH. It preserves
active physical displays and prevents its virtual display from being left as the
only output after a completed stream.

To remove the Windows helper, first disconnect and verify a working physical
screen and an idle helper. Stop and unregister **Hypertile Display Recovery**,
then restore the backed-up Sunshine display option if it is still the setting
installed by this helper. Preserve other later Sunshine configuration changes.
Retain the recovery journal until the physical display is confirmed working.
Uninstalling Hypertile on Linux intentionally does not disable remote recovery.

Hardware validation must cover normal disconnect, window close, docking changes,
lid close/open and recovery without SSH. Native display API success confirms
Windows' output configuration; the user must confirm the panel actually lights.
Pre-login, lock-screen, sleep/wake and reboot behavior require separate validation.
The adapter assumes one dedicated virtual capture display; additional unmanaged
virtual displays require separate support.
