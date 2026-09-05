"""Scene definitions and orchestration, hosted by the stream single writer.

No network/process owner here: every source operation delegates to Controller.
Scene intent, its baseline, and its progress live in the controller's journal.
"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from service import atomic_json


def check(condition, message):
    if not condition:
        raise ValueError(message)


def name(value):
    check(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value), "invalid scene name")
    return value


def leaves(spec):
    children = spec.get("columns", spec.get("rows"))
    if children is None:
        return [spec]
    return [leaf for child in children for leaf in leaves(child)]


def identify(spec):
    spec = copy.deepcopy(spec)
    spec.setdefault("layout_id", str(uuid.uuid4()))
    for leaf in leaves(spec):
        leaf.setdefault("id", str(uuid.uuid4()))
    return spec


class Layouts:
    def __init__(self):
        src = os.environ.get("HYPERTILE_SRC")
        self.ctl = str(Path(src) / "bin/hypertile-ctl" if src else Path.home() / ".local/bin/hypertile-ctl")
        self.directory = Path(os.environ.get("HYPERTILE_LAYOUTS_DIR") or
                              Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypr/layouts")
        self.stamp, self.cache = None, []

    def run(self, *args, document=None):
        result = subprocess.run([self.ctl, *args], input=json.dumps(document) if document is not None else None,
                                capture_output=True, text=True, timeout=10)
        check(result.returncode == 0, result.stderr.strip() or "layout command failed")
        return result.stdout

    def all(self):
        stamp = [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(self.directory.glob("*.lua"))]
        if stamp != self.stamp:
            self.cache = [v for v in json.loads(self.run("list", "--json"))["layouts"] if v.get("spec")]
            self.stamp = stamp
        return copy.deepcopy(self.cache)

    def get(self, hint, identity=None):
        entries = self.all()
        matches = [v for v in entries if (v["spec"].get("layout_id") == identity if identity else v["name"] == hint)]
        check(len(matches) == 1, "Scene layout is missing or its identity is ambiguous; choose a layout again")
        return matches[0]

    def ensure(self, hint):
        entry = self.get(hint)
        spec = identify(entry["spec"])
        if spec != entry["spec"]:
            # One-time metadata migration. No geometry, fill or app rules change.
            self.run("save", "-", "--no-reload", document={"name": hint, "spec": spec})
            self.stamp = None
        return {"name": hint, "spec": spec}

    def persist(self, workspace, rule):
        check(re.fullmatch(r"[1-9][0-9]*", workspace), "invalid scene workspace")
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        directory = Path(os.environ.get("HYPERTILE_RULES_DIR") or state / "hypertile/workspace-rules")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=".scene-", dir=directory)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(rule + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, directory / (workspace + ".lua"))
            (state / "omarchy/workspace-layouts" / (workspace + ".lua")).unlink(missing_ok=True)
        finally:
            Path(path).unlink(missing_ok=True)


class Manager:
    def __init__(self, controller, computers, layouts=None, directory=None):
        self.ctl, self.computers = controller, computers
        self.layouts = layouts or Layouts()
        self.directory = directory or controller.config.parent / "scenes"
        self.records = controller.state.setdefault("scenes", {})

    def path(self, value):
        return self.directory / (name(value) + ".json")

    def load(self, value):
        try:
            return json.loads(self.path(value).read_text())
        except FileNotFoundError:
            raise ValueError("No saved scene named " + value) from None

    def resolve(self, doc, migrate=False):
        check(isinstance(doc, dict) and doc.get("version") == 1, "unsupported scene schema")
        hint = doc.get("layout", "").removeprefix("lua:")
        name(hint)
        entry = self.layouts.get(hint, doc.get("layout_id"))
        if migrate:
            entry = self.layouts.ensure(entry["name"])
        spec = entry["spec"]
        nodes = leaves(spec)
        ids = [n.get("id") for n in nodes if n.get("id")]
        check(len(ids) == len(set(ids)), "duplicate zone identities")
        inputs = doc.get("sources", {})
        check(isinstance(inputs, dict), "scene sources must be an object")
        computers = self.computers()
        output, blocked, used, apps = {}, set(), set(), set()
        for key, source in inputs.items():
            check(isinstance(source, dict), "invalid scene source")
            matches = [n for n in nodes if n.get("id") == key]
            if not matches and not doc.get("layout_id"):
                matches = [n for n in nodes if n["name"] == key]
            check(len(matches) == 1, "Scene zone is missing: " + str(source.get("zone", key)) + "; choose its replacement")
            leaf = matches[0]
            kind = source.get("type")
            check(kind in ("local", "stream", "empty"), "monitor inputs require a validated hardware profile")
            check(not leaf.get("spacer") or kind == "empty", "A spacer can only contain Empty")
            value = {"type": kind, "zone": leaf["name"]}
            if kind == "stream":
                computer, profile = source.get("computer"), source.get("profile")
                check(computer in computers, "Configure computer " + str(computer) + " first")
                check(profile in computers[computer]["profiles"], "Unknown profile for " + computer)
                check(computer not in used, "A computer can occupy only one scene zone")
                used.add(computer)
                value.update(computer=computer, profile=profile)
            if kind == "local" and source.get("app_class"):
                app = source["app_class"]
                check(isinstance(app, str) and 0 < len(app) <= 250 and "\n" not in app, "invalid app class")
                check(app != "com.moonlight_stream.Moonlight", "Choose a configured computer for Moonlight")
                check(app not in apps, "An app class can occupy only one scene zone")
                apps.add(app)
                value["app_class"] = app
            if kind in ("empty", "stream"):
                blocked.add(leaf["name"])
            output[leaf.get("id", leaf["name"])] = value
        cycle = spec.get("cycle", spec.get("fill", [n["name"] for n in nodes if not n.get("spacer")]))
        check(any(zone not in blocked for zone in cycle), "Leave one fill zone for local windows")
        normalized = {"version": 1, "layout": entry["name"], "sources": output}
        if spec.get("layout_id"):
            normalized["layout_id"] = spec["layout_id"]
        if doc.get("name"):
            normalized["name"] = name(doc["name"])
        return normalized, spec

    def workspace(self, request, snap):
        workspace = str(request.get("workspace") or snap["workspace"])
        check(re.fullmatch(r"[1-9][0-9]*", workspace), "Scenes currently use numbered workspaces")
        check(any(w["selector"] == workspace for w in snap["workspaces"]), "Create this workspace before applying a scene")
        return workspace

    def capture(self, workspace, snap, migrate=True):
        ws = next(w for w in snap["workspaces"] if w["selector"] == workspace)
        check(ws["layout"].startswith("lua:"), "Choose a Hypertile layout before saving content")
        entry = self.layouts.ensure(ws["layout"][4:]) if migrate else self.layouts.get(ws["layout"][4:])
        spec, bindings = entry["spec"], {}
        active = self.records.get(workspace)
        if active and active.get("phase") not in ("waiting-workspace", "restored") and active.get("document") and active["document"].get("layout_id") == spec.get("layout_id"):
            bindings = copy.deepcopy(active["document"]["sources"])
            bindings = {k: v for k, v in bindings.items() if v["type"] != "stream"}
        by_name = {n["name"]: n.get("id", n["name"]) for n in leaves(spec)}
        for r in self.ctl.records.values():
            if r["desired"] and r["assignment"]["workspace"] == workspace:
                zone = r["assignment"]["zone"]
                check(zone in by_name, "An assigned source zone is missing: " + zone)
                bindings[by_name[zone]] = {"zone": zone, "type": "stream", "computer": r["computer"], "profile": r["profile"]}
        doc = {"version": 1, "layout": entry["name"], "sources": bindings}
        if spec.get("layout_id"):
            doc["layout_id"] = spec["layout_id"]
        # A change to a named scene keeps the name: the scene is then modified
        # (Save writes it back) rather than a new unsaved one.
        if active and active.get("phase") not in ("waiting-workspace", "restored") and active.get("document") \
                and active["document"].get("name") and active["document"].get("layout_id") == spec.get("layout_id"):
            doc["name"] = active["document"]["name"]
        return doc

    def modified(self, document):
        """Whether the document differs from its saved definition (unnamed: always)."""
        if not document.get("name"):
            return True
        try:
            saved, _ = self.resolve(self.load(document["name"]))
        except (ValueError, KeyError, TypeError):
            return True
        return saved["sources"] != document["sources"] or saved.get("layout_id") != document.get("layout_id")

    def public(self, record):
        if not record:
            return {"phase": "none", "sources": [], "document": None}
        out = {k: copy.deepcopy(record[k]) for k in ("document", "workspace", "generation", "operation", "phase", "error", "modified", "results") if k in record}
        out["can_restore"] = bool(record.get("baseline"))
        out["sources"] = []
        for key, source in record.get("document", {}).get("sources", {}).items():
            item = {**source, "zone_id": key}
            if source["type"] == "stream":
                r = self.ctl.records.get(source["computer"])
                item["status"] = r["observed"] if r else "pending"
                item["error"] = r.get("error") if r else None
                item["suppressed"] = source["computer"] in record.get("suppressed", [])
            else:
                item["status"] = "ready"
                for result in record.get("results", []):
                    if result["zone"] == source["zone"]:
                        item.update(result)
            out["sources"].append(item)
        return out

    def start(self, doc, workspace, snap, restoring=False):
        document, spec = self.resolve(doc)
        check(document.get("layout_id"), "Save the scene first to establish layout and zone identities")
        for source in document["sources"].values():
            if source["type"] == "stream":
                r = self.ctl.records.get(source["computer"])
                check(not r or not r["desired"] or r["assignment"]["workspace"] == workspace,
                      "Computer is already assigned on another workspace: " + source["computer"])
        old = self.records.get(workspace)
        if not restoring and old and old.get("document") == document and old["phase"] not in ("needs-attention", "restored", "waiting-workspace") and not old.get("suppressed"):
            return self.public(old)
        if old and old.get("baseline") and old["phase"] != "restored":
            baseline = copy.deepcopy(old["baseline"])
        else:
            ws = next(w for w in snap["workspaces"] if w["selector"] == workspace)
            baseline = {"layout": ws["layout"], "document": self.capture(workspace, snap) if ws["layout"].startswith("lua:") else None,
                        "windows": [{k: w[k] for k in ("address", "stable_id", "pid", "pin", "pin_exclusive") if k in w}
                                    for w in snap["windows"] if w["workspace"] == workspace], "instance": self.ctl.compositor.instance}
        record = {"workspace": workspace, "document": document, "spec": spec, "baseline": baseline,
                  "generation": (old or {}).get("generation", 0) + 1, "operation": uuid.uuid4().hex,
                  "phase": "stopping", "launched": [], "suppressed": [], "restoring": restoring, "modified": self.modified(document)}
        record["retired_pins"] = copy.deepcopy((old or {}).get("retired_pins", []) + (old or {}).get("pins", []))
        self.records[workspace] = record
        self.ctl.persist()
        self.stop_superseded(record)
        return self.public(record)

    def desired(self, record):
        return {s["computer"]: {**s, "zone_id": key} for key, s in record["document"]["sources"].items()
                if s["type"] == "stream" and s["computer"] not in record.get("suppressed", [])}

    def stop_superseded(self, record):
        wanted = self.desired(record)
        for computer, r in self.ctl.records.items():
            if not r["desired"] or r["assignment"]["workspace"] != record["workspace"]:
                continue
            target = wanted.get(computer)
            retain = target and r["profile"] == target["profile"] and r["phase"] == "watching" and r.get("window")
            if not retain:
                self.ctl.command({"command": "disconnect", "computer": computer, "scene_internal": True})

    def interrupted(self, request):
        if request.get("scene_internal") or request.get("command") not in ("connect", "disconnect", "restore", "release", "swap"):
            return
        computer = request.get("computer")
        for record in self.records.values():
            if computer in self.desired(record):
                if request["command"] in ("disconnect", "restore", "release"):
                    record.setdefault("suppressed", []).append(computer)
                record["modified"] = True

    def swapped(self):
        for record in self.records.values():
            if record["phase"] not in ("ready", "partial"):
                continue
            nodes = {n["name"]: n.get("id") for n in leaves(record["spec"])}
            sources = record["document"]["sources"]
            changes = []
            for key, source in list(sources.items()):
                r = self.ctl.records.get(source.get("computer"))
                if source["type"] == "stream" and r and r["assignment"]["zone"] != source["zone"]:
                    changes.append((key, nodes[r["assignment"]["zone"]], {**source, "zone": r["assignment"]["zone"]}))
            for old, _, _ in changes:
                sources.pop(old)
            for old, key, source in changes:
                displaced = sources.pop(key, None)
                if displaced:
                    displaced["zone"] = next(n["name"] for n in leaves(record["spec"]) if n.get("id") == old)
                    sources[old] = displaced
                sources[key] = source
            if changes:
                record["modified"] = True

    def command(self, request):
        action = request.get("action", "current")
        if action in ("browse", "browse-end"):
            return self.ctl.browser.command(request)
        if action == "list":
            entries = []
            for path in sorted(self.directory.glob("*.json")):
                try:
                    doc, _ = self.resolve(json.loads(path.read_text()))
                    entries.append({"name": path.stem, "layout": doc["layout"], "valid": True})
                except (ValueError, KeyError, TypeError) as error:
                    entries.append({"name": path.stem, "valid": False, "error": str(error)})
            return {"version": 1, "scenes": entries}
        if action == "show":
            return self.load(request["name"])
        if action == "remove":
            self.path(request["name"]).unlink()
            return {"removed": request["name"]}
        if action == "validate":
            doc, _ = self.resolve(request["document"])
            return {"valid": True, "document": doc}
        snap = self.ctl.compositor.snapshot()
        workspace = self.workspace(request, snap)
        if action == "current":
            return self.public(self.records.get(workspace))
        if action == "catalog":
            self.ctl.browser.heartbeat(workspace, request.get("browse_token"))
            computers = self.computers()
            return {"version": 1, "current": self.public(self.records.get(workspace)),
                    "scenes": self.command({"action": "list"})["scenes"],
                    "computers": [{"computer": k, "profiles": [{"name": p, "audio": s.get("audio", "focus"),
                                  "input": s.get("input", "absolute"), "keep_awake": s.get("keep_awake", "visible"),
                                  "system_keys": s.get("system_keys", "never"),
                                  "meeting": "unverified"} for p, s in v["profiles"].items()]} for k, v in computers.items()],
                    "streams": [self.ctl.public(r) for r in self.ctl.records.values()],
                    "active_workspaces": [w for w, r in self.records.items() if r["phase"] != "restored"],
                    "monitor_inputs": [], "workspace": workspace}
        if action == "save":
            doc = request.get("document") or self.capture(workspace, snap)
            doc, _ = self.resolve(doc, migrate=True)
            doc["name"] = name(request["name"])
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            atomic_json(self.path(doc["name"]), doc)
            active = self.records.get(workspace)
            if active and active["document"]["sources"] == doc["sources"] and active["document"]["layout_id"] == doc["layout_id"]:
                active["document"] = copy.deepcopy(doc)
                active["modified"] = False
                if active["phase"] == "restored":
                    # The restored arrangement is now this named scene, applied.
                    active.update(phase="ready", restoring=False)
                    active.pop("error", None)
                self.ctl.persist()
            return {"saved": doc["name"], "document": doc}
        if action == "apply":
            return self.start(self.load(request["name"]), workspace, snap)
        if action == "layout":
            entry = self.layouts.ensure(request["name"])
            return self.start({"version": 1, "layout": entry["name"], "layout_id": entry["spec"]["layout_id"], "sources": {}}, workspace, snap)
        if action in ("restore", "cancel"):
            active = self.records.get(workspace)
            check(active and active.get("baseline"), "No scene changes to restore")
            baseline = active["baseline"]
            if baseline["document"]:
                return self.start(baseline["document"], workspace, snap, restoring=True)
            # Built-in layout baselines have no source zones.
            for r in self.ctl.records.values():
                if r["desired"] and r["assignment"]["workspace"] == workspace:
                    self.ctl.command({"command": "disconnect", "computer": r["computer"], "scene_internal": True})
            active.update(phase="restore-builtin", restoring=True)
            self.ctl.persist()
            return self.public(active)
        if action == "retry":
            active = self.records.get(workspace)
            check(active, "No active scene")
            if active["phase"] == "needs-attention":
                active.update(phase="stopping", error=None)
                self.stop_superseded(active)
            for computer in self.desired(active):
                r = self.ctl.records.get(computer)
                if r and not r["desired"] and r.get("journal"):
                    self.ctl.command({"command": "restore", "computer": computer, "scene_internal": True})
                elif r and r["desired"] and not self.ctl.processes.pid(r):
                    self.ctl.command({"command": "retry", "computer": computer, "scene_internal": True})
                elif not r or not r["desired"]:
                    active["launched"] = [c for c in active["launched"] if c != computer]
            active["content_applied"] = False
            self.ctl.persist()
            return self.public(active)
        if action == "content":
            doc = self.capture(workspace, snap)
            spec = self.layouts.get(doc["layout"], doc["layout_id"])["spec"]
            leaf = next((n for n in leaves(spec) if n["name"] == request.get("zone")), None)
            check(leaf, "Select a zone in the current layout")
            source = {"type": request["type"], "zone": leaf["name"]}
            for k in ("computer", "profile", "app_class"):
                if request.get(k):
                    source[k] = request[k]
            if source["type"] == "stream":
                doc["sources"] = {k: v for k, v in doc["sources"].items()
                                  if v.get("computer") != source.get("computer")}
            doc["sources"][leaf["id"]] = source
            return self.start(doc, workspace, snap)
        raise ValueError("unknown scene command")

    def blocks(self, computer):
        r = self.ctl.records[computer]
        scene = self.records.get(r["assignment"]["workspace"])
        return bool(scene and scene["phase"] in ("stopping", "layout", "restore-builtin") and r["desired"])

    def restore_refs(self, refs):
        for ref in refs:
            workspace = str(ref.get("workspace", ""))
            if workspace in self.records or not re.fullmatch(r"[1-9][0-9]*", workspace):
                continue
            self.records[workspace] = {"workspace": workspace, "document": copy.deepcopy(ref["document"]),
                "phase": "waiting-workspace", "generation": 0, "operation": uuid.uuid4().hex,
                "launched": [], "suppressed": [], "deadline": self.ctl.now() + 45}
        self.ctl.persist()

    def tick(self):
        for record in self.records.values():
            if record["workspace"] in self.ctl.browser.active:
                continue
            try:
                self.step(record)
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as error:
                record.update(phase="needs-attention", error=str(error))

    def step(self, record):
        phase, workspace = record["phase"], record["workspace"]
        if phase == "waiting-workspace":
            snap = self.ctl.compositor.snapshot()
            if any(w["selector"] == workspace for w in snap["workspaces"]):
                suppressed = [c for c in self.desired(record) if c in self.ctl.records and not self.ctl.records[c]["desired"]]
                self.start(record["document"], workspace, snap)
                restored = self.records[workspace]
                # A scene in an older checkpoint must not undo a disconnect.
                restored["suppressed"] = suppressed
            elif self.ctl.now() > record["deadline"]:
                record.update(phase="needs-attention", error="Workspace did not return during session recovery")
            return
        if phase in ("restored", "needs-attention"):
            return
        wanted = self.desired(record)
        local_records = [r for r in self.ctl.records.values() if r["assignment"]["workspace"] == workspace]
        if phase in ("stopping", "restore-builtin"):
            # Old local views must exit before their zones/layout are reused.
            if any(not r["desired"] and self.ctl.processes.pid(r) for r in local_records):
                return
            for r in local_records:
                self.ctl.compositor.call("stream_release", {"computer": r["computer"]})
                self.ctl.applied.pop(r["computer"], None)
            self.ctl.compositor.call("scene_clear", {"workspace": workspace})
            if phase == "restore-builtin":
                rule = self.ctl.compositor.call("scene_layout", {"workspace": workspace, "layout": record["baseline"]["layout"]})
                self.layouts.persist(workspace, rule)
                record["phase"] = "restored"
                return
            # Resolve again before writes: a queued scene cannot use stale IDs.
            document, spec = self.resolve(record["document"])
            record.update(document=document, spec=spec, phase="layout")
            wanted = self.desired(record)
            self.ctl.persist()
        if record["phase"] == "layout":
            rule = self.ctl.compositor.call("scene_layout", {"workspace": workspace, "layout": "lua:" + record["document"]["layout"], "spec": record["spec"]})
            self.layouts.persist(workspace, rule)
            for computer, target in wanted.items():
                r = self.ctl.records.get(computer)
                if r and r["desired"]:
                    r["assignment"] = {"workspace": workspace, "layout": "lua:" + record["document"]["layout"],
                                       "zone": target["zone"], "zone_id": target["zone_id"]}
                    self.ctl.applied.pop(computer, None)
                    record["launched"].append(computer)
            record.update(phase="connecting", content_applied=False)
            self.ctl.persist()
        snap = self.ctl.compositor.snapshot()
        live_ws = next((w for w in snap["workspaces"] if w["selector"] == workspace), None)
        if not live_ws:
            return  # Local session recovery may still be creating this workspace.
        live_spec = snap.get("layouts", {}).get(live_ws["layout"].removeprefix("lua:"), {}).get("spec", {})
        if live_spec.get("layout_id") == record["document"].get("layout_id"):
            document, spec = self.resolve(record["document"])
            if document != record["document"]:
                record.update(document=document, spec=spec, content_applied=False, phase="stopping")
                self.stop_superseded(record)
                return  # Reconcile the full reservation set before either new name is assigned.
        # A user selected a different layout directly: don't force this scene back.
        if live_ws["layout"] != "lua:" + record["document"]["layout"]:
            record.update(phase="needs-attention", error="Workspace layout changed; apply or restore the scene")
            return
        if not record.get("content_applied") or workspace not in snap.get("scene_content", {}):
            sources = [{**value, "zone_id": key} for key, value in record["document"]["sources"].items()]
            content = self.ctl.compositor.call("scene_content_apply", {"workspace": workspace, "layout": live_ws["layout"], "sources": sources})
            record["results"], record["pins"] = content["results"], content["pins"]
            record["content_applied"] = True
        for computer, target in wanted.items():
            if computer in record["launched"]:
                continue
            r = self.ctl.records.get(computer)
            if r and (r["desired"] or r["phase"] != "idle" or self.ctl.processes.pid(r) or r.get("journal")):
                continue
            self.ctl.command({"command": "connect", "computer": computer, "profile": target["profile"],
                              "zone": target["zone"], "workspace": workspace, "scene_internal": True})
            record["launched"].append(computer)
        states = [self.ctl.records.get(c, {}) for c in wanted]
        problems = any(r.get("observed") in ("needs-attention", "restore-pending", "degraded") or not r.get("desired", True) for r in states)
        problems = problems or any(r.get("status") == "needs-attention" for r in record.get("results", []))
        if all(r.get("window") for r in states) and not problems:
            record["phase"] = "ready"
            record.pop("error", None)
        else:
            record["phase"] = "partial" if problems else "connecting"
        if record.get("restoring") and record["phase"] == "ready":
            if record["baseline"].get("instance") == self.ctl.compositor.instance:
                self.ctl.compositor.call("scene_restore_pins", {"workspace": workspace, "windows": record.get("retired_pins", [])})
            record["phase"] = "restored"
