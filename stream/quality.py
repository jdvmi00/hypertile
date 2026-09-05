"""Bounded, typed measurements; no raw logs, screen content or automatic tuning."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time
import uuid


class VideoStats:
    """Moonlight Qt 6.1's completed FFmpeg decoder summary (not live telemetry)."""
    PREFIX = re.compile(r"^\d\d:\d\d:\d\d(?:\.\d+)? - SDL Info \(\d+\): ")
    NUMBER = r"(\d+(?:\.\d+)?)"
    FIELDS = {
        "Incoming frame rate from network": ("received_fps", "FPS", 1000),
        "Decoding frame rate": ("decoded_fps", "FPS", 1000),
        "Rendering frame rate": ("rendered_fps", "FPS", 1000),
        "Frames dropped by your network connection": ("network_drop_pct", "%", 100),
        "Frames dropped due to network jitter": ("jitter_drop_pct", "%", 100),
        "Average decoding time": ("decode_ms", "ms", 60000),
        "Average frame queue delay": ("queue_ms", "ms", 60000),
        "Average rendering time (including monitor V-sync latency)": ("render_ms", "ms", 60000),
    }

    def __init__(self):
        self.current = None

    def feed(self, line):
        line = self.PREFIX.sub("", line.strip())
        if line == "Global video stats":
            self.current = {}
            return None
        if self.current is None or len(line) > 300:
            return None
        for label, (key, unit, limit) in self.FIELDS.items():
            match = re.fullmatch(re.escape(label) + ": " + self.NUMBER + ("" if unit == "%" else " ") + re.escape(unit), line)
            if match:
                value = float(match[1])
                if math.isfinite(value) and 0 <= value <= limit:
                    self.current[key] = value
                if key == "render_ms":
                    result, self.current = self.current, None
                    # Truncated output and non-finite metrics never become a complete result.
                    if all(k in result for k in ("rendered_fps", "network_drop_pct", "jitter_drop_pct", "decode_ms", "queue_ms", "render_ms")):
                        return result
                return None
        match = re.fullmatch("Host processing latency min/max/average: " + "/".join([self.NUMBER] * 3) + " ms", line)
        if match:
            lo, hi, avg = map(float, match.groups())
            if 0 <= lo <= avg <= hi <= 60000:
                self.current["host_processing_ms"] = {"min": lo, "max": hi, "average": avg}
        match = re.fullmatch(r"Average network latency: (\d+) ms \(variance: (\d+) ms\)", line)
        if match and max(map(int, match.groups())) <= 60000:
            self.current.update(network_rtt_ms=int(match[1]), network_variance_ms=int(match[2]))
        return None


def settings_key(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Tracker:
    def __init__(self, controller, clock=time.monotonic, boot=None):
        self.ctl, self.clock = controller, clock
        self.boot = boot or Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.records = controller.state.setdefault("quality", {})

    def runs(self, computer):
        return self.records.setdefault(computer, {"runs": []})["runs"]

    def current(self, r):
        return next((v for v in self.runs(r["computer"]) if v["id"] == r.get("quality_id")), None)

    def begin(self, r, reason):
        run = {"id": uuid.uuid4().hex, "profile": r["profile"], "settings_key": settings_key(r["settings"]),
               "reason": reason, "started_at": self.ctl.now(), "boot": self.boot,
               "clock_start": self.clock() if reason != "adopted" else None,
               "previous_token": r.get("token") if reason != "adopted" else None,
               "stages_ms": {}, "work_ms": {}, "status": "starting",
               "requested": {k: r["settings"].get(k, default) for k, default in
                   (("stream_resolution", None), ("fps", 60), ("bitrate", 60000), ("codec", "HEVC"),
                    ("input", "absolute"), ("system_keys", "never"), ("audio", "focus"))}}
        runs = self.runs(r["computer"])
        runs.append(run)
        del runs[:-20]
        r["quality_id"] = run["id"]
        return run

    def observe(self, r, phase, started, snap):
        run = self.current(r) or self.begin(r, "adopted")
        if run["boot"] != self.boot:
            run["clock_start"] = None
        if r.get("token") and r["token"] != run.get("previous_token"):
            run["token"] = r["token"]
        if phase in ("preflight", "preparing", "launch", "reconnect-stop"):
            run["work_ms"][phase] = round(run["work_ms"].get(phase, 0) + max(0, self.clock() - started) * 1000, 1)
        elapsed = max(0, self.clock() - run["clock_start"]) * 1000 if run["clock_start"] is not None else None
        if elapsed is not None and r["phase"] not in run["stages_ms"]:
            run["stages_ms"][r["phase"]] = round(elapsed, 1)
        run["status"] = r["observed"]
        run["client_version"] = r.get("resolved", {}).get("client_version", "unknown")
        if r.get("window") and r["phase"] == "watching":
            if "window_ready_ms" not in run:
                run["window_ready_ms"] = round(elapsed, 1) if elapsed is not None else None
            window = next((w for w in snap["windows"] if w["address"] == r["window"]["address"]), {})
            if window.get("size"):
                run["view_size"] = copy.deepcopy(window["size"])
            mode = r.get("resolved", {}).get("current", {}).get("mode")
            if mode:
                run["host_mode"] = copy.deepcopy(mode)

    def harvest(self):
        for computer, record in self.records.items():
            for run in record["runs"]:
                token = run.get("token")
                if run.get("closed") or not token or not re.fullmatch(r"[a-f0-9]{32}", token):
                    continue
                path = self.ctl.root / (token + ".events")
                try:
                    event = json.loads(path.read_text())
                except (OSError, ValueError):
                    continue
                run["quality_parser"] = event.get("quality_parser") == 1
                if event.get("performance"):
                    run["metrics"] = copy.deepcopy(event["performance"])
                    run["metrics_at"] = event["performance_at"]
                    run["metrics_source"] = "completed-decoder-segment"
                if event.get("closed"):
                    run["closed"], run["ended_at"] = True, self.ctl.now()
                    if run.get("measurement", {}).get("status") == "collecting":
                        run["measurement"]["status"] = "complete" if run.get("metrics") else "no-metrics"

    def measure(self, r, seconds):
        if type(seconds) is not int or not 10 <= seconds <= 300:
            raise ValueError("measurement duration must be 10–300 seconds")
        run = self.current(r)
        if not run or not run.get("quality_parser"):
            version = r.get("resolved", {}).get("client_version", "unknown")
            if version != "unknown" and not version.startswith("6.1."):
                raise ValueError("Quality collection supports Moonlight Qt 6.1; use the client's Statistics overlay on this version")
            raise ValueError("Reconnect once to enable quality measurements in this client")
        if run.get("measurement", {}).get("status") == "recording":
            return
        run["measurement"] = {"seconds": seconds, "status": "recording", "deadline": self.clock() + seconds,
                              "boot": self.boot, "token": r["token"]}

    def due(self):
        for computer, record in list(self.records.items()):
            for run in list(record["runs"]):
                measurement = run.get("measurement", {})
                if measurement.get("status") != "recording":
                    continue
                r = self.ctl.records.get(computer, {})
                if measurement["boot"] != self.boot or not r.get("desired") or r.get("token") != measurement["token"] or r.get("phase") != "watching":
                    measurement["status"] = "cancelled"
                elif self.clock() >= measurement["deadline"]:
                    measurement["status"] = "collecting"
                    try:
                        self.ctl.command({"command": "reconnect", "computer": computer, "reason": "measurement"})
                    except (ValueError, RuntimeError):
                        measurement["status"] = "cancelled"

    def assess(self, r, value):
        if value not in ("readable", "too-small", "blurry"):
            raise ValueError("readability must be readable, too-small, or blurry")
        run = self.current(r)
        if not run or not r.get("window"):
            raise ValueError("Assess readability while the stream window is ready")
        run["readability"] = {"value": value, "at": self.ctl.now(), "view_size": copy.deepcopy(run.get("view_size"))}

    def report(self, r):
        runs = self.runs(r["computer"])
        current = self.current(r)
        def public(run):
            out = {k: copy.deepcopy(v) for k, v in run.items() if k not in ("token", "previous_token", "boot", "clock_start")}
            if out.get("measurement"):
                out["measurement"] = {k: v for k, v in out["measurement"].items() if k in ("status", "seconds")}
            return out
        # Compare only identical profile settings; a reused profile name is not evidence.
        comparable = [v for v in runs if v["settings_key"] == settings_key(r["settings"])]
        measured = next((v for v in reversed(comparable) if v.get("metrics")), None)
        advice = []
        if measured:
            m = measured["metrics"]
            if m.get("network_drop_pct", 0) > .5 or m.get("jitter_drop_pct", 0) > .5:
                advice.append("Frame loss was measured. Compare a lower bitrate on the same connection before saving a preset.")
            if m.get("decode_ms", 0) > 1000 / r["settings"].get("fps", 60):
                advice.append("Decoding exceeded one frame interval. Compare a lower resolution or hardware decoder.")
        assessment = current.get("readability", {}) if current else {}
        if (assessment.get("view_size") != (current or {}).get("view_size")
                or (current or {}).get("settings_key") != settings_key(r["settings"])):
            assessment = {}
        if assessment.get("value") == "too-small":
            advice.append("Text is too small at this view size. Enlarge the zone or use a larger host UI scale.")
        elif assessment.get("value") == "blurry":
            advice.append("Compare stream resolution and host scaling using the same text sample.")
        version = r.get("resolved", {}).get("client_version", "unknown")
        reason = None if current and current.get("quality_parser") else (
            "Quality collection supports Moonlight Qt 6.1; use the client's Statistics overlay on this version."
            if version != "unknown" and not version.startswith("6.1.") else
            "Reconnect once to enable collection in an existing stream.")
        return {"version": 1, "current": public(current) if current else None,
                "last_measurement": public(measured) if measured else None,
                "history": [public(v) for v in reversed(runs[-5:])],
                "readability": assessment.get("value", "unverified"), "advice": advice,
                "collection_reason": reason,
                "encode_ms": None, "end_to_end_ms": None,
                "limits": "Host processing includes more than encoding. Window-ready timing is not first-frame or end-to-end latency."}
