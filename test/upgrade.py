"""Upgrade preserves unresolved host recovery and removes only owned runtime files."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'session'))
from upgrade import check_legacy, cleanup, obsolete

class UpgradeTests(unittest.TestCase):
    def test_pending_or_corrupt_state_refuses_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'streams/state.json'
            path.parent.mkdir()
            for value in ({'version': 1, 'computers': {'mac': {'desired': True}}},
                          {'version': 1, 'computers': {'mac': {'desired': False, 'journal': {'output': {}}}}},
                          {'version': 99, 'computers': {}}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): check_legacy(root)
            path.write_text('not JSON')
            with self.assertRaises(ValueError): check_legacy(root)
            path.write_text(json.dumps({'version': 1, 'computers': {'mac': {'desired': False, 'journal': {}}}}))
            check_legacy(root)
    def test_cleanup_preserves_user_files_and_new_scene_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary, data = root / 'bin', root / 'data'
            for path in obsolete(binary, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('legacy')
            preserved = [data / 'hypertile/stream/custom.py', data / 'hypertile/scenes/scenes.py',
                         data / 'hypertile/streams/state.json', binary / 'remote-desktops']
            for path in preserved:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('keep')
            cleanup(binary, data)
            cleanup(binary, data)
            self.assertTrue(all(not p.exists() for p in obsolete(binary, data)))
            self.assertTrue(all(p.read_text() == 'keep' for p in preserved))

if __name__ == '__main__': unittest.main()
