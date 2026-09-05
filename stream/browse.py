"""Leased layout previews: source intent stays on the committed layout."""
import copy
import re
import subprocess
import time
import uuid


class Browser:
    def __init__(self, controller, clock=time.monotonic):
        self.ctl, self.clock = controller, clock
        self.epoch = uuid.uuid4().hex
        self.state = controller.state.setdefault("browse", {"active": {}, "closed": []})
        self.active = self.state["active"]

    def retire(self, token):
        if token not in self.state["closed"]:
            self.state["closed"].append(token)
            del self.state["closed"][:-64]

    def end(self, workspace, token=None):
        # A close may reach the writer before the first debounced preview.
        # Retire that owner even when it has not started yet.
        if token:
            self.retire(token)
        record = self.active.get(workspace)
        if record and (token is None or record["token"] == token):
            self.retire(record["token"])
            record["ending"] = True
            self.ctl.persist()
            snap = self.ctl.compositor.snapshot()
            ws = next((w for w in snap["workspaces"] if w["selector"] == workspace), None)
            # A separate workspace change or a new compositor supersedes this
            # preview. Never overwrite it with a late overlay close.
            if record["instance"] == self.ctl.compositor.instance and ws and ws["layout"] in record["shown"]:
                self.ctl.compositor.call("scene_layout", {"workspace": workspace, **record["base"]})
            del self.active[workspace]
        self.ctl.persist()
        return {"preview": False}

    def command(self, request):
        workspace, token = str(request.get("workspace", "")), request.get("browse_token", "")
        if not re.fullmatch(r"[1-9][0-9]*", workspace) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", token):
            raise ValueError("Layout preview requires a workspace and owner token")
        if request["action"] == "browse-end":
            return self.end(workspace, token)
        if token in self.state["closed"]:
            return {"preview": False}
        layout = request["name"].removeprefix("lua:")
        entry = self.ctl.scenes.layouts.get(layout)
        record = self.active.get(workspace)
        if record and record["token"] != token:
            self.end(workspace)
            record = None
        if not record:
            snap = self.ctl.compositor.snapshot()
            ws = next((w for w in snap["workspaces"] if w["selector"] == workspace), None)
            if not ws:
                raise ValueError("Preview workspace no longer exists")
            scene = self.ctl.scenes.records.get(workspace, {})
            if scene.get("phase", "ready") not in ("ready", "partial", "restored", "needs-attention"):
                raise ValueError("Wait for the scene to finish before browsing layouts")
            sources = [r for r in self.ctl.records.values() if r["assignment"]["workspace"] == workspace]
            if any(r["phase"] not in ("watching", "idle", "unresolved", "attention") for r in sources):
                raise ValueError("Wait for the stream operation to finish before browsing layouts")
            base = {"layout": ws["layout"]}
            spec = snap.get("layouts", {}).get(ws["layout"].removeprefix("lua:"), {}).get("spec")
            if spec:
                base["spec"] = copy.deepcopy(spec)
            record = {"token": token, "base": base, "shown": [ws["layout"]],
                      "instance": self.ctl.compositor.instance, "epoch": self.epoch}
            self.active[workspace] = record
        record["deadline"] = self.clock() + 10
        target = "lua:" + entry["name"]
        if target not in record["shown"]:
            record["shown"].append(target)
        # Persist the restoration target before changing the compositor.
        self.ctl.persist()
        try:
            self.ctl.compositor.call("scene_layout", {"workspace": workspace, "layout": target, "spec": entry["spec"]})
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            record["ending"] = True
            self.ctl.persist()
            raise
        return {"preview": True, "layout": target}

    def heartbeat(self, workspace, token):
        record = self.active.get(workspace)
        if record and record["token"] == token and not record.get("ending") and record["epoch"] == self.epoch:
            record["deadline"] = self.clock() + 10

    def tick(self):
        for workspace, record in list(self.active.items()):
            ended = record.get("ending") or record["epoch"] != self.epoch or self.clock() >= record["deadline"]
            sources = [r for r in self.ctl.records.values() if r["assignment"]["workspace"] == workspace]
            ended = ended or any(r["phase"] == "watching" and not self.ctl.processes.pid(r) for r in sources)
            if ended:
                self.end(workspace)

    def before_command(self, request):
        command = request.get("command")
        if command == "scene":
            if request.get("action") in ("browse", "browse-end", "catalog", "current", "list", "show", "validate", "remove"):
                return
            workspace = request.get("workspace") or self.ctl.compositor.snapshot()["workspace"]
            if str(workspace) in self.active:
                self.end(str(workspace))
        elif command not in ("status", "quality", "probe", "stop"):
            # Explicit stream changes and swaps must reconcile the real layout.
            for workspace in list(self.active):
                self.end(workspace)
