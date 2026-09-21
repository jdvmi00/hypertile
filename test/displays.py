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
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
from adapter import DisplayError, bounds, clean_scale, match, normalized, validate
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
    WAKE_OPTIONS = ('key_press_enables_dpms', 'mouse_move_enables_dpms')
    options = dict(key_press_enables_dpms=True, mouse_move_enables_dpms=True)
    def wake_options(self): return dict(self.options)
    def set_wake_options(self, options): self.options = dict(options)
    def power(self, connector, awake):
        self.calls.append(('power', connector, awake))
        for m in self.current:
            if m['enabled'] and (not connector or m['connector'] == connector):
                m['awake'] = awake


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
    def awake(self, connector):
        return next(m for m in self.adapter.current if m['connector'] == connector)['awake']
    def test_show_workspace_moves_existing_then_focuses_without_saving(self):
        self.adapter.workspaces = lambda: [dict(id=5, name='5', monitor='DP-1')]
        self.adapter.dispatch = Mock()
        self.adapter.run = Mock(return_value=json.dumps(dict(id=5, name='5', monitor='DP-2')))
        result = self.service.show_workspace('DP-2', '5')
        self.assertEqual(result['workspace'], '5')
        self.assertEqual(self.adapter.calls, [('move', '5', 'DP-2')])
        self.assertEqual([c.args for c in self.adapter.dispatch.call_args_list],
                         [('focus', '{monitor="DP-2"}'), ('focus', '{workspace="5"}')])
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertFalse(self.service.pending_path.exists())

    def test_show_new_named_workspace_and_verify_readback(self):
        self.adapter.dispatch = Mock()
        self.adapter.run = Mock(return_value=json.dumps(dict(id=-1337, name='research', monitor='DP-2')))
        self.service.show_workspace('DP-2', 'name:research')
        self.assertEqual(self.adapter.calls, [])
        self.adapter.run.return_value = json.dumps(dict(id=1, name='1', monitor='DP-1'))
        with self.assertRaisesRegex(DisplayError, 'did not show'):
            self.service.show_workspace('DP-2', 'name:research')

    def test_show_workspace_rejects_unavailable_outputs_invalid_ids_and_preview(self):
        self.adapter.dispatch = Mock()
        for workspace in ('0', '-1', '2147483648', 'special:scratchpad', 'name:x";error()'):
            with self.assertRaises(DisplayError):
                self.service.show_workspace('DP-2', workspace)
        for changes in ({'awake': False}, {'enabled': False}, {'mirror_of': 'connector:DP-1'}):
            self.adapter.current[1] = dict(display('DP-2', 1920), **changes)
            with self.assertRaises(DisplayError):
                self.service.show_workspace('DP-2', '1')
        with self.assertRaises(DisplayError):
            self.service.show_workspace('missing', '1')
        atomic(self.service.pending_path, dict(token='test'))
        with self.assertRaisesRegex(DisplayError, 'preview'):
            self.service.show_workspace('DP-1', '1')
        self.adapter.dispatch.assert_not_called()
        self.assertEqual(self.adapter.calls, [])

    def test_sleep_holds_input_wake_off_while_another_display_is_awake(self):
        # Hyprland's global DPMS flag would otherwise let any key or mouse move undo the sleep.
        self.adapter.options = dict(key_press_enables_dpms=True, mouse_move_enables_dpms=False)
        self.assertEqual(self.service.power('DP-2', False), dict(awake=False, connector='DP-2'))
        self.assertFalse(self.awake('DP-2'))
        self.assertEqual(self.adapter.options, dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False))
        self.assertEqual(read(self.service.power_path)['original'], dict(key_press_enables_dpms=True, mouse_move_enables_dpms=False))
        self.service.power('DP-2', True)
        self.assertTrue(self.awake('DP-2'))
        self.assertEqual(self.adapter.options, dict(key_press_enables_dpms=True, mouse_move_enables_dpms=False))
        self.assertFalse(self.service.power_path.exists())
    def test_sleeping_the_last_awake_display_keeps_a_keyboard_way_back(self):
        self.adapter.options = dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False)
        self.service.power('DP-2', False)
        self.service.power('DP-1', False)
        self.assertEqual(self.adapter.options, dict(key_press_enables_dpms=True, mouse_move_enables_dpms=False))
        self.assertEqual(read(self.service.power_path)['original'], dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False),
                         'the values from before the first sleep survive a second sleep')
        self.service.power('', True)
        self.assertTrue(self.awake('DP-1') and self.awake('DP-2'))
        self.assertEqual(self.adapter.options, dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False))
        self.assertFalse(self.service.power_path.exists())
    def test_wake_options_settle_after_external_wake_and_config_reload(self):
        self.service.power('DP-2', False)
        self.adapter.options = dict(key_press_enables_dpms=True, mouse_move_enables_dpms=True)  # hyprctl reload
        self.assertTrue(self.service.settle_power())
        self.assertEqual(self.adapter.options, dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False))
        self.adapter.current[1]['awake'] = True  # hypridle or hyprctl woke it
        self.assertEqual(self.service.catalog()['displays'][1]['awake'], True)
        self.assertEqual(self.adapter.options, dict(key_press_enables_dpms=True, mouse_move_enables_dpms=True))
        self.assertFalse(self.service.power_path.exists())
        self.assertFalse(self.service.settle_power())
    def test_sleep_refuses_disabled_or_unknown_displays_and_previews(self):
        with self.assertRaisesRegex(DisplayError, 'connected, enabled'):
            self.service.power('DP-9', False)
        self.assertFalse(self.service.power_path.exists())
        atomic(self.service.pending_path, dict(token='t', deadline=time.time() + 15))
        with self.assertRaisesRegex(DisplayError, 'preview'):
            self.service.power('DP-2', False)
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
    def test_scale_snaps_to_the_divisor_hyprland_would_pick(self):
        self.assertAlmostEqual(clean_scale(6144, 2560, 1.4), 4 / 3)
        self.assertAlmostEqual(clean_scale(6144, 2560, 1.5), 1.6)
        self.assertAlmostEqual(clean_scale(2304, 1536, 1.33333), 4 / 3)
        self.assertEqual(clean_scale(1920, 1080, 1.5), 1.5)
        self.assertEqual(clean_scale(0, 0, 1.4), 1.4)
        self.adapter.current[0].update(width=6144, height=2560, modes=['6144x2560@60.00Hz'])
        doc = self.doc(); doc['displays'][0].update(width=6144, height=2560, scale=1.4); doc['displays'][1]['x'] = 4608
        result = validate(doc, self.adapter.displays())
        self.assertAlmostEqual(result[0]['scale'], 4 / 3)
        self.assertEqual(doc['displays'][0]['scale'], 1.4)
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
    def transactional_policy(self, failure=None):
        state = Path(self.temp.name)
        rules = state / 'hypertile/workspace-rules'
        omarchy = state / 'omarchy/workspace-layouts'
        rules.mkdir(parents=True, exist_ok=True)
        omarchy.mkdir(parents=True, exist_ok=True)
        (rules / '1.lua').write_bytes(b'original rule\n')
        (omarchy / '1.lua').write_bytes(b'omarchy rule\n')
        class Policy:
            state = {}
            def validate_changes(self, document): pass
            def reconcile(self, document, reason): pass
            def _save_runtime(self): pass
            def restore_layouts(self, snapshot): pass
            def capture_workspaces(self): return []
            def commit(self, document, preferences_path=None, before_rule=None):
                assert read(preferences_path) == document
                before_rule('1')
                (rules / '1.lua').write_bytes(b'new rule\n')
                before_rule('2')
                (rules / '2.lua').write_bytes(b'new second rule\n')
                (omarchy / '1.lua').unlink()
                if failure:
                    raise failure
        self.service.policy = Policy()
        doc = self.doc()
        doc['displays'][1]['x'] = 2000
        doc['workspaces'] = {'1': {'layout': 'dwindle'}, '2': {'layout': None}}
        return doc, rules, omarchy
    def assert_transaction_recovered(self, rules, omarchy):
        self.assertEqual((rules / '1.lua').read_bytes(), b'original rule\n')
        self.assertFalse((rules / '2.lua').exists())
        self.assertEqual((omarchy / '1.lua').read_bytes(), b'omarchy rule\n')
        self.assertEqual(self.adapter.current[1]['x'], 1920)
        self.assertFalse(self.service.pending_path.exists())
        self.assertFalse(self.service.confirmed_path.exists())
    def test_midcommit_failure_restores_rules_geometry_and_confirmation(self):
        doc, rules, omarchy = self.transactional_policy(PermissionError('injected rule write failure'))
        pending = self.service.preview(doc, watchdog=False)
        with self.assertRaisesRegex(PermissionError, 'injected'):
            self.service.keep(pending['token'])
        self.assert_transaction_recovered(rules, omarchy)
    def test_crash_after_rule_writes_before_confirmation_recovers_on_startup(self):
        doc, rules, omarchy = self.transactional_policy(SystemExit('injected process death'))
        pending = self.service.preview(doc, watchdog=False)
        with self.assertRaises(SystemExit):
            self.service.keep(pending['token'])
        self.assertEqual(read(self.service.pending_path)['phase'], 'committing')
        self.assertFalse(self.service.confirmed_path.exists())
        self.service.restore()
        self.assert_transaction_recovered(rules, omarchy)
    def test_confirmation_write_failure_restores_already_staged_rules(self):
        doc, rules, omarchy = self.transactional_policy()
        pending = self.service.preview(doc, watchdog=False)
        def failing_atomic(path, value):
            if path == self.service.confirmed_path:
                raise PermissionError('injected confirmed write failure')
            return atomic(path, value)
        with patch('service.atomic', side_effect=failing_atomic):
            with self.assertRaisesRegex(PermissionError, 'confirmed'):
                self.service.keep(pending['token'])
        self.assert_transaction_recovered(rules, omarchy)
    def test_confirmation_marker_keeps_committed_rules_after_crash(self):
        doc, rules, omarchy = self.transactional_policy()
        pending = self.service.preview(doc, watchdog=False)
        journal = read(self.service.pending_path)
        journal['phase'] = 'committing'
        self.service.keep(pending['token'])
        atomic(self.service.pending_path, journal)  # crash before pending unlink
        self.service.revert(pending['token'])
        self.assertEqual((rules / '1.lua').read_bytes(), b'new rule\n')
        self.assertTrue((rules / '2.lua').exists())
        self.assertFalse((omarchy / '1.lua').exists())
        self.assertEqual(self.adapter.current[1]['x'], 2000)
        self.assertEqual(read(self.service.confirmed_path)['_transaction'], pending['token'])
    def test_transaction_rollback_preserves_unrelated_rule_changes(self):
        doc, rules, omarchy = self.transactional_policy(PermissionError('injected failure'))
        (rules / '99.lua').write_bytes(b'unrelated initial\n')
        pending = self.service.preview(doc, watchdog=False)
        (rules / '99.lua').write_bytes(b'unrelated changed during preview\n')
        (omarchy / '100.lua').write_bytes(b'unrelated new rule\n')
        with self.assertRaises(PermissionError):
            self.service.keep(pending['token'])
        self.assert_transaction_recovered(rules, omarchy)
        self.assertEqual((rules / '99.lua').read_bytes(), b'unrelated changed during preview\n')
        self.assertEqual((omarchy / '100.lua').read_bytes(), b'unrelated new rule\n')
    def test_rule_fsync_failure_prevents_confirmation(self):
        doc, rules, omarchy = self.transactional_policy()
        pending = self.service.preview(doc, watchdog=False)
        with patch('service.sync_rules', side_effect=OSError('injected rule fsync failure')):
            with self.assertRaisesRegex(OSError, 'fsync'):
                self.service.keep(pending['token'])
        self.assert_transaction_recovered(rules, omarchy)
    def test_skipped_rule_is_not_restored_by_failed_commit(self):
        doc, rules, omarchy = self.transactional_policy(PermissionError('injected failure'))
        doc['workspaces']['3'] = {'layout': 'dwindle'}
        (rules / '3.lua').write_bytes(b'initial third rule\n')
        pending = self.service.preview(doc, watchdog=False)
        # The commit skips this workspace (for example, it now belongs to a scene).
        (rules / '3.lua').write_bytes(b'new scene-owned rule\n')
        with self.assertRaises(PermissionError):
            self.service.keep(pending['token'])
        self.assert_transaction_recovered(rules, omarchy)
        self.assertEqual((rules / '3.lua').read_bytes(), b'new scene-owned rule\n')
    def test_rule_recovery_failure_retains_journal_for_retry(self):
        doc, rules, omarchy = self.transactional_policy(PermissionError('injected failure'))
        pending = self.service.preview(doc, watchdog=False)
        with patch('service.restore_rules', return_value=['temporary rule permission failure']):
            with self.assertRaises(PermissionError):
                self.service.keep(pending['token'])
        self.assertEqual(read(self.service.pending_path)['phase'], 'recovery-needed')
        self.service.revert(pending['token'])
        self.assert_transaction_recovered(rules, omarchy)
    def test_nan_rejected(self):
        doc = self.doc(); doc['displays'][0]['scale'] = float('nan')
        with self.assertRaisesRegex(DisplayError, 'finite'): validate(doc, self.adapter.displays())

    def test_mirror_readback_resolves_numeric_monitor_id(self):
        monitors = [dict(name='DP-1', id=0, width=1920, height=1080, refreshRate=60, x=0, y=0, scale=1, mirrorOf='none'),
                    dict(name='DP-2', id=1, width=1920, height=1080, refreshRate=60, x=0, y=0, scale=1, mirrorOf='0')]
        actual = normalized(monitors)
        self.assertEqual(actual[1]['mirror_of'], actual[0]['id'])
        self.assertEqual(actual[1]['mirror_connector'], 'DP-1')
        monitors[1]['mirrorOf'] = 'DP-1'
        self.assertEqual(normalized(monitors), actual)

    def test_mirror_transaction_and_clear(self):
        doc = self.doc()
        doc['displays'][1]['mirror_of'] = doc['displays'][0]['id']
        doc['displays'][1]['x'] = 0
        pending = self.service.preview(doc, watchdog=False)
        self.assertEqual(self.adapter.current[1]['mirror_connector'], 'DP-1')
        self.service.keep(pending['token'])
        catalog = self.service.catalog()
        self.assertEqual(catalog['displays'][1]['extended_position'], dict(x=1920, y=0))
        extended = dict(version=1, displays=catalog['displays'])
        extended['displays'][1].update(mirror_of=None, x=1920)
        pending = self.service.preview(extended, watchdog=False)
        self.assertFalse(self.adapter.current[1].get('mirror_connector'))
        self.service.revert(pending['token'])
        self.assertEqual(self.adapter.current[1]['mirror_connector'], 'DP-1')

    def test_mirror_validation(self):
        for source in ('connector:DP-2', 'missing'):
            doc = self.doc()
            doc['displays'][1]['mirror_of'] = source
            with self.assertRaisesRegex(DisplayError, 'independent'):
                validate(doc, self.adapter.displays())
        doc = self.doc()
        doc['displays'][0]['mirror_of'] = doc['displays'][1]['id']
        doc['displays'][1]['mirror_of'] = doc['displays'][0]['id']
        with self.assertRaisesRegex(DisplayError, 'chains and cycles'):
            validate(doc, self.adapter.displays())
        doc['displays'][0].update(mirror_of=None, enabled=False)
        with self.assertRaisesRegex(DisplayError, 'connected and enabled'):
            validate(doc, self.adapter.displays())
        doc['displays'][0]['enabled'] = True
        with self.assertRaisesRegex(DisplayError, 'connected and enabled'):
            validate(doc, self.adapter.displays()[1:])

    def test_mirror_source_applied_first_and_source_unplug_rollback(self):
        doc = self.doc()
        doc['displays'][0]['mirror_of'] = doc['displays'][1]['id']
        pending = self.service.preview(doc, watchdog=False)
        self.assertEqual(self.adapter.calls[0][1], 'DP-2')
        self.adapter.current = self.adapter.current[:1]
        result = self.service.revert(pending['token'])
        self.assertFalse(result['errors'])
        self.assertTrue(self.adapter.current[0]['enabled'])
        self.assertFalse(self.adapter.current[0].get('mirror_of'))

    def test_rollback_to_mirror_with_missing_source_promotes_remaining_output(self):
        self.adapter.current[1].update(mirror_of=self.adapter.current[0]['id'], mirror_connector='DP-1')
        doc = self.doc()
        doc['displays'][1].update(mirror_of=None, x=1920)
        pending = self.service.preview(doc, watchdog=False)
        self.adapter.current = self.adapter.current[1:]
        result = self.service.revert(pending['token'])
        self.assertTrue(result['fallback'])
        self.assertFalse(result['errors'])
        self.assertFalse(self.adapter.current[0].get('mirror_of'))

    def test_mirror_readback_ignores_position_but_requires_relationship(self):
        from adapter import same
        a = dict(display(), mirror_of='connector:DP-2', mirror_connector='DP-2')
        self.assertTrue(same(a, dict(a, x=1920)))
        self.assertFalse(same(a, dict(a, mirror_connector='DP-3')))
        self.assertFalse(same(a, dict(a, mirror_of=None, mirror_connector=None)))

    def test_runtime_mirrors_follow_external_changes_without_rewriting_preferences(self):
        from adapter import runtime_mirrors
        doc = self.doc()
        doc['displays'][1]['mirror_of'] = doc['displays'][0]['id']
        actual = runtime_mirrors(doc, self.adapter.displays())
        self.assertIsNone(actual['displays'][1]['mirror_of'])
        self.assertEqual(doc['displays'][1]['mirror_of'], doc['displays'][0]['id'])

    def test_countdown_starts_after_application_settles(self):
        original = self.adapter.apply
        def slow(d):
            time.sleep(.3)
            original(d)
        self.adapter.apply = slow
        doc = self.doc(); doc['displays'][1]['x'] = 2000
        start = time.time()
        pending = self.service.preview(doc, watchdog=False)
        self.assertGreaterEqual(pending['deadline'], start + Service.PREVIEW_SECONDS + .25)
        self.assertEqual(read(self.service.pending_path)['deadline'], pending['deadline'])
        self.assertGreater(pending['seconds'], Service.PREVIEW_SECONDS - 1)

    def test_watcher_idles_until_events_or_safety_poll(self):
        from service import Watcher
        consulted = []
        original = self.adapter.displays
        self.adapter.displays = lambda: consulted.append(1) or original()
        watcher = Watcher(self.service)
        self.assertTrue(watcher.tick([], 0.0))
        for now in (.5, 1.0, 4.9):
            self.assertFalse(watcher.tick([], now), 'a quiet desktop is not polled')
        self.assertFalse(watcher.tick(['workspace>>2', 'activewindow>>foot,shell'], 2.0), 'focus events are not placement events')
        self.assertTrue(watcher.tick(['moveworkspacev2>>1,1,DP-2'], 2.5))
        self.assertFalse(watcher.tick([], 7.0))
        self.assertTrue(watcher.tick([], 7.6), 'the safety poll still runs')
        self.assertTrue(watcher.tick(['monitorremoved>>DP-2'], 7.7))
        self.assertEqual(len(consulted), 4)
        atomic(self.service.power_path, dict(original={}, apply={}))
        self.assertTrue(watcher.tick([], 7.8), 'wake options settle while an output sleeps')
        self.service.power_path.unlink(missing_ok=True)
        polling = Watcher(self.service, polling=True)
        self.assertTrue(polling.tick([], 0.0))
        self.assertTrue(polling.tick([], .5), 'without the event socket the old cadence remains')

if __name__ == '__main__': unittest.main()
