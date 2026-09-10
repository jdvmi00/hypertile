"""Generic scene fixtures and definition checks, with no host or client process."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / p) for p in ("scenes", "session")]
from scene_service import SceneController
from scenes import identify
import scene_recovery

class Layouts:
    def __init__(self):
        self.entries = [{"name": "quad", "spec": {"layout_id": "layout-one", "columns": [
            {"name": "left", "id": "z-left"}, {"name": "right", "id": "z-right"},
            {"name": "extra", "id": "z-extra"}], "fill": ["left", "right", "extra"]}}]

    def get(self, hint, identity=None):
        found = [e for e in self.entries if (e["spec"].get("layout_id") == identity if identity else e["name"] == hint)]
        if len(found) != 1:
            raise ValueError("layout identity is missing or ambiguous")
        return copy.deepcopy(found[0])

    def ensure(self, hint):
        return self.get(hint)

    def persist(self, workspace, rule):
        pass



class Compositor:
    instance = "one"
    def __init__(self, layouts):
        self.desktop = {"windows": [], "workspace": "1", "monitors": [], "scene_content": {},
            "layouts": {"quad": {"spec": layouts.entries[0]["spec"]}},
            "workspaces": [{"selector": "1", "layout": "lua:quad", "visible": False}]}
        self.calls, self.fail_layout = [], False
    def snapshot(self):
        return copy.deepcopy(self.desktop)
    def call(self, method, args):
        self.calls.append((method, copy.deepcopy(args)))
        if method == "scene_layout":
            if self.fail_layout:
                raise RuntimeError("injected scene layout failure")
            self.desktop["workspaces"][0]["layout"] = args["layout"]
            self.desktop["layouts"][args["layout"][4:]] = {"spec": args.get("spec", {})}
            return "scene rule"
        if method == "scene_content_apply":
            self.desktop["scene_content"][args["workspace"]] = copy.deepcopy(args)
            return {"results": [], "pins": []}
        if method == "scene_clear":
            self.desktop["scene_content"].pop(args["workspace"], None)
        return True

class SceneTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root))
        env.start()
        self.addCleanup(env.stop)
        self.layouts = Layouts()
        self.comp = Compositor(self.layouts)
        self.now = 100
        self.ctl = self.controller()
    def controller(self):
        ctl = SceneController(self.root / "hypertile/scenes", self.root / "scenes.json", self.comp, now=lambda: self.now)
        ctl.scenes.layouts = self.layouts
        return ctl
    def tick(self, count=1):
        for _ in range(count): self.ctl.tick()
    def command(self, action, **kw):
        return self.ctl.command({"command": "scene", "action": action, "workspace": "1", **kw})
    def save(self, name="work", zone="right"):
        return self.command("save", name=name, document={"version": 1, "layout": "quad", "sources": {zone: {"type": "empty"}}})
    def apply(self, name="work"):
        return self.command("apply", name=name)
    def ready(self):
        self.save()
        self.apply()
        self.tick(3)
        self.assertEqual(self.command("current")["phase"], "ready")
    def test_private_save_and_idempotent_apply(self):
        self.ready()
        self.assertEqual((self.root / "scenes/work.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.command("current")["document"]["layout_id"], "layout-one")
        count = len(self.comp.calls)
        self.apply()
        self.tick()
        self.assertEqual(len(self.comp.calls), count)
    def test_named_edit_and_restore(self):
        self.ready()
        self.command("content", zone="left", type="local")
        self.tick()
        self.assertEqual(self.command("current")["document"]["name"], "work")
        self.assertTrue(self.command("current")["modified"])
        self.command("restore")
        self.tick()
        self.assertEqual(self.command("current")["phase"], "restored")
    def test_invalid_empty_and_legacy_sources_do_not_write(self):
        for sources, message in [({n: {"type": "empty"} for n in ("left", "right", "extra")}, "Leave one"),
                                 ({"right": {"type": "stream", "computer": "laptop"}}, "Legacy stream")]:
            with self.assertRaisesRegex(ValueError, message):
                self.command("save", name="bad", document={"version": 1, "layout": "quad", "sources": sources})
            self.assertFalse((self.root / "scenes/bad.json").exists())
    def test_failure_retry_and_stable_zone_rename(self):
        self.save()
        self.apply()
        self.comp.fail_layout = True
        self.tick()
        self.assertEqual(self.command("current")["phase"], "needs-attention")
        self.comp.fail_layout = False
        self.command("retry")
        self.tick()
        self.assertEqual(self.command("current")["phase"], "ready")
        self.layouts.entries[0]["spec"]["columns"][1]["name"] = "renamed"
        self.layouts.entries[0]["spec"]["fill"][1] = "renamed"
        self.tick(3)
        self.assertEqual(self.command("current")["document"]["sources"]["z-right"]["zone"], "renamed")
    def test_identity_generation_is_pure(self):
        source = {"columns": [{"name": "left"}, {"name": "right"}]}
        result = identify(source)
        self.assertNotIn("layout_id", source)
        self.assertNotEqual(result["columns"][0]["id"], result["columns"][1]["id"])

    def test_missing_session_times_out_across_service_restart_and_accepts_late_refs(self):
        self.ready()
        document = self.command("current")["document"]
        self.comp.instance = "two"
        self.ctl = self.controller()
        self.assertEqual(self.command("current")["phase"], "waiting-session")
        self.assertNotIn("1", self.command("catalog")["active_workspaces"])
        self.assertTrue(self.command("current")["can_dismiss"])
        self.assertEqual(self.ctl.tick_interval(), 1)
        self.now += 44
        self.ctl = self.controller()
        self.tick()
        self.assertEqual(self.command("current")["phase"], "waiting-session")
        self.now += 1
        self.tick()
        current = self.command("current")
        self.assertEqual(current["phase"], "needs-attention")
        self.assertIn("could not be put back after login", current["error"])
        self.assertFalse(current["can_restore"])
        self.ctl.command({"command": "session-restore", "scenes": [{"workspace": "1", "document": document}]})
        self.tick(3)
        self.assertEqual(self.command("current")["phase"], "ready")

    def test_old_waiting_records_receive_a_deadline_once(self):
        self.ready()
        record = self.ctl.scenes.records["1"]
        record["phase"] = "waiting-session"
        record.pop("deadline", None)
        self.ctl.persist()
        self.ctl = self.controller()
        self.assertEqual(self.ctl.scenes.records["1"]["deadline"], 145)
        self.now = 146
        self.ctl = self.controller()
        self.tick()
        self.assertEqual(self.command("current")["phase"], "needs-attention")

    def test_dismiss_deleted_scene_keeps_layout_and_blocks_late_recovery(self):
        self.ready()
        document = self.command("current")["document"]
        self.command("remove", name="work")
        record = self.ctl.scenes.records["1"]
        record.update(phase="needs-attention")
        record.pop("baseline", None)
        self.assertTrue(self.command("current")["deleted"])
        before = len(self.comp.calls)
        self.command("dismiss")
        self.assertEqual(self.comp.calls[before:], [("scene_clear", {"workspace": "1"})])
        self.assertEqual(self.comp.desktop["workspaces"][0]["layout"], "lua:quad")
        self.assertEqual(self.command("current")["phase"], "none")
        self.ctl = self.controller()
        self.ctl.command({"command": "session-restore", "scenes": [{"workspace": "1", "document": document}]})
        self.tick(3)
        self.assertNotIn("1", self.ctl.scenes.records)
        # A new login can restore scenes again; dismissal only supersedes
        # recovery requests from this compositor session.
        self.comp.instance = "three"
        self.ctl = self.controller()
        self.ctl.command({"command": "session-restore", "scenes": [{"workspace": "1", "document": document}]})
        self.assertIn("1", self.ctl.scenes.records)

    def test_dismiss_missing_workspace_and_failed_clear(self):
        self.ready()
        with self.assertRaisesRegex(ValueError, "Only a waiting or failed"):
            self.command("dismiss")
        self.ctl.scenes.records["1"]["phase"] = "needs-attention"
        self.comp.desktop["workspaces"] = []
        with patch.object(self.comp, "call", side_effect=RuntimeError("compositor unavailable")):
            with self.assertRaisesRegex(RuntimeError, "compositor unavailable"):
                self.command("dismiss")
        self.assertIn("1", self.ctl.scenes.records)
        self.command("dismiss")
        self.assertNotIn("1", self.ctl.scenes.records)

    def test_missing_workspace_recovery_has_an_actionable_error(self):
        self.save()
        document = self.command("show", name="work")
        self.comp.desktop["workspaces"] = []
        self.ctl.command({"command": "session-restore", "scenes": [{"workspace": "1", "document": document}]})
        self.now += 46
        self.tick()
        current = self.command("current")
        self.assertIn("Its workspace did not return", current["error"])
        self.assertTrue(current["can_dismiss"])

if __name__ == "__main__": unittest.main()
