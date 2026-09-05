"""Failure-oriented stream lifecycle checks; no real hosts or compositor."""
import copy
import fcntl
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
import controller as s
import streams as integration
import mac_display

IDENTITY = "12345678-1234-1234-1234-123456789ABC"
MODE = {"resolution": "1920x1080", "hidpi": True, "refresh": 60}
OLD = {"resolution": "2560x1440", "hidpi": False, "refresh": 60}
BUILTIN = "AAAAAAAA-1234-1234-1234-123456789ABC"
PANEL = {"resolution": "1728x1117", "hidpi": True, "refresh": "ProMotion"}


def computer(adapter="external"):
    display = {"adapter": adapter}
    if adapter != "external":
        display.update(uuid=IDENTITY, mode=MODE, require_ac=True)
    return {"host": "laptop.example", "pairing_uuid": IDENTITY, "title": "Laptop - Moonlight",
            "ssh": {"user": "tester"}, "profiles": {"desktop": {"stream_resolution": "2560x1440", "display": display}}}


class Host:
    def __init__(self, adapter="betterdisplay"):
        self.display = computer(adapter)["profiles"]["desktop"]["display"]
        self.current = {"mode": copy.deepcopy(OLD), "output": "1"}
        self.calls = []
        self.error = None
        self.fail_field = None
        self.before_change = None
        self.ac_power = True
        self.topology = {"lid_closed": True, "display_id": "5"}

    def probe(self, pairing=True):
        if self.error:
            raise ValueError(self.error)
        return {"current": copy.deepcopy(self.current), "identity": {"UUID": IDENTITY, "displayID": self.topology["display_id"]},
                "ac_power": self.ac_power, "modes": [MODE, OLD], "topology": copy.deepcopy(self.topology)}

    def remote(self, operation):
        return self.probe(False)

    def change(self, field, expected, value):
        if self.before_change:
            self.before_change(field, expected, value)
        if field == self.fail_field:
            raise ValueError("injected host failure")
        if self.current[field] != expected:
            raise ValueError("restore-conflict")
        self.calls.append((field, copy.deepcopy(value)))
        self.current[field] = copy.deepcopy(value)


class MainHost(Host):
    """Two physical panels with independent modes and one Sunshine output."""
    def __init__(self):
        super().__init__()
        self.display["follow_main"] = True
        self.identity = IDENTITY
        self.panels = {IDENTITY: copy.deepcopy(OLD), BUILTIN: copy.deepcopy(PANEL)}
        self.available = {IDENTITY, BUILTIN}
        self.refreshes = 0

    def switch(self, identity, lid_closed):
        self.panels[self.identity] = copy.deepcopy(self.current["mode"])
        self.identity = identity
        self.current["mode"] = copy.deepcopy(self.panels[identity])
        self.topology = {"lid_closed": lid_closed, "display_id": "5" if identity == IDENTITY else "1",
                         "display_uuid": identity}

    def probe(self, pairing=True):
        observed = super().probe(pairing)
        observed["identity"]["UUID"] = self.identity
        return observed

    def remote(self, operation, **values):
        if operation == "refresh":
            if values["expected_identity"] != self.identity or values["expected"] != self.current:
                raise ValueError("display-topology-changed")
            self.refreshes += 1
            return {}
        return self.probe(False)

    def change(self, field, expected, value, **guards):
        if guards.get("expected_identity", self.identity) != self.identity:
            raise ValueError("display-topology-changed")
        super().change(field, expected, value)
        self.panels[self.identity] = copy.deepcopy(self.current["mode"])

    def for_display(self, identity):
        owner = self
        class Pinned:
            def remote(self, operation):
                if identity not in owner.available:
                    raise ValueError("display-missing")
                result = owner.probe(False)
                result["current"]["mode"] = copy.deepcopy(owner.panels[identity])
                result["identity"] = {"UUID": identity, "displayID": "5" if identity == IDENTITY else "1"}
                result["topology"].update(display_uuid=identity, display_id=result["identity"]["displayID"])
                return result

            def change(self, field, expected, value):
                assert field == "mode"
                if owner.panels[identity] != expected:
                    raise ValueError("restore-conflict")
                owner.panels[identity] = copy.deepcopy(value)
                if owner.identity == identity:
                    owner.current["mode"] = copy.deepcopy(value)
                owner.calls.append(("restore-mode", identity))
        return Pinned()


class Compositor:
    instance = "one"

    def __init__(self):
        self.desktop = {"windows": [], "streams": [], "workspace": "1", "layouts": {}, "monitors": [],
                        "workspaces": [{"selector": "1", "layout": "lua:quad", "visible": False}]}
        self.calls = []
        self.invalid = False
        self.swap_plan = None
        self.swap_error = None
        self.swap_timeout = False

    def snapshot(self):
        return copy.deepcopy(self.desktop)

    def call(self, method, args):
        self.calls.append((method, copy.deepcopy(args)))
        if method == "stream_check" and self.invalid:
            raise ValueError("assignment-invalid: zone missing")
        if method == "stream_assign":
            self.desktop["streams"] = [r for r in self.desktop["streams"] if r["computer"] != args["computer"]] + [copy.deepcopy(args)]
        if method == "stream_release":
            self.desktop["streams"] = [r for r in self.desktop["streams"] if r["computer"] != args["computer"]]
        if method == "stream_swap_plan":
            return copy.deepcopy(self.swap_plan)
        if method in ("stream_swap_apply", "stream_swap_cancel"):
            if method == "stream_swap_apply" and self.swap_error:
                raise RuntimeError(self.swap_error)
            for w in args["windows"]:
                for source in self.desktop["streams"]:
                    if source["computer"] == w.get("computer"):
                        source["zone"] = w["zone"] if method == "stream_swap_apply" else w["before"]
            if method == "stream_swap_apply" and self.swap_timeout:
                raise subprocess.TimeoutExpired("injected lost apply reply", 5)
        return True


class Processes:
    def __init__(self):
        self.alive = None
        self.count = 0
        self.log = {}

    def pid(self, record):
        return self.alive

    def events(self, record):
        return self.log

    def launch(self, record):
        self.alive = 123
        self.count += 1

    def stop(self, record, force=False):
        self.alive = None


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "computers.json"
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": computer()}}))
        self.comp = Compositor()
        self.proc = Processes()
        self.host = Host("external")
        self.now = 100
        self.ctl = self.controller()

    def controller(self):
        return s.Controller(self.root, self.config, self.comp, self.proc, lambda *_: self.host, lambda: self.now)

    def connect(self):
        return self.ctl.command({"command": "connect", "computer": "laptop", "profile": "desktop", "zone": "right"})

    def tick(self, n=1):
        for _ in range(n):
            self.ctl.tick()
            self.now += 1

    def test_queued_disconnect_prevents_launch_and_retries(self):
        accepted = self.connect()
        self.assertEqual(accepted["observed"], "preflight")
        self.assertTrue(accepted["operation"])
        r = self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.assertGreater(r["generation"], accepted["generation"])
        self.tick(8)
        self.assertEqual(self.proc.count, 0)
        self.assertEqual(self.ctl.records["laptop"]["observed"], "disconnected")

    def test_repeated_connect_is_idempotent_and_conflicting_assignment_rejected(self):
        a, b = self.connect(), self.connect()
        self.assertEqual(a["operation"], b["operation"])
        with self.assertRaisesRegex(ValueError, "already owned"):
            self.ctl.command({"command": "connect", "computer": "laptop", "zone": "left"})
        self.tick(4)
        self.connect()
        self.assertEqual(self.proc.count, 1)

    def test_disconnect_in_each_connect_phase(self):
        for n in range(4):
            with self.subTest(phase=n):
                self.connect()
                self.tick(n)
                self.ctl.command({"command": "disconnect", "computer": "laptop"})
                count = self.proc.count
                self.tick(5)
                self.assertIsNone(self.proc.alive)
                self.assertEqual(self.proc.count, count)

    def test_restart_adopts_owned_process_and_does_not_relaunch(self):
        self.connect()
        self.tick(3)
        self.ctl = self.controller()
        self.tick(3)
        self.assertEqual(self.proc.count, 1)

    def test_old_compositor_process_is_stopped_before_relaunch(self):
        self.connect()
        self.tick(3)
        self.comp.instance = "two"
        self.ctl = self.controller()
        self.tick(6)
        self.assertEqual(self.proc.count, 2)

    def test_only_final_title_and_owned_pid_qualify(self):
        self.connect()
        self.tick(3)
        self.comp.desktop["windows"] = [{"address": "a", "pid": 999, "stable_id": 1, "class": s.CLASS,
                                         "title": "Laptop - Moonlight", "workspace": "1"}]
        self.tick()
        self.assertNotIn("window", self.ctl.records["laptop"])
        self.comp.desktop["windows"][0].update(pid=123, title="Moonlight")
        self.tick()
        self.assertEqual(self.ctl.records["laptop"]["observed"], "startup-window")
        self.comp.desktop["windows"][0]["title"] = "Laptop - Moonlight"
        self.tick()
        r = self.ctl.records["laptop"]
        self.assertEqual(r["observed"], "window-ready")
        self.assertFalse(any(m == "stream_focus" for m, _ in self.comp.calls))
        self.assertNotEqual(r["observed"], "streaming")

    def test_network_retry_is_bounded_and_reserves_zone(self):
        self.host.error = "host-unreachable"
        self.connect()
        for _ in range(8):
            self.tick()
            self.now += 30
        r = self.ctl.records["laptop"]
        self.assertEqual(r["attempts"], 3)
        self.assertEqual(r["observed"], "needs-attention")
        self.assertTrue(r["desired"])
        self.assertTrue(self.comp.desktop["streams"])
        self.assertEqual(self.proc.count, 0)

    def ready_swap(self):
        self.connect()
        self.tick(3)
        self.comp.desktop["windows"] = [{"address": "a", "pid": 123, "stable_id": 1, "class": s.CLASS,
                                         "title": "Laptop - Moonlight", "workspace": "1"}]
        self.tick()
        self.comp.swap_plan = {"workspace": "1", "layout": "lua:quad", "windows": [
            {"computer": "laptop", "address": "a", "pid": 123, "stable_id": 1, "before": "right", "zone": "left"},
            {"address": "b", "pid": 456, "stable_id": 2, "before": "left", "zone": "right"}]}
        return {"command": "swap", "windows": [{"address": "a", "stable_id": 1}, {"address": "b", "stable_id": 2}]}

    def test_swap_persists_assignment_without_relaunch_or_host_changes(self):
        request = self.ready_swap()
        original = copy.deepcopy(self.ctl.records["laptop"])
        result = self.ctl.command(request)
        self.assertTrue(result["swapped"])
        self.ctl = self.controller()
        self.tick(3)
        current = self.ctl.records["laptop"]
        self.assertEqual(current["assignment"]["zone"], "left")
        for field in ("generation", "token", "operation", "journal", "window", "settings"):
            self.assertEqual(current.get(field), original.get(field), field)
        self.assertEqual(self.proc.count, 1)
        self.assertEqual(self.host.calls, [])
        self.assertNotIn("swap", self.ctl.state)
        self.assertFalse(any(m == "stream_focus" for m, _ in self.comp.calls))

    def test_swap_lost_reply_replays_absolute_assignments_after_restart(self):
        request = self.ready_swap()
        self.comp.swap_timeout = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.ctl.command(request)
        disk = json.loads((self.root / "state.json").read_text())
        self.assertIn("swap", disk)
        self.assertEqual(disk["computers"]["laptop"]["assignment"]["zone"], "right")
        self.assertEqual(self.comp.desktop["streams"][0]["zone"], "left")
        self.comp.swap_timeout = False
        self.ctl = self.controller()
        self.tick(2)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "left")
        self.assertEqual(self.proc.count, 1)

    def test_failed_swap_rolls_back_without_stopping_stream(self):
        request = self.ready_swap()
        self.comp.swap_timeout = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.ctl.command(request)
        self.comp.swap_timeout = False
        self.comp.swap_error = "swap unavailable: target has closed"
        with self.assertRaisesRegex(RuntimeError, "swap unavailable"):
            self.ctl.finish_swap()
        self.tick(2)
        self.assertNotIn("swap", self.ctl.state)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "right")
        self.assertEqual(self.comp.desktop["streams"][0]["zone"], "right")
        self.assertEqual(self.proc.count, 1)
        self.assertEqual(self.proc.alive, 123)

    def test_swap_rejects_stale_owner_before_journaling(self):
        request = self.ready_swap()
        self.comp.swap_plan["windows"][0]["stable_id"] = 999
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.ctl.command(request)
        self.assertNotIn("swap", self.ctl.state)
        self.assertFalse(any(m == "stream_swap_apply" for m, _ in self.comp.calls))

    def test_two_stream_swap_updates_both_saved_assignments(self):
        request = self.ready_swap()
        other = copy.deepcopy(self.ctl.records["laptop"])
        other.update(computer="other", window={"address": "b", "pid": 456, "stable_id": 2})
        other["assignment"]["zone"] = "left"
        self.ctl.records["other"] = other
        self.comp.swap_plan["windows"][1]["computer"] = "other"
        self.ctl.command(request)
        disk = json.loads((self.root / "state.json").read_text())["computers"]
        self.assertEqual(disk["laptop"]["assignment"]["zone"], "left")
        self.assertEqual(disk["other"]["assignment"]["zone"], "right")

    def test_pending_swap_cannot_replay_addresses_into_new_compositor(self):
        request = self.ready_swap()
        self.comp.swap_timeout = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.ctl.command(request)
        self.comp.calls.clear()
        self.comp.instance = "two"
        self.ctl = self.controller()
        self.ctl.finish_swap()
        self.assertNotIn("swap", self.ctl.state)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "right")
        self.assertFalse(any(m == "stream_swap_apply" for m, _ in self.comp.calls))

    def test_pairing_failure_is_not_retried(self):
        self.host.error = "pairing-required"
        self.connect()
        self.tick(5)
        self.assertEqual(self.ctl.records["laptop"]["attempts"], 0)

    def test_window_close_cancels_intent_but_unknown_exit_does_not_retry(self):
        for evidence, desired in (({"quit": True}, False), ({"closed": True, "quit": True}, False), ({"closed": True}, True)):
            self.connect()
            self.tick(3)
            self.proc.alive = None
            self.proc.log = evidence
            self.tick(4)
            self.assertEqual(self.ctl.records["laptop"]["desired"], desired)
            count = self.proc.count
            self.now += 100
            self.tick(2)
            self.assertEqual(self.proc.count, count)
            if desired:
                self.ctl.command({"command": "disconnect", "computer": "laptop"})
                self.tick(2)
            self.proc.log = {}

    def test_missing_zone_does_not_reassign_and_stops_stream(self):
        self.connect()
        self.tick(3)
        self.comp.invalid = True
        self.tick(2)
        r = self.ctl.records["laptop"]
        self.assertEqual(r["assignment"]["zone"], "right")
        self.assertIn("assignment-invalid", r["error"])
        self.assertIsNone(self.proc.alive)

    def test_session_restore_does_not_resurrect_disconnect(self):
        self.connect()
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(2)
        self.ctl.command({"command": "session-restore", "sources": [{"computer": "laptop", "zone": "right", "workspace": "1", "profile": "desktop"}]})
        self.tick(3)
        self.assertFalse(self.ctl.records["laptop"]["desired"])
        self.assertEqual(self.proc.count, 0)

    def test_session_restore_retains_unknown_source_as_pending(self):
        source = {"computer": "unknown", "profile": "desktop", "workspace": "1", "zone": "right", "layout": "lua:quad"}
        self.ctl.command({"command": "session-restore", "sources": [source]})
        self.tick(3)
        r = self.ctl.records["unknown"]
        self.assertTrue(r["desired"])
        self.assertEqual(r["observed"], "needs-attention")
        self.assertEqual(r["assignment"]["zone"], "right")
        self.assertEqual(self.proc.count, 0)

    def test_restart_waits_for_local_recovery_to_create_workspace(self):
        self.connect()
        self.tick(3)
        self.comp.instance = "two"
        self.comp.desktop["workspaces"] = []
        self.ctl = self.controller()
        self.tick(8)
        self.assertEqual(self.proc.count, 1)
        self.comp.desktop["workspaces"] = [{"selector": "1", "layout": "lua:quad"}]
        self.tick(5)
        self.assertEqual(self.proc.count, 2)

    def test_pending_restore_and_explicit_release(self):
        self.connect()
        r = self.ctl.records["laptop"]
        r["journal"] = {"mode": {"original": OLD, "applied": MODE, "phase": "applied"}}
        self.host.error = "host-unreachable"
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(2)
        self.assertEqual(r["observed"], "restore-pending")
        self.assertFalse(self.comp.desktop["streams"])
        with self.assertRaisesRegex(ValueError, "keep-host-settings"):
            self.ctl.command({"command": "release", "computer": "laptop"})
        self.ctl.command({"command": "release", "computer": "laptop", "keep_host_settings": True})
        self.assertFalse(r["journal"])

    def test_original_and_intent_are_durable_before_every_write(self):
        host = Host()
        record = {}
        saved = []
        def persist():
            saved.append(copy.deepcopy(record))
        def before(field, expected, value):
            self.assertEqual(saved[-1]["journal"][field]["original"], expected)
            self.assertEqual(saved[-1]["journal"][field]["applied"], value)
        host.before_change = before
        s.prepare(record, host, persist)
        self.assertEqual(record["journal"]["mode"]["original"], OLD)
        host.before_change = None
        s.prepare(record, host, persist)  # Reconnect keeps the first baseline.
        self.assertEqual(len(host.calls), 2)
        self.assertTrue(s.restore(record, host, persist))
        self.assertEqual(host.current["mode"], OLD)

    def test_partial_prepare_rolls_back_only_changes_that_happened(self):
        host, record = Host(), {}
        host.fail_field = "mode"
        with self.assertRaises(ValueError):
            s.prepare(record, host, lambda: None)
        host.fail_field = None
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.current, {"mode": OLD, "output": "1"})
        self.assertEqual([field for field, _ in host.calls], ["output", "output"])

    def test_crash_after_apply_recovers_intent_without_rebaselining(self):
        host, record = Host(), {}
        record["journal"] = {"mode": {"original": OLD, "applied": MODE, "phase": "intent"}}
        host.current = {"mode": copy.deepcopy(MODE), "output": "5"}
        s.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["mode"]["original"], OLD)
        self.assertFalse(host.calls)
        self.assertTrue(s.restore(record, host, lambda: None))

    def test_manual_changes_preserved_and_conflict_persisted(self):
        host, record = Host(), {}
        s.prepare(record, host, lambda: None)
        manual = {"resolution": "1280x720", "hidpi": True, "refresh": 60}
        host.current["mode"] = manual
        self.assertFalse(s.restore(record, host, lambda: None))
        self.assertEqual(host.current["mode"], manual)
        self.assertEqual(record["journal"]["mode"]["phase"], "conflict")
        self.assertEqual(host.current["output"], "1")

    def ready_mac(self):
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": computer("betterdisplay")}}))
        self.host = Host()
        self.connect()
        self.tick(3)
        self.comp.desktop["windows"] = [{"address": "a", "pid": 123, "stable_id": 1, "class": s.CLASS,
                                         "title": "Laptop - Moonlight", "workspace": "1"}]
        self.tick()
        return self.ctl.records["laptop"]

    def test_lid_change_reapplies_mode_without_replacing_original_baseline(self):
        r = self.ready_mac()
        baseline, assignment = copy.deepcopy(r["journal"]), copy.deepcopy(r["assignment"])
        self.host.topology["lid_closed"] = False
        self.host.current["mode"] = {"resolution": "6144x2560", "hidpi": False, "refresh": 60}
        self.now += 6
        self.tick()
        self.assertEqual(r["phase"], "reconnect-stop")
        self.assertEqual(r["journal"], baseline)
        self.ctl = self.controller()  # Pending recovery must survive controller restart.
        r = self.ctl.records["laptop"]
        self.proc.alive = None
        self.proc.log = {"closed": True, "quit": True, "terminated": 0}
        self.comp.desktop["windows"] = []
        self.tick(3)
        self.assertEqual(r["phase"], "launch")
        self.assertEqual(self.host.current["mode"], MODE)
        self.assertEqual(r["journal"], baseline)
        self.assertEqual(r["assignment"], assignment)
        self.assertEqual(r["mac_topology"], self.host.topology)
        self.assertNotIn("display_recovery", r)

    def test_mode_change_without_lid_transition_is_preserved(self):
        r = self.ready_mac()
        manual = {"resolution": "1280x720", "hidpi": False, "refresh": 60}
        self.host.current["mode"] = manual.copy()
        calls = len(self.host.calls)
        self.now += 6
        self.tick()
        self.assertEqual(self.host.current["mode"], manual)
        self.assertEqual(len(self.host.calls), calls)
        self.assertEqual(r["observed"], "degraded")
        self.assertNotIn("display_recovery", r)

    def test_lid_recovery_tracks_new_numeric_id_for_same_display(self):
        host, record = Host(), {}
        s.prepare(record, host, lambda: None)
        host.topology = {"lid_closed": False, "display_id": "7"}
        record["display_recovery"] = {"current": copy.deepcopy(host.current), "topology": copy.deepcopy(host.topology)}
        s.prepare(record, host, lambda: None)
        self.assertEqual(host.current["output"], "7")
        self.assertEqual(record["journal"]["output"]["original"], "1")
        self.assertEqual(record["journal"]["output"]["applied"], "7")
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.current["output"], "1")

    def test_lid_recovery_rejects_changes_after_it_was_requested(self):
        for change in ("mode", "topology"):
            with self.subTest(change=change):
                host, record = Host(), {}
                s.prepare(record, host, lambda: None)
                host.topology["lid_closed"] = False
                host.current["mode"] = {"resolution": "6144x2560", "hidpi": False, "refresh": 60}
                record["display_recovery"] = {"current": copy.deepcopy(host.current), "topology": copy.deepcopy(host.topology)}
                if change == "mode":
                    host.current["mode"] = {"resolution": "1280x720", "hidpi": False, "refresh": 60}
                else:
                    host.topology["lid_closed"] = True
                calls = len(host.calls)
                with self.assertRaises(ValueError):
                    s.prepare(record, host, lambda: None)
                self.assertEqual(len(host.calls), calls)

    def test_disconnect_cancels_pending_lid_reconnect(self):
        r = self.ready_mac()
        self.host.topology["lid_closed"] = False
        self.host.current["mode"] = {"resolution": "6144x2560", "hidpi": False, "refresh": 60}
        self.now += 6
        self.tick()
        self.assertEqual(r["phase"], "reconnect-stop")
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(3)
        self.assertFalse(r["desired"])
        self.assertEqual(r["observed"], "disconnected")
        self.assertEqual(r["journal"], {})
        self.assertEqual(self.host.current["mode"], OLD)
        self.assertEqual(self.proc.count, 1)

    def recover_main(self, host, record):
        health = host.probe(False)
        record["display_recovery"] = {"current": health["current"], "topology": health["topology"]}
        s.prepare(record, host, lambda: None)

    def test_main_screen_switch_restores_only_the_old_panel(self):
        host, record = MainHost(), {}
        s.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["mode"]["display_uuid"], IDENTITY)
        host.switch(BUILTIN, False)
        self.recover_main(host, record)
        self.assertEqual(host.current, {"mode": PANEL, "output": "1"})
        self.assertEqual(host.panels[IDENTITY], OLD)
        self.assertNotIn("mode", record["journal"])
        self.assertEqual(record["journal"]["output"]["original"], "1")
        # Simulate the durable record being loaded after a controller restart.
        record = json.loads(json.dumps(record))
        host.switch(IDENTITY, True)
        self.recover_main(host, record)
        self.assertEqual(host.current, {"mode": MODE, "output": "5"})
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.current, {"mode": OLD, "output": "1"})
        self.assertEqual(host.panels[BUILTIN], PANEL)

    def test_unplugged_mode_restore_does_not_target_the_builtin_panel(self):
        host, record = MainHost(), {}
        s.prepare(record, host, lambda: None)
        host.switch(BUILTIN, False)
        host.available.remove(IDENTITY)
        self.recover_main(host, record)
        self.assertEqual(host.current, {"mode": PANEL, "output": "1"})
        self.assertEqual(record["journal"]["mode"]["phase"], "unavailable")
        self.assertFalse(s.restore(record, host, lambda: None))
        host.available.add(IDENTITY)
        self.assertTrue(s.restore(record, host, lambda: None))
        self.assertEqual(host.panels[IDENTITY], OLD)
        self.assertEqual(host.panels[BUILTIN], PANEL)

    def test_main_screen_does_not_require_or_apply_external_mode(self):
        host = MainHost()
        host.switch(BUILTIN, False)
        profile = computer("betterdisplay")["profiles"]["desktop"]
        profile["display"]["follow_main"] = True
        native = s.Host(computer("betterdisplay"), profile)
        native.remote = lambda *_: {**host.probe(False), "modes": [PANEL]}
        native.probe(pairing=False)  # A 16:9 mode is absent from this panel.
        record = {}
        s.prepare(record, host, lambda: None)
        self.assertEqual(host.current["mode"], PANEL)
        self.assertEqual(host.calls, [])
        self.assertEqual(host.refreshes, 1)
        self.assertTrue(s.same_setting("mode", PANEL, PANEL.copy()))
        self.assertFalse(s.same_setting("mode", PANEL, {**PANEL, "refresh": 60}))

    def test_main_change_reconnects_same_zone_and_disconnect_cancels_it(self):
        c = computer("betterdisplay")
        c["profiles"]["desktop"]["display"]["follow_main"] = True
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": c}}))
        self.host = MainHost()
        self.connect()
        self.tick(3)
        self.comp.desktop["windows"] = [{"address": "a", "pid": 123, "stable_id": 1, "class": s.CLASS,
                                         "title": "Laptop - Moonlight", "workspace": "1"}]
        self.tick()
        r = self.ctl.records["laptop"]
        assignment = copy.deepcopy(r["assignment"])
        # Main display can change even if the lid has not moved.
        self.host.switch(BUILTIN, True)
        self.now += 6
        self.tick()
        self.assertEqual(r["phase"], "reconnect-stop")
        self.assertEqual(r["assignment"], assignment)
        self.ctl = self.controller()
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(3)
        self.assertEqual(self.proc.count, 1)
        self.assertEqual(self.ctl.records["laptop"]["journal"], {})
        self.assertEqual(self.host.panels[BUILTIN], PANEL)

    def test_main_screen_switch_replays_after_output_write_crash(self):
        host, record = MainHost(), {}
        s.prepare(record, host, lambda: None)
        host.switch(BUILTIN, False)
        health = host.probe(False)
        record["display_recovery"] = {"current": health["current"], "topology": health["topology"]}
        # Crash after the output write, before the readback/phase update.
        saved = []
        def persist():
            saved[:] = [copy.deepcopy(record)]
        change = host.change
        def crash(field, expected, value, **guards):
            change(field, expected, value, **guards)
            if field == "output":
                raise RuntimeError("crash")
        host.change = crash
        with self.assertRaisesRegex(RuntimeError, "crash"):
            s.prepare(record, host, persist)
        host.change = change
        record = saved[0]
        s.prepare(record, host, lambda: None)
        self.assertEqual(record["journal"]["output"]["original"], "1")
        self.assertEqual(host.current, {"mode": PANEL, "output": "1"})
        self.assertTrue(s.restore(record, host, lambda: None))

    def test_native_profile_needs_no_betterdisplay_uuid_or_mode(self):
        c = computer()
        c["platform"] = "macos"
        c["profiles"]["desktop"]["display"] = {"adapter": "macos"}
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": c}}))
        s.configuration(self.config)
        h = s.Host(c, c["profiles"]["desktop"])
        observed = {"identity": {"UUID": BUILTIN, "displayID": "1"}, "current": {"mode": PANEL, "output": "1"},
                    "modes": [], "ac_power": True, "topology": {"lid_closed": False, "display_id": "1"}}
        h.remote = Mock(return_value=observed)
        record = {}
        s.prepare(record, h, lambda: None)
        self.assertEqual(record["journal"], {})
        self.assertFalse(any(call.args[0] == "change" for call in h.remote.call_args_list))
        self.assertEqual(h.remote.call_args.args[0], "refresh")

    def test_native_adapter_never_invokes_betterdisplay_or_changes_mode(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        (directory / "sunshine.conf").write_text("output_name = 1\n")
        request = {"adapter": "macos", "pairing_uuid": IDENTITY, "operation": "probe"}
        def run(argv):
            self.assertNotIn(mac_display.BETTER, argv)
            return "AC Power" if argv[0] == "/usr/bin/pmset" else '"AppleClamshellState" = No'
        with patch.object(Path, "home", return_value=self.root), \
             patch.object(mac_display, "native_display", return_value=({"UUID": BUILTIN, "displayID": "1"}, PANEL, "3456x2234")), \
             patch.object(mac_display, "run", side_effect=run), \
             patch.object(mac_display, "restart_sunshine") as restart:
            result = mac_display.display(request)
            self.assertEqual(result["current"]["mode"], PANEL)
            self.assertEqual(result["render_resolution"], "3456x2234")
            with self.assertRaisesRegex(ValueError, "preserves the host mode"):
                mac_display.display({**request, "operation": "change", "field": "mode", "expected": PANEL, "value": MODE})
            restart.assert_not_called()

    def test_mac_main_identity_race_is_rejected_before_writing(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        graphics = Mock()
        graphics.CGMainDisplayID.return_value = 1
        with patch.object(Path, "home", return_value=self.root), \
             patch.object(mac_display.ctypes, "CDLL", return_value=graphics), \
             patch.object(mac_display, "run", return_value=json.dumps({"UUID": BUILTIN, "displayID": "1"})) as run, \
             patch.object(mac_display, "restart_sunshine") as restart:
            with self.assertRaisesRegex(ValueError, "display-topology-changed"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "follow_main": True,
                                     "expected_identity": IDENTITY, "operation": "change", "field": "mode",
                                     "expected": OLD, "value": MODE})
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][1], "get")
            restart.assert_not_called()

    def test_nominal_refresh_tolerance_does_not_hide_other_mode_changes(self):
        actual = {**MODE, "refresh": 59.95}
        self.assertTrue(s.same_setting("mode", MODE, actual))
        self.assertFalse(s.same_setting("mode", MODE, {**actual, "refresh": 50}))
        self.assertFalse(s.same_setting("mode", MODE, {**actual, "hidpi": False}))
        host = Host()
        host.current = {"mode": actual, "output": "5"}
        record = {"journal": {"mode": {"original": OLD, "applied": MODE, "phase": "intent"}}}
        s.prepare(record, host, lambda: None)
        self.assertTrue(s.restore(record, host, lambda: None))

    def test_invalid_configuration_rejected(self):
        for edit in (lambda c: c.update(host="-oProxyCommand=evil"),
                     lambda c: c.update(pairing_uuid="localhost"),
                     lambda c: c["profiles"]["desktop"].update(stream_resolution="1920x1080;touch /tmp/bad")):
            value = computer()
            edit(value)
            self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": value}}))
            with self.assertRaises(ValueError):
                s.configuration(self.config)

    def test_job_stale_generation_cannot_exec(self):
        self.connect()
        r = self.ctl.records["laptop"]
        r.update(desired=False, token="new")
        self.ctl.persist()
        job = self.root / "job.json"
        s.atomic_json(job, {"state": str(self.root / "state.json"), "computer": "laptop", "token": "old"})
        with patch.object(os, "execvp") as execute:
            s.launch_job(job)
            execute.assert_not_called()

    def test_disconnect_cannot_miss_a_pid_being_published(self):
        self.connect()
        with (self.root / "laptop.gate").open("a") as gate, ThreadPoolExecutor(max_workers=1) as worker:
            fcntl.flock(gate, fcntl.LOCK_EX)
            command = worker.submit(self.ctl.command, {"command": "disconnect", "computer": "laptop"})
            try:
                with self.assertRaises(TimeoutError):
                    command.result(timeout=.05)
                self.proc.alive = 123  # The launch publishes its PID before exec.
            finally:
                fcntl.flock(gate, fcntl.LOCK_UN)
            self.assertFalse(command.result(timeout=1)["desired"])
        self.tick(3)
        self.assertIsNone(self.proc.alive)
        self.assertEqual(self.proc.count, 0)

    def test_ssh_health_loss_keeps_view_but_power_loss_stops_it(self):
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": computer("betterdisplay")}}))
        self.host = Host()
        self.connect()
        self.tick(3)
        self.comp.desktop["windows"] = [{"address": "a", "pid": 123, "stable_id": 1, "class": s.CLASS,
                                         "title": "Laptop - Moonlight", "workspace": "1"}]
        self.host.error = "host-unreachable"
        self.now += 31
        self.tick()
        self.assertEqual(self.ctl.records["laptop"]["observed"], "degraded")
        self.assertEqual(self.proc.alive, 123)
        self.host.error = None
        self.host.ac_power = False
        self.now += 31
        self.tick(2)
        self.assertIsNone(self.proc.alive)
        self.assertIn("power-required", self.ctl.records["laptop"]["error"])

    def test_visible_workspace_controls_only_owned_window_inhibition(self):
        self.connect()
        self.tick(3)
        self.comp.desktop["windows"] = [{"address": "a", "pid": 123, "stable_id": 1, "class": s.CLASS,
                                         "title": "Laptop - Moonlight", "workspace": "1"}]
        self.tick()
        self.assertIn(("stream_inhibit", {"computer": "laptop", "enabled": False}), self.comp.calls)
        self.comp.desktop["workspaces"][0]["visible"] = True
        self.tick()
        self.assertIn(("stream_inhibit", {"computer": "laptop", "enabled": True}), self.comp.calls)

    def test_cli_never_requests_host_app_termination(self):
        c = computer()
        args = s.stream_argv(c, c["profiles"]["desktop"])
        self.assertIn("--no-quit-after", args)
        self.assertNotIn("--quit-after", args)
        self.assertEqual(args[-2], IDENTITY)

    def test_logs_never_persist_urls_or_secret_parameters(self):
        self.assertIsNone(s.log_event("GET https://host/launch?rikey=SECRET&uniqueid=CLIENT"))
        self.assertIsNone(s.log_event("Video stream is 2560x1440x60 https://host/?secret=SECRET"))
        self.assertEqual(s.log_event("Video stream is 2560x1440x60 (format 0x100)"),
                         {"negotiated_video": {"width": 2560, "height": 1440, "fps": 60}})
        self.assertEqual(s.log_event("Quit event received"), {"quit": True})

    def test_local_session_ignores_managed_windows_and_keeps_offline_source(self):
        self.connect()
        state = self.root / "hypertile/streams"
        state.mkdir(parents=True)
        s.atomic_json(state / "state.json", self.ctl.state)
        desktop = self.comp.snapshot()
        desktop["windows"] = [{"address": "local"}, {"address": "remote", "stream": "laptop"}]
        with patch.dict(os.environ, XDG_STATE_HOME=str(self.root)):
            captured = integration.capture(desktop)
        self.assertEqual([w["address"] for w in captured["windows"]], ["local"])
        self.assertEqual(captured["streams"][0]["computer"], "laptop")

    def test_offline_remote_submission_does_not_block_local_recovery(self):
        from service import Recovery
        desktop = self.comp.snapshot()
        desktop["streams"] = [{"computer": "laptop", "profile": "desktop", "zone": "right", "workspace": "1", "layout": "lua:quad"}]
        record = {"version": 1, "instance": "old", "desktop": desktop}
        with patch.object(integration, "restore", return_value=["remote offline"]):
            recovery = Recovery(record, self.comp, object(), 0, lambda _: None)
        self.assertEqual(recovery.tick(1), "restoring")
        self.assertEqual(recovery.tick(4), "complete")
        self.assertIn("remote offline", recovery.report()["limitations"])
        self.assertEqual(record["desktop"]["streams"], desktop["streams"])

    def test_mac_host_identity_checked_before_display_reads_or_changes(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": "other-host"}}))
        with patch.object(Path, "home", return_value=self.root), patch.object(mac_display, "run") as run:
            with self.assertRaisesRegex(ValueError, "host-identity-mismatch"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "probe"})
            run.assert_not_called()

    def test_mac_uuid_queries_exclude_default_display_group(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        # Stop just after resolving the identifier; this assertion prevents the
        # live BetterDisplay behavior where UUID-only queries include a group.
        def run(argv):
            self.assertIn("-type=Display", argv)
            self.assertIn("-UUID=" + IDENTITY, argv)
            raise ValueError("sentinel")
        with patch.object(Path, "home", return_value=self.root), patch.object(mac_display, "run", side_effect=run), \
             patch.object(mac_display.ctypes, "CDLL", return_value=Mock()):
            with self.assertRaisesRegex(ValueError, "display-missing"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "probe"})

    def test_mac_mode_changes_refresh_sunshine_cached_pointer_scale(self):
        directory = self.root / ".config/sunshine"
        directory.mkdir(parents=True)
        (directory / "sunshine_state.json").write_text(json.dumps({"root": {"uniqueid": IDENTITY}}))
        (directory / "sunshine.conf").write_text("output_name = 4\n")
        for hidpi in (True, False):
            with self.subTest(original_hidpi=hidpi):
                mode = {"resolution": "1920x1080", "hidpi": hidpi, "refresh": 60}
                before = mode.copy()
                target = {**mode, "hidpi": not hidpi}
                sunshine = {"running": True, "scale": .5 if hidpi else 1, "restarts": 0}
                def command(argv):
                    if argv[0] == "/usr/bin/open":
                        sunshine.update(running=True, scale=.5 if mode["hidpi"] else 1,
                                        restarts=sunshine["restarts"] + 1)
                        return ""
                    if argv[1] == "get":
                        return {"-identifiers": json.dumps({"UUID": IDENTITY, "displayID": "4"}),
                                "-resolution": mode["resolution"], "-hiDPI": "on" if mode["hidpi"] else "off",
                                "-refreshRate": str(mode["refresh"]) + "Hz"}[argv[-1]]
                    values = dict(arg.split("=", 1) for arg in argv[2:])
                    mode.update(resolution=values["-resolution"], hidpi=values["-hiDPI"] == "on",
                                refresh=float(values["-refreshRate"]))
                    return ""
                def process(argv, **kwargs):
                    if argv[0] == "/usr/bin/pkill":
                        sunshine["running"] = False
                    return subprocess.CompletedProcess(argv, 0 if sunshine["running"] else 1)
                graphics = Mock()
                graphics.CGDisplayIsActive.return_value = 1
                with patch.object(Path, "home", return_value=self.root), \
                     patch.object(mac_display.ctypes, "CDLL", return_value=graphics), \
                     patch.object(mac_display, "run", side_effect=command), \
                     patch.object(mac_display.subprocess, "run", side_effect=process):
                    mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "change",
                                         "field": "mode", "expected": before, "value": target})
                self.assertEqual(mode, target)
                self.assertEqual(sunshine["scale"], .5 if target["hidpi"] else 1)
                self.assertEqual(sunshine["restarts"], 1)
                self.assertEqual((directory / "sunshine.conf").read_text(), "output_name = 4\n")


if __name__ == "__main__":
    unittest.main()
