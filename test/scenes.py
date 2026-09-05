"""Scenes exercised with real stream state transitions and fake host/compositor IO."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("stream_fixtures", Path(__file__).with_name("stream.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
s = fixtures.s
from scenes import Manager, identify
from audio import host_headset


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


class Compositor(fixtures.Compositor):
    def __init__(self, layouts):
        super().__init__()
        self.layouts = layouts
        self.desktop["scene_content"] = {}
        self.desktop["layouts"] = {"quad": {"spec": layouts.entries[0]["spec"]}}
        self.fail_layout = False

    def call(self, method, args):
        if method == "scene_layout":
            if self.fail_layout:
                raise RuntimeError("injected scene layout failure")
            self.desktop["workspaces"][0]["layout"] = args["layout"]
            self.desktop["layouts"][args["layout"][4:]] = {"spec": args.get("spec", {})}
        if method == "scene_content_apply":
            self.calls.append((method, copy.deepcopy(args)))
            self.desktop["scene_content"][args["workspace"]] = copy.deepcopy(args)
            return {"results": [], "pins": []}
        if method == "scene_clear":
            self.desktop["scene_content"].pop(args["workspace"], None)
        result = super().call(method, args)
        if method == "stream_check":
            entry = self.layouts.get(args["layout"][4:])
            leaf = next(n for n in entry["spec"]["columns"] if (n["id"] == args["zone_id"] if args.get("zone_id") else n["name"] == args["zone"]))
            return {"zone": leaf["name"], "zone_id": leaf["id"]}
        return result


class Processes:
    def __init__(self, comp):
        self.comp, self.alive, self.count = comp, {}, {}

    def pid(self, record):
        return self.alive.get(record["computer"])

    def events(self, record):
        return {}

    def launch(self, record):
        computer = record["computer"]
        self.count[computer] = self.count.get(computer, 0) + 1
        pid = 1000 + sum(self.count.values())
        self.alive[computer] = pid
        self.comp.desktop["windows"].append({"address": str(pid), "stable_id": pid, "pid": pid, "class": s.CLASS,
            "title": record["config"]["title"], "workspace": record["assignment"]["workspace"]})

    def stop(self, record, force=False):
        pid = self.alive.pop(record["computer"], None)
        self.comp.desktop["windows"] = [w for w in self.comp.desktop["windows"] if w["pid"] != pid]


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "computers.json"
        computers = {"laptop": fixtures.computer(), "second": fixtures.computer()}
        computers["laptop"]["profiles"]["meeting"] = {**computers["laptop"]["profiles"]["desktop"], "audio": "continuous", "keep_awake": "always"}
        computers["second"].update(pairing_uuid="22345678-1234-1234-1234-123456789ABC", title="Second - Moonlight")
        self.config.write_text(json.dumps({"version": 1, "computers": computers}))
        self.layouts = Layouts()
        self.comp = Compositor(self.layouts)
        self.proc = Processes(self.comp)
        self.hosts = {"laptop.example": fixtures.Host("external")}
        self.now = 100
        self.ctl = self.controller()

    def controller(self):
        ctl = s.Controller(self.root, self.config, self.comp, self.proc, lambda c, _: self.hosts[c["host"]], lambda: self.now)
        ctl.scenes = Manager(ctl, lambda: s.configuration(self.config), self.layouts, self.root / "scenes")
        return ctl

    def tick(self, n=1):
        for _ in range(n):
            self.ctl.tick()
            self.now += 1

    def command(self, action, **kwargs):
        return self.ctl.command({"command": "scene", "action": action, "workspace": "1", **kwargs})

    def save(self, name="work", computer="laptop", zone="right", **extra):
        doc = {"version": 1, "layout": "quad", "sources": {zone: {"type": "stream", "computer": computer, "profile": "desktop"}, **extra}}
        return self.command("save", name=name, document=doc)

    def apply(self, name="work"):
        return self.command("apply", name=name)

    def ready(self):
        self.save()
        self.apply()
        self.tick(6)
        self.assertEqual(self.command("current")["phase"], "ready")

    def test_save_versioned_ids_is_private_and_does_not_connect(self):
        doc = self.save()["document"]
        self.assertEqual(doc["layout_id"], "layout-one")
        self.assertEqual(doc["sources"]["z-right"]["computer"], "laptop")
        self.assertEqual((self.root / "scenes/work.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.proc.alive)

    def test_apply_is_idempotent_and_move_reuses_connection(self):
        self.ready()
        original = self.apply()
        pid = self.proc.alive["laptop"]
        self.assertEqual(self.apply()["operation"], original["operation"])
        self.save("move", zone="left", extra={"type": "empty"})
        self.apply("move")
        self.tick(4)
        self.assertEqual(self.proc.alive["laptop"], pid)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "left")
        self.assertEqual(self.command("current")["phase"], "ready")
        self.assertFalse(any(m == "stream_focus" for m, _ in self.comp.calls))

    def test_latest_scene_cancels_queued_source(self):
        self.save()
        self.save("other", computer="second")
        self.apply()
        self.apply("other")
        self.tick(9)
        self.assertEqual(self.proc.count.get("laptop", 0), 0)
        self.assertEqual(self.proc.count["second"], 1)

    def test_content_picker_moves_existing_computer_instead_of_duplicating(self):
        self.ready()
        pid = self.proc.alive["laptop"]
        self.command("content", type="stream", computer="laptop", profile="desktop", zone="left")
        self.tick(4)
        current = self.command("current")
        self.assertEqual(len(current["document"]["sources"]), 1)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "left")
        self.assertEqual(self.proc.alive["laptop"], pid)

    def test_content_change_keeps_scene_name_until_saved_back(self):
        self.ready()
        self.command("content", type="empty", zone="left")
        self.tick(6)
        scene = self.command("current")
        self.assertEqual(scene["document"]["name"], "work")
        self.assertTrue(scene["modified"])
        self.assertEqual(scene["document"]["sources"]["z-left"]["type"], "empty")
        saved = json.loads((self.root / "scenes/work.json").read_text())
        self.assertNotIn("z-left", saved["sources"])
        self.assertFalse(self.command("save", name="work")["document"]["sources"]["z-left"] is None)
        scene = self.command("current")
        self.assertFalse(scene["modified"])
        self.assertEqual(json.loads((self.root / "scenes/work.json").read_text())["sources"]["z-left"]["type"], "empty")
        self.assertFalse(self.command("apply", name="work")["modified"])

    def test_saving_a_restored_arrangement_makes_it_the_applied_scene(self):
        self.ready()
        self.command("restore")
        self.tick(8)
        self.assertEqual(self.command("current")["phase"], "restored")
        self.assertEqual(self.command("save", name="again")["document"]["name"], "again")
        scene = self.command("current")
        self.assertEqual((scene["phase"], scene["document"]["name"], scene["modified"]), ("ready", "again", False))
        self.tick(4)
        self.assertEqual(self.command("current")["phase"], "ready")
        self.assertEqual(self.proc.count["laptop"], 1)
        self.command("content", type="empty", zone="left")
        self.tick(6)
        scene = self.command("current")
        self.assertEqual((scene["document"]["name"], scene["modified"]), ("again", True))

    def test_profile_switch_and_disconnect_cancel_replacement(self):
        self.ready()
        self.ctl.command({"command": "profile", "computer": "laptop", "profile": "meeting"})
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(12)
        self.assertEqual(self.proc.count["laptop"], 1)
        self.assertFalse(self.ctl.records["laptop"]["desired"])

    def test_profile_switch_waits_for_old_exit_then_uses_audio_policy(self):
        self.ready()
        self.ctl.command({"command": "profile", "computer": "laptop", "profile": "meeting"})
        self.tick(12)
        self.assertEqual(self.proc.count["laptop"], 2)
        r = self.ctl.records["laptop"]
        self.assertEqual(r["profile"], "meeting")
        args = s.stream_argv(r["config"], r["settings"])
        self.assertIn("--no-mute-on-focus-loss", args)
        self.assertIn("--keep-awake", args)

    def test_restart_retains_scene_and_process(self):
        self.ready()
        pid = self.proc.alive["laptop"]
        self.ctl = self.controller()
        self.comp.desktop["scene_content"] = {}
        self.tick(5)
        self.assertEqual(self.proc.alive["laptop"], pid)
        self.assertEqual(self.proc.count["laptop"], 1)
        self.assertIn("1", self.comp.desktop["scene_content"])

    def test_invalid_reference_preflight_does_not_touch_active_desktop(self):
        self.ready()
        path = self.root / "scenes/work.json"
        doc = json.loads(path.read_text())
        doc["sources"]["deleted-id"] = doc["sources"].pop("z-right")
        path.write_text(json.dumps(doc))
        self.comp.calls.clear()
        with self.assertRaisesRegex(ValueError, "zone is missing"):
            self.apply()
        self.assertFalse(self.comp.calls)
        self.assertTrue(self.proc.alive)

    def test_layout_and_zone_rename_follow_ids_without_relaunch(self):
        self.ready()
        e = self.layouts.entries[0]
        e["name"] = "renamed"
        e["spec"]["columns"][1]["name"] = "renamed-zone"
        e["spec"]["fill"][1] = "renamed-zone"
        self.comp.desktop["workspaces"][0]["layout"] = "lua:renamed"
        self.comp.desktop["layouts"]["renamed"] = {"spec": copy.deepcopy(e["spec"])}
        self.tick(3)
        self.assertEqual(self.command("current")["document"]["layout"], "renamed")
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "renamed-zone")
        self.assertEqual(self.proc.count["laptop"], 1)

    def test_empty_scene_restores_initial_layout_and_sources(self):
        self.ctl.command({"command": "connect", "computer": "laptop", "zone": "left", "workspace": "1"})
        self.tick(5)
        self.command("save", name="local", document={"version": 1, "layout": "quad", "sources": {"right": {"type": "empty"}}})
        self.apply("local")
        self.tick(6)
        self.assertFalse(self.proc.alive)
        self.command("restore")
        self.tick(10)
        self.assertTrue(self.proc.alive)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "left")
        self.assertEqual(self.command("current")["phase"], "restored")

    def test_all_fill_zones_and_duplicate_computer_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "one fill zone"):
            self.command("save", name="bad", document={"version": 1, "layout": "quad", "sources": {n: {"type": "empty"} for n in ("left", "right", "extra")}})
        with self.assertRaisesRegex(ValueError, "only one"):
            self.save(extra={"type": "stream", "computer": "laptop", "profile": "desktop"})
        with self.assertRaisesRegex(ValueError, "app class can occupy only one"):
            self.command("save", name="bad", document={"version": 1, "layout": "quad", "sources": {
                n: {"type": "local", "app_class": "editor"} for n in ("left", "right")}})

    def test_offline_source_reports_partial_after_local_content_applies(self):
        self.hosts["laptop.example"].error = "pairing-required"
        self.save(extra={"type": "empty"})
        self.apply()
        self.tick(8)
        self.assertEqual(self.command("current")["phase"], "partial")
        self.assertIn("1", self.comp.desktop["scene_content"])
        self.assertEqual(next(x for x in self.command("current")["sources"] if x["type"] == "stream")["status"], "needs-attention")

    def test_repeated_stream_connect_accepts_identified_assignment(self):
        self.ready()
        pid = self.proc.alive["laptop"]
        self.ctl.command({"command": "connect", "computer": "laptop", "zone": "right"})
        self.assertEqual(self.proc.alive["laptop"], pid)

    def test_scene_swap_retains_identity_connection_and_saved_definition(self):
        self.ready()
        original = copy.deepcopy(self.ctl.records["laptop"])
        saved = (self.root / "scenes/work.json").read_bytes()
        source = {**original["window"], "computer": "laptop", "before": "right", "before_id": "z-right",
                  "zone": "left", "zone_id": "z-left", "pin": "right"}
        local = {"address": "editor", "stable_id": 2, "pid": 2, "before": "left", "before_id": "z-left",
                 "zone": "right", "zone_id": "z-right"}
        self.comp.swap_plan = {"workspace": "1", "layout": "lua:quad", "windows": [source, local]}
        request = {"command": "swap", "windows": [{k: w[k] for k in ("address", "stable_id")} for w in (source, local)]}
        self.assertTrue(self.ctl.command(request)["swapped"])
        self.tick(4)
        current = self.ctl.records["laptop"]
        self.assertEqual(current["assignment"]["zone"], "left")
        self.assertEqual(current["assignment"]["zone_id"], "z-left")
        for key in ("window", "generation", "operation", "profile", "token", "journal"):
            self.assertEqual(current.get(key), original.get(key))
        self.assertEqual(self.proc.count["laptop"], 1)
        scene = self.command("current")
        self.assertTrue(scene["modified"])
        self.assertEqual(scene["document"]["sources"]["z-left"]["computer"], "laptop")
        self.assertEqual((self.root / "scenes/work.json").read_bytes(), saved)
        # A controller restart must retain the moved assignment and scene.
        self.ctl = self.controller()
        self.tick(3)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone_id"], "z-left")
        self.assertEqual(self.proc.count["laptop"], 1)
        # A deleted/recreated origin with the same name must not pass validation.
        source.update(before="left", before_id="replacement-id", zone="right", zone_id="z-right")
        with self.assertRaisesRegex(ValueError, "assignment changed"):
            self.ctl.command(request)
        self.assertNotIn("swap", self.ctl.state)

    def test_clipboard_is_an_explicit_shortcut_with_no_content_in_journal(self):
        self.ready()
        self.assertFalse(any(m == "stream_shortcut" for m, _ in self.comp.calls))
        self.ctl.command({"command": "clipboard", "computer": "laptop"})
        self.assertIn(("stream_shortcut", {"computer": "laptop", "action": "clipboard"}), self.comp.calls)
        self.assertNotIn("clipboard", (self.root / "state.json").read_text())

    def test_mac_clipboard_limit_is_explicit_and_never_injects_keys(self):
        self.ready()
        record = self.ctl.records["laptop"]
        record["config"]["platform"] = "macos"
        self.assertEqual(self.ctl.public(record)["clipboard"]["state"], "unsupported")
        with self.assertRaisesRegex(ValueError, "does not implement"):
            self.ctl.command({"command": "clipboard", "computer": "laptop"})
        self.assertFalse(any(m == "stream_shortcut" for m, _ in self.comp.calls))

    def test_system_key_capture_requires_a_profile_choice(self):
        computer = fixtures.computer()
        profile = computer["profiles"]["desktop"]
        argv = s.stream_argv(computer, profile)
        self.assertEqual(argv[argv.index("--capture-system-keys") + 1], "never")
        profile["system_keys"] = "always"
        argv = s.stream_argv(computer, profile)
        self.assertEqual(argv[argv.index("--capture-system-keys") + 1], "always")
        profile["system_keys"] = "invalid"
        self.config.write_text(json.dumps({"version": 1, "computers": {"laptop": computer}}))
        with self.assertRaisesRegex(ValueError, "system key capture"):
            s.configuration(self.config)

    def test_rename_while_queued_uses_resolved_zone(self):
        self.ready()
        self.save("move", zone="left")
        self.apply("move")
        self.layouts.entries[0]["spec"]["columns"][0]["name"] = "renamed"
        self.layouts.entries[0]["spec"]["fill"][0] = "renamed"
        self.tick(5)
        self.assertEqual(self.ctl.records["laptop"]["assignment"]["zone"], "renamed")
        self.assertEqual(self.command("current")["phase"], "ready")

    def test_identity_generation_does_not_mutate_input(self):
        original = {"columns": [{"name": "a"}, {"name": "b"}]}
        result = identify(original)
        self.assertNotIn("layout_id", original)
        self.assertNotEqual(result["columns"][0]["id"], result["columns"][1]["id"])
        self.assertEqual(identify(result), result)

    def test_snapshot_scene_does_not_undo_a_disconnect(self):
        self.ready()
        doc = copy.deepcopy(self.command("current")["document"])
        self.ctl.command({"command": "disconnect", "computer": "laptop"})
        self.tick(4)
        self.ctl.scenes.records.clear()
        self.ctl.command({"command": "session-restore", "sources": [], "scenes": [{"workspace": "1", "document": doc}]})
        self.tick(10)
        self.assertFalse(self.ctl.records["laptop"]["desired"])
        self.assertEqual(self.proc.count["laptop"], 1)

    def test_headset_mutes_only_the_owned_client(self):
        calls = []
        def run(argv, **_):
            calls.append(argv)
            return SimpleNamespace(stdout=json.dumps([
                {"index": 1, "mute": False, "properties": {"application.process.id": "100"}},
                {"index": 2, "mute": False, "properties": {"application.process.id": "200"}}]))
        with patch("audio.shutil.which", return_value="/usr/bin/pactl"):
            self.assertEqual(host_headset(100, run)["state"], "local-muted")
        self.assertEqual(calls[1:], [["pactl", "set-sink-input-mute", "1", "1"]])

    def test_host_audio_resolves_native_pipewire_client_without_muting_others(self):
        calls = []
        inputs = [
            {"index": 10, "client": "6131", "mute": False, "properties": {"client.id": "82"}},
            {"index": 11, "client": "6132", "mute": False, "properties": {}},
            {"index": 12, "client": "missing", "mute": False, "properties": {"application.name": "Moonlight"}},
            {"index": 13, "client": "6131", "mute": False, "properties": {"application.process.id": "200"}}]
        clients = [{"index": 6131, "properties": {"application.process.id": "100"}},
                   {"index": 6132, "properties": {"application.process.id": "200"}}]
        def run(argv, **_):
            calls.append(argv)
            return SimpleNamespace(stdout=json.dumps(clients if argv[-1] == "clients" else inputs))
        with patch("audio.shutil.which", return_value="/usr/bin/pactl"):
            self.assertEqual(host_headset(100, run)["state"], "local-muted")
        self.assertEqual([v for v in calls if v[1] == "set-sink-input-mute"],
                         [["pactl", "set-sink-input-mute", "10", "1"]])

    def test_layout_failure_remains_recoverable(self):
        self.ready()
        self.save("move", zone="left")
        self.comp.fail_layout = True
        self.apply("move")
        self.tick()
        self.assertEqual(self.command("current")["phase"], "needs-attention")
        self.comp.fail_layout = False
        self.command("restore")
        self.tick(8)
        self.assertEqual(self.command("current")["phase"], "restored")


if __name__ == "__main__":
    unittest.main()
