"""Session capture and recovery for generic app scenes."""
import copy
import json
import os
from pathlib import Path
import socket
import time


class CapturePaused(ValueError):
    pass


def capture(desktop, instance=None, now=None, warnings=None):
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hypertile"
    scene_path = root / "scenes/state.json"
    scene_state = json.loads(scene_path.read_text()) if scene_path.exists() else {"version": 1}
    if scene_state.get("version") != 1:
        raise ValueError("unsupported scene state version; session capture paused")
    now = time.monotonic() if now is None else now
    warnings = warnings if warnings is not None else []
    for workspace, lease in scene_state.get("browse", {}).get("active", {}).items():
        if instance is not None and lease.get("instance") != instance:
            continue
        deadline = lease.get("deadline")
        if not isinstance(deadline, (int, float)) or now < deadline:
            raise CapturePaused("A layout preview is active; retaining the last committed session checkpoint")
        base = lease.get("base", {})
        if not isinstance(base.get("layout"), str):
            raise CapturePaused("An expired layout preview has no saved layout; close the overlay or restart Scenes")
        # Expiry ends the saving pause even if the writer died. Capture the
        # committed layout, never promote an abandoned preview to a checkpoint.
        ws = next((w for w in desktop["workspaces"] if w["selector"] == workspace), None)
        if ws and ws["layout"] in lease.get("shown", []):
            ws["layout"] = base["layout"]
            if base.get("spec") and base["layout"].startswith("lua:"):
                desktop["layouts"].setdefault(base["layout"][4:], {})["spec"] = copy.deepcopy(base["spec"])
            for saved in lease.get("windows", []):
                window = next((w for w in desktop["windows"] if all(w.get(k) == saved.get(k) for k in ("address", "stable_id", "pid"))), None)
                if window and window["workspace"] == workspace and not window.get("floating"):
                    window["pin"] = saved.get("pin")
                    window["pin_exclusive"] = saved.get("pin_exclusive", False)
            warnings.append("A layout preview expired; saving its committed layout. Close the overlay or restart Scenes to restore it on screen.")
    if instance is not None and scene_state.get("instance") != instance:
        scene_state = {}  # Old compositor identities cannot describe this desktop.
    scene_refs, scene_windows = [], set()
    for workspace, record in scene_state.get("scenes", {}).items():
        if not record.get("document") or record.get("phase") in ("restored", "waiting-session"):
            continue
        doc = copy.deepcopy(record["document"])
        for key, source in list(doc["sources"].items()):
            if source["type"] != "app":
                continue
            app = record.get("apps", {}).get(key, {})
            ref = app.get("window")
            window = next((w for w in desktop["windows"] if ref and all(w.get(k) == v for k, v in ref.items())), None)
            pins = [source["zone"]]
            if key in record.get("reconciling", {}):
                pins.append(record["reconciling"][key])  # The atomic rename may not have reached the compositor yet.
            if app.get("status") in ("moved", "closed") or (ref and (not window or window["workspace"] != workspace or window.get("pin") not in pins or window.get("floating"))):
                del doc["sources"][key]  # Recovery preserves user departures; saved definitions stay intact.
            elif window:
                scene_windows.add(window["address"])
            else:
                candidates = [w for w in desktop["windows"] if w.get("class") == source["app_class"]
                              and (not source.get("app_title") or w.get("title") == source["app_title"])]
                if len(candidates) > 1:
                    del doc["sources"][key]  # Preserve every unassigned peer through normal app recovery.
                elif candidates:
                    scene_windows.add(candidates[0]["address"])
        scene_refs.append({"workspace": workspace, "document": doc})
    desktop.pop("streams", None)
    desktop.pop("scene_content", None)  # Compositor addresses are not scene definitions.
    desktop["scenes"] = scene_refs
    return exclude_windows(desktop, scene_windows)


def exclude_windows(desktop, scene_windows):
    windows = [w for w in desktop["windows"] if w["address"] not in scene_windows]
    desktop["windows"] = windows
    addresses = {w["address"] for w in windows}
    for ws in desktop["workspaces"]:
        ws["order"] = [a for a in ws.get("order", []) if a in addresses]
    if desktop.get("active") not in addresses:
        desktop["active"] = None
    return desktop


def definitions(sources, scenes):
    warnings = ["Legacy remote assignments were not reopened. Migrate them to installed app sources."] if sources else []
    legacy = [r for r in scenes if any(s["type"] == "stream" for s in r["document"]["sources"].values())]
    if legacy:
        warnings.append("Legacy stream scenes need migration to installed app sources; their saved definitions were kept.")
    return [r for r in scenes if r not in legacy], warnings


def deliver(scenes):
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(1)
        client.connect(str(runtime / "hypertile-scenes/control.sock"))
        client.sendall(json.dumps({"command": "session-restore", "scenes": scenes}).encode() + b"\n")
        data = bytearray()
        while not data.endswith(b"\n") and len(data) < 65536:
            part = client.recv(4096)
            if not part:
                break
            data.extend(part)
        result = json.loads(data)
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("result"), dict) or result["result"].get("accepted") is not True:
            raise ValueError("Scene recovery was not acknowledged")


class Delivery:
    """Durable outgoing refs; a lost reply is safe to retry at the scene writer."""
    def __init__(self, path, instance, write):
        self.path, self.instance, self.write = path, instance, write
        self.pending, self.loaded = [], False
        self.next_attempt, self.delay = 0, 1
        self.error = None
        self.paused = False

    def load(self):
        if self.loaded:
            return
        value = json.loads(self.path.read_text()) if self.path.exists() else {"version": 1, "scenes": []}
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("scenes"), list):
            raise ValueError("Invalid pending scene recovery; retaining the last checkpoint")
        self.pending = value["scenes"] if value.get("instance", self.instance) == self.instance else []
        self.paused = value.get("paused", False) if value.get("instance", self.instance) == self.instance else False
        self.loaded = True

    def save(self, scenes, paused=None):
        paused = self.paused if paused is None else paused
        self.write(self.path, {"version": 1, "instance": self.instance, "scenes": scenes, "paused": paused})
        self.pending, self.loaded = copy.deepcopy(scenes), True
        self.paused = paused

    def enqueue(self, sources, scenes):
        refs, warnings = definitions(sources, scenes)
        try:
            self.save(refs, False)  # Before sending, and before the local restore starts.
        except (OSError, ValueError):
            self.paused = True  # A failed replacement must not send the old intent.
            raise
        self.next_attempt, self.delay, self.error = 0, 1, None
        return warnings

    def tick(self, now):
        self.load()
        if self.paused or not self.pending or now < self.next_attempt:
            return False
        self.next_attempt = now + self.delay
        self.delay = min(30, self.delay * 2)
        try:
            deliver(self.pending)
            self.save([])  # Only an explicit acknowledgment retires the queue.
        except (OSError, ValueError) as error:
            self.error = str(error)
            return False
        self.error = None
        return True

    def preserve(self, desktop):
        self.load()
        workspaces = {r["workspace"] for r in desktop.get("scenes", [])}
        refs = [copy.deepcopy(r) for r in self.pending if r["workspace"] not in workspaces]
        scene_windows = set()
        for ref in refs:
            for key, source in list(ref["document"]["sources"].items()):
                if source["type"] != "app":
                    continue
                matches = [w for w in desktop["windows"] if w.get("class") == source["app_class"]
                           and (not source.get("app_title") or w.get("title") == source["app_title"])]
                if len(matches) == 1:
                    scene_windows.add(matches[0]["address"])
                elif len(matches) > 1:
                    # As in ordinary scene capture, ambiguous peers belong to
                    # normal app recovery, not a guessed scene assignment.
                    del ref["document"]["sources"][key]
        desktop.setdefault("scenes", []).extend(refs)
        return exclude_windows(desktop, scene_windows)

    def pause(self, value):
        self.load()
        self.save(self.pending, value)

    def status(self):
        return {"pending": len(self.pending), "error": self.error, "paused": self.paused}
