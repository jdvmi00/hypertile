"""Source-preserving display saves and configuration transaction recovery."""
import copy
import json
import subprocess
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
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
