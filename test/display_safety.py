"""Capability changes and mode intent across previews, PBP, docking and recovery."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
from adapter import Adapter, DisplayError, clean_scale, same
from configuration import Configuration
from modes import AUTOMATIC, automatic_options
from service import Service, read
from displays import Fake, display


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, XDG_STATE_HOME=self.temp.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.adapter = Fake()
        self.service = Service(self.adapter, self.root / 'state')
        self.service.policy = None

    def document(self):
        return dict(version=1, displays=self.service.catalog()['displays'], workspaces={})

    def configuration(self, mode='highres'):
        self.config = Configuration(self.root / 'config/hypr')
        self.config.root.mkdir(parents=True)
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\n')
        self.config.path.write_text('local scale = 1\n'
            'hl.monitor({output="",mode="preferred",position="auto",scale=scale})\n'
            f'hl.monitor({{output="DP-1",mode="{mode}",position="0x0",scale=scale}})\n'
            'hl.monitor({output="DP-2",mode="1920x1080@60",position="1920x0",scale=scale})\n')
        self.service.configuration = self.config
        self.adapter.reload = Mock()

    def test_workspace_only_save_has_no_display_writes(self):
        document = self.document()
        document['workspaces']['1'] = dict(monitor='connector:DP-2', layout='dwindle')
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(read(self.service.confirmed_path)['workspaces'], document['workspaces'])

    def test_moving_one_screen_does_not_touch_other_modes_or_refresh(self):
        self.adapter.current[0].update(refresh=144, modes=['1920x1080@144.00Hz'])
        document = self.document()
        document['displays'][1].update(x=-1080, y=-400, transform=1, scale=1)
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertEqual(self.adapter.calls, [('apply', 'DP-2', True)])
        self.assertEqual(self.adapter.current[0]['refresh'], 144)

    def test_same_geometry_still_applies_an_explicit_policy_change(self):
        self.configuration('1920x1080@60')
        document = self.document()
        document['displays'][0]['mode_policy'] = 'highres'
        pending = self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.calls, [('apply', 'DP-1', True)])
        self.service.keep(pending['token'])
        self.assertIn('mode="highres"', self.config.path.read_text())
        self.assertEqual(self.service.catalog()['displays'][0]['mode_policy'], 'highres')

    def test_shadowed_connector_mode_does_not_replace_winning_description_mode(self):
        self.configuration('1920x1080@60')
        self.config.path.write_text(self.config.path.read_text() +
            'hl.monitor({output="desc:Panel",mode="1920x1080@75",position="0x0",scale=1})\n')
        self.adapter.current[0].update(description='Panel ABC', refresh=75,
                                      modes=['1920x1080@60.00Hz', '1920x1080@75.00Hz'])
        native = Adapter()
        native.run = Mock(return_value='ok')
        apply = self.adapter.apply
        def partial_rule(d, **kwargs):
            native.apply(d, **kwargs)
            # Native partial updates inherit the exact connector's old mode,
            # even when a later description rule was previously authoritative.
            actual = dict(d, refresh=60) if kwargs.get('preserve_mode') else d
            apply(actual, **kwargs)
        self.adapter.apply = partial_rule
        document = self.document()
        document['displays'][0]['y'] = 100
        pending = self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.current[0]['refresh'], 75)
        self.service.revert(pending['token'])
        self.assertEqual(self.adapter.current[0]['refresh'], 75)
        self.assertEqual(self.adapter.current[0]['y'], 0)
        self.assertTrue(all('mode="1920x1080@75"' in call.args[-1] for call in native.run.call_args_list))

    def test_computed_description_mode_cannot_inherit_a_shadowed_connector(self):
        self.configuration('1920x1080@60')
        self.config.path.write_text(self.config.path.read_text() +
            'hl.monitor({output="desc:Panel",mode=selected_mode,position="0x0",scale=1})\n')
        self.adapter.current[0]['description'] = 'Panel ABC'
        document = self.document()
        document['displays'][0]['y'] = 100
        with self.assertRaisesRegex(DisplayError, 'computed mode'):
            self.service.preview(document, watchdog=False)
        self.assertFalse(any(call[0] == 'apply' for call in self.adapter.calls))

    def automatic_fallback(self, **resolved):
        self.configuration('1920x1080@60')
        self.adapter.current[0]['modes'] += [
            '1920x1080@120.00Hz', '1920x1080@144.00Hz',
            '3840x2160@60.00Hz', '1366x768@60.00Hz']
        apply = self.adapter.apply
        fallback = dict(width=1920, height=1080, refresh=120)
        fallback.update(resolved)
        def choose(d, **kwargs):
            actual = dict(d)
            if d.get('mode_policy') in AUTOMATIC:
                actual.update(fallback)
                actual['scale'] = clean_scale(actual['width'], actual['height'], d['scale'])
            apply(actual, **kwargs)
        self.adapter.apply = choose
        # Exercise production polling/verification, with only hardware and the
        # passage of time replaced. The normal fake assumes exact application.
        self.adapter.verify = lambda desired, **kwargs: Adapter.verify(self.adapter, desired, **kwargs)
        sleeping = patch('adapter.time.sleep')
        sleeping.start()
        self.addCleanup(sleeping.stop)
        document = self.document()
        document['displays'][0].update(width=3840, height=2160, refresh=60, mode_policy='highres')
        document['displays'][1]['x'] = 3840
        return document

    def test_automatic_fallback_is_saved_as_resolved_geometry_and_native_policy(self):
        document = self.automatic_fallback()
        pending = self.service.preview(document, watchdog=False)
        journal = read(self.service.pending_path)
        for resolved in (journal['document']['displays'][0], journal['expected']['DP-1']):
            self.assertEqual((resolved['width'], resolved['height'], resolved['refresh']), (1920, 1080, 120))
            self.assertEqual(resolved['mode_policy'], 'highres')
        self.service.keep(pending['token'])
        self.assertIn('mode="highres"', self.config.path.read_text())
        self.assertEqual(read(self.service.confirmed_path)['displays'][0]['refresh'], 120)

    def test_fallback_scale_is_replanned_before_keep(self):
        document = self.automatic_fallback(width=1366, height=768, refresh=60)
        document['displays'][0]['scale'] = 1.5
        pending = self.service.preview(document, watchdog=False)
        journal = read(self.service.pending_path)
        self.assertEqual(journal['document']['displays'][0]['scale'], 2)
        self.assertNotIn('scale=1.5', journal['config_plan']['after'])
        self.service.keep(pending['token'])
        self.assertEqual(read(self.service.confirmed_path)['displays'][0]['width'], 1366)
        self.assertIn('scale=2', self.config.path.read_text())

    def test_revert_restores_previous_mode_after_automatic_fallback(self):
        document = self.automatic_fallback()
        before = self.adapter.displays()
        pending = self.service.preview(document, watchdog=False)
        report = self.service.revert(pending['token'])
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['external'], [])
        self.assertTrue(all(same(a, b) for a, b in zip(before, self.adapter.current)))

    def test_crash_before_automatic_readback_can_restore_previous_mode(self):
        document = self.automatic_fallback()
        before = self.adapter.displays()
        apply = self.adapter.apply
        class PowerLoss(BaseException):
            pass
        def crash(d, **kwargs):
            apply(d, **kwargs)
            raise PowerLoss()
        self.adapter.apply = crash
        with self.assertRaises(PowerLoss):
            self.service.preview(document, watchdog=False)
        self.assertEqual(read(self.service.pending_path)['resolving'], 'DP-1')
        self.adapter.apply = apply
        restarted = Service(self.adapter, self.service.directory)
        restarted.configuration, restarted.policy = self.config, None
        report = restarted.revert()
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['external'], [])
        self.assertTrue(all(same(a, b) for a, b in zip(before, self.adapter.current)))

    def test_later_apply_failure_restores_resolved_automatic_output(self):
        document = self.automatic_fallback()
        before = self.adapter.displays()
        apply = self.adapter.apply
        failed = False
        def fail_second(d, **kwargs):
            nonlocal failed
            if d['connector'] == 'DP-2' and not failed:
                failed = True
                raise DisplayError('Injected second output failure')
            apply(d, **kwargs)
        self.adapter.apply = fail_second
        with self.assertRaisesRegex(DisplayError, 'second output failure'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(read(self.service.directory / 'recovery.json')['external'], [])
        self.assertTrue(all(same(a, b) for a, b in zip(before, self.adapter.current)))

    def test_fallback_overlap_reverts_before_disabling_another_output(self):
        document = self.automatic_fallback(width=3840, height=2160, refresh=60)
        # An existing automatic policy's estimate can be smaller than the
        # mode eventually selected by the compositor.
        document['displays'][0].update(width=1920, height=1080)
        document['displays'][1]['x'] = 1920
        self.adapter.current.append(display('DP-3', 3840))
        document['displays'].append(dict(self.adapter.current[-1], enabled=False))
        before = self.adapter.displays()
        with self.assertRaisesRegex(DisplayError, 'overlap'):
            self.service.preview(document, watchdog=False)
        self.assertTrue(all(same(a, b) for a, b in zip(before, self.adapter.current)))
        self.assertEqual(read(self.service.directory / 'recovery.json')['external'], [])
        self.assertNotIn(('apply', 'DP-3', False), self.adapter.calls)

    def test_keep_does_not_accept_another_automatic_mode_after_preview(self):
        document = self.automatic_fallback()
        pending = self.service.preview(document, watchdog=False)
        self.adapter.current[0]['refresh'] = 144
        with self.assertRaisesRegex(DisplayError, 'did not apply'):
            self.service.keep(pending['token'])
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertEqual(self.adapter.current[0]['refresh'], 144)
        self.assertIn('DP-1', read(self.service.directory / 'recovery.json')['external'])

    def test_replanning_does_not_adopt_external_configuration_edits(self):
        document = self.automatic_fallback()
        apply = self.adapter.apply
        source = self.config.path.read_text() + '-- external edit\n'
        def edited(d, **kwargs):
            apply(d, **kwargs)
            self.config.path.write_text(source)
        self.adapter.apply = edited
        with self.assertRaisesRegex(DisplayError, 'configuration changed during preview'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.assertFalse(self.service.confirmed_path.exists())

    def test_failed_keep_restores_config_and_mode_after_automatic_fallback(self):
        document = self.automatic_fallback()
        before, source = self.adapter.displays(), self.config.path.read_text()
        pending = self.service.preview(document, watchdog=False)
        self.adapter.reload.side_effect = [DisplayError('Injected reload failure'), None]
        with self.assertRaisesRegex(DisplayError, 'reload failure'):
            self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), source)
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertTrue(all(same(a, b) for a, b in zip(before, self.adapter.current)))
        self.assertEqual(read(self.service.directory / 'recovery.json')['external'], [])

    def test_automatic_readback_still_checks_mode_availability_and_other_fields(self):
        requested = dict(display(), mode_policy='highres', width=3840, height=2160)
        actual = dict(display(), refresh=120, modes=['1920x1080@120.00Hz'])
        adapter = Adapter()
        with patch('adapter.time.sleep'):
            adapter.displays = lambda: [copy.deepcopy(actual)]
            self.assertEqual(adapter.verify([requested], resolve_modes=True)[0]['refresh'], 120)
            with self.assertRaises(DisplayError):
                adapter.verify([dict(requested, mode_policy='fixed')], resolve_modes=True)
            for change in (dict(x=100), dict(scale=2), dict(transform=1), dict(enabled=False),
                           dict(modes=[]), dict(mirror_of='other', mirror_connector='DP-2'),
                           dict(width=0, modes=['0x1080@120.00Hz'])):
                with self.subTest(change=change), self.assertRaises(DisplayError):
                    adapter.displays = lambda: [dict(actual, **change)]
                    adapter.verify([requested], resolve_modes=True)

    def test_automatic_readback_waits_for_requested_mode_before_accepting_fallback(self):
        requested = dict(display(), mode_policy='highres', width=3840, height=2160)
        old = dict(display(), modes=['1920x1080@60.00Hz', '3840x2160@60.00Hz'])
        adapter = Adapter()
        adapter.displays = Mock(side_effect=[[old], [old], [dict(old, width=3840, height=2160)]])
        with patch('adapter.time.sleep'):
            self.assertEqual(adapter.verify([requested], resolve_modes=True)[0]['width'], 3840)
        self.assertEqual(adapter.displays.call_count, 3)

    def test_automatic_readback_rejects_an_unsettled_fallback(self):
        requested = dict(display(), mode_policy='highres', width=3840, height=2160)
        first = dict(display(), refresh=120, modes=['1920x1080@120.00Hz', '1920x1080@144.00Hz'])
        second = dict(first, refresh=144)
        adapter = Adapter()
        adapter.displays = Mock(side_effect=[[first], [second]] * 25)
        with patch('adapter.time.sleep'), self.assertRaises(DisplayError):
            adapter.verify([requested], resolve_modes=True)

    def test_auto_fullscreen_pbp_save_and_return_does_not_pin_pbp_size(self):
        self.configuration()
        self.adapter.current = [dict(display(), width=6144, height=2560, refresh=120,
                                     scale=4/3, modes=['6144x2560@120.00Hz'])]
        for width, refresh in ((6144, 120), (3072, 60), (6144, 120)):
            self.adapter.current[0].update(width=width, refresh=refresh,
                modes=[f'{width}x2560@{refresh}.00Hz'])
            document = self.document()
            self.assertEqual(document['displays'][0]['mode_policy'], 'highres')
            self.assertEqual(document['displays'][0]['automatic_modes'][0]['width'], width)
            pending = self.service.preview(document, watchdog=False)
            self.service.keep(pending['token'])
            self.assertIn('mode="highres"', self.config.path.read_text())
            self.assertNotIn('3072x2560', self.config.path.read_text())
        self.assertEqual(self.adapter.calls, [])

    def test_legacy_geometry_edits_preserve_each_native_policy(self):
        for policy in AUTOMATIC:
            with self.subTest(policy=policy):
                self.configuration_once(policy)
                before = self.config.path.read_text()
                document = dict(version=1, displays=self.adapter.displays())
                for d in document['displays']:
                    d.pop('mode_policy', None)
                document['displays'][0]['scale'] = 2
                pending = self.service.preview(document, watchdog=False)
                self.assertEqual(self.adapter.current[0]['mode_policy'], policy)
                self.service.keep(pending['token'])
                self.assertIn(f'mode="{policy}"', self.config.path.read_text())
                self.assertEqual(self.config.path.read_text(), before.replace('position="0x0",scale=scale', 'position="0x0",scale=2'))
                self.adapter.current[0]['scale'] = 1

    def configuration_once(self, mode):
        if not hasattr(self, 'config'):
            self.configuration(mode)
        else:
            source = self.config.path.read_text()
            for policy in AUTOMATIC:
                source = source.replace(f'mode="{policy}",position="0x0",scale=2', f'mode="{mode}",position="0x0",scale=scale')
            self.config.path.write_text(source)

    def test_manual_refresh_cap_survives_geometry_save(self):
        self.configuration('1920x1080@60')
        self.adapter.current[0]['modes'].append('1920x1080@144.00Hz')
        document = self.document()
        document['displays'][0]['scale'] = 2
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertEqual(self.adapter.current[0]['refresh'], 60)
        self.assertIn('mode="1920x1080@60"', self.config.path.read_text())

    def test_selecting_explicit_mode_leaves_automatic_policy(self):
        self.configuration()
        self.adapter.current[0]['modes'].append('1920x1080@75.00Hz')
        document = self.document()
        document['displays'][0].update(mode_policy='fixed', refresh=75)
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertIn('mode="1920x1080@75.00000"', self.config.path.read_text())

    def test_rejects_mode_change_since_catalog_before_any_writes(self):
        document = self.document()
        document['displays'][1]['x'] = 2200
        self.adapter.current[0]['modes'].append('1280x720@60.00Hz')
        with self.assertRaisesRegex(DisplayError, 'available modes changed'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse(self.service.pending_path.exists())

    def test_same_port_different_monitor_before_keep_cannot_receive_rollback(self):
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        self.adapter.current[1]['identity'] = 'new-monitor'
        self.adapter.calls.clear()
        with self.assertRaisesRegex(DisplayError, 'connections or available modes changed'):
            self.service.keep(pending['token'])
        self.assertFalse(any(c[0] == 'apply' for c in self.adapter.calls))
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertTrue(read(self.service.directory / 'recovery.json')['fallback'])

    def test_pbp_before_revert_does_not_replay_fullscreen_mode(self):
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        self.adapter.current[1]['modes'] = ['960x1080@60.00Hz']
        # Even stale geometry readback must not authorize an unadvertised mode.
        self.adapter.calls.clear()
        result = self.service.revert(pending['token'])
        self.assertTrue(result['fallback'])
        self.assertFalse(any(c[0] == 'apply' for c in self.adapter.calls))

    def test_mode_list_order_and_formatting_do_not_cancel_preview(self):
        self.adapter.current[1]['modes'] += ['1280x720@60.00Hz', '1920x1080@60.00Hz']
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        self.adapter.current[1]['modes'] = ['1280x720@60Hz', '1920x1080@60Hz']
        self.service.keep(pending['token'])
        self.assertTrue(self.service.confirmed_path.exists())

    def test_hotplug_during_apply_stops_before_the_next_output(self):
        document = self.document()
        for d in document['displays']:
            d['y'] = 100
        original = self.adapter.apply
        def apply(d, **kwargs):
            original(d)
            self.adapter.current[1]['modes'].append('1280x720@60.00Hz')
        self.adapter.apply = apply
        with self.assertRaisesRegex(DisplayError, 'available modes changed'):
            self.service.preview(document, watchdog=False)
        self.assertFalse(any(c[:2] == ('apply', 'DP-2') for c in self.adapter.calls))

    def test_unplugging_untouched_output_prevents_saving_stale_arrangement(self):
        document = self.document()
        document['displays'][0]['scale'] = 2
        pending = self.service.preview(document, watchdog=False)
        self.adapter.current.pop()
        with self.assertRaisesRegex(DisplayError, 'connections or available modes changed'):
            self.service.keep(pending['token'])
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertTrue(self.adapter.current[0]['enabled'])

    def test_configuration_commit_rechecks_after_preference_writes(self):
        self.configuration()
        source = self.config.path.read_text()
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        commit = self.config.commit
        def reconnect(plan, before_write=None):
            self.adapter.current[1]['identity'] = 'another-monitor'
            commit(plan, before_write)
        self.config.commit = reconnect
        with self.assertRaisesRegex(DisplayError, 'connections or available modes changed'):
            self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), source)

    def test_keep_rechecks_capabilities_after_reload_before_confirming(self):
        self.configuration()
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        def changed():
            self.adapter.current[1]['modes'] = ['960x1080@60.00Hz']
        self.adapter.reload.side_effect = changed
        self.adapter.calls.clear()
        with self.assertRaisesRegex(DisplayError, 'available modes changed'):
            self.service.keep(pending['token'])
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertFalse(any(c[0] == 'apply' for c in self.adapter.calls))
        self.assertEqual(read(self.service.pending_path)['phase'], 'recovery-needed')

    def test_virtual_output_without_modes_keeps_confirmed_resolution(self):
        self.adapter.current[1]['modes'] = []
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertEqual(self.adapter.current[1]['width'], 1920)

    def test_virtual_output_rejects_new_automatic_selector_without_modes(self):
        self.adapter.current[0]['modes'] = []
        document = self.document()
        document['displays'][0]['mode_policy'] = 'highres'
        with self.assertRaisesRegex(DisplayError, 'needs advertised modes'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.calls, [])

    def test_fallback_selector_is_preserved_in_new_connector_rule(self):
        self.configuration()
        self.config.path.write_text('hl.monitor({output="",mode="highres",position="auto",scale=1})\n')
        document = self.document()
        document['displays'][0]['scale'] = 2
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertEqual(self.config.mode_policies(self.adapter.displays()), {'DP-1': 'highres', 'DP-2': 'highres'})
        self.assertNotIn('1920x1080', self.config.path.read_text())

    def test_automatic_choice_never_invents_a_mode(self):
        for modes in ([], ['3840x2160@60.00Hz', '6144x2560@120.00Hz'], ['3072x2560@60.00Hz']):
            with self.subTest(modes=modes):
                d = dict(display(), modes=modes)
                choices = automatic_options(d)
                self.assertEqual(bool(choices), bool(modes))
                if choices:
                    self.assertIn(f"{choices[0]['width']}x{choices[0]['height']}@{choices[0]['refresh']:.2f}Hz", modes)

    def test_native_adapter_sends_selector_not_automatic_readback(self):
        adapter = Adapter()
        adapter.run = Mock(return_value='ok')
        adapter.apply(dict(display(), mode_policy='highres'))
        command = adapter.run.call_args.args[-1]
        self.assertIn('mode="highres"', command)
        self.assertNotIn('1920x1080', command)

    def test_disconnected_preferences_are_retained_without_replaying_modes(self):
        document = self.document()
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        original = read(self.service.confirmed_path)['displays'][1]
        self.adapter.current.pop()
        catalog = self.service.catalog()
        saved = next(d for d in catalog['displays'] if not d['connected'])
        self.assertEqual(saved['refresh'], original['refresh'])
        self.assertEqual(saved['scale'], original['scale'])
        self.assertEqual(self.adapter.calls, [])

    def test_disabled_automatic_output_uses_new_capabilities_on_enable(self):
        self.configuration()
        self.adapter.current[0].update(enabled=False, width=0, height=0,
                                       modes=['1280x720@60.00Hz'])
        catalog = self.service.catalog()
        d = catalog['displays'][0]
        self.assertEqual((d['width'], d['height']), (1280, 720))
        d['enabled'] = True
        pending = self.service.preview(dict(version=1, displays=catalog['displays']), watchdog=False)
        self.service.keep(pending['token'])
        self.assertIn('mode="highres"', self.config.path.read_text())

    def test_timeout_retains_recovery_journal_without_more_display_writes(self):
        document = self.document()
        document['displays'][0]['scale'] = 2
        def unresponsive(d, **kwargs):
            self.adapter.displays = Mock(side_effect=DisplayError('Hyprland timed out'))
            raise DisplayError('Hyprland timed out')
        self.adapter.apply = Mock(side_effect=unresponsive)
        with self.assertRaisesRegex(DisplayError, 'timed out'):
            self.service.preview(document, watchdog=False)
        self.adapter.apply.assert_called_once()
        self.assertTrue(self.service.pending_path.exists())
        self.assertFalse(self.service.confirmed_path.exists())

    def test_geometry_edit_preserves_exact_custom_rule_mode(self):
        self.configuration('modeline 148.50 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync')
        native = Adapter()
        native.run = Mock(return_value='ok')
        original = self.adapter.apply
        def apply(d, **kwargs):
            native.apply(d, **kwargs)
            original(d, **kwargs)
        self.adapter.apply = apply
        document = self.document()
        document['displays'][0]['scale'] = 2
        pending = self.service.preview(document, watchdog=False)
        self.service.revert(pending['token'])
        for call in native.run.call_args_list:
            self.assertNotIn('mode=', call.args[-1])
        self.assertIn('modeline 148.50', self.config.path.read_text())

    def test_invalid_policy_is_rejected_before_any_writes(self):
        document = self.document()
        document['displays'][0]['mode_policy'] = 'made-up'
        with self.assertRaisesRegex(DisplayError, 'automatic mode'):
            self.service.preview(document, watchdog=False)
        self.assertEqual(self.adapter.calls, [])

    def test_same_geometry_policy_change_reverts_even_without_policy_readback(self):
        self.configuration('1920x1080@60')
        native = Adapter()
        native.run = Mock(return_value='ok')
        original = self.adapter.apply
        def apply(d, **kwargs):
            native.apply(d, **kwargs)
            original(d, **kwargs)
            for actual in self.adapter.current:
                actual.pop('mode_policy', None)
        self.adapter.apply = apply
        document = self.document()
        document['displays'][0]['mode_policy'] = 'highres'
        pending = self.service.preview(document, watchdog=False)
        self.service.revert(pending['token'])
        commands = [c.args[-1] for c in native.run.call_args_list]
        self.assertIn('mode="highres"', commands[0])
        self.assertIn('mode="1920x1080@60.00000"', commands[-1])

    def test_description_custom_modeline_survives_geometry_edit(self):
        modeline = 'modeline 148.50 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync'
        self.configuration(modeline)
        self.config.path.write_text(self.config.path.read_text().replace('output="DP-1"', 'output="desc:My display"'))
        self.adapter.current[0]['description'] = 'My display serial123'
        native = Adapter()
        native.run = Mock(return_value='ok')
        original = self.adapter.apply
        def apply(d, **kwargs):
            native.apply(d, **kwargs)
            original(d, **kwargs)
        self.adapter.apply = apply
        document = self.document()
        document['displays'][0]['scale'] = 2
        pending = self.service.preview(document, watchdog=False)
        self.service.keep(pending['token'])
        self.assertIn('mode="' + modeline + '"', native.run.call_args.args[-1])
        self.assertIn('mode="' + modeline + '"', self.config.path.read_text())

    def test_recovery_does_not_reload_old_config_onto_changed_hardware(self):
        self.configuration()
        document = self.document()
        document['displays'][1]['x'] = 2200
        pending = self.service.preview(document, watchdog=False)
        journal = read(self.service.pending_path)
        self.config.commit(journal['config_plan'])
        journal['config_touched'] = True
        self.adapter.current[1]['modes'] = ['960x1080@60.00Hz']
        source = self.config.path.read_text()
        result = self.service._rollback(journal)
        self.assertTrue(result['errors'])
        self.assertEqual(source, self.config.path.read_text())
        self.adapter.reload.assert_not_called()
        self.assertTrue(self.service.pending_path.exists())


if __name__ == '__main__':
    unittest.main()
