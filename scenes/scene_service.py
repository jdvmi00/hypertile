"""Independent scene writer: no host config, stream lock, or connection controller."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from service import atomic_json, read_json
from scenes import Manager
from browse import Browser
from ipc import daemon, request


class SceneController:
    def __init__(self, root, config, compositor, now=time.time):
        self.root, self.config, self.compositor, self.now = root, config, compositor, now
        self.state = read_json(root / "state.json") if (root / "state.json").exists() else {"version": 1}
        if self.state.get("version") != 1:
            raise ValueError("unsupported scene state version")
        self.running = True
        self.scenes = Manager(self)
        self.browser = Browser(self)
        if self.state.get("instance") != compositor.instance:
            self.state["app_launches"].clear()
            for record in self.scenes.records.values():
                if record.get("phase") != "restored":
                    record.update(phase="waiting-session")
                    record.pop("baseline", None)
        self.state["instance"] = compositor.instance
        self.persist()

    def persist(self):
        atomic_json(self.root / "state.json", self.state)

    def command(self, payload):
        command = payload.get("command")
        if command == "status":
            return {"instance": self.compositor.instance, "scenes": len(self.scenes.records)}
        if command == "stop":
            for workspace in list(self.browser.active):
                self.browser.end(workspace)
            self.running = False
            return {"stopping": True}
        if command == "session-restore":
            self.scenes.restore_refs(payload.get("scenes", []))
            return {"accepted": True}
        if command != "scene":
            raise ValueError("Scenes only manages layouts and app placement")
        self.browser.before_command(payload)
        return self.scenes.command(payload)

    def tick(self):
        before = json.dumps(self.state, sort_keys=True)
        self.scenes.apps.reap()
        self.browser.tick()
        self.scenes.tick()
        if before != json.dumps(self.state, sort_keys=True):
            self.persist()

    def tick_interval(self):
        if any(r["phase"] in ("stopping", "layout", "connecting", "waiting-workspace", "restore-builtin")
               or any(a["status"] in ("pending", "waiting-window") for a in r.get("apps", {}).values())
               for r in self.scenes.records.values()):
            return .2
        return 1 if self.browser.active else 30


def paths():
    return (Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hypertile/scenes",
            Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "hypertile-scenes",
            Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypertile/scenes.json")


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Save and apply layouts with ordinary desktop apps")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("daemon", "status", "stop", "list", "show", "save", "validate", "apply", "current", "restore", "cancel", "retry", "remove", "catalog", "content", "layout", "browse", "browse-end"):
        child = commands.add_parser(action)
        if action in ("show", "save", "apply", "remove", "layout", "browse"):
            child.add_argument("name")
        if action in ("browse", "browse-end", "catalog"):
            child.add_argument("--browse-token", required=action != "catalog")
        if action in ("validate", "save"):
            child.add_argument("--file")
        if action == "content":
            child.add_argument("--zone", required=True)
            child.add_argument("--type", choices=("local", "app", "empty"), required=True)
            child.add_argument("--desktop-id")
            child.add_argument("--app-class")
            child.add_argument("--app-title")
        child.add_argument("--workspace")
        child.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root, runtime, config = paths()
    try:
        if args.action == "daemon":
            daemon(root, runtime, config, SceneController)
            return 0
        payload = {**vars(args), "command": args.action if args.action in ("stop", "status") else "scene"}
        if getattr(args, "file", None):
            payload["document"] = json.loads(sys.stdin.read() if args.file == "-" else Path(args.file).read_text())
        if args.action == "validate" and not payload.get("document"):
            raise ValueError("validate requires --file FILE (or - for stdin)")
        if args.action not in ("stop", "status"):
            try:
                request(runtime, {"command": "status"}, timeout=1)
            except (OSError, ValueError):
                entry = Path(__file__).resolve().parents[1] / "bin/hypertile-scenes"
                if not entry.exists():
                    entry = Path.home() / ".local/bin/hypertile-scenes"
                subprocess.Popen([sys.executable, str(entry), "daemon"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                for _ in range(50):
                    try:
                        request(runtime, {"command": "status"}, timeout=.2)
                        break
                    except (OSError, ValueError):
                        time.sleep(.1)
        print(json.dumps(request(runtime, payload), indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("hypertile-scenes: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
