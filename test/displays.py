#!/usr/bin/env python3
"""Display validation, transactional persistence, and failure-injection tests."""
import copy
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
from adapter import DisplayError, bounds, match, normalized, validate
from service import Service, atomic, read


def display(name='DP-1', x=0):
    return dict(id='connector:' + name, identity='connector:' + name, connector=name,
                connected=True, ambiguous=False, enabled=True, width=1920, height=1080,
                refresh=60., scale=1., transform=0, x=x, y=0, modes=['1920x1080@60.00Hz'], awake=True)


class Fake:
    def __init__(self):
        self.current = [display(), display('DP-2', 1920)]
        self.calls = []
        self.fail = False
    def displays(self): return copy.deepcopy(self.current)
    def workspaces(self): return [dict(name='1', monitor='DP-1'), dict(name='work', monitor='DP-2')]
    def conflicts(self): return []
    def apply(self, d):
        self.calls.append(('apply', d['connector'], d['enabled']))
        if self.fail:
            self.fail = False
            raise DisplayError('Injected apply failure')
        self.current = [dict(d) if m['connector'] == d['connector'] else m for m in self.current]
    def verify(self, desired):
        from adapter import same
        if not all(any(m['connector'] == d['connector'] and same(m, d) for m in self.current) for d in desired):
            raise DisplayError('readback mismatch')
        return self.displays()
    def move(self, workspace, connector): self.calls.append(('move', workspace, connector))


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, XDG_STATE_HOME=self.temp.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.adapter = Fake()
        self.service = Service(self.adapter, self.temp.name)
        self.service.policy = None
    def doc(self): return dict(version=1, displays=self.adapter.displays(), workspaces={})
    def test_scene_browse_lease_blocks_display_preview_before_writes(self):
        state = Path(self.temp.name) / 'hypertile/scenes/state.json'
        atomic(state, {'browse': {'active': {'1': {'token': 'owned'}}}})
        with self.assertRaisesRegex(DisplayError, 'layout preview'):
            self.service.preview(self.doc(), watchdog=False)
        self.assertFalse(self.service.pending_path.exists())
        self.assertEqual(self.adapter.calls, [])
        atomic(state, {'browse': {'active': {}}})
        pending = self.service.preview(self.doc(), watchdog=False)
        self.service.revert(pending['token'])

    def test_catalog_retains_duplicate_identity_preferences_with_one_unplugged(self):
        saved = [dict(display(name, x), id='edid:abc@' + name, identity='edid:abc', explicit_match=True)
                 for name, x in [('DP-1', 0), ('DP-2', 1920)]]
        document = dict(version=1, displays=saved, workspaces={'1': {'monitor': 'edid:abc@DP-2'}})
        atomic(self.service.confirmed_path, document)
        self.adapter.current = [dict(saved[1], id='edid:abc', ambiguous=False)]
        catalog = self.service.catalog()
        connected = [d for d in catalog['displays'] if d['connected']]
        self.assertEqual([d['id'] for d in connected], ['edid:abc@DP-2'])
        self.assertEqual(len(catalog['displays']), 2)
        self.assertEqual(catalog['confirmed']['workspaces']['1']['monitor'], connected[0]['id'])
        from policy import validate as validate_policy
        validate_policy(dict(document, displays=catalog['displays']))

    def test_two_saved_preferences_cannot_claim_one_connector(self):
        first = dict(display(), id='edid:abc@old', identity='edid:abc', explicit_match=True)
        second = dict(first, id='edid:abc')
        current = [dict(second)]
        with self.assertRaisesRegex(DisplayError, 'More than one saved display'):
            validate(dict(version=1, displays=[first, second]), current)

    def test_invalid_document_shape_is_actionable(self):
        for value in ([], None, "wrong"):
            with self.assertRaisesRegex(DisplayError, 'version 1'):
                validate(value, self.adapter.displays())

    def test_last_display_rejected(self):
        doc = self.doc()
        for d in doc['displays']: d['enabled'] = False
        with self.assertRaisesRegex(DisplayError, 'last usable'): validate(doc, self.adapter.displays())
    def test_rotation_and_fractional_bounds(self):
        d = dict(display(), scale=1.25, transform=1)
        self.assertEqual(bounds(d), (0, 0, 864, 1536))
    def test_bad_modes_and_overlap(self):
        doc = self.doc(); doc['displays'][0]['refresh'] = 144
        with self.assertRaisesRegex(DisplayError, 'Unsupported'): validate(doc, self.adapter.displays())
        doc = self.doc(); doc['displays'][1]['x'] = 100
        with self.assertRaisesRegex(DisplayError, 'overlap'): validate(doc, self.adapter.displays())
    def test_keep_only_persists_confirmed(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        pending = self.service.preview(doc, watchdog=False)
        self.assertFalse(self.service.confirmed_path.exists())
        self.service.keep(pending['token'])
        self.assertEqual(read(self.service.confirmed_path)['displays'][1]['x'], 2000)
        self.assertFalse(self.service.pending_path.exists())
    def test_timeout_reverts_without_commit(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        pending = self.service.preview(doc, watchdog=False)
        data = read(self.service.pending_path); data['deadline'] = time.time() - 1; atomic(self.service.pending_path, data)
        with self.assertRaisesRegex(DisplayError, 'expired'): self.service.keep(pending['token'])
        self.assertEqual(self.adapter.current[1]['x'], 1920)
        self.assertFalse(self.service.confirmed_path.exists())
    def test_failed_application_rolls_back(self):
        self.adapter.fail = True
        with self.assertRaises(DisplayError): self.service.preview(self.doc(), watchdog=False)
        self.assertFalse(self.service.pending_path.exists())
        self.assertTrue(self.adapter.current[0]['enabled'])
    def test_external_change_not_overwritten(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        self.service.preview(doc, watchdog=False)
        self.adapter.current[1]['x'] = 2100
        result = self.service.revert()
        self.assertEqual(self.adapter.current[1]['x'], 2100)
        self.assertIn('DP-2', result['external'])
    def test_unplug_recovers_other_output(self):
        doc = self.doc(); doc['displays'][0]['enabled'] = False
        self.service.preview(doc, watchdog=False)
        self.adapter.current = self.adapter.current[:1]
        result = self.service.revert()
        self.assertTrue(self.adapter.current[0]['enabled'])
        self.assertTrue(result['fallback'])
    def test_overlap_previews_rejected(self):
        self.service.preview(self.doc(), watchdog=False)
        with self.assertRaisesRegex(DisplayError, 'already active'): self.service.preview(self.doc(), watchdog=False)
    def test_restart_rolls_back(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        self.service.preview(doc, watchdog=False)
        self.service.restore()
        self.assertEqual(self.adapter.current[1]['x'], 1920)
    def test_destinations_enabled_first(self):
        self.adapter.current[1]['enabled'] = False
        doc = self.doc(); doc['displays'][0]['enabled'] = False; doc['displays'][1]['enabled'] = True
        self.service.preview(doc, watchdog=False)
        applies = [call for call in self.adapter.calls if call[0] == 'apply']
        self.assertEqual(applies[0], ('apply', 'DP-2', True))
    def test_explicit_duplicate_identity_follows_connector(self):
        saved = dict(display(), id='edid:abc@DP-1', identity='edid:abc', explicit_match=True)
        current = [dict(display(), id='edid:abc', identity='edid:abc')]
        self.assertEqual(match(saved, current), current[0])
        self.assertIsNone(match(dict(saved, explicit_match=False), current))
    def test_keep_crash_window_does_not_undo_confirmation(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        pending = self.service.preview(doc, watchdog=False)
        atomic(self.service.confirmed_path, dict(doc, _transaction=pending['token']))
        result = self.service.revert()
        self.assertEqual(result['reason'], 'already-confirmed')
        self.assertEqual(self.adapter.current[1]['x'], 2000)
        self.assertFalse(self.service.pending_path.exists())
    def test_current_mode_without_advertised_modes_remains_valid(self):
        for d in self.adapter.current: d['modes'] = []
        doc = self.doc(); doc['displays'][1]['transform'] = 1
        self.assertEqual(len(validate(doc, self.adapter.displays())), 2)
    def test_unavailable_saved_output_never_matches_arbitrary_connector(self):
        saved = dict(display(), id='edid:abc@DP-1', identity='edid:abc', explicit_match=True)
        current = [dict(display('DP-3'), id='edid:abc', identity='edid:abc')]
        self.assertIsNone(match(saved, current))
    def test_offline_display_fields_are_validated(self):
        doc = self.doc()
        offline = display('DP-3', 4000)
        offline['scale'] = float('nan')
        doc['displays'].append(offline)
        with self.assertRaisesRegex(DisplayError, 'finite'):
            validate(doc, self.adapter.displays())
    def test_restore_unavailable_mode_keeps_usable_desktop_and_intent(self):
        doc = self.doc(); doc['displays'][1]['refresh'] = 144
        atomic(self.service.confirmed_path, doc)
        report = self.service.restore()
        self.assertTrue(report['fallback'])
        self.assertTrue(self.adapter.current[0]['enabled'])
        self.assertEqual(read(self.service.confirmed_path)['displays'][1]['refresh'], 144)
        self.assertIn('Unsupported mode', report['errors'][0])
    def test_writer_lock_refreshes_stale_daemon_policy(self):
        from policy import WorkspacePolicy
        self.service.policy = WorkspacePolicy(self.adapter, self.service.directory)
        self.service.policy.state = dict(locations={'1': 'OLD'}, suppressed=[])
        latest = dict(locations={'1': 'DP-2'}, available=[], suppressed=['1'], initialized=True)
        atomic(self.service.directory / 'workspace-runtime.json', latest)
        with self.service.lock():
            self.assertEqual(self.service.policy.state, latest)
    def test_event_rechecks_pending_under_writer_guard(self):
        class Policy:
            state = {}
            def reconcile(self, document, reason):
                raise AssertionError('Event must not apply policy during a preview')
        self.service.policy = Policy()
        atomic(self.service.pending_path, dict(token='active'))
        self.assertFalse(self.service.event())
    def test_monitor_event_cannot_cancel_new_preview(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        pending = self.service.preview(doc, watchdog=False)
        result = self.service.restore('reconnect')
        self.assertTrue(result['preview_active'])
        self.assertEqual(read(self.service.pending_path)['token'], pending['token'])
        self.assertEqual(self.adapter.current[1]['x'], 2000)
    def test_stop_refuses_runtime_replacement_while_writer_busy(self):
        with (self.service.directory / 'daemon.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            with self.assertRaisesRegex(DisplayError, 'Runtime files must not be replaced'):
                self.service.stop(timeout=.01)
    def test_stop_recovers_preview_after_writer_exit(self):
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        self.service.preview(doc, watchdog=False)
        self.service.stop(timeout=.01)
        self.assertFalse(self.service.pending_path.exists())
        self.assertEqual(self.adapter.current[1]['x'], 1920)
    def test_nan_rejected(self):
        doc = self.doc(); doc['displays'][0]['scale'] = float('nan')
        with self.assertRaisesRegex(DisplayError, 'finite'): validate(doc, self.adapter.displays())

if __name__ == '__main__': unittest.main()
