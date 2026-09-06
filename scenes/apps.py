"""Installed desktop entries and one-shot scene placement. Apps own their lifecycle."""
import configparser
import os
from pathlib import Path
import subprocess
import time


def text(value, label):
    if not isinstance(value, str) or not value or len(value) > 250 or any(ord(c) < 32 for c in value):
        raise ValueError("invalid " + label)
    return value


def matches(window, source):
    return window.get("class") == source["app_class"] and (not source.get("app_title") or window.get("title") == source["app_title"])


def identity(window):
    return {key: window[key] for key in ("address", "stable_id", "pid")}


class DesktopApps:
    def __init__(self):
        self.entries, self.next_scan = {}, 0
        self.children = {}

    def scan(self):
        if time.monotonic() < self.next_scan:
            return self.entries
        directories = [Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")]
        directories += [Path(p) for p in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if p]
        entries, seen = {}, set()
        for directory in directories:
            base = directory / "applications"
            for path in sorted(base.rglob("*.desktop")):
                desktop_id = str(path.relative_to(base)).replace("/", "-")
                if desktop_id in seen:
                    continue
                seen.add(desktop_id)  # Hidden user entries mask system entries too.
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(path)
                    app = parser["Desktop Entry"]
                    if app.get("Type") != "Application" or app.getboolean("Hidden", fallback=False) or not app.get("Exec"):
                        continue
                    match = app.get("X-RemoteDesktops-WindowClass") or app.get("StartupWMClass")
                    title = app.get("X-RemoteDesktops-WindowTitle")
                    entry = {"desktop_id": desktop_id, "name": app.get("Name", desktop_id), "path": str(path),
                             "visible": not app.getboolean("NoDisplay", fallback=False),
                             "icon": (app.get("Icon") or "")[:250]}
                    if match:
                        entry["app_class"] = text(match, "app class")
                    if title:
                        entry["app_title"] = text(title, "app title")
                    entries[desktop_id] = entry
                except (OSError, UnicodeError, configparser.Error, KeyError, ValueError):
                    continue
        self.entries, self.next_scan = entries, time.monotonic() + 5
        return entries

    def resolve(self, source):
        desktop_id = text(source.get("desktop_id"), "desktop ID")
        if not desktop_id.endswith(".desktop") or "/" in desktop_id or "\\" in desktop_id:
            raise ValueError("Use an installed desktop ID, not a path")
        entry = self.scan().get(desktop_id)
        if not entry:
            raise ValueError("Install the app first: " + desktop_id)
        result = {"desktop_id": desktop_id, "app_name": entry["name"],
                  "app_class": text(source.get("app_class") or entry.get("app_class"), "app class")}
        title = source.get("app_title") or entry.get("app_title")
        if title:
            result["app_title"] = text(title, "app title")
        # Per-computer launchers publish exact identity; do not weaken it to
        # Moonlight's shared class and accidentally claim another computer.
        for key in ("app_class", "app_title"):
            if entry.get(key) and result.get(key) != entry[key]:
                raise ValueError("Window match disagrees with installed app: " + desktop_id)
        return result

    def catalog(self, windows):
        out = []
        for entry in self.scan().values():
            if not entry["visible"]:
                continue
            app = {k: v for k, v in entry.items() if k not in ("path", "visible")}
            # Wayland desktop IDs often are the app ID. Only offer this fallback
            # when a live window demonstrates it; otherwise the CLI accepts an
            # explicit match instead of guessing.
            if not app.get("app_class"):
                stem = entry["desktop_id"][:-8]
                if any(w.get("class") == stem for w in windows):
                    app["app_class"] = stem
            # A packaging placeholder such as "@@startup_wm_class" never
            # matches a window; the entry would only clutter the picker.
            if app.get("app_class") and "@@" not in app["app_class"]:
                out.append(app)
        return sorted(out, key=lambda v: (v["name"].casefold(), v["desktop_id"]))

    def launch(self, source):
        # Re-resolve immediately before launch. gio implements desktop Exec
        # expansion; neither stored commands nor shell interpolation are used.
        self.next_scan = 0
        self.resolve(source)
        path = self.entries[source["desktop_id"]]["path"]
        self.children[source["desktop_id"]] = subprocess.Popen(["gio", "launch", path],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def failure(self, desktop_id):
        child = self.children.get(desktop_id)
        code = child.poll() if child else None
        if code is not None:
            del self.children[desktop_id]
        return "App launcher exited with status " + str(code) if code else None


class AppPlacement:
    def __init__(self, controller, desktop=None):
        self.ctl, self.desktop = controller, desktop or DesktopApps()
        self.launches = controller.state.setdefault("app_launches", {})

    def reap(self):
        for desktop_id in list(self.desktop.children):
            error = self.desktop.failure(desktop_id)
            if error and desktop_id in self.launches:
                self.launches[desktop_id]["error"] = error

    def retry(self, record):
        for source in record["document"]["sources"].values():
            if source["type"] == "app":
                attempt = self.launches.get(source["desktop_id"])
                if attempt and (attempt.get("error") or self.ctl.now() >= attempt["deadline"]):
                    self.launches.pop(source["desktop_id"], None)

    def observe(self, record, snap):
        before = [(k, v["status"]) for k, v in record.get("apps", {}).items()]
        for key, state in record.get("apps", {}).items():
            if state["status"] != "ready":
                continue
            source = record["document"]["sources"][key]
            window = next((w for w in snap["windows"] if identity(w) == state["window"]), None)
            if not window:
                state["status"] = "closed"
            elif window["workspace"] != record["workspace"] or window.get("floating") or window.get("pin") != source["zone"]:
                state["status"] = "moved"
        return before != [(k, v["status"]) for k, v in record.get("apps", {}).items()]

    def step(self, record, snap):
        self.observe(record, snap)
        states = record.setdefault("apps", {})
        results = []
        for key, source in record["document"]["sources"].items():
            if source["type"] != "app":
                continue
            state = states.setdefault(key, {"status": "pending"})
            if state["status"] in ("pending", "waiting-window"):
                found = [w for w in snap["windows"] if matches(w, source)]
                if len(found) > 1:
                    state.update(status="needs-attention", error="More than one matching window is open; close extras or use an exact title")
                elif found:
                    window = found[0]
                    # Consume placement before IPC. An uncertain reply must never
                    # cause a later move to be undone by a retry after restart.
                    state.update(status="needs-attention", error="Placement was interrupted; apply the scene again", window=identity(window))
                    self.ctl.persist()
                    pin = self.ctl.compositor.call("scene_app_place", {**identity(window), "workspace": record["workspace"],
                        "layout": "lua:" + record["document"]["layout"], "zone": source["zone"], "zone_id": key,
                        "operation": record["operation"], "app_class": source["app_class"], "app_title": source.get("app_title")})
                    record.setdefault("pins", []).append(pin)
                    state.update(status="ready", error=None)
                    self.launches.pop(source["desktop_id"], None)
                else:
                    attempt = self.launches.get(source["desktop_id"])
                    if not attempt:
                        attempt = {"deadline": self.ctl.now() + 45}
                        self.launches[source["desktop_id"]] = attempt
                        self.ctl.persist()  # A crash here leaves an uncertain launch, never an automatic duplicate.
                        try:
                            self.desktop.launch(source)
                        except (OSError, ValueError) as error:
                            attempt["error"] = str(error)
                    failure = self.desktop.failure(source["desktop_id"])
                    if failure:
                        attempt["error"] = failure
                    if self.ctl.now() >= attempt["deadline"]:
                        attempt.setdefault("error", "No matching window appeared within 45 seconds; check the app, then Retry")
                    state.update(status="needs-attention" if attempt.get("error") else "waiting-window", error=attempt.get("error"))
            results.append({"zone": source["zone"], "status": state["status"], "error": state.get("error")})
        return results
