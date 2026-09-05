"""Real lifecycle transitions with controlled clocks, client exits and typed logs."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("stream_fixtures", Path(__file__).with_name("stream.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from quality import Tracker, VideoStats, settings_key


SUMMARY = """00:00:31 - SDL Info (0): Global video stats
----------------------------------------------------------
Video stream: 2560x1440 60.00 FPS (Codec: HEVC)
Incoming frame rate from network: 60.00 FPS
Decoding frame rate: 59.99 FPS
Rendering frame rate: 59.97 FPS
Host processing latency min/max/average: 1.0/4.0/2.0 ms
Frames dropped by your network connection: 0.01%
Frames dropped due to network jitter: 0.02%
Average network latency: 3 ms (variance: 1 ms)
Average decoding time: 0.10 ms
Average frame queue delay: 0.01 ms
Average rendering time (including monitor V-sync latency): 1.40 ms
"""


class ParserTests(unittest.TestCase):
    def parse(self, text):
        parser = VideoStats()
        return [result for line in text.splitlines() if (result := parser.feed(line))]

    def test_versioned_summary_is_numeric_and_does_not_claim_encode_latency(self):
        metrics = self.parse(SUMMARY)[0]
        self.assertEqual(metrics["rendered_fps"], 59.97)
        self.assertEqual(metrics["network_drop_pct"], .01)
        self.assertEqual(metrics["host_processing_ms"]["average"], 2)
        self.assertNotIn("encode_ms", metrics)

    def test_rejects_text_without_header_nonfinite_out_of_range_and_incomplete(self):
        self.assertEqual(self.parse(SUMMARY.split("\n", 1)[1]), [])
        for value in ("nan", "-1", "101", "0.01% https://host/?secret=TOKEN"):
            self.assertEqual(self.parse(SUMMARY.replace("0.01%", value + "%")), [])
        self.assertEqual(self.parse(SUMMARY.replace("0.10 ms", "nan ms")), [])
        self.assertEqual(self.parse(SUMMARY.rsplit("Average rendering time", 1)[0]), [])

    def test_multiple_segments_do_not_merge_missing_fields(self):
        second = SUMMARY.replace("Average decoding time: 0.10 ms\n", "")
        self.assertEqual(len(self.parse(SUMMARY + second)), 1)
        without_host = "\n".join(l for l in SUMMARY.splitlines() if not l.startswith("Host processing"))
        self.assertNotIn("host_processing_ms", self.parse(without_host)[0])


class QualityTests(unittest.TestCase):
    def setUp(self):
        fixtures.StreamTests.setUp(self)
        self.event_token = None
        self.proc.events = lambda r: self.proc.log if r.get("token") and r["token"] == self.event_token else {}

    def controller(self):
        ctl = fixtures.s.Controller(self.root, self.config, self.comp, self.proc, lambda *_: self.host, lambda: self.now)
        if not hasattr(self, "clock_now"):
            self.clock_now = 100
        ctl.quality = Tracker(ctl, clock=lambda: self.clock_now, boot="test")
        return ctl

    connect = fixtures.StreamTests.connect

    def tick(self, count=1):
        for _ in range(count):
            self.ctl.tick()
            self.now += 1
            self.clock_now += 1

    def ready(self):
        self.connect()
        self.tick(3)
        self.window()
        self.tick()

    def window(self):
        self.comp.desktop["windows"] = [{"address": "a", "pid": 123, "stable_id": 1, "class": fixtures.s.CLASS,
            "title": "Laptop - Moonlight", "workspace": "1", "size": {"x": 1000, "y": 600}}]

    def close(self):
        self.event_token = self.ctl.records["laptop"]["token"]
        self.proc.alive = None
        self.proc.log = {"quit": True, "closed": True}
        self.comp.desktop["windows"] = []

    def test_window_timing_uses_monotonic_clock_and_is_not_reset_by_polling(self):
        self.now = 10000
        self.connect()
        self.now -= 3600
        self.tick(3)
        self.window()
        self.tick()
        first = self.ctl.quality.report(self.ctl.records["laptop"])["current"]["window_ready_ms"]
        self.assertEqual(first, 3000)
        self.tick(4)
        self.assertEqual(self.ctl.quality.report(self.ctl.records["laptop"])["current"]["window_ready_ms"], first)

    def test_reconnect_is_idempotent_keeps_assignment_and_journal_and_does_not_disconnect(self):
        self.ready()
        original = copy.deepcopy(self.ctl.records["laptop"])
        first = self.ctl.command({"command": "reconnect", "computer": "laptop"})
        self.assertEqual(self.ctl.command({"command": "reconnect", "computer": "laptop"})["operation"], first["operation"])
        self.tick()
        self.assertIn(("stream_close", {"computer": "laptop"}), self.comp.calls)
        self.close()
        self.tick(3)
        self.proc.log = {}
        self.tick()
        self.window()
        self.tick()
        r = self.ctl.records["laptop"]
        self.assertTrue(r["desired"])
        self.assertEqual(r["phase"], "watching")
        self.assertEqual(r["assignment"], original["assignment"])
        self.assertEqual(r.get("journal"), original.get("journal"))
        self.assertEqual(self.host.calls, [])
        self.assertEqual(self.proc.count, 2)
        self.assertEqual(self.ctl.quality.report(r)["current"]["reason"], "reconnect")

    def test_disconnect_cancels_reconnect_before_late_launch(self):
        self.ready()
        self.ctl.command({"command": "reconnect", "computer": "laptop"})
        self.tick()
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.close()
        self.tick(12)
        self.assertFalse(self.ctl.records["laptop"]["desired"])
        self.assertEqual(self.proc.count, 1)

    def test_restart_mid_reconnect_retains_single_operation(self):
        self.ready()
        operation = self.ctl.command({"command": "reconnect", "computer": "laptop"})["operation"]
        self.tick()
        self.ctl = self.controller()
        self.assertEqual(self.ctl.records["laptop"]["operation"], operation)
        self.close()
        self.tick(4)
        self.assertEqual(self.proc.count, 2)

    def test_measurement_is_cancelled_when_disconnected_or_rebooted(self):
        for cancel in ("disconnect", "boot"):
            with self.subTest(cancel=cancel):
                self.ready()
                r = self.ctl.records["laptop"]
                run = self.ctl.quality.current(r)
                run["quality_parser"] = True
                self.ctl.command({"command": "measure", "computer": "laptop", "seconds": 10})
                if cancel == "disconnect":
                    self.ctl.command({"command": "disconnect", "computer": "laptop"})
                    self.close()
                    self.tick(2)
                else:
                    self.ctl.quality.boot = "another-boot"
                self.clock_now += 20
                self.ctl.quality.due()
                self.assertEqual(run["measurement"]["status"], "cancelled")

    def test_measurement_due_once_and_late_logger_result_is_attached_to_old_run(self):
        self.ready()
        r = self.ctl.records["laptop"]
        old = self.ctl.quality.current(r)
        old["quality_parser"] = True
        self.ctl.quality.measure(r, 10)
        self.clock_now += 11
        self.ctl.quality.due()
        operation = r["operation"]
        self.ctl.quality.due()
        self.assertEqual(r["operation"], operation)
        self.assertEqual(old["measurement"]["status"], "collecting")
        self.assertNotEqual(self.ctl.quality.current(r)["id"], old["id"])
        event = {"closed": True, "quality_parser": 1, "performance_at": 123, "performance": {"decode_ms": .3}}
        (self.root / (old["token"] + ".events")).write_text(json.dumps(event))
        self.ctl.quality.harvest()
        report = self.ctl.quality.report(r)
        self.assertEqual(report["last_measurement"]["id"], old["id"])
        self.assertEqual(old["measurement"]["status"], "complete")
        self.assertNotIn("token", json.dumps(report))

    def test_readability_and_metrics_are_not_reused_for_changed_settings_or_size(self):
        self.ready()
        r = self.ctl.records["laptop"]
        self.ctl.quality.assess(r, "readable")
        self.assertEqual(self.ctl.quality.report(r)["readability"], "readable")
        self.comp.desktop["windows"][0]["size"]["x"] = 500
        self.tick()
        self.assertEqual(self.ctl.quality.report(r)["readability"], "unverified")
        run = self.ctl.quality.current(r)
        self.ctl.quality.assess(r, "readable")
        run["metrics"] = {"decode_ms": .5}
        r["settings"]["bitrate"] = 10000
        self.assertIsNone(self.ctl.quality.report(r)["last_measurement"])
        self.assertEqual(self.ctl.quality.report(r)["readability"], "unverified")

    def test_measurement_requires_new_logger_and_history_is_bounded(self):
        self.ready()
        r = self.ctl.records["laptop"]
        with self.assertRaisesRegex(ValueError, "Reconnect once"):
            self.ctl.quality.measure(r, 10)
        for _ in range(30):
            self.ctl.quality.begin(r, "retry")
        self.assertEqual(len(self.ctl.quality.runs("laptop")), 20)
        self.assertEqual(len(self.ctl.quality.report(r)["history"]), 5)
        self.assertNotEqual(settings_key({"bitrate": 1}), settings_key({"bitrate": 2}))

    def test_fast_polling_is_limited_to_transitions_and_preserves_backoff(self):
        self.assertEqual(self.ctl.tick_interval(), 1)
        self.connect()
        self.assertEqual(self.ctl.tick_interval(), .2)
        r = self.ctl.records["laptop"]
        r["next_at"] = self.now + 10
        self.assertEqual(self.ctl.tick_interval(), 1)
        r.update(phase="watching", next_at=0)
        self.assertEqual(self.ctl.tick_interval(), 1)
        r["phase"] = "reconnect-stop"
        self.assertEqual(self.ctl.tick_interval(), .2)

    def test_new_compositor_run_cannot_relabel_old_client_statistics(self):
        self.ready()
        r = self.ctl.records["laptop"]
        old = self.ctl.quality.current(r)
        new = self.ctl.quality.begin(r, "compositor-recovery")
        r["phase"] = "restart-stop"
        self.ctl.quality.observe(r, "restart-stop", self.clock_now, self.comp.snapshot())
        self.assertNotIn("token", new)
        self.assertIn("token", old)
        r.update(phase="connecting", token="f" * 32)
        self.ctl.quality.observe(r, "launch", self.clock_now, self.comp.snapshot())
        self.assertEqual(new["token"], "f" * 32)
        self.assertNotEqual(old["token"], new["token"])

    def test_unsupported_client_reports_limit_without_requesting_repeated_reconnects(self):
        self.ready()
        r = self.ctl.records["laptop"]
        r["resolved"]["client_version"] = "6.2.0"
        with self.assertRaisesRegex(ValueError, "supports Moonlight Qt 6.1"):
            self.ctl.quality.measure(r, 10)
        self.assertIn("Statistics overlay", self.ctl.quality.report(r)["collection_reason"])


if __name__ == "__main__":
    unittest.main()
