"""Single-writer, user-session controller for paired Moonlight desktops.

The state file is the write-ahead log: intent precedes host writes and launches.
Each loop performs one bounded step, then accepts the next user command. No
worker can complete after a newer disconnect generation has been accepted.
"""
import argparse
import configparser
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "session"))
from service import Compositor, atomic_json, read_json
from mac_display import same_setting, manages_mode
from scenes import Manager
from audio import host_headset
from quality import Tracker, VideoStats
from browse import Browser
import windows_display

CLASS = "com.moonlight_stream.Moonlight"
TOKEN = "HYPERTILE_STREAM_TOKEN"
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")


def paths():
    home = Path.home()
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / "hypertile/streams"
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "hypertile-stream"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "hypertile/computers.json"
    return state, runtime, config


def load(path, default):
    try:
        return read_json(path)
    except FileNotFoundError:
        return copy.deepcopy(default)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def resolution(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{3,5}x\d{3,5}", value), "resolution must be WIDTHxHEIGHT")
    require(all(240 <= int(n) <= 16384 for n in value.split("x")), "resolution outside supported range")
    return value


def configuration(path):
    value = load(path, {"version": 1, "computers": {}})
    require(value.get("version") == 1 and isinstance(value.get("computers"), dict), "unsupported computers.json schema")
    identities = set()
    for name, computer in value["computers"].items():
        require(NAME.fullmatch(name), "invalid computer ID")
        require(isinstance(computer.get("host"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", computer["host"]), "invalid host")
        require(UUID.fullmatch(computer.get("pairing_uuid", "")), "pairing_uuid must reference a paired Moonlight computer")
        identity = computer["pairing_uuid"].lower()
        require(identity not in identities, "two computers refer to the same pairing identity")
        identities.add(identity)
        require(isinstance(computer.get("title"), str) and 1 <= len(computer["title"]) <= 250, "title must be the final Moonlight window title")
        require(isinstance(computer.get("profiles"), dict) and computer["profiles"], "computer needs profiles")
        require(computer.get("platform", "unknown") in ("macos", "windows", "linux", "unknown"), "invalid host platform")
        for profile_name, p in computer["profiles"].items():
            require(NAME.fullmatch(profile_name), "invalid profile ID")
            resolution(p.get("stream_resolution"))
            require(type(p.get("fps", 60)) is int and 20 <= p.get("fps", 60) <= 240, "invalid FPS")
            require(type(p.get("bitrate", 60000)) is int and 1000 <= p.get("bitrate", 60000) <= 200000, "invalid bitrate")
            require(p.get("codec", "HEVC") in ("HEVC", "H.264", "AV1", "auto"), "invalid codec")
            require(p.get("audio", "focus") in ("focus", "continuous", "host"), "invalid audio policy")
            require(p.get("input", "absolute") in ("absolute", "relative"), "invalid input policy")
            require(p.get("system_keys", "never") in ("never", "fullscreen", "always"), "invalid system key capture policy")
            require(p.get("keep_awake", "visible") in ("visible", "always", "never"), "invalid keep_awake policy")
            require(p.get("aspect", "fit") == "fit", "only aspect=fit is supported")
            require(p.get("decoder", "hardware") in ("hardware", "software", "auto"), "invalid decoder")
            for flag in ("hdr", "yuv444"):
                require(type(p.get(flag, False)) is bool, "invalid " + flag)
            display = p.get("display", {"adapter": "external"})
            require(display.get("adapter") in ("external", "betterdisplay", "macos", "windows"), "unknown display adapter")
            if display["adapter"] == "windows":
                require(computer.get("platform") == "windows", "Windows display adapter requires platform=windows")
                require(windows_display.ALIAS.fullmatch(computer.get("ssh", {}).get("alias", "")), "Windows adapter requires an approved ssh.alias")
                device = display.get("device_id", "")
                require(isinstance(device, str) and 1 <= len(device) <= 512 and device.startswith("\\\\?\\DISPLAY#")
                        and all(ord(c) >= 32 for c in device), "Windows adapter requires a persistent display device_id")
            if display["adapter"] == "betterdisplay":
                require(UUID.fullmatch(display.get("uuid", "")), "display requires a persistent UUID")
                require(type(display.get("follow_main", False)) is bool, "follow_main must be boolean")
                mode = display.get("mode", {})
                resolution(mode.get("resolution"))
                require(type(mode.get("hidpi")) is bool and type(mode.get("refresh")) in (int, float)
                        and 20 <= mode["refresh"] <= 240, "invalid host mode")
            if display["adapter"] in ("betterdisplay", "macos"):
                if display["adapter"] == "macos":
                    require(computer.get("platform") == "macos", "native adapter requires platform=macos")
                    require(display.get("follow_main", True) is True, "native desktop follows the main display")
                    require("mode" not in display and "uuid" not in display, "native desktop preserves the main display mode")
                ssh = computer.get("ssh", {})
                require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", ssh.get("user", "")), "Mac adapter requires ssh.user")
                if "control_path" in ssh:
                    require(isinstance(ssh["control_path"], str) and ssh["control_path"].startswith("/"), "SSH control_path must be absolute")
    return value["computers"]


def moonlight_hosts():
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    c = configparser.ConfigParser(interpolation=None)
    c.read(base / "Moonlight Game Streaming Project/Moonlight.conf")
    hosts = c["hosts"] if c.has_section("hosts") else {}
    result = {}
    for key, value in hosts.items():
        if key.endswith("\\uuid"):
            prefix = key[:-4]
            # Certificate material never leaves Moonlight's own configuration.
            result[value.lower()] = {"name": hosts.get(prefix + "hostname"),
                                      "paired": bool(hosts.get(prefix + "srvcert")),
                                      "address": hosts.get(prefix + "manualaddress")}
    return result


class Host:
    def __init__(self, computer, profile):
        self.computer, self.profile = computer, profile
        self.display = profile.get("display", {"adapter": "external"})

    def remote(self, operation, **values):
        if self.display["adapter"] == "windows":
            return windows_display.remote(self.computer, self.display, operation, **values)
        ssh = self.computer["ssh"]
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=5"]
        if ssh.get("control_path"):
            argv += ["-S", ssh["control_path"]]
        argv += [ssh["user"] + "@" + self.computer["host"], "python3 -"]
        request = {"operation": operation, "adapter": self.display["adapter"], "display_uuid": self.display.get("uuid"),
                   "follow_main": self.display.get("follow_main", self.display["adapter"] == "macos"),
                   "pairing_uuid": self.computer["pairing_uuid"], **values}
        program = "REQUEST = " + repr(request) + "\n" + Path(__file__).with_name("mac_display.py").read_text()
        p = subprocess.run(argv, input=program, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        if p.returncode:
            # SSH diagnostics can contain configuration details; expose a typed error.
            raise ValueError("host-unreachable: SSH unavailable; check the approved account/control socket")
        try:
            result = json.loads(p.stdout)
        except ValueError:
            raise ValueError("display-probe-failed: remote adapter returned invalid data") from None
        if not result.get("ok"):
            raise ValueError(result.get("error", "display operation failed"))
        return result["result"]

    def probe(self, pairing=True):
        info = {"adapter": self.display["adapter"], "permissions": "unknown", "media_path": "unknown"}
        if pairing:
            known = moonlight_hosts().get(self.computer["pairing_uuid"].lower())
            require(known and known["paired"], "pairing-required: pair this UUID in Moonlight first")
            require(shutil.which("moonlight"), "moonlight-missing: install Moonlight Qt")
            version = subprocess.run(["moonlight", "--version"], text=True, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, timeout=4)
            match = re.search(r"Moonlight v?(\d+\.\d+(?:\.\d+)?)", version.stdout)
            info["client_version"] = match[1] if match else "unknown"
            # Address is useful for diagnostics; the actual launch uses the paired
            # UUID so host selection and certificate verification stay in Moonlight.
            try:
                with socket.create_connection((self.computer["host"], 47989), timeout=4):
                    pass
            except OSError:
                raise ValueError("host-unreachable: Sunshine port 47989 unavailable") from None
            info["pairing"] = "configured; certificate checked by Moonlight at connection"
            apps = subprocess.run(["moonlight", "list", self.computer["pairing_uuid"]], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
            require(apps.returncode == 0 and "Desktop" in (line.strip() for line in apps.stdout.splitlines()),
                    "pairing-or-app-required: Moonlight could not list the paired host's Desktop app")
            info["pairing"] = "authenticated app list via Moonlight"
            info["moonlight_saved_address"] = known["address"]
        if self.display["adapter"] == "external":
            return {**info, "restoration": "externally-managed", "display": "externally-managed"}
        observed = self.remote("probe")
        if self.display["adapter"] == "windows":
            require(not observed.get("error"), observed.get("error", "Windows display helper error"))
            return {**info, "display": observed, "restoration": "managed"}
        require(not manages_mode(self.display, observed) or
                any(same_setting("mode", self.display["mode"], m) for m in observed["modes"]),
                "display-mode-unavailable: requested mode is not advertised")
        require(not self.display.get("require_ac", False) or observed["ac_power"], "power-required: connect the Mac to AC")
        return {**info, **observed, "restoration": "managed"}

    def change(self, field, expected, value, **guards):
        return self.remote("change", field=field, expected=expected, value=value, **guards)

    def for_display(self, identity):
        profile = copy.deepcopy(self.profile)
        profile["display"].update(uuid=identity, follow_main=False)
        return Host(self.computer, profile)


def prepare(record, host, persist):
    if host.display["adapter"] == "external":
        return
    if host.display["adapter"] == "windows":
        return windows_display.prepare(record, host, persist)
    observed = host.probe(pairing=False)
    following = host.display.get("follow_main", host.display["adapter"] == "macos")
    desired = {"output": observed["identity"]["displayID"]}
    if manages_mode(host.display, observed):
        desired["mode"] = host.display["mode"]
    recovery = record.get("display_recovery")
    if recovery:
        require(observed.get("topology") == recovery["topology"], "display-topology-changed: lid changed again during recovery")
        for field in desired:
            require(same_setting(field, observed["current"][field], recovery["current"][field])
                    or same_setting(field, observed["current"][field], desired[field]),
                    "restore-conflict: display changed after recovery was requested")
    journal = record.setdefault("journal", {})
    if "mode" not in desired and "mode" in journal:
        # A mode belongs to its physical UUID, never to whichever panel is now
        # primary. Restore the old display when reachable; retain pending work
        # if it has been unplugged or changed independently.
        restore(record, host, persist, fields=("mode",))
        observed = host.probe(pairing=False)
        require(observed["identity"]["displayID"] == desired["output"], "display-topology-changed: main display moved")
    # Capture every baseline before the first mutation. Restarting Sunshine
    # must not turn a side effect into the next setting's "original" value.
    for field in desired:
        current = observed["current"][field]
        if field not in journal and not same_setting(field, current, desired[field]):
            journal[field] = {"original": current, "applied": desired[field], "phase": "intent"}
            if following and field == "mode":
                journal[field]["display_uuid"] = observed["identity"]["UUID"]
    persist()
    for field in desired:
        current = observed["current"][field]
        entry = journal.get(field)
        if entry is None:
            require(same_setting(field, current, desired[field]), "restore-conflict: unchanged setting moved during preparation")
            continue
        if field == "mode" and following:
            require(entry.get("display_uuid", host.display["uuid"]).lower() == observed["identity"]["UUID"].lower(),
                    "display-identity-changed: mode journal belongs to another display")
        if field == "output" and recovery and entry["applied"] != desired[field]:
            require(entry["applied"] == recovery["current"][field], "capture-display-changed: output no longer owned")
            # Follow a new main display or a renewed CoreGraphics ID without
            # replacing the original Sunshine output baseline.
            entry.update(applied=desired[field], phase="intent")
            persist()
        require(same_setting(field, entry["applied"], desired[field]), "display-identity-changed: restore the previous journal first")
        if same_setting(field, current, entry["applied"]):
            entry["phase"] = "applied"  # Recover a crash after the write, before readback.
            persist()
            continue
        expected = recovery["current"][field] if recovery else entry["original"]
        require(same_setting(field, current, expected) and (recovery or entry["phase"] == "intent"),
                "restore-conflict: host setting changed while owned")
        guards = {"expected_identity": observed["identity"]["UUID"]} if following else {}
        host.change(field, current, entry["applied"], **guards)
        observed = host.probe(pairing=False)
        require(observed["identity"]["displayID"] == desired["output"], "display-topology-changed: main display moved")
        require(same_setting(field, observed["current"][field], entry["applied"]), "display-readback-failed: restoration required")
        entry["requested"] = desired[field]
        entry["applied"] = observed["current"][field]
        entry["phase"] = "applied"
        persist()
    if following:
        # Opening/closing a panel can change Sunshine's cached input display
        # even when its numeric output setting needed no write.
        host.remote("refresh", expected_identity=observed["identity"]["UUID"], expected=observed["current"])
    record["resolved"] = {**record.get("resolved", {}), **{k: v for k, v in observed.items() if k != "modes"}}
    record["mac_topology"] = observed.get("topology")
    record.pop("display_recovery", None)
    persist()


def restore(record, host, persist, fields=("mode", "output")):
    if host.display["adapter"] == "windows":
        return windows_display.restore(record, host, persist)
    journal = record.get("journal", {})
    if not journal:
        return True
    # Mode is a compound setting: changing only one component can select another
    # mode. Compare/restore the entire tuple, then the capture output.
    for field in fields:
        entry = journal.get(field)
        if not entry:
            continue
        target = host.for_display(entry.get("display_uuid", host.display["uuid"])) if field == "mode" and host.display.get("follow_main") else host
        try:
            observed = target.remote("probe")
        except ValueError as error:
            if field != "mode" or "display-missing" not in str(error):
                raise
            entry["phase"] = "unavailable"
            persist()
            continue
        current = observed["current"][field]
        if same_setting(field, current, entry["original"]):
            del journal[field]
            persist()
            continue
        recovery = record.get("display_recovery")
        lid_reset = (recovery and observed.get("topology") == recovery["topology"]
                     and same_setting(field, current, recovery["current"][field]))
        if not same_setting(field, current, entry["applied"]) and not lid_reset:
            entry["phase"] = "conflict"
            persist()
            continue
        target.change(field, current, entry["original"])
        observed = target.remote("probe")
        require(same_setting(field, observed["current"][field], entry["original"]), "restore-readback-failed")
        del journal[field]
        persist()
    if not journal:
        record.pop("display_recovery", None)
    return not journal


def stream_argv(computer, p):
    return ["moonlight", "stream", "--resolution", p["stream_resolution"], "--fps", str(p.get("fps", 60)),
            "--bitrate", str(p.get("bitrate", 60000)), "--display-mode", "windowed",
            "--absolute-mouse" if p.get("input", "absolute") == "absolute" else "--no-absolute-mouse",
            "--capture-system-keys", p.get("system_keys", "never"), "--no-quit-after", "--no-game-optimization",
            "--video-codec", p.get("codec", "HEVC"), "--video-decoder", p.get("decoder", "hardware"),
            "--keep-awake" if p.get("keep_awake") == "always" else "--no-keep-awake",
            "--mute-on-focus-loss" if p.get("audio", "focus") == "focus" else "--no-mute-on-focus-loss",
            "--audio-on-host" if p.get("audio") == "host" else "--no-audio-on-host",
            "--hdr" if p.get("hdr") else "--no-hdr", "--yuv444" if p.get("yuv444") else "--no-yuv444",
            computer["pairing_uuid"], "Desktop"]


def log_event(line):
    """Moonlight Qt 6.1 evidence only; raw lines/URLs/keys are never retained."""
    if "://" in line:
        return None
    m = re.search(r"Video stream is (\d+)x(\d+)x(\d+)", line)
    if m:
        return {"negotiated_video": {"width": int(m[1]), "height": int(m[2]), "fps": int(m[3])}}
    if "FFmpeg-based video decoder chosen" in line:
        return {"decoder": "initialized", "video_ready": "unverified"}
    m = re.search(r"Connection terminated: (-?\d+)", line)
    if m:
        return {"terminated": int(m[1])}
    if "Quit event received" in line:
        return {"quit": True}
    if "No video received from host" in line:
        return {"error": "no-video"}
    if "not paired" in line.lower():
        return {"error": "pairing-required"}
    return None


def owned(pid, token):
    if not pid or not token:
        return False
    try:
        proc = Path("/proc") / str(pid)
        return (TOKEN + "=" + token).encode() in (proc / "environ").read_bytes().split(b"\0") and ") Z " not in (proc / "stat").read_text()
    except OSError:
        return False


def launch_job(path):
    """Exec Moonlight in the same PID Hyprland assigned its launch rules to.

    A logger child consumes a pipe; only extracted, typed observations reach disk.
    A per-job lock and the current generation close the dispatch/restart gap.
    """
    job = read_json(path)
    lock = open(path.with_suffix(".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return
    # This lock intentionally survives exec until the stream exits.
    os.set_inheritable(lock.fileno(), True)
    gate = (path.parent / (job["computer"] + ".gate")).open("a")
    fcntl.flock(gate, fcntl.LOCK_EX)
    # The gate is close-on-exec. A disconnect cannot slip between validating
    # intent and publishing this PID, then miss a process that launches late.
    records = read_json(Path(job["state"]))["computers"]
    current = records.get(job["computer"], {})
    if not current.get("desired") or current.get("token") != job["token"]:
        gate.close()
        lock.close()
        return
    atomic_json(path.with_suffix(".pid"), {"pid": os.getpid()})
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        gate.close()
        lock.close()
        os.close(write_fd)
        supported = job.get("client_version", "").startswith("6.1.")
        evidence = {"parser": "moonlight-qt-6.1" if supported else "unsupported-version", "video_ready": "unverified"}
        stats = VideoStats()
        if supported:
            evidence["quality_parser"] = 1
        atomic_json(path.with_suffix(".events"), evidence)
        with os.fdopen(read_fd, errors="replace") as pipe:
            for line in pipe:
                event = log_event(line) if supported else None
                metrics = stats.feed(line) if supported else None
                if metrics:
                    evidence.update(performance=metrics, performance_at=time.time())
                if event:
                    evidence.update(event)
                if event or metrics:
                    atomic_json(path.with_suffix(".events"), evidence)
        evidence["closed"] = True
        atomic_json(path.with_suffix(".events"), evidence)
        os._exit(0)
    os.close(read_fd)
    os.dup2(write_fd, 1)
    os.dup2(write_fd, 2)
    os.close(write_fd)
    os.execvp(job["argv"][0], job["argv"])


class Processes:
    def __init__(self, root, compositor):
        self.root, self.compositor = root, compositor

    def job(self, record):
        return self.root / (record["token"] + ".json")

    def pid(self, record):
        if not record.get("token"):
            return None
        pid = load(self.job(record).with_suffix(".pid"), {}).get("pid")
        return pid if owned(pid, record["token"]) else None

    def events(self, record):
        return load(self.job(record).with_suffix(".events"), {}) if record.get("token") else {}

    def launch(self, record):
        path = self.job(record)
        atomic_json(path, {"state": str(self.root / "state.json"), "token": record["token"],
                          "client_version": record.get("resolved", {}).get("client_version", "unknown"),
                          "computer": record["computer"], "argv": stream_argv(record["config"], record["settings"])})
        wrapper = Path(os.environ["HYPERTILE_SRC"]) / "bin/hypertile-stream" if os.environ.get("HYPERTILE_SRC") else Path.home() / ".local/bin/hypertile-stream"
        cmd = "exec " + shlex.join(["env", TOKEN + "=" + record["token"], str(wrapper), "launch-job", str(path)])
        self.compositor.call("stream_launch", {**record["assignment"], "computer": record["computer"], "command": cmd})

    def stop(self, record, force=False):
        pid = self.pid(record)
        if pid:
            try:
                os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass


class Controller:
    def __init__(self, root, config, compositor, processes=None, host_factory=Host, now=time.time):
        self.root, self.config, self.compositor = root, config, compositor
        self.processes = processes or Processes(root, compositor)
        self.host_factory, self.now = host_factory, now
        self.state = load(root / "state.json", {"version": 1, "computers": {}})
        require(self.state.get("version") == 1, "unsupported stream state version")
        self.records = self.state["computers"]
        self.running = True
        self.applied = {}
        self.inhibitors = {}
        self.scenes = Manager(self, lambda: configuration(self.config))
        self.quality = Tracker(self)
        self.browser = Browser(self)
        for record in self.records.values():
            record.pop("pid", None)  # Reconcile using the token and job's durable PID.
            if record.get("desired") and record.get("instance") != compositor.instance:
                if self.processes.pid(record):
                    self.processes.stop(record)
                record["phase"] = "restart-stop"
                record["observed"] = "reconnecting"
                record["instance"] = compositor.instance
                self.quality.begin(record, "compositor-recovery")
            record["next_at"] = 0
        self.persist()

    def persist(self):
        atomic_json(self.root / "state.json", self.state)

    def public(self, r):
        fields = ("computer", "profile", "generation", "operation", "desired", "observed", "assignment", "error",
                  "attempts", "next_at", "pid", "window", "resolved", "journal", "evidence", "host_health", "audio_health")
        out = {k: r[k] for k in fields if k in r}
        out["version"] = 1
        out["requested"] = {k: v for k, v in r["settings"].items() if k in
                            ("stream_resolution", "fps", "bitrate", "codec", "decoder", "hdr", "yuv444", "input", "system_keys", "audio", "keep_awake", "display")}
        mac = r["config"].get("platform") == "macos" or r["settings"].get("display", {}).get("adapter") in ("betterdisplay", "macos")
        out["clipboard"] = {"state": "unsupported" if mac else "unverified",
                            "reason": "Stock Sunshine on macOS does not implement clipboard text input" if mac else None}
        out["quality"] = self.quality.report(r)
        out["next_actions"] = (["focus", "disconnect"] if r.get("window") else ["retry", "disconnect"]) if r["desired"] else ["connect"]
        if r.get("journal"):
            out["next_actions"] += ["restore", "release --keep-host-settings"]
        return out

    def command(self, request):
        self.browser.before_command(request)
        if request.get("command") not in ("status", "stop"):
            self.finish_swap()
        self.scenes.interrupted(request)
        if request.get("command") in ("connect", "disconnect", "restore", "release", "retry", "reconnect"):
            computer = request.get("computer")
            require(isinstance(computer, str) and NAME.fullmatch(computer), "invalid computer ID")
            with (self.root / (computer + ".gate")).open("a") as gate:
                fcntl.flock(gate, fcntl.LOCK_EX)
                return self._command(request)
        return self._command(request)

    def _command(self, request):
        action, computer = request["command"], request.get("computer")
        if action == "scene":
            return self.scenes.command(request)
        if action == "status":
            if computer:
                require(computer in self.records, "computer has no managed session")
                return self.public(self.records[computer])
            return {"version": 1, "computers": [self.public(r) for r in self.records.values()], "instance": self.compositor.instance}
        if action == "stop":
            self.running = False  # Restart preserves ownership and the running views.
            return {"stopped": True}
        if action == "swap":
            plan = self.compositor.call("stream_swap_plan", {"windows": request["windows"]})
            sources = [w for w in plan["windows"] if w.get("computer")]
            require(sources, "swap requires a managed stream window")
            for w in sources:
                r = self.records.get(w["computer"])
                require(r and r["desired"] and r["phase"] == "watching", "stream is not ready to swap")
                require(r.get("window") == {k: w[k] for k in ("address", "pid", "stable_id")},
                        "stream window identity changed")
                assignment = r["assignment"]
                require(all(assignment.get(k) == v for k, v in
                            {"workspace": plan["workspace"], "layout": plan["layout"], "zone": w["before"]}.items())
                        and (not assignment.get("zone_id") or assignment["zone_id"] == w.get("before_id")),
                        "stream assignment changed")
            self.state["swap"] = {"plan": plan, "instance": self.compositor.instance}
            self.persist()  # Durable before either reservation or local pin changes.
            self.finish_swap()
            return {"swapped": True, "computers": [self.public(self.records[w["computer"]]) for w in sources]}
        if action == "session-restore":
            outcomes = []
            for source in request.get("sources", []):
                # Existing durable intent wins, including an explicit disconnect.
                if source["computer"] not in self.records:
                    try:
                        outcomes.append(self.command({"command": "connect", **source}))
                    except (ValueError, RuntimeError) as error:
                        require(NAME.fullmatch(source["computer"]), "invalid restored computer ID")
                        try:
                            computers = configuration(self.config)
                        except (OSError, ValueError):
                            computers = {}
                        c = computers.get(source["computer"], {})
                        settings = c.get("profiles", {}).get(source["profile"], {})
                        # A fresh controller may start before local windows create
                        # their workspaces. Keep the reference even when it cannot
                        # yet connect, so the next checkpoint cannot erase it.
                        r = {"computer": source["computer"], "profile": source["profile"],
                             "assignment": {k: source[k] for k in ("workspace", "layout", "zone")},
                             "config": c, "settings": settings, "desired": True, "generation": 1,
                             "operation": uuid.uuid4().hex, "instance": self.compositor.instance,
                             "phase": "waiting-workspace" if settings else "unresolved",
                             "observed": "needs-attention", "error": str(error), "attempts": 0,
                             "next_at": 0, "waiting_until": self.now() + 45}
                        self.records[source["computer"]] = r
                        self.persist()
                        outcomes.append(self.public(r))
            self.scenes.restore_refs(request.get("scenes", []))
            return {"sources": outcomes}
        r = self.records.get(computer)
        if action in ("quality", "measure", "readability"):
            require(r, "computer has no managed session")
            if action == "measure":
                require(r["desired"] and r["phase"] == "watching", "Measure while the stream window is ready")
                self.quality.measure(r, request.get("seconds", 30))
            if action == "readability":
                self.quality.assess(r, request["value"])
            if action != "quality":
                self.persist()
            return self.quality.report(r)
        if action == "local":
            require(r and r["desired"] and r.get("window"), "stream has no ready window")
            return self.compositor.call("stream_local", {"computer": computer})
        if action in ("clipboard", "input-release", "stats"):
            require(r and r["desired"] and r.get("window"), "stream has no ready window")
            capability = self.public(r)["clipboard"]
            require(action != "clipboard" or capability["state"] != "unsupported", capability["reason"])
            self.compositor.call("stream_shortcut", {"computer": computer, "action": action})
            return {"sent": action, "computer": computer}
        if action == "profile":
            require(r and r["desired"], "connect this computer before changing its profile")
            return self.scenes.command({"action": "content", "workspace": r["assignment"]["workspace"],
                                       "zone": r["assignment"]["zone"], "type": "stream", "computer": computer,
                                       "profile": request["profile"]})
        if action == "connect":
            computers = configuration(self.config)
            require(computer in computers, "unknown computer; edit computers.json")
            c = computers[computer]
            profile = request.get("profile") or next(iter(c["profiles"]))
            require(profile in c["profiles"], "unknown profile")
            require(request.get("zone"), "connect requires --zone")
            snap = self.compositor.snapshot()
            workspace = str(request.get("workspace") or snap["workspace"])
            ws = next((w for w in snap["workspaces"] if w["selector"] == workspace), None)
            require(ws, "assignment-invalid: workspace must already exist")
            assignment = {"workspace": workspace, "layout": ws["layout"], "zone": request["zone"]}
            if r and r["desired"]:
                require(r["profile"] == profile and all(r["assignment"].get(k) == v for k, v in assignment.items()), "computer already owned; disconnect before changing profile or assignment")
                if r.get("window"):
                    self.compositor.call("stream_focus", {"computer": computer})
                return self.public(r)
            require(not r or (r["phase"] == "idle" and not self.processes.pid(r)), "disconnect is still in progress")
            require(not r or not r.get("journal"), "restore-pending: restore or release existing host settings before connecting")
            for other in self.records.values():
                require(not other["desired"] or other["assignment"] != assignment, "zone already reserved")
            checked = self.compositor.call("stream_check", {**assignment, "computer": computer})
            if isinstance(checked, dict) and checked.get("zone_id"):
                assignment["zone_id"] = checked["zone_id"]
            r = {"computer": computer, "profile": profile, "settings": c["profiles"][profile], "config": c,
                 "assignment": assignment, "generation": (r or {}).get("generation", 0) + 1,
                 "operation": uuid.uuid4().hex, "desired": True, "phase": "preflight", "observed": "preflight",
                 "attempts": 0, "next_at": 0, "instance": self.compositor.instance}
            self.records[computer] = r
            self.quality.begin(r, "connect")
        elif action == "reconnect":
            require(r and r["desired"], "use connect for a disconnected computer")
            if r.get("reconnecting"):
                return self.public(r)
            require(r["phase"] == "watching" and self.processes.pid(r), "stream is not ready; use retry after it stops")
            if request.get("repair_display"):
                host = self.host_factory(r["config"], r["settings"])
                require(host.display["adapter"] == "betterdisplay", "display repair requires a managed Mac display")
                health = host.remote("probe")
                r["display_recovery"] = {"current": health["current"], "topology": health.get("topology")}
            r.update(phase="reconnect-stop", observed="reconnecting", next_at=0, reconnecting=True,
                     stopping_at=self.now(), close_requested=False, error=None,
                     generation=r["generation"] + 1, operation=uuid.uuid4().hex)
            self.quality.begin(r, request.get("reason", "reconnect"))
        elif action in ("disconnect", "restore", "release"):
            require(r, "computer has no managed session")
            if action == "release":
                require(request.get("keep_host_settings"), "release requires --keep-host-settings to acknowledge retained host settings")
                require(not r["desired"] and not self.processes.pid(r), "disconnect before releasing the host journal")
                r["journal"] = {}
                r["observed"], r["phase"], r["error"] = "disconnected", "idle", None
            else:
                r.pop("reconnecting", None)
                r.update(desired=False, generation=r["generation"] + 1, operation=uuid.uuid4().hex,
                         phase="stopping", observed="restoring", next_at=0, stopping_at=self.now(), error=None)
        elif action == "focus":
            require(r and r["desired"], "computer is disconnected")
            self.compositor.call("stream_focus", {"computer": computer})
        elif action == "retry":
            require(r and r["desired"], "use connect for a disconnected computer")
            require(not self.processes.pid(r), "stream is still running; disconnect it first")
            if not r.get("journal"):
                computers = configuration(self.config)
                require(computer in computers and r["profile"] in computers[computer]["profiles"], "configure the saved computer and profile first")
                r["config"] = computers[computer]
                r["settings"] = computers[computer]["profiles"][r["profile"]]
            r.update(phase="preflight", observed="preflight", next_at=0, attempts=0, error=None,
                     token=None, generation=r["generation"] + 1, operation=uuid.uuid4().hex)
            r.pop("reconnecting", None)
            self.quality.begin(r, "retry")
        else:
            raise ValueError("unknown stream command")
        self.persist()
        return self.public(r)

    def finish_swap(self):
        pending = self.state.get("swap")
        if not pending:
            return
        plan = pending["plan"]
        if pending["instance"] != self.compositor.instance:
            # Window references cannot be replayed into a new compositor.
            self.state.pop("swap")
            self.persist()
            return
        try:
            self.compositor.call("stream_swap_apply", plan)
        except RuntimeError as error:
            if "swap unavailable:" in str(error):
                self.compositor.call("stream_swap_cancel", plan)
                self.state.pop("swap")
                self.applied.clear()
                self.persist()
            raise
        # Assignment edits do not change the launch generation/token, profile,
        # PID or host restoration journal. An IPC retry applies absolute zones.
        for w in plan["windows"]:
            if w.get("computer"):
                r = self.records[w["computer"]]
                r["assignment"]["zone"] = w["zone"]
                if w.get("zone_id"):
                    r["assignment"]["zone_id"] = w["zone_id"]
                else:
                    r["assignment"].pop("zone_id", None)
                self.applied.pop(w["computer"], None)
        self.scenes.swapped()
        self.state.pop("swap")
        self.persist()

    def assign(self, r, window=None):
        args = {**r["assignment"], "computer": r["computer"], "profile": r["profile"], "title": r["config"]["title"]}
        if window:
            args.update({k: window[k] for k in ("address", "pid", "stable_id", "title")})
            previous = r.get("window", {})
            args["placed"] = all(previous.get(k) == window[k] for k in ("address", "pid", "stable_id"))
        if self.applied.get(r["computer"]) != args:
            self.compositor.call("stream_assign", args)
            if window:
                args["placed"] = True
            self.applied[r["computer"]] = args

    def release_zone(self, r):
        self.compositor.call("stream_release", {"computer": r["computer"]})
        self.applied.pop(r["computer"], None)
        r.pop("window", None)

    def failure(self, r, error):
        r["error"] = str(error)
        if "host-unreachable" in str(error) and r["desired"] and r.get("attempts", 0) < 3:
            r["attempts"] = r.get("attempts", 0) + 1
            r.update(phase="preflight", observed="reconnecting", next_at=self.now() + (2, 5, 15)[r["attempts"] - 1])
        else:
            r.update(phase="failed-restore", observed="needs-attention", next_at=0)

    def step(self, r, snap):
        phase, now = r["phase"], self.now()
        if r.get("next_at", 0) > now:
            return
        pid = self.processes.pid(r)
        r["pid"] = pid
        if pid:
            r.pop("missing_since", None)
        else:
            r.setdefault("missing_since", now)
        evidence = self.processes.events(r)
        # SDL's explicit quit can precede logger EOF (a helper may retain the
        # pipe). Don't turn a normal close into launch uncertainty in that gap.
        if r["desired"] and phase != "reconnect-stop" and not pid and evidence.get("quit") and "terminated" not in evidence:
            self.command({"command": "disconnect", "computer": r["computer"]})
            phase = r["phase"]
        if phase == "restart-stop":
            if pid:
                self.processes.stop(r, force=True)
                return
            r.update(phase="waiting-workspace", token=None, next_at=0, waiting_until=now + 45)
            return
        if not r["desired"]:
            self.release_zone(r)
            if (phase == "idle" and r.get("journal", {}).get("windows")
                    and now >= r.get("next_restore_check", 0)):
                r["phase"] = "restoring"
            if phase == "stopping":
                if pid:
                    self.processes.stop(r, force=now - r["stopping_at"] > 5)
                    return
                r["phase"] = "restoring"
            if r["phase"] == "restoring":
                try:
                    done = restore(r, self.host_factory(r["config"], r["settings"]), self.persist)
                    r["next_restore_check"] = now + 5
                    r.update(phase="idle", observed="disconnected" if done else "restore-pending",
                             error=None if done else ((r.get("resolved", {}).get("display", {}).get("error") or "physical-display-restoration-pending: open the lid or attach a monitor")
                                                      if r.get("journal", {}).get("windows") else "restore-conflict: manual changes preserved"))
                except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                    r["next_restore_check"] = now + 10
                    r.update(phase="idle", observed="restore-pending", error=str(error))
            return
        if phase == "reconnect-stop":
            if pid:
                if not r.get("close_requested"):
                    # Persist first: a repeated close after a lost reply is harmless.
                    r["close_requested"] = True
                    self.persist()
                    self.compositor.call("stream_close", {"computer": r["computer"]})
                elif now - r["stopping_at"] > 5:
                    self.processes.stop(r, force=now - r["stopping_at"] > 8)
                return
            if not evidence.get("closed") and now - r["stopping_at"] < 8:
                return  # Give the logger time to publish its final decoder summary.
            r.pop("window", None)
            r.update(token=None, phase="preflight", observed="reconnecting", next_at=0)
            self.assign(r)  # Keep the zone reserved while the client restarts.
            return
        if phase == "unresolved":
            return
        if phase == "waiting-workspace":
            if any(w["selector"] == r["assignment"]["workspace"] for w in snap["workspaces"]):
                r.update(phase="preflight", observed="preflight", error=None)
            elif now > r["waiting_until"]:
                raise ValueError("assignment-invalid: workspace did not return during session recovery")
            return
        if phase == "attention" and r.get("journal", {}).get("windows"):
            if now >= r.get("next_restore_check", 0):
                r["next_restore_check"] = now + 10
                done = restore(r, self.host_factory(r["config"], r["settings"]), self.persist)
                r["observed"] = "needs-attention" if done else "restore-pending"
            return  # Finishing recovery never restarts a failed stream.
        if phase == "failed-restore":
            if pid:
                r.setdefault("stopping_at", now)
                self.processes.stop(r, force=now - r["stopping_at"] > 5)
                return
            done = restore(r, self.host_factory(r["config"], r["settings"]), self.persist)
            r["next_restore_check"] = now + 5
            r.update(phase="attention", observed="needs-attention" if done else "restore-pending")
            return
        # Re-establish reservations after a compositor reload, even when offline.
        known = {s["computer"]: s for s in snap.get("streams", [])}
        if r["computer"] not in known:
            self.applied.pop(r["computer"], None)
            self.inhibitors.pop(r["computer"], None)
        checked = self.compositor.call("stream_check", {**r["assignment"], "computer": r["computer"]})
        if isinstance(checked, dict) and checked.get("zone") != r["assignment"]["zone"]:
            r["assignment"]["zone"] = checked["zone"]
            self.applied.pop(r["computer"], None)
        if phase == "preflight":
            self.assign(r)
            # Don't compete with a manually launched view of this host.
            require(not any(w["class"] == CLASS and w["title"] == r["config"]["title"] and w.get("pid") != pid
                            for w in snap["windows"]), "unmanaged-stream: close the existing view before connecting")
            info = self.host_factory(r["config"], r["settings"]).probe()
            r["resolved"] = {k: v for k, v in info.items() if k != "modes"}
            r.update(phase="preparing", observed="preparing-display", error=None)
        elif phase == "preparing":
            self.assign(r)
            prepare(r, self.host_factory(r["config"], r["settings"]), self.persist)
            r.update(phase="launch", observed="connecting")
            r["next_host_probe"] = now + (5 if r["settings"].get("display", {}).get("adapter") in ("betterdisplay", "macos") else 30)
        elif phase == "launch":
            # The token and launch intent survive a dispatch timeout or crash.
            if not r.get("token") or self.processes.events(r).get("closed"):
                r["token"] = uuid.uuid4().hex
            r.update(phase="connecting", observed="connecting", launched_at=now)
            self.persist()
            if not pid:
                self.processes.launch(r)
        elif phase in ("connecting", "watching"):
            evidence = self.processes.events(r)
            r["evidence"] = evidence
            windows = [w for w in snap["windows"] if w.get("pid") == pid and w["class"] == CLASS] if pid else []
            final = [w for w in windows if w["title"] == r["config"]["title"]]
            if len(final) == 1:
                w = final[0]
                if w.get("workspace") != r["assignment"]["workspace"]:
                    self.applied.pop(r["computer"], None)
                self.assign(r, w)
                r["window"] = {k: w[k] for k in ("address", "pid", "stable_id")}
                r.update(phase="watching", observed="window-ready", error=None)
                r.pop("reconnecting", None)
                if r["settings"].get("audio") == "host" and now >= r.get("next_audio_check", 0):
                    r["audio_health"] = host_headset(pid)
                    r["next_audio_check"] = now + 5
                if r["settings"].get("display", {}).get("adapter") == "windows" and now >= r.get("next_host_probe", 0):
                    r["next_host_probe"] = now + 15
                    try:
                        health = self.host_factory(r["config"], r["settings"]).remote("status")
                    except (ValueError, subprocess.TimeoutExpired) as error:
                        r["host_health"] = {"state": "unknown", "error": str(error)}
                    else:
                        require(not health.get("error"), health.get("error", "Windows display helper error"))
                        require(health.get("phase") in ("preparing", "streaming"), "display-restored: reconnect the Windows stream")
                        r["host_health"] = {"state": "checked", "at": now}
                if r["settings"].get("display", {}).get("adapter") in ("betterdisplay", "macos") and now >= r.get("next_host_probe", 0):
                    r["next_host_probe"] = now + 5
                    host = self.host_factory(r["config"], r["settings"])
                    try:
                        health = host.remote("probe")
                    except ValueError as error:
                        if "host-unreachable" not in str(error):
                            raise
                        r["host_health"] = {"state": "unknown", "error": str(error)}
                    except subprocess.TimeoutExpired:
                        r["host_health"] = {"state": "unknown", "error": "SSH probe timed out"}
                    else:
                        require(not host.display.get("require_ac") or health["ac_power"], "power-required: host lost AC power")
                        before, after = r.get("mac_topology") or {}, health.get("topology") or {}
                        lid_changed = (type(before.get("lid_closed")) is bool and type(after.get("lid_closed")) is bool
                                       and before["lid_closed"] != after["lid_closed"])
                        following = host.display.get("follow_main", host.display["adapter"] == "macos")
                        capture_changed = following and before and (
                            before.get("display_id") != after.get("display_id") or
                            before.get("display_uuid") != after.get("display_uuid"))
                        unmanaged_mode_changed = (following and not manages_mode(host.display, health) and
                            not same_setting("mode", health["current"]["mode"], r["resolved"]["current"]["mode"]))
                        if lid_changed or capture_changed or unmanaged_mode_changed:
                            require(health["current"]["output"] == r["resolved"]["current"]["output"],
                                    "capture-display-changed: capture output changed during lid transition")
                            r["display_recovery"] = {"current": health["current"], "topology": health["topology"]}
                            self.command({"command": "reconnect", "computer": r["computer"],
                                          "reason": "main-display-change" if following else "lid-change"})
                            return  # Stop the local client before refreshing Sunshine's display/input state.
                        require(health["current"]["output"] == health["identity"]["displayID"], "capture-display-changed: check Sunshine configuration")
                        r["mac_topology"] = health.get("topology")
                        r["host_health"] = {"state": "checked", "at": now}
                        if manages_mode(host.display, health) and not same_setting("mode", health["current"]["mode"], host.display["mode"]):
                            r["host_health"] = {"state": "unknown", "error": "display-mode-changed: use reconnect --repair-display to restore the stream size"}
                        r["resolved"].update({k: v for k, v in health.items() if k != "modes"})
                if r.get("host_health", {}).get("state") == "unknown":
                    r["observed"] = "degraded"
            elif windows:
                self.assign(r)
                r["observed"] = "startup-window"
            else:
                r.pop("window", None)
                self.assign(r)
            if evidence.get("closed") and not pid:
                # Unknown/abnormal exits never trigger automatic reconnect. Only
                # explicit Moonlight connection-loss codes are retry candidates.
                code = evidence.get("terminated")
                if code == -100 and r.get("attempts", 0) < 3:
                    r["token"] = None
                    self.quality.begin(r, "network-recovery")
                    self.failure(r, ValueError("host-unreachable: Moonlight connection lost"))
                elif evidence.get("quit") and code is None:
                    self.command({"command": "disconnect", "computer": r["computer"]})
                else:
                    r.update(phase="failed-restore", observed="needs-attention", error="stream-exited: retry or disconnect")
            elif not pid and now - r["missing_since"] > (15 if phase == "connecting" else 3):
                r.update(phase="failed-restore", observed="needs-attention", error="launch-uncertain: retry or disconnect")
            elif not final and now - r["launched_at"] > 60:
                self.processes.stop(r)
                r.update(phase="failed-restore", observed="needs-attention", error="window-timeout: check Moonlight and host permissions")
        else:
            self.assign(r)

    def tick(self):
        self.browser.tick()
        self.finish_swap()
        before = json.dumps(self.state, sort_keys=True)
        self.quality.harvest()
        self.quality.due()
        self.scenes.tick()
        snap = self.compositor.snapshot()
        for r in self.records.values():
            if r["assignment"]["workspace"] in self.browser.active or self.scenes.blocks(r["computer"]):
                continue
            phase, started = r["phase"], self.quality.clock()
            try:
                self.step(r, snap)
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as error:
                if r["phase"] in ("failed-restore", "attention") or "assignment-invalid" in str(error):
                    if self.processes.pid(r):
                        self.processes.stop(r)
                    if "assignment-invalid" in str(error):
                        self.release_zone(r)
                    r.update(phase="attention" if r["phase"] == "failed-restore" else "failed-restore",
                             observed="needs-attention", error=str(error))
                elif not r["desired"]:
                    r.update(phase="idle", observed="restore-pending", error=str(error))
                else:
                    self.failure(r, error)
            finally:
                self.quality.observe(r, phase, started, snap)
        if before != json.dumps(self.state, sort_keys=True):
            self.persist()
        self.keep_awake(snap)

    def keep_awake(self, snap):
        visible = {w["selector"] for w in snap["workspaces"] if w.get("visible")}
        for r in self.records.values():
            if not r.get("window"):
                self.inhibitors.pop(r["computer"], None)
                continue
            policy = r["settings"].get("keep_awake", "visible")
            needed = r["desired"] and (policy == "always" or (policy == "visible" and r["assignment"]["workspace"] in visible))
            value = (r["window"]["stable_id"], needed)
            if self.inhibitors.get(r["computer"]) != value:
                self.compositor.call("stream_inhibit", {"computer": r["computer"], "enabled": needed})
                self.inhibitors[r["computer"]] = value

    def tick_interval(self):
        # Observe transitions promptly; keep retry backoff and steady polling.
        moving = {"preflight", "preparing", "launch", "connecting", "reconnect-stop",
                  "stopping", "restoring", "restart-stop", "failed-restore"}
        return .2 if any(r["phase"] in moving and r.get("next_at", 0) <= self.now()
                         for r in self.records.values()) else 1


def request(runtime, payload, timeout=55):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout)
        client.connect(str(runtime / "control.sock"))
        client.sendall(json.dumps(payload).encode() + b"\n")
        data = bytearray()
        while not data.endswith(b"\n") and len(data) < 2_000_000:
            part = client.recv(65536)
            if not part:
                break
            data.extend(part)
        result = json.loads(data)
        require(result.get("ok"), result.get("error", "controller request failed"))
        return result["result"]


def daemon(root, runtime, config):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(runtime, 0o700)
    with (root / "writer.lock").open("w") as lock:
        instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        require(instance, "start the controller inside the Hyprland session")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            previous = request(runtime, {"command": "status"})
            if previous.get("instance") == instance:
                return
            alive = subprocess.run(["hyprctl", "-i", previous["instance"], "version"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            require(alive.returncode != 0, "stream controller belongs to another running compositor")
            request(runtime, {"command": "stop"})
            for _ in range(50):
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.1)
            else:
                raise ValueError("previous stream controller has not stopped")
        controller = Controller(root, config, Compositor(instance, runtime))
        def stop(*_):
            controller.running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        path = runtime / "control.sock"
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(16)
            try:
                next_tick = 0
                while controller.running:
                    if select.select([server], [], [], min(.2, max(0, next_tick - time.monotonic())))[0]:
                        with server.accept()[0] as client:
                            client.settimeout(2)
                            try:
                                data = bytearray()
                                while not data.endswith(b"\n") and len(data) < 65536:
                                    part = client.recv(8192)
                                    if not part:
                                        break
                                    data.extend(part)
                                result = {"ok": True, "result": controller.command(json.loads(data))}
                            except Exception as error:
                                result = {"ok": False, "error": str(error)}
                            try:
                                client.sendall(json.dumps(result).encode() + b"\n")
                            except OSError:
                                pass  # Intent remains durable if the CLI disconnects.
                    if time.monotonic() >= next_tick:
                        try:
                            controller.tick()
                        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                            # A compositor outage must not erase sources or launch duplicates.
                            controller.applied.clear()
                        next_tick = time.monotonic() + controller.tick_interval()
            finally:
                path.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    root, runtime, config = paths()
    parser = argparse.ArgumentParser(description="Manage paired remote desktops in Hypertile zones")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("daemon", "stop", "computers"):
        p = commands.add_parser(name)
        p.add_argument("--json", action="store_true")
    p = commands.add_parser("launch-job", help=argparse.SUPPRESS)
    p.add_argument("path", type=Path)
    p = commands.add_parser("swap", help="exchange two ready windows; normally invoked by Super+Shift+Arrow")
    p.add_argument("address")
    p.add_argument("stable_id", type=int)
    p.add_argument("target")
    p.add_argument("target_stable_id", type=int)
    p.add_argument("--json", action="store_true")
    p = commands.add_parser("scene", help="save and apply workspace scenes")
    subs = p.add_subparsers(dest="action", required=True)
    for action in ("list", "show", "save", "validate", "apply", "current", "restore", "cancel", "retry", "remove", "catalog", "content", "layout", "browse", "browse-end"):
        child = subs.add_parser(action)
        if action in ("show", "save", "apply", "remove", "layout", "browse"):
            child.add_argument("name")
        if action in ("browse", "browse-end", "catalog"):
            child.add_argument("--browse-token", required=action != "catalog")
        if action in ("validate", "save"):
            child.add_argument("--file")
        if action == "content":
            child.add_argument("--zone", required=True)
            child.add_argument("--type", choices=("local", "stream", "empty"), required=True)
            child.add_argument("--computer")
            child.add_argument("--profile")
            child.add_argument("--app-class")
        child.add_argument("--workspace")
        child.add_argument("--json", action="store_true")
    for name in ("probe", "connect", "focus", "disconnect", "status", "retry", "restore", "release", "profile", "clipboard", "input-release", "stats", "local", "reconnect", "quality", "measure", "readability"):
        p = commands.add_parser(name)
        p.add_argument("computer", nargs="?" if name == "status" else None)
        p.add_argument("--json", action="store_true")
        if name in ("probe", "connect", "profile"):
            p.add_argument("--profile", required=name == "profile")
        if name == "connect":
            p.add_argument("--zone", required=True)
            p.add_argument("--workspace")
        if name == "release":
            p.add_argument("--keep-host-settings", action="store_true")
        if name == "measure":
            p.add_argument("--seconds", type=int, default=30)
        if name == "reconnect":
            p.add_argument("--repair-display", action="store_true", help="explicitly restore the managed Mac display mode")
        if name == "readability":
            p.add_argument("value", choices=("readable", "too-small", "blurry"))
    args = parser.parse_args()
    if args.command == "swap":
        args.windows = [{"address": args.address, "stable_id": args.stable_id},
                        {"address": args.target, "stable_id": args.target_stable_id}]
    try:
        if args.command == "scene" and getattr(args, "file", None):
            args.document = json.loads(sys.stdin.read() if args.file == "-" else Path(args.file).read_text())
        if args.command == "scene" and args.action == "validate":
            require(getattr(args, "document", None), "validate requires --file FILE (or - for stdin)")
        if args.command == "launch-job":
            launch_job(args.path)
            return
        if args.command == "daemon":
            daemon(root, runtime, config)
            return
        if args.command == "computers":
            computers = configuration(config)
            paired = moonlight_hosts()
            result = {"config": str(config), "computers": [{"computer": k, "host": v["host"],
                      "pairing_uuid": v["pairing_uuid"], "paired": paired.get(v["pairing_uuid"].lower(), {}).get("paired", False),
                      "profiles": list(v["profiles"])} for k, v in computers.items()]}
        elif args.command == "probe":
            computers = configuration(config)
            require(args.computer in computers, "unknown computer")
            c = computers[args.computer]
            profile = args.profile or next(iter(c["profiles"]))
            require(profile in c["profiles"], "unknown profile")
            result = {"computer": args.computer, "profile": profile, **Host(c, c["profiles"][profile]).probe()}
        else:
            if args.command not in ("status", "stop"):
                try:
                    request(runtime, {"command": "status"}, timeout=1)
                except (OSError, ValueError):
                    subprocess.Popen([sys.executable, str(Path(sys.argv[0]).resolve()), "daemon"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    for _ in range(50):
                        try:
                            request(runtime, {"command": "status"}, timeout=.2)
                            break
                        except (OSError, ValueError):
                            time.sleep(.1)
            result = request(runtime, vars(args))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
        elif "computers" in result:
            for r in result["computers"]:
                print(r["computer"], r.get("observed", "paired" if r.get("paired") else "pairing-required"),
                      r.get("profile", ", ".join(r.get("profiles", []))), sep="\t")
        else:
            print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("hypertile-stream: " + str(error), file=sys.stderr)
        if args.command == "swap" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "Hypertile swap", str(error)], check=False)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
