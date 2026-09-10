"""Generic scene fixtures and definition checks, with no host or client process."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
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

    def test_bad_scene_files_are_isolated_in_list_and_catalog(self):
        self.save()
        for bad in ({"version": 1, "layout": None}, {"version": 1, "layout": []},
                    {"version": 1, "layout": 42}, {"version": 1, "layout": "quad", "sources": []}, None):
            (self.root / "scenes/bad.json").write_text(json.dumps(bad))
            for action in ("list", "catalog"):
                entries = {v["name"]: v for v in self.command(action)["scenes"]}
                self.assertTrue(entries["work"]["valid"])
                self.assertFalse(entries["bad"]["valid"])
                self.assertTrue(entries["bad"]["error"])
        (self.root / "scenes/bad.json").write_bytes(b'\xff')
        self.assertFalse(self.command("list")["scenes"][0]["valid"])
        original = Path.read_text
        def unreadable(path, *args, **kwargs):
            if path.name == "bad.json": raise PermissionError("scene is unreadable")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", unreadable):
            self.assertIn("unreadable", self.command("catalog")["scenes"][0]["error"])

    def test_retired_pins_are_deduplicated_bounded_and_reset_after_restore(self):
        window = {"address": "a", "stable_id": 1, "pid": 2}
        snap = {"windows": [window]}
        pin = dict(window, zone="right", before="left")
        dead = dict(pin, stable_id=99)
        old = {"phase": "ready", "retired_pins": [pin, dead] * 100, "pins": [pin]}
        self.assertEqual(self.ctl.scenes.retired_pins(old, snap), [pin])
        old["retired_pins"] = [dict(pin, zone=str(i)) for i in range(1000)]
        kept = self.ctl.scenes.retired_pins(old, snap)
        self.assertEqual(len(kept), 512)
        self.assertEqual(kept[-1], pin)
        old["phase"] = "restored"
        self.assertEqual(self.ctl.scenes.retired_pins(old, snap), [])

    def test_scene_layout_catalog_excludes_compile_failures(self):
        from scenes import Layouts as RealLayouts
        layouts = RealLayouts()
        layouts.directory = self.root / "layouts"
        good = {"name": "good", "spec": {"name": "one"}}
        bad = {"name": "bad", "spec": {"fill": "invalid"}, "error": "fill must be an array"}
        with patch.object(layouts, "run", return_value=json.dumps({"layouts": [bad, good]})):
            self.assertEqual(layouts.all(), [good])
            with self.assertRaisesRegex(ValueError, "missing"):
                layouts.get("bad")

    def test_autostart_reports_invalid_state_without_overwriting_it(self):
        checkout = Path(__file__).resolve().parents[1]
        state = self.root / "hypertile/scenes/state.json"
        for body in ('{"version":999}', '[]'):
            state.write_text(body)
            env = dict(os.environ, HYPERTILE_SRC=str(checkout), XDG_RUNTIME_DIR=str(self.root / "runtime"),
                       HYPRLAND_INSTANCE_SIGNATURE="test-invalid-state", XDG_CONFIG_HOME=str(self.root / "config"))
            result = subprocess.run([sys.executable, str(checkout / "bin/hypertile-scenes"), "list"],
                                    env=env, text=True, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Scene service did not start", result.stderr)
            self.assertIn("unsupported scene state version", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(state.read_text(), body)

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
