#!/usr/bin/env python3
"""Display validation, transactional persistence, and failure-injection tests."""
import contextlib
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


@contextlib.contextmanager
def nonblocking_locks():
    """Exercise real locks, but fail instead of hanging on recursive acquisition."""
    flock = fcntl.flock
    with patch('service.fcntl.flock', side_effect=lambda fd, operation: flock(fd, operation | fcntl.LOCK_NB)):
        yield


def display(name='DP-1', x=0):
    return dict(id='connector:' + name, identity='connector:' + name, connector=name,
                connected=True, ambiguous=False, enabled=True, width=1920, height=1080,
                refresh=60., scale=1., transform=0, x=x, y=0, modes=['1920x1080@60.00Hz'], awake=True)


class Fake:
    def __init__(self):
        self.current = [display(), display('DP-2', 1920)]
        self.live = [dict(id=1, name='1', monitor='DP-1'), dict(id=-2, name='work', monitor='DP-2')]
        self.calls = []
        self.fail = False
    def displays(self): return copy.deepcopy(self.current)
    def workspaces(self): return copy.deepcopy(self.live)
    def conflicts(self): return []
    def apply(self, d):
        self.calls.append(('apply', d['connector'], d['enabled']))
        if self.fail:
            self.fail = False
            raise DisplayError('Injected apply failure')
        self.current = [dict(d, awake=m['awake']) if m['connector'] == d['connector'] else m for m in self.current]
    def verify(self, desired):
        from adapter import same
        if not all(any(m['connector'] == d['connector'] and same(m, d) for m in self.current) for d in desired):
            raise DisplayError('readback mismatch')
        return self.displays()
    def move(self, workspace, connector):
        self.calls.append(('move', workspace, connector))
        for item in self.live:
            if Service._handoff_workspace(item) == workspace:
                item['monitor'] = connector
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

    def test_layout_helper_reads_catalog_without_reacquiring_parent_lock_or_mutating_power(self):
        for variable in ('HYPERTILE_DISPLAY_APPLY', 'HYPERTILE_DISPLAY_LOCKED'):
            with self.subTest(variable=variable), nonblocking_locks(), self.service.lock():
                with patch.dict(os.environ, {variable: '1'}), patch.object(self.service, '_settle_power') as settle:
                    self.assertEqual(len(self.service.catalog()['displays']), 2)
                    settle.assert_not_called()

    def removal(self):
        saved = self.doc()
        saved['workspaces'] = {'2': dict(monitor=saved['displays'][1]['id'], layout='lua:quad')}
        atomic(self.service.confirmed_path, saved)
        self.adapter.current.pop()
        document = copy.deepcopy(saved)
        document['removed_displays'] = [document['displays'].pop()['id']]
        document['workspaces']['2']['monitor'] = None
        return saved, document

    def test_removal_is_staged_and_revert_preserves_saved_profile(self):
        saved, document = self.removal()
        result = self.service.preview(document, watchdog=False)
        self.assertEqual(read(self.service.confirmed_path), saved)
        self.service.revert(result['token'])
        self.assertEqual(read(self.service.confirmed_path), saved)
        self.assertEqual(len(self.service.catalog()['displays']), 2)

    def test_keep_removal_preserves_layout_and_rediscovers_reconnected_display(self):
        saved, document = self.removal()
        result = self.service.preview(document, watchdog=False)
        self.service.keep(result['token'])
        confirmed = read(self.service.confirmed_path)
        self.assertEqual(len(confirmed['displays']), 1)
        self.assertNotIn('removed_displays', confirmed)
        self.assertEqual(confirmed['workspaces']['2'], dict(monitor=None, layout='lua:quad'))
        self.assertEqual(len(self.service.catalog()['displays']), 1)
        self.adapter.current.append(saved['displays'][1])
        self.assertEqual(len(self.service.catalog()['displays']), 2)
        self.assertEqual(read(self.service.confirmed_path), confirmed)

    def test_immediate_removal_saves_without_geometry_changes_or_pending_preview(self):
        saved, _ = self.removal()
        result = self.service.remove_display(saved['displays'][1]['id'], watchdog=False)
        self.assertEqual(result['removed'], saved['displays'][1]['id'])
        self.assertNotIn('token', result)
        self.assertFalse(self.service.pending_path.exists())
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(read(self.service.confirmed_path)['workspaces']['2'], dict(monitor=None, layout='lua:quad'))
        self.assertEqual(len(self.service.catalog()['displays']), 1)

    def test_immediate_removal_rejects_connected_unknown_and_mirror_sources(self):
        saved, _ = self.removal()
        with self.assertRaisesRegex(DisplayError, 'connected display'):
            self.service.remove_display(saved['displays'][0]['id'], watchdog=False)
        with self.assertRaisesRegex(DisplayError, 'no longer available'):
            self.service.remove_display('missing', watchdog=False)
        mirror = dict(saved['displays'][1], id='absent-mirror', connector='DP-3', mirror_of=saved['displays'][1]['id'])
        saved['displays'].append(mirror)
        atomic(self.service.confirmed_path, saved)
        with self.assertRaisesRegex(DisplayError, 'mirror source'):
            self.service.remove_display(saved['displays'][1]['id'], watchdog=False)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(read(self.service.confirmed_path), saved)

    def test_immediate_removal_does_not_require_waking_remaining_display(self):
        saved, _ = self.removal()
        self.adapter.current[0]['awake'] = False
        self.service.remove_display(saved['displays'][1]['id'], watchdog=False)
        self.assertFalse(self.awake('DP-1'))
        self.assertEqual(self.adapter.calls, [])

    def test_immediate_removal_with_sleep_guard_preserves_power_and_allows_wake(self):
        saved, _ = self.removal()
        original_options = self.adapter.wake_options()
        self.service.power('DP-1', False)
        self.assertTrue(self.service.power_path.exists())
        self.adapter.calls.clear()
        with nonblocking_locks():
            result = self.service.remove_display(saved['displays'][1]['id'], watchdog=False)
            self.assertEqual(result['removed'], saved['displays'][1]['id'])
            self.assertEqual(len(read(self.service.confirmed_path)['displays']), 1)
            self.assertFalse(self.service.pending_path.exists())
            self.assertFalse(self.awake('DP-1'))
            self.assertEqual(self.adapter.calls, [])
            self.assertTrue(self.adapter.options['key_press_enables_dpms'])
            self.service.power('DP-1', True)
        self.assertTrue(self.awake('DP-1'))
        self.assertFalse(self.service.power_path.exists())
        self.assertEqual(self.adapter.wake_options(), original_options)

    def test_immediate_removal_rejects_existing_preview(self):
        saved, document = self.removal()
        pending = self.service.preview(document, watchdog=False)
        with self.assertRaisesRegex(DisplayError, 'Keep or revert'):
            self.service.remove_display(saved['displays'][1]['id'], watchdog=False)
        self.assertEqual(read(self.service.pending_path)['token'], pending['token'])
        self.assertEqual(read(self.service.confirmed_path), saved)

    def test_reconnect_before_preview_rejects_removal_without_mutations(self):
        saved, document = self.removal()
        self.adapter.current.append(saved['displays'][1])
        with self.assertRaisesRegex(DisplayError, 'connected display'):
            self.service.preview(document, watchdog=False)
        self.assertFalse(self.service.pending_path.exists())
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(read(self.service.confirmed_path), saved)

    def test_reconnect_during_preview_reverts_removal(self):
        saved, document = self.removal()
        result = self.service.preview(document, watchdog=False)
        self.adapter.current.append(saved['displays'][1])
        with self.assertRaisesRegex(DisplayError, 'connected display'):
            self.service.keep(result['token'])
        self.assertFalse(self.service.pending_path.exists())
        self.assertEqual(read(self.service.confirmed_path), saved)

    def test_reused_connector_cannot_be_removed_even_with_different_identity(self):
        saved, document = self.removal()
        self.adapter.current.append(dict(saved['displays'][1], id='new-panel', identity='new-panel'))
        with self.assertRaisesRegex(DisplayError, 'connector now in use'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.calls, [])

    def test_removal_rejects_dangling_workspace_and_disconnected_mirror_references(self):
        saved, document = self.removal()
        document['workspaces'] = saved['workspaces']
        with self.assertRaisesRegex(DisplayError, 'workspace placement'):
            self.service.preview(document, watchdog=False)
        document['workspaces'] = {}
        mirror = dict(saved['displays'][1], id='absent-mirror', connector='DP-3', mirror_of=document['removed_displays'][0])
        document['displays'].append(mirror)
        with self.assertRaisesRegex(DisplayError, 'mirror source'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.calls, [])

    def test_removal_ids_must_be_known_unique_and_absent_from_draft(self):
        saved, document = self.removal()
        for ids in ('DP-2', [1], ['missing'], document['removed_displays'] * 2, [saved['displays'][0]['id']]):
            with self.subTest(ids=ids), self.assertRaises(DisplayError):
                self.service.preview(dict(document, removed_displays=ids), watchdog=False)
        self.assertEqual(self.adapter.calls, [])

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
    def test_one_pixel_overlap_is_rejected(self):
        doc = self.doc()
        doc['displays'][1]['x'] = 1919
        with self.assertRaisesRegex(DisplayError, 'overlap'):
            validate(doc, self.adapter.displays())

    def test_disabled_at_startup_gets_an_editable_advertised_mode(self):
        self.adapter.current[1].update(enabled=False, width=0, height=0, x=-1, y=-1)
        doc = dict(version=1, displays=self.service.catalog()['displays'], workspaces={})
        d = doc['displays'][1]
        self.assertEqual((d['width'], d['height'], d['refresh']), (1920, 1080, 60))
        d.update(enabled=True, x=1920, y=0)
        pending = self.service.preview(doc, watchdog=False)
        self.service.keep(pending['token'])
        self.assertTrue(self.adapter.current[1]['enabled'])

    def test_disabled_catalog_retains_saved_mode_scale_and_position(self):
        saved = dict(self.doc(), configuration_backed=True)
        saved['displays'][1].update(enabled=False, scale=1.5, transform=1, x=1920, y=-200)
        atomic(self.service.confirmed_path, saved)
        self.adapter.current[1].update(enabled=False, width=0, height=0, scale=1, transform=0, x=-1, y=-1)
        d = self.service.catalog()['displays'][1]
        self.assertEqual((d['width'], d['height'], d['scale'], d['transform'], d['x'], d['y']),
                         (1920, 1080, 1.5, 1, 1920, -200))
        self.assertFalse(d['enabled'])

    def test_disabled_virtual_output_can_reenable_its_confirmed_unadvertised_mode(self):
        saved = self.doc()
        saved['displays'][1]['enabled'] = False
        atomic(self.service.confirmed_path, saved)
        self.adapter.current[1].update(enabled=False, width=0, height=0, modes=[])
        doc = dict(version=1, displays=self.service.catalog()['displays'], workspaces={})
        doc['displays'][1]['enabled'] = True
        with self.assertRaisesRegex(DisplayError, 'Unsupported mode'):
            validate(doc, self.adapter.displays())
        pending = self.service.preview(doc, watchdog=False)
        self.assertTrue(self.adapter.current[1]['enabled'])
        self.service.revert(pending['token'])
        doc['displays'][1]['width'] = 3840
        with self.assertRaisesRegex(DisplayError, 'Unsupported mode'):
            self.service.preview(doc, watchdog=False)

    def test_preview_records_normalized_scale(self):
        self.adapter.current[0].update(width=6144, height=2560, modes=['6144x2560@60.00Hz'])
        self.adapter.current[1]['x'] = 6144
        doc = self.doc()
        doc['displays'][0]['scale'] = 1.4
        doc['displays'][1]['x'] = 4608
        pending = self.service.preview(doc, watchdog=False)
        self.assertAlmostEqual(read(self.service.pending_path)['document']['displays'][0]['scale'], 4 / 3)
        self.service.keep(pending['token'])
        self.assertAlmostEqual(read(self.service.confirmed_path)['displays'][0]['scale'], 4 / 3)

    def test_revert_disables_new_mirror_without_disabling_its_source(self):
        self.adapter.current[1]['enabled'] = False
        self.adapter.workspaces = lambda: [dict(name='1', monitor='DP-1')]
        doc = self.doc()
        doc['displays'][1].update(enabled=True, mirror_of=doc['displays'][0]['id'])
        pending = self.service.preview(doc, watchdog=False)
        result = self.service.revert(pending['token'])
        self.assertFalse(result['fallback'])
        self.assertFalse(result['errors'])
        self.assertTrue(self.adapter.current[0]['enabled'])
        self.assertFalse(self.adapter.current[1]['enabled'])

    def test_disabling_last_awake_output_requires_waking_destination(self):
        self.service.power('DP-2', False)
        doc = self.doc()
        doc['displays'][0]['enabled'] = False
        with self.assertRaisesRegex(DisplayError, 'Wake an extended display'):
            self.service.preview(doc, watchdog=False)
        self.assertFalse(self.service.pending_path.exists())
        self.assertTrue(self.adapter.current[0]['enabled'])
        self.service.power('DP-2', True)
        pending = self.service.preview(doc, watchdog=False)
        self.service.revert(pending['token'])

    def test_reenabling_previously_sleeping_output_wakes_it_before_source_disable(self):
        self.service.power('DP-2', False)
        self.adapter.current[1]['enabled'] = False
        doc = self.doc()
        doc['displays'][0]['enabled'] = False
        doc['displays'][1]['enabled'] = True
        pending = self.service.preview(doc, watchdog=False)
        self.assertTrue(self.awake('DP-2'))
        self.assertLess(self.adapter.calls.index(('power', 'DP-2', True)),
                        self.adapter.calls.index(('apply', 'DP-1', False)))
        self.service.revert(pending['token'])

    def test_unplugging_awake_output_restores_keyboard_wake(self):
        self.adapter.options = dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False)
        self.service.power('DP-2', False)
        self.adapter.current = self.adapter.current[1:]
        self.service.settle_power()
        self.assertTrue(self.adapter.options['key_press_enables_dpms'])
        self.adapter.current.append(display())
        self.service.settle_power()
        self.assertFalse(self.adapter.options['key_press_enables_dpms'])
        self.service.power('DP-2', True)
        self.assertFalse(self.adapter.options['key_press_enables_dpms'])

    def test_sleep_all_keeps_keyboard_wake(self):
        self.adapter.options = dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False)
        self.service.power('', False)
        self.assertFalse(self.awake('DP-1') or self.awake('DP-2'))
        self.assertTrue(self.adapter.options['key_press_enables_dpms'])
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
    def test_rollback_skips_empty_workspaces_destroyed_by_evacuation(self):
        self.adapter.workspaces = lambda: [dict(id=1, name='1', monitor='DP-1'),
                                           dict(id=2, name='2', monitor='DP-2')]
        doc = self.doc()
        doc['displays'][1]['mirror_of'] = doc['displays'][0]['id']
        pending = self.service.preview(doc, watchdog=False)
        self.adapter.workspaces = lambda: [dict(id=1, name='1', monitor='DP-1')]
        result = self.service.revert(pending['token'])
        self.assertFalse(result['errors'])
        self.assertNotIn(('move', '2', 'DP-2'), self.adapter.calls)
        self.assertIn(('move', '1', 'DP-1'), self.adapter.calls)
    def test_destinations_enabled_first(self):
        self.adapter.current[1]['enabled'] = False
        doc = self.doc(); doc['displays'][0]['enabled'] = False; doc['displays'][1]['enabled'] = True
        self.service.preview(doc, watchdog=False)
        applies = [call for call in self.adapter.calls if call[0] == 'apply']
        self.assertEqual(applies[0], ('apply', 'DP-2', True))
        self.assertLess(self.adapter.calls.index(('apply', 'DP-2', True)),
                        self.adapter.calls.index(('move', '1', 'DP-2')))
        self.assertLess(self.adapter.calls.index(('move', '1', 'DP-2')),
                        self.adapter.calls.index(('apply', 'DP-1', False)))

    def test_disable_carries_numbered_named_and_special_workspaces_and_revert_restores(self):
        self.adapter.live += [dict(id=8, name='8', monitor='DP-2', windows=2),
                              dict(id=-99, name='special:scratchpad', monitor='DP-2', windows=1)]
        original = self.adapter.workspaces()
        doc = self.doc()
        doc['displays'][1]['enabled'] = False
        pending = self.service.preview(doc, watchdog=False)
        self.assertTrue(all(w['monitor'] == 'DP-1' for w in self.adapter.workspaces()))
        for key in ('name:work', '8', 'special:scratchpad'):
            self.assertLess(self.adapter.calls.index(('move', key, 'DP-1')),
                            self.adapter.calls.index(('apply', 'DP-2', False)))
        result = self.service.revert(pending['token'])
        self.assertFalse(result['errors'])
        self.assertEqual(self.adapter.workspaces(), original)

    def test_disable_avoids_sleeping_mirrored_and_other_disabled_destinations(self):
        self.adapter.current[0]['awake'] = False
        self.adapter.current += [dict(display('DP-3', 3840), mirror_of='connector:DP-1', mirror_connector='DP-1'),
                                 display('DP-4', 5760), display('DP-5', 7680)]
        self.adapter.live.append(dict(name='9', monitor='DP-4'))
        doc = self.doc()
        doc['displays'][1]['enabled'] = False
        doc['displays'][3]['enabled'] = False
        pending = self.service.preview(doc, watchdog=False)
        locations = {w['name']: w['monitor'] for w in self.adapter.workspaces()}
        self.assertEqual(locations, {'1': 'DP-1', 'work': 'DP-5', '9': 'DP-5'})
        self.service.keep(pending['token'])
        self.assertEqual(self.adapter.workspaces()[1]['monitor'], 'DP-5')

    def test_failed_evacuation_does_not_disable_source(self):
        self.adapter.move = lambda *args: None
        doc = self.doc()
        doc['displays'][1]['enabled'] = False
        with self.assertRaisesRegex(DisplayError, 'did not move workspace'):
            self.service.preview(doc, watchdog=False)
        self.assertNotIn(('apply', 'DP-2', False), self.adapter.calls)
        self.assertFalse(self.service.pending_path.exists())

    def test_evacuation_failure_restores_workspaces_already_moved(self):
        self.adapter.live.append(dict(id=-99, name='special:scratchpad', monitor='DP-2', windows=1))
        original = self.adapter.workspaces()
        move = self.adapter.move
        def fail_second(workspace, connector):
            if workspace == 'special:scratchpad' and connector == 'DP-1':
                raise DisplayError('Injected move failure')
            move(workspace, connector)
        self.adapter.move = fail_second
        doc = self.doc()
        doc['displays'][1]['enabled'] = False
        with self.assertRaisesRegex(DisplayError, 'Injected move failure'):
            self.service.preview(doc, watchdog=False)
        self.assertEqual(self.adapter.workspaces(), original)
        self.assertNotIn(('apply', 'DP-2', False), self.adapter.calls)

    def test_evacuation_allows_empty_workspace_to_disappear(self):
        self.adapter.live[1]['windows'] = 0
        self.adapter.move = lambda *args: self.adapter.live.pop()
        doc = self.doc()
        doc['displays'][1]['enabled'] = False
        pending = self.service.preview(doc, watchdog=False)
        self.service.keep(pending['token'])
        self.assertFalse(self.adapter.current[1]['enabled'])

    def test_restore_evacuates_workspaces_before_disabling(self):
        doc = self.doc()
        doc['displays'][1]['enabled'] = False
        atomic(self.service.confirmed_path, doc)
        self.service.restore()
        self.assertEqual(self.adapter.workspaces()[1]['monitor'], 'DP-1')
        self.assertLess(self.adapter.calls.index(('move', 'name:work', 'DP-1')),
                        self.adapter.calls.index(('apply', 'DP-2', False)))

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

    def test_watchdog_rechecks_extended_deadline_under_lock(self):
        doc = self.doc()
        doc['displays'][1]['x'] = 2000
        pending = self.service.preview(doc, watchdog=False)
        # The watchdog saw the applying deadline expire while the writer held
        # the lock. By the time it gets the lock, application has reset it.
        result = self.service.revert(pending['token'], expired_only=True)
        self.assertEqual(result['reason'], 'not-expired')
        self.assertTrue(self.service.pending_path.exists())
        self.assertEqual(self.adapter.current[1]['x'], 2000)
        record = read(self.service.pending_path)
        record['deadline'] = time.time() - 1
        atomic(self.service.pending_path, record)
        self.assertEqual(self.service.revert(pending['token'], expired_only=True)['reason'], 'reverted')
        self.assertEqual(self.adapter.current[1]['x'], 1920)

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

class MirrorHandoffTests(unittest.TestCase):
    class Desktop(Fake):
        def __init__(self):
            super().__init__()
            self.current[0]['active_workspace'] = dict(id=1, name='1')
            self.current[1].update(width=3840, height=2160, scale=2, refresh=120,
                                   modes=['3840x2160@120.00Hz'], mirror_of=self.current[0]['id'],
                                   mirror_connector='DP-1', extended_position=dict(x=1920, y=0))
            self.current.append(display('DP-3', 6000))
            self.live = [dict(id=1, name='1', monitor='DP-1'), dict(id=2, name='2', monitor='DP-1'),
                         dict(id=-10, name='research', monitor='DP-1'),
                         dict(id=-99, name='special:scratchpad', monitor='DP-1'),
                         dict(id=3, name='3', monitor='DP-3')]
            self.active = copy.deepcopy(self.live[0])
            self.fail_on = None
        def workspaces(self): return copy.deepcopy(self.live)
        def run(self, *args):
            return json.dumps(self.active if args == ('-j', 'activeworkspace') else dict(address='0xbeef'))
        def dispatch(self, operation, arguments): self.calls.append((operation, arguments))
        def move(self, workspace, connector):
            super().move(workspace, connector)
            for item in self.live:
                if Service._handoff_workspace(item) == workspace:
                    item['monitor'] = connector
        def apply(self, d):
            if self.fail_on == d['connector']:
                self.fail_on = None
                raise DisplayError('Injected handoff failure')
            super().apply(d)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, XDG_STATE_HOME=self.temp.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.adapter = self.Desktop()
        self.service = Service(self.adapter, self.temp.name)
        self.service.policy = None
        self.saved = dict(version=1, displays=self.adapter.displays(),
                          workspaces={'3': dict(monitor='connector:DP-1', layout=None)})
        atomic(self.service.confirmed_path, self.saved)

    def test_switch_carries_all_workspaces_preserves_modes_and_unrelated_output(self):
        original_modes = [(d['width'], d['height'], d['refresh'], d['scale'], d['transform']) for d in self.adapter.current]
        result = self.service.use_display('DP-2', watchdog=False)
        self.assertEqual(result['previous_source'], 'DP-1')
        self.assertEqual([w['monitor'] for w in self.adapter.live], ['DP-2'] * 4 + ['DP-3'])
        self.assertEqual(original_modes, [(d['width'], d['height'], d['refresh'], d['scale'], d['transform']) for d in self.adapter.current])
        self.assertFalse(any(c[:2] == ('apply', 'DP-3') for c in self.adapter.calls))
        self.assertEqual(self.adapter.current[0]['mirror_connector'], 'DP-2')
        self.assertFalse(self.adapter.current[1].get('mirror_of'))
        self.assertIn(('focus', '{window="address:0xbeef"}'), self.adapter.calls)
        self.assertEqual(read(self.service.confirmed_path)['workspaces'], self.saved['workspaces'])
        self.assertFalse(self.service.pending_path.exists())
        self.service.use_display('DP-1', watchdog=False)
        self.assertEqual([w['monitor'] for w in self.adapter.live], ['DP-1'] * 4 + ['DP-3'])
        self.assertEqual(read(self.service.confirmed_path)['displays'][1]['extended_position'], dict(x=1920, y=0))

    def test_next_cycles_only_the_focused_group_and_source_is_an_inert_noop(self):
        self.service.use_display('DP-1', watchdog=False)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertEqual(self.service.use_display('next', watchdog=False)['connector'], 'DP-2')
        self.adapter.active['monitor'] = 'DP-2'
        self.assertEqual(self.service.use_display('next', watchdog=False)['connector'], 'DP-1')
        self.adapter.active['monitor'] = 'DP-3'
        with self.assertRaisesRegex(DisplayError, 'mirror group'):
            self.service.use_display('next', watchdog=False)

    def test_switch_with_sleep_guard_settles_power_and_allows_wake(self):
        original_options = self.adapter.wake_options()
        self.service.power('DP-3', False)
        self.assertTrue(self.service.power_path.exists())
        # A config reload can reset the options while the output stays asleep.
        self.adapter.options = dict(original_options)
        with nonblocking_locks():
            result = self.service.use_display('DP-2', watchdog=False)
            self.assertEqual(result['previous_source'], 'DP-1')
            self.assertEqual([w['monitor'] for w in self.adapter.live], ['DP-2'] * 4 + ['DP-3'])
            self.assertFalse(self.service.pending_path.exists())
            self.assertEqual(read(self.service.confirmed_path)['displays'][0]['mirror_of'], 'connector:DP-2')
            self.assertFalse(self.adapter.current[2]['awake'])
            self.assertEqual(self.adapter.wake_options(), dict(key_press_enables_dpms=False, mouse_move_enables_dpms=False))
            self.service.power('DP-3', True)
        self.assertTrue(self.adapter.current[2]['awake'])
        self.assertFalse(self.service.power_path.exists())
        self.assertEqual(self.adapter.wake_options(), original_options)

    def test_failures_restore_the_desktop_focus_and_saved_configuration(self):
        original = self.adapter.displays()
        self.adapter.fail_on = 'DP-1'  # Destination is ready and windows have moved.
        with self.assertRaisesRegex(DisplayError, 'Injected handoff'):
            self.service.use_display('DP-2', watchdog=False)
        from adapter import same
        self.assertTrue(all(same(a, b) for a, b in zip(original, self.adapter.current)))
        self.assertEqual([w['monitor'] for w in self.adapter.live], ['DP-1'] * 4 + ['DP-3'])
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertFalse(self.service.pending_path.exists())
        self.assertFalse(read(self.service.directory / 'recovery.json')['errors'])

    def test_commit_failure_rolls_back_after_successful_handoff(self):
        policy = Mock(state={})
        policy.capture_workspaces.side_effect = self.adapter.workspaces
        policy.commit.side_effect = DisplayError('Injected commit failure')
        self.service.policy = policy
        with self.assertRaisesRegex(DisplayError, 'commit failure'):
            self.service.use_display('DP-2', watchdog=False)
        self.assertEqual([w['monitor'] for w in self.adapter.live], ['DP-1'] * 4 + ['DP-3'])
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertFalse(self.service.pending_path.exists())

    def test_refuses_sleeping_disconnected_disabled_independent_targets_and_pending_edits(self):
        for connector in ('DP-3', 'missing'):
            with self.assertRaises(DisplayError):
                self.service.use_display(connector, watchdog=False)
        for fields in (dict(awake=False), dict(enabled=False), dict(connected=False)):
            old = copy.deepcopy(self.adapter.current[1])
            self.adapter.current[1].update(fields)
            with self.assertRaises(DisplayError):
                self.service.use_display('DP-2', watchdog=False)
            self.adapter.current[1] = old
        atomic(self.service.pending_path, dict(token='other'))
        with self.assertRaisesRegex(DisplayError, 'preview'):
            self.service.use_display('DP-2', watchdog=False)
        self.assertEqual(self.adapter.calls, [])

    def test_larger_source_finds_free_space_and_retargets_multiple_saved_mirrors(self):
        from handoff import plan
        original = copy.deepcopy(self.saved)
        original['displays'][1]['scale'] = 1
        original['displays'][2]['x'] = 1920
        original['displays'].append(dict(display('DP-4'), mirror_of='connector:DP-1', connected=False))
        changed, previous = plan(original, 'DP-2')
        self.assertEqual(previous, 'DP-1')
        self.assertEqual(changed['displays'][3]['mirror_of'], 'connector:DP-2')
        self.assertEqual(changed['displays'][2], original['displays'][2])
        ax, ay, aw, ah = bounds(changed['displays'][1])
        bx, by, bw, bh = bounds(changed['displays'][2])
        self.assertFalse(min(ax + aw, bx + bw) > max(ax, bx) and min(ay + ah, by + bh) > max(ay, by))
        self.assertEqual(original['displays'][0].get('mirror_of'), None)


if __name__ == '__main__': unittest.main()
