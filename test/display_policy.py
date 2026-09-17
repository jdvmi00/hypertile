"""Placement and layout intent contracts without a running compositor."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "displays"))
from policy import WorkspacePolicy, effective_layout, project_session, read_rules, validate


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.document = {"version": 1, "displays": [
            {"id": "wide", "connector": "DP-1", "default_layout": "lua:columns"},
            {"id": "portrait", "connector": "DP-2", "default_layout": "lua:vertical"}],
            "workspaces": {"1": {"monitor": "wide", "layout": None},
                           "name:work": {"monitor": "portrait", "layout": "lua:quad"}}}
        self.policy = WorkspacePolicy()
        self.both = {"wide": "DP-1", "portrait": "DP-2"}

    def ws(self, monitor="DP-1", key="1", layout="lua:columns"):
        return {"selector": key, "monitor": monitor, "layout": layout}

    def test_precedence_and_explicit_choices_follow_moves(self):
        self.assertEqual(effective_layout("1", "portrait", self.document, {}, "dwindle"), ("lua:vertical", "monitor"))
        self.assertEqual(effective_layout("name:work", "wide", self.document, {}, "dwindle"), ("lua:quad", "explicit"))
        self.assertEqual(effective_layout("1", "missing", self.document, {}, "master"), ("master", "global"))
        self.assertEqual(effective_layout("1", "wide", self.document, {"1": "lua:quad"}, "dwindle"), ("lua:quad", "explicit"))
        self.assertEqual(effective_layout("name:work", "wide", self.document, {"name:work": None}, "dwindle"), ("lua:columns", "monitor"))
        self.assertEqual(effective_layout("1", "wide", self.document, {}, "dwindle", {"1": "lua:scene"}), ("lua:scene", "scene"))

    def test_migrate_rules_and_do_not_infer_from_effective_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "1.lua").write_text('hl.workspace_rule({workspace="1", layout="lua:columns"})')
            (root / "2.lua").write_text('-- hypertile: monitor-default\nhl.workspace_rule({workspace="2", layout="lua:columns"})')
            (root / "name:work.lua").write_text('hl.workspace_rule({workspace="name:work", layout="lua:quad"})')
            self.assertEqual(read_rules(root), {"1": "lua:columns", "2": None, "name:work": "lua:quad"})

    def test_apply_and_future_creation(self):
        self.policy.plan(self.document, [], self.both, "startup")
        self.assertEqual(self.policy.plan(self.document, [self.ws("DP-2")], self.both), [{"workspace": "1", "monitor": "DP-1"}])
        self.policy.acknowledge([self.ws()])
        self.assertEqual(self.policy.plan(self.document, [self.ws("DP-2")], self.both), [])
        self.assertEqual(self.policy.plan(self.document, [self.ws("DP-2")], self.both, "apply"), [{"workspace": "1", "monitor": "DP-1"}])

    def test_evacuation_returns_without_focus_actions(self):
        self.policy.plan(self.document, [self.ws()], self.both, "startup")
        self.assertEqual(self.policy.plan(self.document, [self.ws("DP-2")], {"portrait": "DP-2"}), [])
        self.assertEqual(self.policy.plan(self.document, [self.ws("DP-2")], self.both), [{"workspace": "1", "monitor": "DP-1"}])

    def test_manual_move_while_absent_suppresses_until_reapply(self):
        self.policy.plan(self.document, [self.ws()], self.both, "startup")
        self.policy.plan(self.document, [self.ws("DP-2")], {"portrait": "DP-2"})
        self.policy.plan(self.document, [self.ws("HDMI-1")], {"portrait": "DP-2"})
        self.assertEqual(self.policy.plan(self.document, [self.ws("HDMI-1")], self.both), [])
        self.assertEqual(self.policy.plan(self.document, [self.ws("HDMI-1")], self.both, "startup"), [{"workspace": "1", "monitor": "DP-1"}])

    def test_session_projection_preserves_snapshot_and_scene(self):
        desktop = {"workspaces": [self.ws("gone"), self.ws("gone", "name:work")], "scenes": []}
        before = copy.deepcopy(desktop)
        result = project_session(desktop, self.document, self.both, {})
        self.assertEqual(desktop, before)
        self.assertEqual([(w["monitor"], w["layout"]) for w in result["workspaces"]], [("DP-1", "lua:columns"), ("DP-2", "lua:quad")])
        desktop["scenes"] = [{"workspace": "1", "document": {"layout": "scene"}}]
        self.assertEqual(project_session(desktop, self.document, self.both, {})["workspaces"][0]["layout"], "lua:scene")
        self.assertEqual(project_session(desktop, {"displays": []}, {}, {}), desktop)

    def test_invalid_policy_and_duplicate_initial_rejected(self):
        validate(self.document)
        self.document["workspaces"]["0"] = {}
        with self.assertRaises(ValueError): validate(self.document)
        del self.document["workspaces"]["0"]
        for display in self.document["displays"]: display["initial_workspace"] = "1"
        with self.assertRaises(ValueError): validate(self.document)


class RuntimeTests(unittest.TestCase):
    class Adapter:
        def __init__(self):
            self.live = [{"id": 1, "name": "1", "monitor": "DP-2", "tiledLayout": "master"}]
            self.outputs = [{"id": "wide", "identity": "wide", "connector": "DP-1", "enabled": True, "ambiguous": False},
                            {"id": "portrait", "identity": "portrait", "connector": "DP-2", "enabled": True, "ambiguous": False}]
            self.moves = []
        def displays(self): return copy.deepcopy(self.outputs)
        def workspaces(self): return copy.deepcopy(self.live)
        def move(self, key, monitor):
            self.moves.append((key, monitor))
            self.live[0]["monitor"] = monitor

    def setUp(self):
        self.adapter = self.Adapter()
        self.policy = WorkspacePolicy(self.adapter)
        self.doc = {"version": 1, "displays": [
            {"id": "wide", "connector": "DP-1", "default_layout": "dwindle", "enabled": True},
            {"id": "portrait", "connector": "DP-2", "default_layout": "master", "enabled": True}],
            "workspaces": {"1": {"monitor": "wide", "layout": None}}}
        self.commands = []
        def ctl(*args):
            self.commands.append(args)
            if args[0] == "default": return "scrolling"
            if args[0] == "workspaces": return json.dumps({"workspaces": self.adapter.workspaces()})
            if args[0] == "apply": self.adapter.live[0]["tiledLayout"] = args[1]
        self.policy._ctl = ctl
        self.policy._scenes = lambda: {}
        self.initial = []
        self.policy.select_initial = lambda *_: self.initial.append(True)
        self.rules = patch("policy.read_rules", return_value={})
        self.rules.start()
        self.addCleanup(self.rules.stop)

    def test_runtime_preview_and_reload_do_not_persist_temporary_layouts(self):
        result = self.policy.reconcile(self.doc, "preview")
        self.assertEqual(self.adapter.moves, [("1", "DP-1")])
        self.assertEqual(result["layouts"][0]["source"], "monitor")
        self.assertTrue(any("--no-persist" in args for args in self.commands))
        self.assertFalse(self.initial)
        self.policy.reconcile(self.doc, "restore")
        self.assertEqual(len(self.initial), 1)
        self.policy.state["suppressed"] = ["1"]
        self.policy.reconcile(self.doc, "restore")
        self.assertEqual(len(self.initial), 1)
        self.assertEqual(self.policy.state["suppressed"], ["1"])

    def test_scene_conflict_rejected_before_placement(self):
        self.policy._scenes = lambda: {"1": "lua:quad"}
        self.doc["workspaces"]["1"]["layout"] = "master"
        with self.assertRaisesRegex(ValueError, "replacement confirmation"):
            self.policy.reconcile(self.doc, "preview")
        self.assertEqual(self.adapter.moves, [])
        self.assertEqual(self.commands, [])

    def test_unchanged_scene_preference_does_not_block_display_edits(self):
        self.policy._scenes = lambda: {"1": "lua:quad"}
        self.doc["workspaces"]["1"]["layout"] = "master"
        with patch("policy.read_rules", return_value={"1": "master"}):
            self.policy.reconcile(self.doc, "preview")
        self.assertEqual(self.adapter.moves, [("1", "DP-1")])
        self.assertFalse(any(args[0] == "apply" for args in self.commands))

    def test_rollback_snapshot_uses_live_layout_not_cached_json(self):
        original = self.policy._ctl
        def ctl(*args, **kwargs):
            if args[0] == "workspaces":
                return json.dumps({"workspaces": [{"id": 1, "name": "1", "layout": "dwindle"}]})
            return original(*args, **kwargs)
        self.policy._ctl = ctl
        snapshot = self.policy.capture_workspaces()
        self.assertEqual(snapshot[0]["layout"], "dwindle")
        self.assertNotIn("tiledLayout", snapshot[0])
        self.assertEqual(snapshot[0]["monitor"], "DP-2")
        self.policy.restore_layouts(snapshot)
        self.assertEqual(self.adapter.live[0]["tiledLayout"], "dwindle")

    def test_wrong_layout_readback_is_failure(self):
        self.policy._ctl = lambda *args: "scrolling" if args[0] == "default" else json.dumps({"workspaces": self.adapter.workspaces()}) if args[0] == "workspaces" else ""
        with self.assertRaisesRegex(ValueError, "did not apply"):
            self.policy.reconcile(self.doc, "preview")

    def test_scene_layout_survives_monitor_default_change(self):
        self.policy._scenes = lambda: {"1": "master"}
        self.adapter.live[0]["monitor"] = "DP-1"
        self.policy.reconcile(self.doc, "reconnect")
        self.assertFalse(any(args[0] == "apply" for args in self.commands))


if __name__ == "__main__":
    unittest.main()
