"""Durable delivery and lease expiry: no live compositor or user state."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "session"))
import scene_recovery as scenes
from service import Service, Store, atomic_json
spec = importlib.util.spec_from_file_location("session_fixtures", Path(__file__).with_name("session.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root), XDG_RUNTIME_DIR=str(self.root), XDG_CONFIG_HOME=str(self.root))
        env.start(); self.addCleanup(env.stop)
        self.store = Store(self.root / "hypertile/sessions")
        self.refs = [{"workspace": "1", "document": {"version": 1, "layout": "quad", "sources": {}}}]
        self.queue = scenes.Delivery(self.store.root / "pending-scenes.json", "new", atomic_json)
        self.comp = f.FakeCompositor(f.record()["desktop"])

    def test_retries_back_off_and_survive_restart_and_lost_ack_write(self):
        self.queue.enqueue([], self.refs)
        with patch("scene_recovery.deliver", side_effect=OSError("not listening")) as send:
            for now in (0, .1, 1, 2, 3, 6, 7):
                self.assertFalse(self.queue.tick(now))
            self.assertEqual(send.call_count, 4)  # 0, 1, 3, 7
        self.assertEqual(json.loads(self.queue.path.read_text())["scenes"], self.refs)
        restarted = scenes.Delivery(self.queue.path, "new", atomic_json)
        with patch("scene_recovery.deliver") as send, patch.object(restarted, "write", side_effect=OSError("disk full")):
            self.assertFalse(restarted.tick(100))
        self.assertEqual(restarted.pending, self.refs)
        self.assertEqual(send.call_count, 1)
        with patch("scene_recovery.deliver") as send:
            self.assertTrue(restarted.tick(101))
            self.assertFalse(restarted.tick(200))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(json.loads(self.queue.path.read_text())["scenes"], [])

    def test_checkpoints_and_resume_keep_undelivered_refs_until_ack(self):
        saved = f.record()
        saved["desktop"]["scenes"] = copy.deepcopy(self.refs)
        self.store.checkpoint(saved)
        service = Service(self.store, self.comp, f.Launchers())
        with patch("scene_recovery.deliver", side_effect=OSError("not listening")):
            service.startup()
        self.assertEqual(service.mode, "restoring")
        self.assertEqual(service.recovery.tick(1), "restoring")
        self.assertEqual(service.recovery.tick(3), "complete")
        service.mode = "watching"
        service.checkpoint()
        self.assertEqual(self.store.load()["desktop"]["scenes"], self.refs)
        restarted = Service(self.store, self.comp, f.Launchers())
        restarted.startup()
        self.assertEqual(restarted.scene_delivery.pending, self.refs)
        restarted.command({"command": "freeze"})
        paused = scenes.Delivery(self.queue.path, "new", atomic_json)
        with patch("scene_recovery.deliver") as send:
            self.assertFalse(paused.tick(20))
            send.assert_not_called()
        restarted.command({"command": "resume"})
        self.assertEqual(self.store.load()["desktop"]["scenes"], self.refs)
        self.assertFalse(restarted.scene_delivery.paused)
        # ACK means the scene writer has already made the refs durable.
        path = self.root / "hypertile/scenes/state.json"
        def accept(refs):
            atomic_json(path, {"version": 1, "instance": "new", "scenes": {
                "1": {"document": refs[0]["document"], "phase": "waiting-workspace"}}})
        with patch("scene_recovery.deliver", side_effect=accept):
            self.assertTrue(restarted.scene_delivery.tick(100))
        restarted.checkpoint()
        self.assertEqual(self.store.load()["desktop"]["scenes"], self.refs)
        self.assertEqual(restarted.status()["scene_delivery"]["pending"], 0)

    def test_pending_refs_do_not_replace_a_newer_live_scene(self):
        self.queue.enqueue([], self.refs)
        newer = copy.deepcopy(self.refs)
        newer[0]["document"]["layout"] = "wide"
        self.assertEqual(self.queue.preserve({"scenes": newer, "windows": [], "workspaces": []})["scenes"], newer)

    def test_pending_scene_apps_are_not_also_saved_for_normal_recovery(self):
        refs = copy.deepcopy(self.refs)
        refs[0]["document"]["sources"] = {"a": {"type": "app", "app_class": "terminal"}}
        self.queue.enqueue([], refs)
        desktop = f.record(f.window("1"))["desktop"]
        desktop["active"] = "1"
        desktop["workspaces"] = [{"selector": "1", "order": ["1"]}]
        captured = self.queue.preserve(desktop)
        self.assertEqual(captured["windows"], [])
        self.assertEqual(captured["workspaces"][0]["order"], [])
        self.assertIsNone(captured["active"])
        self.assertEqual(captured["scenes"], refs)
        desktop = f.record(f.window("1"), f.window("2"))["desktop"]
        captured = self.queue.preserve(desktop)
        self.assertEqual(len(captured["windows"]), 2)
        self.assertEqual(captured["scenes"][0]["document"]["sources"], {})
        self.assertEqual(self.queue.pending, refs)

    def test_delivery_requires_an_explicit_ack_over_the_socket(self):
        runtime = self.root / "hypertile-scenes"
        runtime.mkdir()
        address = runtime / "control.sock"
        for reply, success in [(b'null\n', False), (b'{"ok":true}\n', False),
                               (b'{"ok":true,"result":{"accepted":false}}\n', False),
                               (b'{"ok":true,"result":{"accepted":true}}\n', True)]:
            address.unlink(missing_ok=True)
            received = []
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(address)); server.listen(1)
                def respond():
                    with server.accept()[0] as client:
                        data = b""
                        while not data.endswith(b"\n"):
                            data += client.recv(4096)
                        received.append(json.loads(data))
                        client.sendall(reply)
                thread = threading.Thread(target=respond, daemon=True)
                thread.start()
                if success:
                    scenes.deliver(self.refs)
                else:
                    with self.assertRaises(ValueError):
                        scenes.deliver(self.refs)
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(received, [{"command": "session-restore", "scenes": self.refs}])

    def lease(self, **updates):
        lease = {"instance": "new", "token": "owner", "deadline": 10,
                 "base": {"layout": "lua:quad", "spec": {"name": "one"}},
                 "shown": ["lua:quad", "lua:wide"], "windows": [
                     {"address": "1", "stable_id": 1, "pid": 101, "pin": "one", "pin_exclusive": True}]}
        lease.update(updates)
        path = self.root / "hypertile/scenes/state.json"
        atomic_json(path, {"version": 1, "instance": "new", "browse": {"active": {"1": lease}}})
        desktop = f.record(f.window("1"))["desktop"]
        desktop["workspaces"] = [{"selector": "1", "layout": "lua:wide"}]
        desktop["layouts"] = {"wide": {"spec": {"name": "preview"}}}
        return desktop

    def test_live_lease_pauses_then_expiry_saves_committed_layout_and_pins(self):
        desktop = self.lease()
        desktop["layouts"]["quad"] = {"spec": {"name": "one"}, "sizes": {"one": .7}}
        with self.assertRaises(scenes.CapturePaused):
            scenes.capture(copy.deepcopy(desktop), "new", now=9)
        warnings = []
        captured = scenes.capture(desktop, "new", now=10, warnings=warnings)
        self.assertEqual(captured["workspaces"][0]["layout"], "lua:quad")
        self.assertEqual(captured["layouts"]["quad"]["spec"], {"name": "one"})
        self.assertEqual(captured["layouts"]["quad"]["sizes"], {"one": .7})
        self.assertEqual(captured["windows"][0]["pin"], "one")
        self.assertTrue(captured["windows"][0]["pin_exclusive"])
        self.assertIn("expired", warnings[0])

    def test_expired_lease_never_reverts_external_layout_or_departed_window(self):
        desktop = self.lease()
        desktop["workspaces"][0]["layout"] = "dwindle"
        warnings = []
        captured = scenes.capture(desktop, "new", now=10, warnings=warnings)
        self.assertEqual(captured["workspaces"][0]["layout"], "dwindle")
        self.assertFalse(warnings)
        for changes in ({"workspace": "2"}, {"floating": True}, {"stable_id": 99}):
            desktop = self.lease()
            desktop["windows"][0].update(changes, pin="changed")
            self.assertEqual(scenes.capture(desktop, "new", now=10)["windows"][0]["pin"], "changed")

    def test_old_compositor_lease_cannot_pause_or_rewrite_a_new_session(self):
        desktop = self.lease(instance="old", deadline=99999999999)
        captured = scenes.capture(desktop, "new", now=0)
        self.assertEqual(captured["workspaces"][0]["layout"], "lua:wide")

    def test_capture_errors_stay_visible_until_a_successful_checkpoint(self):
        desktop = self.lease()
        self.comp.desktop = desktop
        service = Service(self.store, self.comp, f.Launchers())
        with patch("scene_recovery.time.monotonic", return_value=9):
            with self.assertRaises(scenes.CapturePaused):
                service.checkpoint()
        status = service.status()
        self.assertTrue(status["saving"]["paused"])
        self.assertIsNotNone(status["saving"]["since"])
        self.assertIn("preview", status["error"])
        with patch("scene_recovery.time.monotonic", return_value=10):
            service.checkpoint()
        status = service.status()
        self.assertFalse(status["saving"]["paused"])
        self.assertIsNone(status["error"])
        self.assertIn("expired", status["saving"]["warning"])
        self.assertEqual(self.store.load()["desktop"]["workspaces"][0]["layout"], "lua:quad")

    def test_status_distinguishes_disabled_from_unavailable(self):
        config = self.root / "hypertile/session.json"
        atomic_json(config, {"enabled": False})
        entry = Path(__file__).resolve().parents[1] / "session/service.py"
        result = subprocess.run([sys.executable, str(entry), "status"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"mode": "disabled"})
        atomic_json(config, {"enabled": True})
        result = subprocess.run([sys.executable, str(entry), "status"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__": unittest.main()
