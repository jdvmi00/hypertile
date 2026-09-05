"""Hypertile session service: one writer, bounded checkpoints, guarded restore.

Only the compositor adapter knows Lua. Store owns durable state; Recovery owns
matching and launches; Service serializes IPC, capture and lifecycle transitions.
No third-party Python dependencies.
"""
import argparse
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import streams


def atomic_json(path, value):
    """Publish a complete, durable generation, including the directory entry."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    with path.open() as stream:
        return json.load(stream)


def notify(summary, body, urgency="normal"):
    """Desktop notification plus stderr; the menu runs actions without a terminal."""
    print(f"hypertile-session: {summary}: {body}", file=sys.stderr)
    try:
        subprocess.run(["notify-send", "--app-name=Hypertile", "--urgency=" + urgency, summary, body],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def validate(record):
    if not isinstance(record, dict) or record.get("version") != 1:
        raise ValueError("unsupported session format")
    data = record["desktop"]
    for field in ("windows", "workspaces", "monitors"):
        if not isinstance(data[field], list):
            raise ValueError(f"invalid session {field}")
    if not isinstance(data["layouts"], dict):
        raise ValueError("invalid session layouts")
    addresses = set()
    for window in data["windows"]:
        if window["address"] in addresses:
            raise ValueError("duplicate session window")
        addresses.add(window["address"])
        for field in ("address", "class", "initial_class", "title", "workspace"):
            if not isinstance(window[field], str):
                raise ValueError(f"invalid window {field}")
        for field in ("at", "size"):
            for axis in ("x", "y"):
                if not isinstance(window[field][axis], (int, float)):
                    raise ValueError(f"invalid window {field}")
    return record


class Store:
    def __init__(self, root):
        self.root = root
        root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def named(self, name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            raise ValueError("session names use letters, digits, underscores and hyphens")
        return self.root / "saved" / (name + ".json")

    def load(self, name=None):
        if name and re.fullmatch(r"@previous-[123]", name):
            paths = [self.root / (name[1:] + ".json")]
        else:
            paths = [self.named(name)] if name else [self.root / n for n in ("latest.json", "previous-1.json", "previous-2.json", "previous-3.json")]
        errors = []
        for path in paths:
            try:
                return validate(read_json(path))
            except FileNotFoundError:
                continue
            except (ValueError, KeyError, TypeError) as error:
                errors.append(f"{path.name}: {error}")
        if errors:
            raise ValueError("no valid recovery snapshot: " + "; ".join(errors))
        if name:
            raise ValueError(f"no saved session {name}")
        return None

    # Generations are promoted only when the outgoing latest is this much newer
    # than previous-1. Title changes checkpoint every few seconds; rotating on
    # each of them would let a close-all storm flush every generation before
    # the compositor exits. Spacing bounds the loss to this many seconds.
    SPACING = 120

    def generation(self, name):
        try:
            return validate(read_json(self.root / name))
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return None

    def checkpoint(self, record):
        # Copies preserve the last valid generation even if power fails halfway
        # through rotation. The newest generation is published last.
        latest, previous = self.generation("latest.json"), self.generation("previous-1.json")
        def saved_at(value):
            stamp = value.get("saved_at")
            return stamp if isinstance(stamp, (int, float)) else 0
        if latest and (previous is None or saved_at(latest) - saved_at(previous) >= self.SPACING):
            for source, destination in (("previous-2.json", "previous-3.json"),
                                        ("previous-1.json", "previous-2.json")):
                old = self.generation(source)
                if old:
                    atomic_json(self.root / destination, old)
            atomic_json(self.root / "previous-1.json", latest)
        atomic_json(self.root / "latest.json", record)

    def status(self, **values):
        atomic_json(self.root / "status.json", values)


def lua_string(value):
    # Lua has decimal byte escapes; JSON's \uXXXX is not Lua string syntax.
    return '"' + ''.join('\\' + c if c in '\\"' else f"\\{ord(c):03d}" if ord(c) < 32 else c for c in value) + '"'


class Compositor:
    def __init__(self, instance, runtime):
        self.instance = instance
        self.runtime = runtime
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)

    def call(self, method, value=None):
        fd, name = tempfile.mkstemp(prefix="query-", dir=self.runtime)
        request, answer = Path(name), Path(name + ".answer")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, ensure_ascii=False)
            # Module and method names are constants in this program. All data
            # crosses as JSON files, never interpolated executable Lua/shell.
            code = ("local j=require('hypr.hypertile-json'); "
                    f"local f=assert(io.open({lua_string(str(request))})); "
                    "local v=j.decode(f:read('a')); f:close(); "
                    f"local result=require('hypr.hypertile-session').{method}(v); "
                    f"local out=assert(io.open({lua_string(str(answer))},'w')); "
                    "out:write(j.encode(result)); out:close()")
            result = subprocess.run(["hyprctl", "-i", self.instance, "eval", code],
                                    text=True, capture_output=True, timeout=5)
            if result.returncode or not answer.exists():
                raise RuntimeError((result.stderr or result.stdout).strip() or "compositor query failed")
            return read_json(answer)
        finally:
            request.unlink(missing_ok=True)
            answer.unlink(missing_ok=True)

    def snapshot(self):
        return self.call("snapshot")


class Launchers:
    """Explicit recipes first; desktop entry identity second. Never replay cmdline."""
    def __init__(self, config, proc=Path("/proc")):
        self.apps = config.get("apps", {})
        # Terminal foreground commands the user has declared safe to run again
        # (for example a TUI that re-attaches to its own server). Anything else
        # comes back as a plain shell: replaying arbitrary commands would rerun
        # builds and scripts.
        self.replay = config.get("replay", [])
        if not isinstance(self.replay, list) or not all(isinstance(r, str) for r in self.replay):
            raise ValueError("replay must be an array of command names")
        self.proc = proc
        self.entries = {}
        directories = [Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")]
        directories += [Path(p) for p in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")]
        seen = set()
        for directory in directories:
            base = directory / "applications"
            for path in sorted(base.rglob("*.desktop")):
                desktop_id = str(path.relative_to(base)).replace("/", "-")
                if desktop_id in seen:
                    continue
                seen.add(desktop_id)
                entry = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    entry.read(path)
                    app = entry["Desktop Entry"]
                    if app.get("Type") != "Application" or app.getboolean("Hidden", fallback=False):
                        continue
                    keys = [desktop_id[:-len(".desktop")], app.get("StartupWMClass", "")]
                    for key in keys:
                        if key:
                            self.entries.setdefault(key.casefold(), []).append(str(path))
                except (configparser.Error, KeyError, ValueError):
                    continue

    def recipe(self, window):
        if window.get("stream"):
            return None
        cls = window["initial_class"] or window["class"]
        explicit = self.apps.get(cls, self.apps.get(window["class"]))
        if explicit is False:
            return None
        if explicit is not None:
            argv = explicit["argv"]
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise ValueError(f"apps.{cls}.argv must be a nonempty array of strings")
            return {"argv": argv, "per_window": explicit.get("per_window", False)}
        # Browser owns the tabs and profiles. Only carry profile selectors;
        # startup URLs, remote-debugging flags and arbitrary process args are
        # deliberately not replayed.
        browsers = {"google-chrome": "google-chrome-stable", "chromium": "chromium",
                    "google-chrome-beta": "google-chrome-beta", "google-chrome-unstable": "google-chrome-unstable"}
        if cls.casefold() in browsers:
            argv = [browsers[cls.casefold()], "--restore-last-session"]
            try:
                args = Path(f"/proc/{window['pid']}/cmdline").read_bytes().decode().split("\0")
                for i, argument in enumerate(args):
                    if argument.startswith(("--profile-directory=", "--user-data-dir=")):
                        argv.append(argument)
                    elif argument in ("--profile-directory", "--user-data-dir") and i + 1 < len(args):
                        argv.extend([argument, args[i + 1]])
            except (OSError, UnicodeError):
                pass
            return {"argv": argv, "per_window": False}
        webapp = self.webapp(window)
        if webapp:
            return webapp
        # executable, working-directory option, and how a command follows
        # (an -e flag, or positional arguments).
        terminals = {"com.mitchellh.ghostty": ["ghostty", "--working-directory=", "-e"],
                     "alacritty": ["alacritty", "--working-directory", "-e"],
                     "kitty": ["kitty", "--directory", None], "foot": ["foot", "--working-directory=", None]}
        if cls.casefold() in terminals:
            # A single shell child gives an unambiguous terminal cwd. Shared
            # terminal servers with several children need explicit recipes.
            executable, option, flag = terminals[cls.casefold()]
            cwd, command = None, None
            shell = self.single_shell(window["pid"])
            if shell:
                cwd = self.cwd(shell)
                job = self.foreground(shell)
                if job and os.path.basename(job["argv"][0]) in self.replay:
                    command, cwd = job["argv"], job["cwd"] or cwd
            argv = [executable]
            if cwd:
                argv += [option + cwd] if option.endswith("=") else [option, cwd]
            if command:
                argv += ([flag] if flag else []) + command
            return {"argv": argv, "per_window": True}
        candidates = set(self.entries.get(cls.casefold(), []))
        if len(candidates) == 1:
            return {"argv": ["gio", "launch", candidates.pop()], "per_window": False}
        return None

    def single_shell(self, pid):
        """The terminal's only child, or None. Multi-threaded terminals fork the
        shell from a worker thread, so every task's children count."""
        children = []
        try:
            for task in (self.proc / str(pid) / "task").iterdir():
                children += (task / "children").read_text().split()
        except OSError:
            return None
        return children[0] if len(children) == 1 else None

    def cwd(self, pid):
        try:
            return os.readlink(self.proc / str(pid) / "cwd")
        except OSError:
            return None

    def foreground(self, shell):
        """argv and cwd of the shell's foreground job, or None when it is idle."""
        try:
            stat = (self.proc / str(shell) / "stat").read_text()
            # Fields after the parenthesised comm: state ppid pgrp session tty_nr tpgid ...
            tpgid = stat[stat.rindex(")") + 2:].split()[5]
            if int(tpgid) <= 0 or tpgid == str(shell):
                return None
            argv = (self.proc / tpgid / "cmdline").read_bytes().decode().split("\0")
        except (OSError, ValueError, IndexError, UnicodeError):
            return None
        if argv and argv[-1] == "":
            argv.pop()
        if not argv or not argv[0]:
            return None
        return {"argv": argv, "cwd": self.cwd(tpgid)}

    def webapp(self, window):
        """Chromium-family app windows (--app=URL) carry their URL in the class:
        chrome-<host>_<path with / as _>-<profile>. The browser's own session
        restore does not bring them back; Omarchy launches them through
        omarchy-launch-webapp, which picks the default browser."""
        cls = window["initial_class"] or window["class"]
        if not cls.startswith("chrome-") or "-" not in cls[7:]:
            return None
        app, profile = cls[7:].rsplit("-", 1)
        if "_" not in app:
            return None
        host, path = app.split("_", 1)
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or not re.fullmatch(r"[A-Za-z0-9._~%-]*", path):
            return None
        url = f"https://{host}/" + path.replace("_", "/").lstrip("/")
        if shutil.which("omarchy-launch-webapp"):
            argv = ["omarchy-launch-webapp", url]
        else:
            # The window's process is the browser itself; its executable is
            # the only process argument replayed.
            try:
                executable = Path(f"/proc/{window['pid']}/cmdline").read_bytes().split(b"\0")[0].decode()
            except (OSError, UnicodeError):
                return None
            if not executable:
                return None
            argv = [executable, "--app=" + url]
        return {"argv": argv + ["--profile-directory=" + profile], "per_window": True}

    def capture(self, desktop):
        for window in desktop["windows"]:
            window["launch"] = self.recipe(window)
        return desktop


def match_windows(saved, current, matches, same_instance=False):
    """Match uniquely, allowing titles to settle. Never guess between peers."""
    available = {w["address"]: w for w in current if w["address"] not in matches.values()}
    pending = [w for w in saved if w["address"] not in matches]
    if same_instance:
        for old in pending[:]:
            live = available.get(old["address"])
            if live and live.get("stable_id") == old.get("stable_id") and live["pid"] == old["pid"]:
                matches[old["address"]] = live["address"]
                del available[live["address"]]
                pending.remove(old)
    def identity(w):
        return w["initial_class"] or w["class"]
    for field in ("title", "initial_title", None):
        for old in pending[:]:
            if field and not old.get(field):
                continue
            peers = [w for w in pending if identity(w) == identity(old) and (not field or w.get(field) == old.get(field))]
            candidates = [w for w in available.values() if identity(w) == identity(old) and (not field or w.get(field) == old.get(field))]
            if len(peers) == len(candidates) == 1:
                live = candidates[0]
                matches[old["address"]] = live["address"]
                del available[live["address"]]
                pending.remove(old)
    return matches


class Recovery:
    def __init__(self, record, compositor, launchers, now, persist, progress=None):
        self.record = record
        self.desktop = record["desktop"]
        self.compositor = compositor
        self.launchers = launchers
        progress = progress or {}
        self.matches = progress.get("matches", {})
        self.placed = set()
        self.launched = set(progress.get("launched", []))
        self.outstanding = None
        self.children = []
        self.persist = persist
        self.errors = []
        self.warnings = []
        self.hopeless = {}  # saved address -> why no launch can help
        self.next_launch = now + 1  # Let autostart/session-aware apps appear first.
        self.deadline = now + max(30, len(self.desktop["windows"]) * 3 + 10)
        self.settled = None
        compositor.call("prepare", self.desktop)
        self.warnings.extend(streams.restore(self.desktop.get("streams", []), self.desktop.get("scenes", [])))

    def progress(self):
        return {"matches": self.matches, "launched": sorted(self.launched)}

    def reap(self):
        self.children = [child for child in self.children if child.poll() is None]

    def tick(self, now):
        current = self.compositor.snapshot()
        alive = {w["address"] for w in current["windows"]}
        for old, new in list(self.matches.items()):
            if new not in alive:
                del self.matches[old]
                self.placed.discard(old)
        if self.outstanding:
            old, cls, before, until = self.outstanding
            candidates = [w for w in current["windows"] if w["address"] not in before
                          and (w["initial_class"] or w["class"]) == cls]
            if len(candidates) == 1 and candidates[0]["address"] not in self.matches.values():
                self.matches[old] = candidates[0]["address"]
                self.outstanding = None
            elif now >= until:
                self.outstanding = None
        before_matches = dict(self.matches)
        match_windows(self.desktop["windows"], current["windows"], self.matches,
                      self.record["instance"] == self.compositor.instance)
        if self.matches != before_matches or self.matches != getattr(self, "persisted_matches", {}):
            self.persist(self.progress())
            self.persisted_matches = dict(self.matches)
        layouts = {w["selector"]: w["layout"] for w in self.desktop["workspaces"]}
        for saved in self.desktop["windows"]:
            old = saved["address"]
            if old in self.matches and old not in self.placed:
                self.compositor.call("place", {"saved": saved, "address": self.matches[old], "layout": layouts.get(saved["workspace"])})
                self.placed.add(old)
        pending = [w for w in self.desktop["windows"] if w["address"] not in self.matches]
        # Windows nothing can bring back (no recipe, or a launch that failed)
        # do not hold up placement, ordering and focus until the deadline.
        if all(w["address"] in self.hopeless for w in pending):
            self.settled = self.settled or now
            if now - self.settled >= 2:
                self.finish()
                return "complete" if not pending else "partial"
        else:
            self.settled = None
        if now >= self.deadline:
            self.finish()
            return "partial"
        if now >= self.next_launch and not self.outstanding:
            for saved in pending:
                cls = saved["initial_class"] or saved["class"]
                # A recipe explicitly changed after the snapshot takes precedence,
                # and a built-in recipe added since the snapshot can rescue a
                # window the snapshot had no recipe for.
                if cls in self.launchers.apps:
                    recipe = self.launchers.recipe(saved)
                else:
                    recipe = saved.get("launch") or self.launchers.recipe(saved)
                if not recipe:
                    self.hopeless[saved["address"]] = "no launch recipe"
                    continue
                peers = [w for w in current["windows"] if (w["initial_class"] or w["class"]) == cls]
                expected = sum((w["initial_class"] or w["class"]) == cls for w in self.desktop["windows"])
                if len(peers) >= expected or (peers and not recipe.get("per_window")):
                    continue
                key = saved["address"] if recipe.get("per_window") else str(saved["pid"]) + json.dumps(recipe["argv"])
                if key in self.launched:
                    continue
                self.launched.add(key)
                # Commit launch intent first: a service restart within the same
                # compositor must not launch the same application twice.
                self.persist(self.progress())
                try:
                    child = subprocess.Popen(recipe["argv"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, start_new_session=True)
                    self.children.append(child)
                except OSError as error:
                    self.errors.append(f"{cls}: {error}")
                    self.hopeless[saved["address"]] = "launch failed"
                    continue
                # Only a per-window launch serializes: its new window is
                # attributed by class to the most recent launch. Applications
                # that restore their own windows start together.
                if recipe.get("per_window"):
                    self.outstanding = (saved["address"], cls, alive, now + 5)
                    self.next_launch = now + 1
                    break
        return "restoring"

    def finish(self):
        result = self.compositor.call("finish", {"snapshot": self.desktop, "matches": self.matches})
        if isinstance(result, dict):
            self.warnings.extend(str(w) for w in result.get("warnings", []))

    def report(self):
        limitations = list(self.warnings)
        if any(w.get("grouped") for w in self.desktop["windows"]):
            limitations.append("Hyprland tab groups are not reconstructed")
        if any(not w["layout"].startswith("lua:") for w in self.desktop["workspaces"]):
            limitations.append("Built-in layout trees are not reconstructed")
        return {"matched": len(self.matches), "total": len(self.desktop["windows"]),
                "unmatched": [{"class": w["class"], "title": w["title"], "reason": self.hopeless.get(w["address"], "no matching window")}
                              for w in self.desktop["windows"] if w["address"] not in self.matches],
                "errors": self.errors, "limitations": limitations}


class Service:
    def __init__(self, store, compositor, launchers):
        self.store, self.compositor, self.launchers = store, compositor, launchers
        self.mode = "watching"
        self.recovery = None
        self.last = None
        self.dirty_since = self.changed_at = None
        self.running = True
        self.error = None
        self.progress = {}
        self.persisted_status = None
        self.selector = selectors.DefaultSelector()

    def record(self):
        return {"version": 1, "instance": self.compositor.instance, "saved_at": time.time(),
                "desktop": self.launchers.capture(streams.capture(self.compositor.snapshot()))}

    def status(self):
        value = {"instance": self.compositor.instance, "mode": self.mode, "error": self.error}
        if self.recovery:
            value.update(self.recovery.report())
        value["progress"] = self.progress
        if value != self.persisted_status:
            self.store.status(**value)
            self.persisted_status = json.loads(json.dumps(value))
        return value

    def checkpoint(self):
        if self.mode != "watching":
            return
        record = self.record()
        if record["desktop"] != self.last:
            self.store.checkpoint(record)
            self.last = record["desktop"]
        self.dirty_since = self.changed_at = None
        if self.error:
            self.error = None
            self.status()

    def restore(self, record, progress=None):
        if self.mode == "restoring":
            raise ValueError("restoration is already in progress")
        # Publish the protected source and the restoring marker before any
        # compositor mutation. A crash/restart resumes from this source.
        atomic_json(self.store.root / "recovery.json", record)
        self.mode = "restoring"
        self.error = None
        self.progress = progress or {}
        self.status()
        def persist(value):
            self.progress = value
            self.status()
        try:
            self.recovery = Recovery(record, self.compositor, self.launchers, time.monotonic(), persist, self.progress)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
            self.mode = "partial"
            self.error = str(error)
            self.status()
            raise
        return self.status()

    def startup(self):
        # Nothing restarts the service until the next config reload, and a
        # missing service blocks nothing but loses every checkpoint. Startup
        # failures therefore degrade to a reported error, never an exit.
        try:
            self.begin()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
            self.error = f"startup: {error}"
            if self.mode == "restoring":
                self.mode = "partial"
            self.status()
            notify("Session recovery failed to start", str(error))

    def recovery_source(self):
        return validate(read_json(self.store.root / "recovery.json"))

    def begin(self):
        try:
            previous = read_json(self.store.root / "status.json")
        except (FileNotFoundError, ValueError):
            previous = {}
        if not isinstance(previous, dict):
            previous = {}
        same = previous.get("instance") == self.compositor.instance
        note = None
        if previous.get("mode") in ("restoring", "partial"):
            try:
                source = self.recovery_source()
            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                note = f"recovery source unavailable ({error}); using the latest checkpoint"
            else:
                self.restore(source, previous.get("progress") if same else None)
                return
        record = self.store.load()
        if record and record["instance"] != self.compositor.instance:
            self.restore(record)
        elif previous.get("mode") == "frozen" and same:
            self.mode = "frozen"
            self.status()
        else:
            if record and record["instance"] == self.compositor.instance:
                self.last = record["desktop"]
            self.checkpoint()
            self.error = note
            self.status()
            if note:
                notify("Session recovery", note)

    def command(self, request):
        command, name = request["command"], request.get("name")
        if command == "status":
            return self.status()
        if command == "save":
            if not name:
                raise ValueError("save requires a session name")
            atomic_json(self.store.named(name), self.record())
            return {"saved": name}
        if command == "restore":
            retry = not name and self.mode == "partial"
            progress = None
            if retry and self.recovery is not None:
                record, progress = self.recovery.record, {"matches": dict(self.recovery.matches)}
            elif retry and (self.store.root / "recovery.json").exists():
                # The protected source outlives a restore that failed before
                # matching started (for example a compositor error at startup).
                record = self.recovery_source()
            else:
                record = self.store.load(name)
            if record is None:
                raise ValueError("no recovery snapshot")
            return self.restore(record, progress)
        if command == "freeze":
            # During partial restoration, preserve the original source.
            saved = self.mode == "watching"
            self.checkpoint()
            if self.mode == "restoring":
                self.mode = "partial"
            elif self.mode != "partial":
                self.mode = "frozen"
            return dict(self.status(), saved=saved)
        if command == "resume":
            if self.mode == "restoring":
                raise ValueError("wait for restoration to finish before accepting the current desktop")
            self.mode, self.recovery = "watching", None
            self.progress = {}
            self.error = None
            self.checkpoint()
            return self.status()
        if command == "stop":
            self.running = False
            return self.status()
        raise ValueError(f"unknown session command: {command}")

    def dirty(self, now):
        self.dirty_since = self.dirty_since if self.dirty_since is not None else now
        self.changed_at = now

    def serve(self, socket_path, event_path):
        # Subscribe before startup queries so no window event is lost between
        # capturing the desktop and entering the event loop.
        with socket.socket(socket.AF_UNIX) as events, socket.socket(socket.AF_UNIX) as server:
            events.connect(str(event_path))
            socket_path.unlink(missing_ok=True)
            server.bind(str(socket_path))
            os.chmod(socket_path, 0o600)
            server.listen(4)
            self.selector.register(events, selectors.EVENT_READ, "events")
            self.selector.register(server, selectors.EVENT_READ, "control")
            # logind's delay inhibitor gives us time to freeze before a direct
            # systemctl reboot/poweroff tears down the graphical session. The
            # Omarchy menu still needs its earlier guard: it closes apps before
            # asking logind to shut down. No authentication prompt is allowed.
            shutdown = None
            shutdown_buffer = b""
            def release():
                # Drop the delay inhibitor. A stuck monitor must not take the
                # event loop down with a TimeoutExpired.
                if shutdown.poll() is None:
                    os.killpg(shutdown.pid, signal.SIGTERM)
                try:
                    shutdown.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(shutdown.pid, signal.SIGKILL)
                    shutdown.wait()
                shutdown.stdout.close()
            try:
                shutdown = subprocess.Popen([
                    "systemd-inhibit", "--no-ask-password", "--what=shutdown", "--mode=delay",
                    "--who=Hypertile", "--why=Save desktop session",
                    "dbus-monitor", "--system",
                    "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForShutdown'",
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
                self.selector.register(shutdown.stdout, selectors.EVENT_READ, "shutdown")
            except OSError:
                pass  # Non-systemd desktops can use the explicit freeze command.
            try:
                self.startup()
                next_reconcile = time.monotonic() + 5
                event_buffer = b""
                while self.running:
                    for key, _ in self.selector.select(timeout=0.25):
                        if key.data == "shutdown":
                            chunk = os.read(shutdown.stdout.fileno(), 4096)
                            shutdown_buffer += chunk
                            if b"boolean true" in shutdown_buffer or not chunk:
                                try:
                                    if chunk:
                                        self.command({"command": "freeze"})
                                finally:
                                    self.selector.unregister(shutdown.stdout)
                                    release()  # even if capture fails
                        elif key.data == "control":
                            connection, _ = server.accept()
                            with connection:
                                connection.settimeout(2)
                                try:
                                    raw = b""
                                    while b"\n" not in raw and len(raw) < 65536:
                                        part = connection.recv(4096)
                                        if not part:
                                            break
                                        raw += part
                                    response = {"ok": True, "result": self.command(json.loads(raw))}
                                except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
                                    response = {"ok": False, "error": str(error)}
                                try:
                                    connection.sendall(json.dumps(response).encode() + b"\n")
                                except OSError:
                                    pass
                        else:
                            chunk = events.recv(65536)
                            if not chunk:
                                # Never query/save after compositor disconnect:
                                # teardown can masquerade as an empty desktop.
                                return
                            event_buffer += chunk
                            lines = event_buffer.split(b"\n")
                            event_buffer = lines.pop()
                            meaningful = (b"openwindow", b"closewindow", b"movewindow", b"workspace", b"focusedmon",
                                          b"activewindow", b"changefloatingmode", b"fullscreen", b"windowtitle",
                                          b"monitoradded", b"monitorremoved", b"moveworkspace", b"configreloaded")
                            if any(line.startswith(meaningful) for line in lines):
                                self.dirty(time.monotonic())
                    if not self.running:
                        break
                    now = time.monotonic()
                    if self.recovery:
                        self.recovery.reap()
                    try:
                        if self.mode == "restoring":
                            result = self.recovery.tick(now)
                            if result != "restoring":
                                self.mode = "watching" if result == "complete" else "partial"
                                self.checkpoint()
                                self.status()
                                if result == "partial":
                                    report = self.recovery.report()
                                    notify("Session restore incomplete",
                                           f"{report['total'] - report['matched']} of {report['total']} windows were not "
                                           "restored. Automatic saving is paused; see hypertile-ctl session status.")
                        elif self.mode == "watching":
                            due = self.changed_at is not None and (now - self.changed_at >= 1 or now - self.dirty_since >= 5)
                            if due or now >= next_reconcile:
                                self.checkpoint()
                                next_reconcile = now + 5
                        if self.mode == "watching":
                            self.error = None
                    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
                        self.error = str(error)
                        # Leave the disk source untouched on capture/restore errors.
                        if self.mode == "restoring":
                            self.mode = "partial"
                        self.status()
                        self.dirty_since = self.changed_at = None
                        next_reconcile = now + 5
            finally:
                socket_path.unlink(missing_ok=True)
                self.selector.close()
                if shutdown and not shutdown.stdout.closed:
                    release()


def paths():
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hypertile/sessions"
    runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / "hypertile-session"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypertile/session.json"
    return state, runtime, config


def request(runtime, command, name=None):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(15)
        client.connect(str(runtime / "control.sock"))
        client.sendall(json.dumps({"command": command, "name": name}).encode() + b"\n")
        raw = b""
        while b"\n" not in raw:
            part = client.recv(65536)
            if not part:
                raise RuntimeError("session service disconnected")
            raw += part
    response = json.loads(raw)
    if not response["ok"]:
        raise RuntimeError(response["error"])
    return response["result"]


def main():
    parser = argparse.ArgumentParser(description="Save and restore Hypertile desktop sessions")
    parser.add_argument("command", choices=["daemon", "status", "save", "restore", "freeze", "resume", "stop", "logout", "reboot", "shutdown"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    state, runtime, config_path = paths()
    if args.command != "daemon":
        power_action = args.command in ("logout", "reboot", "shutdown")
        if power_action:
            try:
                disabled = read_json(config_path).get("enabled", True) is False
            except FileNotFoundError:
                disabled = False
            if disabled:
                os.execvp("omarchy", ["omarchy", "system", args.command])
        if not power_action:
            print(json.dumps(request(runtime, args.command, args.name), indent=2))
            return
        # No application closes until the durable snapshot/freeze is ACKed. A
        # service that cannot answer must never leave the user unable to log
        # out: warn, then delegate to Omarchy anyway.
        try:
            value = request(runtime, "freeze")
        except (OSError, RuntimeError) as error:
            notify("Desktop session not saved", f"session service unavailable ({error}); "
                   f"{args.command} continues without a snapshot", urgency="critical")
        else:
            if not value.get("saved"):
                reasons = {"partial": "an incomplete restore still protects the previous snapshot",
                           "frozen": "the session was frozen earlier and later changes were not saved",
                           "restoring": "a restore is still running"}
                notify("Desktop session not saved",
                       reasons.get(value.get("mode"), "automatic saving is paused")
                       + "; hypertile-ctl session resume re-enables saving", urgency="critical")
        os.execvp("omarchy", ["omarchy", "system", args.command])
    os.umask(0o077)
    store = Store(state)
    with (state / "writer.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # Config reload: the original service retains ownership.
        instance = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
        try:
            config = read_json(config_path)
        except FileNotFoundError:
            config = {}
        if config.get("enabled", True) is False:
            return
        compositor = Compositor(instance, runtime)
        service = Service(store, compositor, Launchers(config))
        def stop(_signum, _frame):
            # Signals are not evidence that a final compositor query is safe.
            service.running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        event_path = Path(os.environ["XDG_RUNTIME_DIR"]) / "hypr" / instance / ".socket2.sock"
        service.serve(runtime / "control.sock", event_path)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"hypertile-session: {error}", file=sys.stderr)
        sys.exit(1)
