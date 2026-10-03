"""Source-preserving display saves and configuration transaction recovery."""
import copy
import json
import subprocess
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
from configuration import Configuration, declarations
from adapter import DisplayError, bounds
from service import Service, atomic, read
from displays import Fake

SOURCE = '''-- Keep this comment and shared variable.
local monitor_scale = 1
hl.env("GDK_SCALE", "1")
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = monitor_scale })
-- Native screen, with a multiline declaration.
hl.monitor({
    output = "DP-1", mode = "1920x1080@60", -- keep the mode comment
    position = "0x0", scale = monitor_scale, transform = 0,
    vrr = 1,
})
'''


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Configuration(self.root / 'hypr')
        self.config.root.mkdir()
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\n')
        self.config.path.write_text(SOURCE)
        self.adapter = Fake()
        self.adapter.reload = lambda: None
        self.service = Service(self.adapter, self.root / 'state')
        self.service.configuration = self.config
        self.service.policy = None
        self.before = self.adapter.displays()
        self.doc = dict(version=1, displays=copy.deepcopy(self.before), workspaces={})
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root))
        env.start()
        self.addCleanup(env.stop)

    def plan(self):
        return self.config.plan(self.before, self.doc)

    def test_missing_wayland_output_after_reload_rolls_back_config_and_preferences(self):
        self.doc['displays'][0]['x'] = -1920
        pending = self.service.preview(self.doc, watchdog=False)
        registered = True
        def reload():
            nonlocal registered
            registered = self.config.path.read_text() == SOURCE
        def verify(displays):
            if not registered:
                raise DisplayError('Missing Wayland output after reload')
        self.adapter.reload = reload
        self.adapter.verify_outputs = verify
        with self.assertRaisesRegex(DisplayError, 'Missing Wayland output'):
            self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), SOURCE)
        self.assertFalse(self.service.confirmed_path.exists())
        self.assertFalse(self.service.pending_path.exists())

    def removal(self):
        self.config.path.write_text(SOURCE + 'hl.monitor({ output = "DP-2", mode = "preferred", position = "1920x0" }); -- spare screen\n')
        self.saved = copy.deepcopy(self.doc)
        atomic(self.service.confirmed_path, self.saved)
        self.adapter.current.pop()
        self.doc['removed_displays'] = [self.doc['displays'].pop()['id']]

    def test_removal_deletes_only_specific_declaration_on_keep(self):
        self.removal()
        source = self.config.path.read_text()
        result = self.service.preview(self.doc, watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.service.keep(result['token'])
        self.assertEqual(self.config.path.read_text(), SOURCE + ' -- spare screen\n')
        self.assertEqual(self.config.path.with_name('monitors.lua.hypertile.bak').read_text(), source)
        self.assertEqual(len(read(self.service.confirmed_path)['displays']), 1)

    def duplicate_profiles(self):
        self.adapter.current = copy.deepcopy(self.before)
        self.doc = dict(version=1, displays=copy.deepcopy(self.before), workspaces={})
        self.removal()
        first = self.saved['displays'][1]
        first.update(id='old-panel', identity='old-panel', description='Old panel', connected=False)
        other = dict(first, id='other-panel', identity='other-panel', description='Other panel',
                     x=3000, width=2560, scale=2)
        self.saved['displays'].append(other)
        self.saved['workspaces'] = {'2': dict(monitor=first['id'], layout='lua:quad'),
                                    '3': dict(monitor=other['id'], layout='lua:columns')}
        atomic(self.service.confirmed_path, self.saved)
        return first, other

    def test_duplicate_stale_profiles_can_be_forgotten_in_either_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                first, other = self.duplicate_profiles()
                source = self.config.path.read_text()
                selected, remaining = (other, first) if reverse else (first, other)
                self.service.remove_display(selected['id'], watchdog=False)
                self.assertEqual(self.config.path.read_text(), source)
                confirmed = read(self.service.confirmed_path)
                self.assertEqual({d['id'] for d in confirmed['displays']},
                                 {self.before[0]['id'], remaining['id']})
                for key, preference in self.saved['workspaces'].items():
                    self.assertEqual(confirmed['workspaces'][key], dict(
                        preference, monitor=None if preference['monitor'] == selected['id'] else preference['monitor']))
                self.service.remove_display(remaining['id'], watchdog=False)
                self.assertNotIn('output = "DP-2"', self.config.path.read_text())
                self.assertIn('lua:quad', str(read(self.service.confirmed_path)['workspaces']))
                self.assertEqual(self.adapter.calls, [])
                self.assertFalse(self.service.pending_path.exists())
                self.adapter.current = copy.deepcopy(self.before)

    def test_duplicate_stale_removal_preserves_connector_mirror_dependency(self):
        first, other = self.duplicate_profiles()
        source = self.config.path.read_text().replace('vrr = 1,', 'vrr = 1, mirror = "DP-2",')
        self.config.path.write_text(source)
        self.adapter.current[0]['mirror_of'] = None
        self.service.remove_display(first['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.service.remove_display(other['id'], watchdog=False)
        self.assertIn('mirror = ""', self.config.path.read_text())

    def test_duplicate_stale_removal_deletes_only_unshared_description(self):
        first, other = self.duplicate_profiles()
        shared = self.config.path.read_text() + 'hl.monitor({output="desc:Other panel", vrr=1})\n'
        self.config.path.write_text(shared + 'hl.monitor({output="desc:Old panel", vrr=1})\n')
        self.service.remove_display(first['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), shared + '\n')

    def test_duplicate_stale_removal_preserves_shared_description_and_computed_mirror(self):
        first, other = self.duplicate_profiles()
        other['description'] = first['description']
        atomic(self.service.confirmed_path, self.saved)
        source = (SOURCE + 'hl.monitor({output="desc:Old panel", vrr=1})\n'
                  'hl.monitor({output="DP-3", mirror=mirror_source})\n')
        self.config.path.write_text(source)
        self.service.remove_display(first['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)

    def test_duplicate_stale_removal_rejects_reused_live_connector(self):
        first, other = self.duplicate_profiles()
        self.adapter.current.append(dict(other, id='new-panel', identity='new-panel', connected=True))
        source = self.config.path.read_text()
        with self.assertRaisesRegex(DisplayError, 'connector now in use'):
            self.service.remove_display(first['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def test_duplicate_stale_removal_failed_save_restores_profiles_and_rules(self):
        first, _ = self.duplicate_profiles()
        source = self.config.path.read_text() + 'hl.monitor({output="desc:Old panel", vrr=1})\n'
        self.config.path.write_text(source)
        self.adapter.reload = Mock(side_effect=[DisplayError('reload failed'), None])
        with self.assertRaisesRegex(DisplayError, 'reload failed'):
            self.service.remove_display(first['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertFalse(self.service.pending_path.exists())

    def test_generated_headers_are_reused_and_removed_with_last_rule(self):
        header = '-- Display settings saved by Hypertile.'
        for cycle in range(3):
            self.doc['displays'][1]['x'] = 2000 + cycle
            self.config.commit(self.plan())
            self.assertEqual(self.config.path.read_text().count(header), 1)
            before = copy.deepcopy(self.doc['displays'])
            self.config.commit(self.config.plan(before, dict(version=1, displays=before[:1],
                                                             removed_displays=[before[1]['id']])))
            self.assertNotIn(header, self.config.path.read_text())
        self.assertEqual(self.config.path.read_text().strip(), SOURCE.strip())

    def test_generated_headers_coalesce_without_changing_user_comments_or_strings(self):
        header = '-- Display settings saved by Hypertile.'
        literal = 'local note = [=[\n' + header + '\n]=]\n--[[\n' + header + '\n]]\n'
        self.config.path.write_text(literal + SOURCE + '\n' + (header + '\n\n') * 3)
        self.doc['displays'][1]['x'] = 2000
        self.config.commit(self.plan())
        source = self.config.path.read_text()
        self.assertTrue(source.startswith(literal + SOURCE))
        self.assertEqual(source.count(header), 3)  # Two inert copies, one real header.
        extra = dict(self.doc['displays'][1], id='extra', connector='DP-3', x=4000)
        self.config.commit(self.config.plan(self.doc['displays'], dict(displays=self.doc['displays'] + [extra])))
        self.assertEqual(self.config.path.read_text().count(header), 3)

    def test_removal_keeps_generated_header_for_remaining_rule(self):
        header = '-- Display settings saved by Hypertile.\n'
        self.config.path.write_text(SOURCE + header +
                                   'hl.monitor({output="DP-2", position="1920x0"})\n' +
                                   '-- user comment\nhl.monitor({output="DP-3", vrr=1})\n')
        self.doc['removed_displays'] = [self.doc['displays'].pop()['id']]
        after = self.plan()['after']
        self.assertIn(header, after)
        self.assertIn('-- user comment\nhl.monitor({output="DP-3", vrr=1})', after)

    def test_removal_failed_reload_restores_configuration_and_profile(self):
        self.removal()
        source = self.config.path.read_text()
        self.adapter.reload = Mock(side_effect=[DisplayError('reload failed'), None])
        result = self.service.preview(self.doc, watchdog=False)
        with self.assertRaisesRegex(DisplayError, 'reload failed'):
            self.service.keep(result['token'])
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertFalse(self.service.pending_path.exists())

    def test_removal_rejects_external_config_edits_without_overwriting(self):
        self.removal()
        result = self.service.preview(self.doc, watchdog=False)
        external = self.config.path.read_text() + '-- edited elsewhere\n'
        self.config.path.write_text(external)
        with self.assertRaisesRegex(DisplayError, 'changed during preview'):
            self.service.keep(result['token'])
        self.assertEqual(self.config.path.read_text(), external)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def test_removal_rechecks_reconnect_just_before_configuration_write(self):
        self.removal()
        source = self.config.path.read_text()
        result = self.service.preview(self.doc, watchdog=False)
        commit = self.config.commit
        def reconnect(plan, before_write=None):
            self.adapter.current.append(self.saved['displays'][1])
            commit(plan, before_write)
        self.config.commit = reconnect
        with self.assertRaisesRegex(DisplayError, 'connected display'):
            self.service.keep(result['token'])
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def test_removal_preserves_fallback_and_deletes_full_description_rules(self):
        self.removal()
        self.before[1]['description'] = 'Spare panel ABC123'
        self.config.path.write_text(SOURCE + 'hl.monitor({ output = "desc:Spare panel ABC123", vrr = 1 })\n')
        self.assertEqual(self.plan()['after'], SOURCE + '\n')

    def test_removal_refuses_shared_description_and_config_mirror_dependencies(self):
        self.removal()
        self.before[1]['description'] = 'Spare panel ABC123'
        for rule, error in [
                ('hl.monitor({ output = "desc:Spare panel", vrr = 1 })', 'shared description'),
                ('hl.monitor({ output = "DP-3", mirror = "DP-2" })', 'mirror rule'),
                ('hl.monitor({ output = "DP-3", mirror = source_output })', 'mirror rule')]:
            with self.subTest(rule=rule), self.assertRaisesRegex(DisplayError, error):
                self.config.path.write_text(SOURCE + rule + '\n')
                self.plan()
        self.before[0]['description'] = self.before[1]['description']
        self.config.path.write_text(SOURCE + 'hl.monitor({ output = "desc:Spare panel ABC123" })\n')
        with self.assertRaisesRegex(DisplayError, 'shared description'):
            self.plan()

    def test_removal_with_no_specific_rule_keeps_configuration_untouched(self):
        self.removal()
        self.config.path.write_text(SOURCE)
        self.assertIsNone(self.plan())

    def test_removal_allows_clearing_existing_mirror_rule_in_same_transaction(self):
        self.removal()
        source = SOURCE.replace('vrr = 1,', 'vrr = 1, mirror = "DP-2",')
        self.config.path.write_text(source)
        self.before[0]['mirror_connector'] = 'DP-2'
        self.doc['displays'][0]['mirror_of'] = None
        self.assertIn('mirror = ""', self.plan()['after'])

    def test_interrupted_removal_save_recovers_configuration_and_profile(self):
        self.removal()
        source = self.config.path.read_text()
        result = self.service.preview(self.doc, watchdog=False)
        pending = read(self.service.pending_path)
        pending.update(phase='committing', config_touched=True)
        atomic(self.service.pending_path, pending)
        self.config.commit(pending['config_plan'])
        self.assertNotIn('output = "DP-2"', self.config.path.read_text())
        self.service.revert(result['token'])
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def stale_mirror_removal(self):
        self.removal()
        source = self.config.path.read_text().replace('vrr = 1,', 'vrr = 1, mirror = "DP-2",')
        # Runtime is already independent because the mirror source is absent.
        self.assertFalse(self.adapter.current[0].get('mirror_connector'))
        self.adapter.current[0]['mirror_of'] = None
        self.config.path.write_text(source)
        self.doc['displays'][0]['mirror_of'] = None
        return source

    def test_removal_clears_stale_mirror_dependency_only_on_keep(self):
        source = self.stale_mirror_removal()
        pending = self.service.preview(self.doc, watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), SOURCE.replace('vrr = 1,', 'vrr = 1, mirror = "",') + ' -- spare screen\n')
        self.assertEqual(self.config.path.with_name('monitors.lua.hypertile.bak').read_text(), source)
        self.assertEqual(len(read(self.service.confirmed_path)['displays']), 1)

    def test_stale_mirror_removal_revert_preserves_original_configuration(self):
        source = self.stale_mirror_removal()
        pending = self.service.preview(self.doc, watchdog=False)
        self.service.revert(pending['token'])
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def test_stale_mirror_removal_failed_save_restores_dependency_and_profile(self):
        source = self.stale_mirror_removal()
        self.adapter.reload = Mock(side_effect=[DisplayError('reload failed'), None])
        pending = self.service.preview(self.doc, watchdog=False)
        with self.assertRaisesRegex(DisplayError, 'reload failed'):
            self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def test_immediate_removal_clears_stale_reference_without_preview_modeset(self):
        source = self.stale_mirror_removal()
        self.service.remove_display(self.saved['displays'][1]['id'], watchdog=False)
        self.assertIn('mirror = ""', self.config.path.read_text())
        self.assertNotIn('output = "DP-2"', self.config.path.read_text())
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(self.config.path.with_name('monitors.lua.hypertile.bak').read_text(), source)
        self.assertFalse(self.service.pending_path.exists())

    def test_immediate_removal_reload_failure_restores_profile_and_configuration(self):
        source = self.stale_mirror_removal()
        self.adapter.reload = Mock(side_effect=[DisplayError('reload failed'), None])
        with self.assertRaisesRegex(DisplayError, 'reload failed'):
            self.service.remove_display(self.saved['displays'][1]['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertFalse(self.service.pending_path.exists())

    def test_immediate_removal_rechecks_reconnect_before_configuration_write(self):
        source = self.stale_mirror_removal()
        commit = self.config.commit
        def reconnect(plan, before_write=None):
            self.adapter.current.append(self.saved['displays'][1])
            commit(plan, before_write)
        self.config.commit = reconnect
        with self.assertRaisesRegex(DisplayError, 'connected display'):
            self.service.remove_display(self.saved['displays'][1]['id'], watchdog=False)
        self.assertEqual(self.config.path.read_text(), source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)
        self.assertFalse(self.service.pending_path.exists())

    def test_stale_mirror_removal_pins_live_position(self):
        source = self.stale_mirror_removal()
        self.config.path.write_text(source.replace('position = "0x0"', 'position = "1920x0"'))
        self.assertIn('position = "0x0"', self.plan()['after'])

    def test_stale_mirror_removal_preserves_unresolved_dependencies(self):
        source = self.stale_mirror_removal()
        for edits in ({'connected': False}, {'enabled': False}, {'mirror_of': 'other-source'}):
            with self.subTest(edits=edits), self.assertRaisesRegex(DisplayError, 'mirror rule'):
                before = copy.deepcopy(self.before)
                document = copy.deepcopy(self.doc)
                before[0].update(edits)
                document['displays'][0].update(edits)
                self.config.plan(before, document)
        for mirror_rule in (source.replace('mirror = "DP-2"', 'mirror = source_output'),
                            source.replace('output = "DP-1"', 'output = "desc:Native"')):
            with self.subTest(source=mirror_rule), self.assertRaisesRegex(DisplayError, 'mirror rule'):
                self.before[0]['description'] = self.doc['displays'][0]['description'] = 'Native panel'
                self.config.path.write_text(mirror_rule)
                self.plan()

    def test_only_adjusted_fields_are_replaced(self):
        self.doc['displays'][0]['refresh'] = 75
        plan = self.plan()
        self.assertEqual(plan['after'], SOURCE.replace('1920x1080@60', '1920x1080@75.00000'))
        self.config.commit(plan)
        self.assertEqual(self.config.path.read_text(), plan['after'])
        self.assertEqual(self.config.path.with_name('monitors.lua.hypertile.bak').read_text(), SOURCE)

    def test_new_connector_inherits_expressions_and_keeps_fallback(self):
        self.doc['displays'][1]['x'] = 2200
        plan = self.plan()
        self.assertTrue(plan['after'].startswith(SOURCE))
        self.assertIn('output = "DP-2", mode = "preferred", position = "2200x0", scale = monitor_scale', plan['after'])
        self.assertEqual(plan['after'].count('output = ""'), 1)

    def test_keep_reloads_automatic_position_dependencies(self):
        # Reload executes the saved declarations and recalculates auto positions;
        # merely copying the preview request would hide issue #32.
        self.adapter.current[0].update(width=2304, height=1536, refresh=120., scale=1.33333,
                                       modes=['2304x1536@120.00Hz'])
        self.adapter.current[1].update(width=6144, height=2560, scale=1.33333, x=1728,
                                       modes=['6144x2560@60.00Hz'], description='External')
        source = SOURCE.replace('local monitor_scale = 1', 'local monitor_scale = 1.33333')
        source = source.replace('1920x1080@60', '2304x1536@120')

        def reload():
            script = """
                local rules = {}
                hl = {env = function() end, monitor = function(rule) rules[rule.output] = rule end}
                dofile(arg[1])
                print(require('hypertile-json').encode(rules))
            """
            runner = self.root / 'reload.lua'
            runner.write_text(script)
            rules = json.loads(subprocess.check_output(['lua', str(runner), str(self.config.path)],
                                                      cwd=Path(__file__).resolve().parents[1], text=True))
            automatic = []
            right = 0
            for d in self.adapter.current:
                rule = rules.get(d['connector'], rules.get('desc:' + d.get('description', ''), rules['']))
                position = rule.get('position', 'auto')
                if position == 'auto':
                    automatic.append(d)
                else:
                    d['x'], d['y'] = map(int, position.split('x'))
                    right = max(right, d['x'] + round(bounds(d)[2]))
            for d in automatic:
                d['x'], d['y'] = right, 0
                right += round(bounds(d)[2])

        self.adapter.reload = reload
        for extra in ('', '\nhl.monitor({output="DP-2", position="auto"})\n',
                      '\nhl.monitor({output="desc:External", position="auto"})\n',
                      '\nhl.monitor({output="DP-2"})\n',
                      '\nlocal pos = "auto"\nhl.monitor({output="DP-2", position=pos})\n'):
            with self.subTest(extra=extra):
                self.config.path.write_text(source + extra)
                reload()
                self.assertEqual(self.adapter.current[1]['x'], 1728)
                doc = dict(version=1, displays=self.adapter.displays(), workspaces={})
                doc['displays'][0].update(x=6336, y=768)
                pending = self.service.preview(doc, watchdog=False)
                self.adapter.verify(doc['displays'])
                self.assertTrue(self.service.keep(pending['token'])['kept'])
                reload()
                self.adapter.verify(doc['displays'])
                self.assertEqual(self.adapter.current[1]['x'], 1728)
                saved = self.config.path.read_text()
                self.assertIn('position = "auto", scale = monitor_scale', saved)
                self.assertIn('-- keep the mode comment', saved)

    def test_noop_does_not_freeze_automatic_settings(self):
        self.assertIsNone(self.plan())
        self.doc['displays'][0]['refresh'] += .001
        self.doc['displays'][0]['scale'] += .0000001
        self.assertIsNone(self.plan())

    def automatic_neighbor(self):
        # A monitor update re-runs Hyprland's automatic placement, even for
        # outputs omitted from that update. Applying DP-2 pins its position.
        pinned = set()
        apply = self.adapter.apply
        def update(display, **kwargs):
            apply(display, **kwargs)
            if display['enabled'] and not display.get('mirror_of'):
                pinned.add(display['connector'])
            if 'DP-2' not in pinned:
                first, second = self.adapter.current
                second['x'] = first['x'] + bounds(first)[2] if first['enabled'] else 0
        self.adapter.apply = update

    def test_preview_anchors_automatic_neighbor_before_topology_changes(self):
        self.automatic_neighbor()
        self.doc['displays'][0]['enabled'] = False
        pending = self.service.preview(self.doc, watchdog=False)
        self.adapter.verify(self.doc['displays'])
        journal = read(self.service.pending_path)
        self.assertEqual(journal['touched'], ['DP-2', 'DP-1'])
        self.assertEqual(self.config.path.read_text(), SOURCE)
        self.service.revert(pending['token'])
        self.adapter.verify(self.before)
        self.assertFalse(self.service.pending_path.exists())

    def test_preview_anchors_automatic_neighbor_before_moving_first_output(self):
        self.automatic_neighbor()
        self.doc['displays'][0]['x'] = -1920
        pending = self.service.preview(self.doc, watchdog=False)
        self.adapter.verify(self.doc['displays'])
        self.service.revert(pending['token'])
        self.adapter.verify(self.before)

    def test_noop_preview_does_not_pin_automatic_neighbor(self):
        self.automatic_neighbor()
        pending = self.service.preview(self.doc, watchdog=False)
        self.assertFalse(any(call[0] == 'apply' for call in self.adapter.calls))
        self.assertEqual(read(self.service.pending_path)['touched'], [])
        self.service.revert(pending['token'])

    def test_automatic_neighbor_keeps_native_mode_and_recovers_after_failure(self):
        self.config.path.write_text(SOURCE + '\nlocal native_mode = "preferred"\n'
                                    'hl.monitor({output="DP-2", mode=native_mode, position="auto"})\n')
        self.automatic_neighbor()
        apply = self.adapter.apply
        applied = []
        def fail_disable(display, **kwargs):
            applied.append((display['connector'], kwargs))
            if not display['enabled']:
                raise DisplayError('Injected disable failure')
            apply(display, **kwargs)
        self.adapter.apply = fail_disable
        self.doc['displays'][0]['enabled'] = False
        with self.assertRaisesRegex(DisplayError, 'Injected disable failure'):
            self.service.preview(self.doc, watchdog=False)
        self.assertEqual(applied[0], ('DP-2', {'preserve_mode': True}))
        self.adapter.verify(self.before)
        self.assertFalse(self.service.pending_path.exists())
        self.assertEqual(read(self.service.directory / 'recovery.json')['errors'], [])

    def test_keep_saves_the_scale_used_by_preview(self):
        # A 6144x2560 mode cannot use 1.4; validation selects 4/3. Saving
        # the original request would disagree with preview and fail reload.
        self.adapter.current[0].update(width=6144, height=2560, modes=['6144x2560@60.00Hz'])
        self.adapter.current[1]['x'] = 6144
        doc = dict(version=1, displays=self.adapter.displays(), workspaces={})
        doc['displays'][0]['scale'] = 1.4
        doc['displays'][1]['x'] = 4608
        pending = self.service.preview(doc, watchdog=False)
        plan = read(self.service.pending_path)['config_plan']
        self.assertIn('scale = ' + str(4 / 3), plan['after'])
        self.assertNotIn('scale = 1.4,', plan['after'])
        self.service.keep(pending['token'])
        self.assertAlmostEqual(read(self.service.confirmed_path)['displays'][0]['scale'], 4 / 3)

    def test_long_comments_and_strings_are_not_rules(self):
        self.config.path.write_text(SOURCE + '\n--[=[ hl.monitor({output="DP-1"}) ]=]\nlocal text = "hl.monitor"\n')
        self.doc['displays'][0]['transform'] = 1
        self.assertIn('--[=[ hl.monitor', self.plan()['after'])

    def test_unsupported_rules_are_specific_and_never_rewritten(self):
        for source in ['if connected then hl.monitor({output="DP-1"}) end',
                       'hl.monitor(settings)', 'hl.monitor({output=connector})',
                       'hl.monitor({output="DP-1"})\nhl.monitor({output="DP-1"})']:
            self.config.path.write_text(source)
            self.doc['displays'][0]['transform'] = 1
            with self.assertRaisesRegex(DisplayError, 'monitors.lua'):
                self.plan()
            self.assertEqual(self.config.path.read_text(), source)

    def test_only_loaded_modules_are_inspected(self):
        other = self.config.root / 'old.lua'
        other.write_text('hl.monitor({output="DP-1"})')
        self.doc['displays'][0]['transform'] = 1
        self.assertIsNotNone(self.plan())
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\nrequire("hypr.old")')
        with self.assertRaisesRegex(DisplayError, 'old.lua'):
            self.plan()

    def test_external_edit_between_preview_and_keep_is_preserved(self):
        self.doc['displays'][0]['transform'] = 1
        plan = self.plan()
        external = SOURCE + '-- external edit\n'
        self.config.path.write_text(external)
        with self.assertRaisesRegex(DisplayError, 'changed during preview'):
            self.config.commit(plan)
        self.assertEqual(self.config.path.read_text(), external)

    def test_external_edit_at_keep_does_not_strand_preview(self):
        self.doc['displays'][0]['transform'] = 1
        pending = self.service.preview(self.doc, watchdog=False)
        external = SOURCE + '-- external edit\n'
        self.config.path.write_text(external)
        with self.assertRaisesRegex(DisplayError, 'changed during preview'):
            self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), external)
        self.assertFalse(self.service.pending_path.exists())

    def test_preview_revert_never_writes_config(self):
        self.doc['displays'][0]['transform'] = 1
        pending = self.service.preview(self.doc, watchdog=False)
        self.assertEqual(self.config.path.read_text(), SOURCE)
        self.service.revert(pending['token'])
        self.assertEqual(self.config.path.read_text(), SOURCE)

    def test_keep_updates_config_and_disables_geometry_replay(self):
        self.doc['displays'][0]['transform'] = 1
        pending = self.service.preview(self.doc, watchdog=False)
        self.service.keep(pending['token'])
        self.assertIn('transform = 1', self.config.path.read_text())
        self.assertTrue(read(self.service.confirmed_path)['configuration_backed'])
        self.adapter.calls.clear()
        self.adapter.current[0]['transform'] = 2  # subsequent manual config change
        self.service.restore('configreload')
        self.assertEqual(self.adapter.current[0]['transform'], 2)
        self.assertEqual(self.adapter.calls, [])

    def test_failed_reload_restores_file_and_geometry(self):
        self.doc['displays'][0]['transform'] = 1
        pending = self.service.preview(self.doc, watchdog=False)
        self.adapter.reload = unittest.mock.Mock(side_effect=[DisplayError('bad reload'), None])
        with self.assertRaisesRegex(DisplayError, 'bad reload'):
            self.service.keep(pending['token'])
        self.assertEqual(self.config.path.read_text(), SOURCE)
        self.assertEqual(self.adapter.current[0]['transform'], 0)
        self.assertFalse(self.service.pending_path.exists())

    def test_crash_after_config_write_is_recovered(self):
        self.doc['displays'][0]['transform'] = 1
        pending = self.service.preview(self.doc, watchdog=False)
        self.adapter.reload = unittest.mock.Mock(side_effect=SystemExit('crash'))
        with self.assertRaises(SystemExit):
            self.service.keep(pending['token'])
        self.assertIn('transform = 1', self.config.path.read_text())
        self.adapter.reload = lambda: None
        self.service.restore()
        self.assertEqual(self.config.path.read_text(), SOURCE)
        self.assertFalse(self.service.pending_path.exists())

    def test_initial_adoption_is_automatic_and_does_not_change_config(self):
        self.service.setup()
        self.assertEqual(self.config.path.read_text(), SOURCE)
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(read(self.service.confirmed_path)['configuration_backed'])

    def test_legacy_saved_geometry_migrates_once(self):
        atomic(self.service.confirmed_path, dict(self.doc, takeover=True))
        with patch.object(self.service, 'preview', side_effect=lambda doc, **kwargs: Service.preview(self.service, doc, watchdog=False, **kwargs)):
            self.service.setup()
        result = self.config.path.read_text()
        self.assertIn('output = "DP-2"', result)
        self.assertNotIn('takeover', read(self.service.confirmed_path))
        self.service.setup()
        self.assertEqual(self.config.path.read_text(), result)

    def test_backup_survives_subsequent_saves(self):
        self.doc['displays'][0]['transform'] = 1
        self.config.commit(self.plan())
        self.doc['displays'][0]['transform'] = 2
        self.config.commit(self.plan())
        self.assertEqual(self.config.path.with_name('monitors.lua.hypertile.bak').read_text(), SOURCE)

    def test_external_edit_after_write_is_not_clobbered_by_recovery(self):
        self.doc['displays'][0]['transform'] = 1
        plan = self.plan()
        self.config.commit(plan)
        self.config.path.write_text('-- edited elsewhere\n' + plan['after'])
        self.assertTrue(self.config.rollback(plan))
        self.assertTrue(self.config.path.read_text().startswith('-- edited elsewhere'))

    def test_mirror_save_preserves_source_and_clear_is_explicit(self):
        self.doc['displays'][1]['mirror_of'] = self.doc['displays'][0]['id']
        plan = self.plan()
        self.assertIn('mirror = "DP-1"', plan['after'])
        self.assertIn('-- keep the mode comment', plan['after'])
        self.assertIn('scale = monitor_scale', plan['after'])
        self.config.path.write_text(plan['after'])
        self.before[1].update(mirror_of=self.before[0]['id'], mirror_connector='DP-1')
        self.doc['displays'][1]['mirror_of'] = None
        plan = self.plan()
        self.assertIn('mirror = ""', plan['after'])
        self.assertNotIn('mirror = "DP-1"', plan['after'])

    def test_enabling_disabled_mirror_explicitly_clears_inactive_config(self):
        self.config.path.write_text(SOURCE + '\nhl.monitor({output="DP-2",disabled=true,mirror="DP-1"})\n')
        self.before[1]['enabled'] = False
        self.doc['displays'][1]['mirror_of'] = None
        plan = self.plan()
        self.assertIn('mirror=""', plan['after'])

    def test_promoted_mirror_pins_anchor_even_when_runtime_position_is_unchanged(self):
        self.config.path.write_text(SOURCE + '\nhl.monitor({output="DP-2",position="1920x0",mirror="DP-1"})\n')
        self.before[1].update(x=0, y=0, mirror_of=self.before[0]['id'], mirror_connector='DP-1')
        self.doc['displays'][1].update(x=0, y=0, mirror_of=None)
        self.doc['displays'][0]['mirror_of'] = self.doc['displays'][1]['id']
        plan = self.plan()
        self.assertIn('position="0x0",mirror=""', plan['after'])
        self.assertIn('mirror = "DP-2"', plan['after'])

    def test_description_prefix_rules_are_edited_like_hyprland(self):
        # Hyprland matches desc: by prefix, so a partial description rule owns
        # the output; appending a connector rule would silently shadow its vrr.
        self.config.path.write_text(SOURCE + 'hl.monitor({ output = "desc:Dell U27", position = "1920x0", vrr = 1 })\n')
        self.before[1]['description'] = self.doc['displays'][1]['description'] = 'Dell U2723QE ABC123'
        self.doc['displays'][1]['x'] = 2200
        plan = self.plan()
        self.assertIn('output = "desc:Dell U27", position = "2200x0", vrr = 1', plan['after'])
        self.assertNotIn('output = "DP-2"', plan['after'])

    def test_last_matching_rule_wins_like_hyprland(self):
        self.config.path.write_text(SOURCE + 'hl.monitor({ output = "desc:Native", position = "0x0" })\n')
        self.before[0]['description'] = self.doc['displays'][0]['description'] = 'Native panel'
        self.doc['displays'][0]['x'] = 100
        plan = self.plan()
        self.assertIn('output = "desc:Native", position = "100x0"', plan['after'])
        self.assertIn('position = "0x0", scale = monitor_scale', plan['after'], 'the shadowed connector rule is left alone')

if __name__ == '__main__':
    unittest.main()
