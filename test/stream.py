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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
import controller as s
import streams as integration
import mac_display

IDENTITY = "12345678-1234-1234-1234-123456789ABC"
MODE = {"resolution": "1920x1080", "hidpi": True, "refresh": 60}
OLD = {"resolution": "2560x1440", "hidpi": False, "refresh": 60}


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

    def probe(self, pairing=True):
        if self.error:
            raise ValueError(self.error)
        return {"current": copy.deepcopy(self.current), "identity": {"UUID": IDENTITY, "displayID": "5"},
                "ac_power": self.ac_power, "modes": [MODE, OLD]}

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
        with patch.object(Path, "home", return_value=self.root), patch.object(mac_display, "run", side_effect=run):
            with self.assertRaisesRegex(ValueError, "sentinel"):
                mac_display.display({"pairing_uuid": IDENTITY, "display_uuid": IDENTITY, "operation": "probe"})


if __name__ == "__main__":
    unittest.main()
