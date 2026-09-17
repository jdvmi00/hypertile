"""Workspace intent, independent of the display adapter and event transport.

Rules written by the existing layout chooser are explicit choices. Inherited
rules carry a marker so their cached effective layout is never mistaken for an
override. Placement preferences are never inferred from compositor snapshots.
"""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import os
from pathlib import Path
import re

INHERITED = "-- hypertile: monitor-default"
LAYOUT = re.compile(r'layout\s*=\s*["\']([^"\']+)["\']')


def selector(workspace):
    if workspace.get("selector"):
        return str(workspace["selector"])
    number = str(workspace.get("id", ""))
    return number if number.isdigit() and int(number) > 0 else "name:" + str(workspace.get("name", ""))


def valid_workspace(value):
    return isinstance(value, str) and (bool(re.fullmatch(r"[1-9][0-9]*", value)) or
        bool(re.fullmatch(r"name:[A-Za-z0-9_.:-]{1,128}", value)))


def valid_layout(value):
    return value is None or isinstance(value, str) and bool(re.fullmatch(r"(?:lua:)?[A-Za-z0-9][A-Za-z0-9_-]*", value))


def qualify(value):
    if value is None or value.startswith("lua:") or value in ("dwindle", "scrolling", "master"):
        return value
    return "lua:" + value


def validate(document):
    """Validate policy alongside display validation before any compositor write."""
    displays = document.get("displays", [])
    ids = {d["id"] for d in displays}
    initial = set()
    for display in displays:
        if not valid_layout(display.get("default_layout")):
            raise ValueError("Invalid monitor default layout")
        workspace = display.get("initial_workspace")
        if workspace is not None and workspace != "":
            if not valid_workspace(workspace):
                raise ValueError("Initial workspace must be a positive number or name:<name>")
            if workspace in initial:
                raise ValueError("A workspace can be initial on only one display")
            initial.add(workspace)
    workspaces = document.get("workspaces", {})
    if not isinstance(workspaces, dict):
        raise ValueError("Workspace preferences must be an object")
    for key, value in workspaces.items():
        if not valid_workspace(key) or not isinstance(value, dict):
            raise ValueError("Workspace must be a positive number or name:<name>")
        if value.get("monitor") is not None and value["monitor"] not in ids:
            raise ValueError(f"Workspace {key} references an unknown saved display")
        if not valid_layout(value.get("layout")):
            raise ValueError(f"Workspace {key} has an invalid layout")
    for display in displays:
        workspace = display.get("initial_workspace")
        preferred = workspaces.get(workspace, {}).get("monitor")
        if preferred and preferred != display["id"]:
            raise ValueError(f"Initial workspace {workspace} is assigned to a different display")


def read_rules(directory=None):
    """Legacy choices migrate as explicit without rewriting or executing Lua."""
    if directory is None:
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        directory = Path(os.environ.get("HYPERTILE_RULES_DIR") or state / "hypertile/workspace-rules")
    result = {}
    for path in Path(directory).glob("*.lua"):
        text = path.read_text()
        match = LAYOUT.search(text)
        # Named workspaces use the selector recorded in the rule, not its file name.
        workspace = re.search(r'workspace\s*=\s*["\']([^"\']+)["\']', text)
        key = workspace[1] if workspace else path.stem
        if valid_workspace(key) and match:
            result[key] = None if INHERITED in text else match[1]
    return result


def effective_layout(key, monitor_id, document, rules, fallback, scenes=None):
    if scenes and key in scenes:
        return scenes[key], "scene"
    preference = document.get("workspaces", {}).get(key, {})
    # A freshly made explicit chooser selection supersedes previously confirmed
    # display policy; selecting Monitor default similarly clears an old override.
    layout = rules.get(key) if key in rules else preference.get("layout")
    if layout:
        return qualify(layout), "explicit"
    display = next((d for d in document.get("displays", []) if d["id"] == monitor_id), {})
    if display.get("default_layout"):
        return qualify(display["default_layout"]), "monitor"
    return fallback, "global"


class WorkspacePolicy:
    """Reconcile event snapshots without continuously pinning workspaces.

    `available` maps saved display identities to active connector names. An
    absent identity must not be guessed by the caller. `plan` returns moves
    only; callers apply them without focusing and call `acknowledge` after
    readback. The state can be journalled across service restarts in one login.
    """
    def __init__(self, adapter=None, state_dir=None, state=None):
        self.adapter = adapter
        self.state_dir = Path(state_dir) if state_dir else None
        if state is None and self.state_dir and (self.state_dir / "workspace-runtime.json").exists():
            state = json.loads((self.state_dir / "workspace-runtime.json").read_text())
        self.state = copy.deepcopy(state or {"locations": {}, "available": [], "suppressed": []})

    def plan(self, document, workspaces, available, reason="event"):
        locations = {selector(w): w.get("monitor", "") for w in workspaces if valid_workspace(selector(w))}
        previous = self.state.get("locations", {})
        previously_available = set(self.state.get("available", []))
        suppressed = set(self.state.get("suppressed", []))
        if reason in ("apply", "startup"):
            suppressed.clear()
        reconnect = set(available) - previously_available
        preferences = document.get("workspaces", {})
        moves = []
        for key, preference in preferences.items():
            identity = preference.get("monitor")
            if not identity or key not in locations:
                continue
            # The first move when an output disappears is compositor evacuation,
            # not a user decision. Subsequent changes while absent suppress return.
            if (reason not in ("apply", "startup") and identity not in previously_available
                    and key in previous and previous[key] != locations[key]):
                suppressed.add(key)
            destination = available.get(identity)
            if destination and key not in suppressed and locations[key] != destination:
                if reason in ("apply", "startup") or identity in reconnect or key not in previous:
                    moves.append({"workspace": key, "monitor": destination})
        self.state.update(locations=locations, available=sorted(available), suppressed=sorted(suppressed))
        return moves

    def acknowledge(self, workspaces):
        self.state["locations"] = {selector(w): w.get("monitor", "") for w in workspaces if valid_workspace(selector(w))}

    def layouts(self, document, workspaces, available, rules, fallback, scenes=None):
        identities = {connector: identity for identity, connector in available.items()}
        result = []
        for workspace in workspaces:
            key = selector(workspace)
            if not valid_workspace(key):
                continue
            layout, source = effective_layout(key, identities.get(workspace.get("monitor")), document, rules, fallback, scenes)
            result.append({"workspace": key, "layout": layout, "source": source,
                           "changed": layout != workspace.get("layout", workspace.get("tiledLayout", workspace.get("tiled_layout")))})
        return result

    def _ctl(self, *args):
        source = os.environ.get("HYPERTILE_SRC")
        command = str(Path(source) / "bin/hypertile-ctl" if source else Path.home() / ".local/bin/hypertile-ctl")
        result = subprocess.run([command, *args], text=True, capture_output=True, timeout=10,
                                env=dict(os.environ, HYPERTILE_DISPLAY_APPLY="1"))
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Workspace layout could not be applied")
        return result.stdout

    def _scenes(self):
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        path = state / "hypertile/scenes/state.json"
        if not path.exists():
            return {}
        records = json.loads(path.read_text()).get("scenes", {})
        return {key: qualify(value["document"]["layout"]) for key, value in records.items()
                if value.get("phase") != "restored" and value.get("document", {}).get("layout")}

    def _available(self, document):
        from adapter import match
        current = self.adapter.displays()
        return {d["id"]: actual["connector"] for d in document.get("displays", [])
                if d.get("enabled", True) and (actual := match(d, current)) and actual["enabled"]
                and (not actual.get("ambiguous") or d.get("explicit_match"))}

    def _save_runtime(self):
        if not self.state_dir:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".workspace-", dir=self.state_dir)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_dir / "workspace-runtime.json")
        finally:
            Path(temporary).unlink(missing_ok=True)

    def validate_changes(self, document):
        validate(document)
        scenes = self._scenes()
        rules = read_rules()
        confirmed = {}
        if self.state_dir and (self.state_dir / "confirmed.json").exists():
            confirmed = json.loads((self.state_dir / "confirmed.json").read_text()).get("workspaces", {})
        for key, preference in document.get("workspaces", {}).items():
            if key not in scenes or "layout" not in preference:
                continue
            baseline = rules[key] if key in rules else confirmed.get(key, {}).get("layout")
            requested = qualify(preference["layout"])
            if requested != qualify(baseline) and requested != scenes[key]:
                raise ValueError("Workspace " + key + " belongs to an active scene. Use the Layouts replacement confirmation first.")
        directory = Path(os.environ.get("HYPERTILE_LAYOUTS_DIR") or
                         Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypr/layouts")
        layouts = [d.get("default_layout") for d in document.get("displays", [])]
        layouts += [v.get("layout") for v in document.get("workspaces", {}).values()]
        for layout in layouts:
            qualified = qualify(layout)
            if qualified and qualified.startswith("lua:") and not (directory / (qualified[4:] + ".lua")).is_file():
                raise ValueError("Layout " + qualified[4:] + " is unavailable; choose a saved layout before applying display preferences")

    def reconcile(self, document, reason="event"):
        validate(document)
        if not document.get("displays"):
            return {"moves": [], "layouts": []}
        available = self._available(document)
        workspaces = self.adapter.workspaces()
        scenes = self._scenes()
        if reason in ("preview", "apply"):
            self.validate_changes(document)
        instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        startup = reason in ("restore", "startup") and (not self.state.get("initialized") or self.state.get("instance") != instance)
        event = "apply" if reason in ("preview", "apply") else "startup" if startup else "event"
        if reason == "reconnect": event = "reconnect"
        if startup:
            self.state.update(instance=instance, initialized=True)
        prior_locations = dict(self.state.get("locations", {}))
        prior_targets = self.state.get("layout_targets", {})
        moves = self.plan(document, workspaces, available, event)
        for move in moves:
            self.adapter.move(move["workspace"], move["monitor"])
        if moves:
            workspaces = self.adapter.workspaces()
            actual = {selector(w): w.get("monitor") for w in workspaces}
            for move in moves:
                if actual.get(move["workspace"]) != move["monitor"]:
                    raise ValueError("Hyprland did not move workspace " + move["workspace"])
        self.acknowledge(workspaces)
        rules = read_rules()
        changed_overrides = set()
        # The staged policy takes precedence during an explicit Apply only.
        # Ordinary monitor events never overwrite a user's later chooser choice.
        if event == "apply":
            for key, preference in document.get("workspaces", {}).items():
                if "layout" in preference:
                    if qualify(preference["layout"]) != rules.get(key):
                        changed_overrides.add(key)
                    rules[key] = preference["layout"]
        fallback = self._ctl("default").strip() or "dwindle"
        scenes = self._scenes()
        layouts = self.layouts(document, workspaces, available, rules, fallback, scenes)
        locations = {selector(w): w.get("monitor") for w in workspaces}
        for item in layouts:
            key = item["workspace"]
            # Layout browsing is deliberately nonpersistent. Never fight a
            # chooser preview or an external live layout on every daemon tick.
            # Explicit layouts follow moves unchanged; only a newly requested
            # override should change them through display management.
            if item["source"] == "explicit" and key not in changed_overrides:
                item["changed"] = False
            elif item["source"] != "scene" and event not in ("startup", "apply") and reason not in ("restore", "configreload"):
                item["changed"] = item["changed"] and (prior_targets.get(key) != item["layout"] or prior_locations.get(key) != locations[key])
            if item["changed"] and item["source"] != "scene":
                self._ctl("apply", item["layout"], "--workspace", item["workspace"], "--no-persist", "--quiet")
        changed = [item for item in layouts if item["changed"] and item["source"] != "scene"]
        if changed:
            # Lua's workspace object is authoritative for live layout rules;
            # Hyprland's JSON tiledLayout may still expose its cached selection.
            actual_layouts = json.loads(self._ctl("workspaces", "--json"))["workspaces"]
            readback = {selector(w): w.get("layout", w.get("tiledLayout")) for w in actual_layouts}
            for item in changed:
                if readback.get(item["workspace"]) != item["layout"]:
                    raise ValueError("Hyprland did not apply the layout for workspace " + item["workspace"])
        self.state["layout_targets"] = {item["workspace"]: item["layout"] for item in layouts}
        if reason != "preview":
            self._save_runtime()
        if event == "startup":
            self.select_initial(document, available)
        return {"moves": moves, "layouts": layouts}

    def commit(self, document):
        """Persist layout intent only after the user keeps the display preview."""
        scenes = self._scenes()
        for key, preference in document.get("workspaces", {}).items():
            if "layout" not in preference or key in scenes:
                continue
            self._ctl("apply", preference["layout"] or "monitor-default", "--workspace", key, "--quiet")
        self.plan(document, self.adapter.workspaces(), self._available(document), "apply")
        self._save_runtime()

    def restore_layouts(self, snapshot):
        scenes = self._scenes()
        current = {selector(w): w for w in self.adapter.workspaces()}
        for workspace in snapshot:
            key = selector(workspace)
            layout = workspace.get("layout", workspace.get("tiledLayout"))
            if key in current and key not in scenes and layout:
                self._ctl("apply", layout, "--workspace", key, "--no-persist", "--quiet")

    def select_initial(self, document, available):
        # Startup alone selects initial workspaces. Reconnect never changes
        # focus; there are no persistent compositor monitor rules to fight a
        # later manual workspace move.
        choices = [(d.get("initial_workspace"), available.get(d["id"])) for d in document.get("displays", [])]
        choices = [(key, connector) for key, connector in choices if key and connector]
        if not choices:
            return
        from adapter import lua_string
        active = json.loads(self.adapter.run("-j", "activeworkspace"))
        for key, connector in choices:
            self.adapter.run("eval", "hl.dispatch(hl.dsp.focus({ monitor=" + lua_string(connector) + " }))")
            self.adapter.run("eval", "hl.dispatch(hl.dsp.focus({ workspace=" + lua_string(key) + " }))")
            self.adapter.move(key, connector)
        if active.get("monitor") in available.values():
            self.adapter.run("eval", "hl.dispatch(hl.dsp.focus({ monitor=" + lua_string(active["monitor"]) + " }))")

    def rollback(self, snapshot):
        """Best effort location recovery after monitor rollback, without focus."""
        active = {d["connector"] for d in self.adapter.displays() if d["enabled"]}
        existing = {selector(w) for w in self.adapter.workspaces()}
        for workspace in snapshot:
            key = selector(workspace)
            if key in existing and workspace.get("monitor") in active:
                self.adapter.move(key, workspace["monitor"])
        self.acknowledge(self.adapter.workspaces())
        self._save_runtime()


def project_session(desktop, document, available, rules=None, fallback="dwindle"):
    """Resolve saved intent before session restore creates or moves windows.

    This does not restore scene applications or create initial workspaces. The
    session restorer remains their sole owner.
    """
    result = copy.deepcopy(desktop)
    if not document.get("displays"):
        return result
    scenes = {str(r["workspace"]): qualify(r["document"]["layout"]) for r in desktop.get("scenes", [])
              if r.get("document", {}).get("layout")}
    rules = read_rules() if rules is None else rules
    reverse = {connector: identity for identity, connector in available.items()}
    for workspace in result.get("workspaces", []):
        key = selector(workspace)
        if not valid_workspace(key):
            continue
        preference = document.get("workspaces", {}).get(key, {})
        destination = available.get(preference.get("monitor"))
        if destination:
            workspace["monitor"] = destination
        elif workspace.get("monitor") not in reverse and available:
            workspace["monitor"] = next(iter(available.values()))
        # Preserve snapshot layouts when display management has not claimed this
        # workspace/monitor. Existing session behavior stays completely intact.
        identity = reverse.get(workspace.get("monitor"))
        display = next((d for d in document.get("displays", []) if d["id"] == identity), {})
        if key in rules or display.get("default_layout") or key in scenes or "layout" in preference:
            workspace["layout"], _ = effective_layout(key, identity, document, rules, fallback, scenes)
    monitors = {selector(w): w.get("monitor") for w in result.get("workspaces", [])}
    for window in result.get("windows", []):
        if window.get("workspace") in monitors:
            window["monitor"] = monitors[window["workspace"]]
    initial = {available[d["id"]]: d["initial_workspace"] for d in document.get("displays", [])
               if d["id"] in available and d.get("initial_workspace")}
    for workspace in result.get("workspaces", []):
        if workspace.get("monitor") in initial:
            workspace["visible"] = selector(workspace) == initial[workspace["monitor"]]
    # Recovery ends by focusing snapshot.workspace/active. Keep its monitor but
    # select that monitor's requested initial workspace, leaving apps untouched.
    old_monitor = monitors.get(str(result.get("workspace", "")))
    if old_monitor in initial:
        result["workspace"] = initial[old_monitor]
        result["active"] = None
    return result
