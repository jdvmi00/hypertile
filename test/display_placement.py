#!/usr/bin/env python3
"""External display resizing, durable edge relationships, and transaction races."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
from adapter import bounds, DisplayError
from configuration import Configuration
from placement import project, rebase, snapshot
from service import Service, Watcher, atomic, read
from displays import display, Fake


def panel(name, x=0, y=0, width=6144, height=2560, scale=4/3, **extra):
    return dict(display(name, x), y=y, width=width, height=height, scale=scale,
                modes=[f'{width}x{height}@60.00Hz'], **extra)


def positions(displays):
    return {d['connector']: (d['x'], d['y']) for d in displays}


class GeometryTests(unittest.TestCase):
    def test_full_split_full_does_not_accumulate_offset(self):
        saved = [panel('HDMI-A-1'), panel('DP-1', 4608)]
        current = copy.deepcopy(saved)
        for width, right in [(3072, 2304), (6144, 4608)] * 4:
            for d in current:
                d['width'] = width
            current = project(saved, current)
            self.assertEqual(positions(current), {'HDMI-A-1': (0, 0), 'DP-1': (right, 0)})
            self.assertEqual([d['width'] for d in current], [width, width])

    def test_split_reference_expands_and_contracts(self):
        saved = [panel('HDMI-A-1', y=-1920, width=3072), panel('DP-1', 2304, -1920, width=3072)]
        current = [dict(d, width=6144) for d in reversed(saved)]
        self.assertEqual(positions(project(saved, current)), {'HDMI-A-1': (0, -1920), 'DP-1': (4608, -1920)})

    def test_left_top_center_bottom_and_offset_alignments(self):
        main = panel('main', width=1920, height=1080, scale=1)
        for y in (0, 40, 140, 280):
            saved = [main, panel('left', -1000, y, width=1000, height=800, scale=1)]
            current = [dict(main, height=1600), dict(saved[1], width=500, height=600)]
            expected_y = {0: 0, 40: 40, 140: 500, 280: 1000}[y]
            self.assertEqual(positions(project(saved, current))['left'], (-500, expected_y))
        saved = [main, panel('top', 0, -800, width=1920, height=800, scale=1)]
        self.assertEqual(positions(project(saved, [main, dict(saved[1], height=500)]))['top'], (0, -500))

    def test_scale_rotation_chain_and_intentional_gap(self):
        saved = [panel('a'), panel('b', 4608), panel('c', 9216), panel('manual', 16000)]
        current = copy.deepcopy(saved)
        current[0]['scale'] = 2
        current[1]['transform'] = 1
        result = project(saved, current)
        self.assertEqual(positions(result), {'a': (0, 0), 'b': (3072, 0), 'c': (4992, 0), 'manual': (16000, 0)})

    def test_unplug_disabled_mirror_and_identical_identity(self):
        saved = [panel('HDMI', identity='same', explicit_match=True),
                 panel('DP', 4608, identity='same', explicit_match=True)]
        only = [dict(saved[1], id='same', width=3072)]
        self.assertEqual(positions(project(saved, only)), {'DP': (4608, 0)})
        current = [dict(d, width=3072) for d in saved]
        current[1]['mirror_of'] = saved[0]['id']
        self.assertEqual(positions(project(saved, current))['DP'], (4608, 0))
        current[1].update(mirror_of=None, enabled=False, width=0)
        self.assertEqual(positions(project(saved, current))['DP'], (4608, 0))
        current[1].update(enabled=True, width=3072)
        self.assertEqual(positions(project(saved, current))['DP'], (2304, 0))
        current[1]['identity'] = 'replacement'
        self.assertEqual(positions(project(saved, current))['DP'], (4608, 0))

    def test_uneven_grid_and_unknown_output_do_not_overlap(self):
        saved = [panel('a'), panel('b', 4608), panel('c', 0, 1920), panel('d', 4608, 1920)]
        current = copy.deepcopy(saved)
        current[0]['transform'] = 1
        current.append(panel('unknown', 7000, 7000))
        result = project(saved, current)
        for i, a in enumerate(result):
            ax, ay, aw, ah = bounds(a)
            for b in result[i + 1:]:
                bx, by, bw, bh = bounds(b)
                self.assertFalse(min(ax + aw, bx + bw) > max(ax, bx) and min(ay + ah, by + bh) > max(ay, by))

    def test_fixed_outputs_stay_and_anchor_their_neighbours(self):
        saved = [panel('HDMI-A-1'), panel('DP-1', 4608), panel('DP-2', 9216)]
        current = [dict(d, width=3072) for d in saved]
        self.assertEqual(positions(project(saved, current, fixed={'DP-1'})),
                         {'HDMI-A-1': (2304, 0), 'DP-1': (4608, 0), 'DP-2': (6912, 0)})
        self.assertEqual(positions(project(saved, current, fixed={'HDMI-A-1', 'DP-2'})),
                         {'HDMI-A-1': (0, 0), 'DP-1': (2304, 0), 'DP-2': (9216, 0)})

    def test_rebase_restates_live_outputs_and_holds_inactive_ones(self):
        saved = [panel('HDMI-A-1'), panel('DP-1', 4608), panel('DP-2', 9216), panel('DP-3', 13824)]
        current = [dict(d, width=3072) for d in saved[:3]] + [panel('DP-5', 20000)]
        current[2].update(enabled=False)
        result = rebase(saved, current)
        self.assertEqual(positions(result), {'HDMI-A-1': (0, 0), 'DP-1': (2304, 0), 'DP-2': (9216, 0),
                                             'DP-3': (13824, 0), 'DP-5': (20000, 0)})
        self.assertEqual([(d['width'], d['enabled']) for d in result],
                         [(3072, True), (6144, True), (6144, True), (6144, True), (3072, True)])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = patch.dict(os.environ, XDG_STATE_HOME=str(self.root))
        environment.start()
        self.addCleanup(environment.stop)
        self.config = Configuration(self.root / 'hypr')
        self.config.root.mkdir()
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\n')
        self.source = ('hl.monitor({output="HDMI-A-1", mode="highres", position="0x0", scale=4/3})\n'
                       'hl.monitor({output="DP-1", mode="highres", position="4608x0", scale=4/3})\n')
        self.config.path.write_text(self.source)
        self.adapter = Fake()
        self.adapter.current = [panel('HDMI-A-1'), panel('DP-1', 4608)]
        self.adapter.live = []
        self.service = Service(self.adapter, self.root / 'state')
        self.service.configuration = self.config
        self.service.policy = None
        self.adapter.reload = lambda: None
        self.saved = dict(version=1, displays=self.adapter.displays(), workspaces={},
                          configuration_backed=True, _transaction='original')
        atomic(self.service.confirmed_path, self.saved)

    def resize(self, width):
        for d in self.adapter.current:
            d.update(width=width, modes=[f'{width}x2560@60.00Hz'])

    def reflow(self):
        return self.service.reflow(self.adapter.displays())

    def reload(self):
        """Hyprland returns every output to its declared coordinates."""
        declared = self.config.positions(self.adapter.current)
        for d in self.adapter.current:
            if declared[d['connector']]:
                d['x'], d['y'] = declared[d['connector']]

    def split(self):
        self.reflow()
        self.resize(3072)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)

    def test_restart_and_reload_keep_original_relationships(self):
        self.reflow()
        self.resize(3072)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.service = Service(self.adapter, self.root / 'state')
        self.service.configuration = self.config
        self.service.policy = None
        self.adapter.current[1]['x'] = 4608  # Reload reapplies saved coordinates.
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.resize(6144)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 4608)
        self.assertEqual(self.config.path.read_text(), self.source)
        self.assertEqual(read(self.service.confirmed_path), self.saved)

    def test_upgrade_recovers_existing_split_reference_without_learning_overlap(self):
        self.resize(3072)
        self.adapter.current[1]['x'] = 2304
        self.saved['displays'] = self.adapter.displays()
        atomic(self.service.confirmed_path, self.saved)
        self.config.path.write_text(self.source.replace('4608x0', '2304x0'))
        self.resize(6144)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 4608)

    def test_quote_only_config_edit_preserves_edges(self):
        self.split()
        reference = read(self.service.directory / 'placement.json')['reference']
        self.config.path.write_text(self.source.replace('"', "'"))
        self.reload()
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.assertEqual(read(self.service.directory / 'placement.json')['reference'], reference)
        for width, right in ((6144, 4608), (3072, 2304)):
            self.resize(width)
            self.reflow()
            self.assertEqual(self.adapter.current[1]['x'], right)

    def test_old_single_quoted_snapshots_are_adopted(self):
        source = self.config.placement_source()
        for rules in source.values():
            for _, fields in rules:
                for key in ('position', 'mirror'):
                    if key in fields:
                        fields[key] = ["'" + fields[key][0][1:-1] + "'"]
        self.saved['placement_source'] = source
        atomic(self.service.confirmed_path, self.saved)
        self.resize(3072)
        self.reflow()  # No placement journal yet; adopt the confirmed reference.
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        path = self.service.directory / 'placement.json'
        state = read(path)
        state['source'] = source
        atomic(path, state)
        self.reload()
        self.reflow()  # A previous process wrote a journal with single quotes.
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.assertEqual(read(path)['reference'], state['reference'])

    def test_runtime_move_retains_inactive_neighbours_reference(self):
        for inactive in ('disabled', 'mirrored', 'absent'):
            with self.subTest(inactive=inactive):
                self.adapter.current = copy.deepcopy(self.saved['displays'])
                (self.service.directory / 'placement.json').unlink(missing_ok=True)
                self.reflow()
                right = copy.deepcopy(self.adapter.current[1])
                if inactive == 'disabled':
                    self.adapter.current[1].update(enabled=False, width=0, height=0)
                elif inactive == 'mirrored':
                    self.adapter.current[1].update(mirror_of=self.adapter.current[0]['id'],
                                                   mirror_connector='HDMI-A-1', x=0)
                else:
                    self.adapter.current.pop()
                self.reflow()
                self.adapter.current[0]['y'] = 100
                self.reflow()
                reference = read(self.service.directory / 'placement.json')['reference']
                self.assertEqual(next(d for d in reference if d['connector'] == right['connector']),
                                 snapshot([right])[0])
                self.adapter.current = [self.adapter.current[0], right]
                self.reflow()
                self.resize(3072)
                self.reflow()
                self.assertEqual(positions(self.adapter.current),
                                 {'HDMI-A-1': (0, 100), 'DP-1': (2304, 0)})

    def test_manual_config_and_runtime_positions_win(self):
        for source_edit in (False, True):
            with self.subTest(source_edit=source_edit):
                self.reflow()
                self.adapter.current[1]['x'] = 7000
                if source_edit:
                    self.config.path.write_text(self.source.replace('4608x0', '7000x0'))
                self.reflow()
                self.resize(3072)
                self.reflow()
                self.assertEqual(self.adapter.current[1]['x'], 7000)
                self.resize(6144)

    def test_pending_preview_and_stale_snapshot_do_not_write(self):
        self.reflow()
        self.resize(3072)
        atomic(self.service.pending_path, dict(token='test'))
        self.assertFalse(self.reflow())
        self.assertEqual(self.adapter.calls, [])
        self.service.pending_path.unlink()
        stale = self.adapter.displays()
        self.resize(6144)
        self.assertFalse(self.service.reflow(stale))
        self.assertEqual(self.adapter.calls, [])

    def test_capability_race_and_session_restore_defer_moves(self):
        self.reflow()
        self.resize(3072)
        stale = self.adapter.displays()
        self.adapter.current[0]['modes'].append('1920x1080@60.00Hz')
        self.assertFalse(self.service.reflow(stale))
        status = self.service.directory.parent / 'sessions/status.json'
        atomic(status, dict(mode='restoring'))
        self.assertFalse(self.reflow())
        self.assertEqual(self.adapter.calls, [])
        status.unlink()
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)

    def test_reposition_requests_only_a_position(self):
        self.reflow()
        self.resize(3072)
        self.adapter.current[1]['awake'] = False
        self.reflow()
        self.assertEqual(self.adapter.calls, [('reposition', 'DP-1', 2304, 0)])
        self.assertFalse(self.adapter.current[1]['awake'])

    def test_output_without_its_own_rule_is_not_moved_and_anchors_its_neighbour(self):
        # A partial request would reset the mode, scale and rotation that such
        # an output inherits from a fallback or description rule.
        fallback = 'hl.monitor({output="", mode="preferred", position="auto", scale=omarchy_monitor_scale})\n'
        for own, moved in (('DP-1', ('DP-1', 2304, 0)), ('HDMI-A-1', ('HDMI-A-1', 2304, 0))):
            with self.subTest(own=own):
                self.adapter.calls.clear()
                self.resize(6144)
                self.adapter.current[0]['x'], self.adapter.current[1]['x'] = 0, 4608
                (self.service.directory / 'placement.json').unlink(missing_ok=True)
                self.config.path.write_text(fallback + next(
                    line for line in self.source.splitlines() if own in line) + '\n')
                self.reflow()
                self.resize(3072)
                self.reflow()
                self.assertEqual(self.adapter.calls, [('reposition', *moved)])

    def test_imported_matching_rule_keeps_output_fixed(self):
        self.adapter.current[1]['description'] = 'Dell right'
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\nrequire("hypr.override")\n')
        (self.config.root / 'override.lua').write_text(
            'hl.monitor({output="desc:Dell right", mode="highres", position="4608x0", scale=4/3})\n')
        self.assertFalse(self.config.uses_connector_rule(self.adapter.current[1]))
        self.assertTrue(self.config.uses_connector_rule(self.adapter.current[0]))
        self.reflow()
        self.resize(3072)
        self.reflow()
        self.assertEqual(self.adapter.calls, [('reposition', 'HDMI-A-1', 2304, 0)])
        self.assertEqual(positions(self.adapter.current),
                         {'HDMI-A-1': (2304, 0), 'DP-1': (4608, 0)})
        self.assertEqual([d['width'] for d in self.adapter.current], [3072, 3072])

    def test_unrelated_imported_rule_does_not_disable_placement(self):
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\nrequire("hypr.extra")\n')
        (self.config.root / 'extra.lua').write_text('hl.monitor({output="DP-7", position="30000x0"})\n')
        self.assertTrue(self.config.uses_connector_rule(self.adapter.current[1]))
        self.split()

    def test_keep_after_an_edge_adjustment_saves_the_live_position(self):
        self.adapter.reload = self.reload
        self.split()
        doc = dict(version=1, displays=self.adapter.displays(), workspaces={})
        doc['displays'][1]['transform'] = 1
        preview = self.service.preview(doc, watchdog=False)
        self.service.keep(preview['token'])
        self.assertIn('position="2304x0"', self.config.path.read_text())
        self.assertEqual((self.adapter.current[1]['x'], self.adapter.current[1]['transform']), (2304, 1))
        self.assertFalse(self.service.pending_path.exists())

    def test_removal_after_an_edge_adjustment_survives_its_reload(self):
        self.adapter.reload = self.reload
        absent = panel('DP-9', 20000)
        self.saved['displays'].append(absent)
        atomic(self.service.confirmed_path, self.saved)
        self.config.path.write_text(self.source + 'hl.monitor({output="DP-9", mode="preferred", position="20000x0", scale=1})\n')
        self.split()
        self.service.remove_display(absent['id'], watchdog=False)
        self.assertNotIn('DP-9', self.config.path.read_text())
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.assertEqual(len(read(self.service.confirmed_path)['displays']), 2)

    def test_reload_is_not_a_manual_move_beside_disabled_or_automatic_outputs(self):
        extra = dict(disabled=(panel('DP-2', 9216, enabled=False), 'hl.monitor({output="DP-2", disabled=true})\n'),
                     automatic=(panel('DP-2', 12000), 'hl.monitor({output="", mode="preferred", position="auto", scale=1})\n'))
        for name, (third, rule) in extra.items():
            with self.subTest(third=name):
                self.resize(6144)
                self.adapter.current = self.adapter.current[:2] + [third]
                self.adapter.current[1]['x'] = 4608
                (self.service.directory / 'placement.json').unlink(missing_ok=True)
                self.config.path.write_text(rule + self.source)
                self.saved['displays'] = self.adapter.displays()
                atomic(self.service.confirmed_path, self.saved)
                self.split()
                self.reload()
                self.assertEqual(self.adapter.current[1]['x'], 4608)
                self.reflow()
                self.assertEqual(self.adapter.current[1]['x'], 2304)
                self.resize(6144)
                self.reflow()
                self.assertEqual(self.adapter.current[1]['x'], 4608)

    def test_upgrade_adopts_saved_edges_despite_an_absent_saved_display(self):
        self.saved['displays'].append(panel('DP-9', 20000))
        atomic(self.service.confirmed_path, self.saved)
        self.resize(3072)  # The first pass finds a transient split with the declared gap.
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)

    def test_unrelated_lua_naming_a_monitor_does_not_disable_placement(self):
        (self.config.root / 'hyprland.lua').write_text('require("hypr.monitors")\nrequire("hypr.bindings")\n')
        (self.config.root / 'bindings.lua').write_text(
            'hl.bind("SUPER+M", function() hl.dispatch(hl.dsp.focus({monitor="+1"})) end)\n')
        self.split()

    def test_unrelated_config_edit_keeps_edges_and_an_edited_position_joins_them(self):
        self.adapter.current.append(panel('DP-2', 9216))
        self.source += 'hl.monitor({output="DP-2", mode="highres", position="9216x0", scale=4/3})\n'
        self.config.path.write_text(self.source)
        self.saved['displays'] = self.adapter.displays()
        atomic(self.service.confirmed_path, self.saved)
        self.split()
        self.assertEqual(self.adapter.current[2]['x'], 4608)
        # A rule for another monitor: nothing here was repositioned.
        self.source += 'hl.monitor({output="DP-7", mode="preferred", position="30000x0", scale=1})\n'
        self.config.path.write_text(self.source)
        self.reload()
        self.reflow()
        self.assertEqual(positions(self.adapter.current), {'HDMI-A-1': (0, 0), 'DP-1': (2304, 0), 'DP-2': (4608, 0)})
        # A deliberate gap for one output leaves the other edge attached.
        self.config.path.write_text(self.source.replace('9216x0', '8000x0'))
        self.reload()
        self.reflow()
        self.assertEqual(positions(self.adapter.current), {'HDMI-A-1': (0, 0), 'DP-1': (2304, 0), 'DP-2': (8000, 0)})
        self.resize(2048)
        self.reflow()
        self.assertEqual(positions(self.adapter.current), {'HDMI-A-1': (0, 0), 'DP-1': (1536, 0), 'DP-2': (8000, 0)})

    def test_manual_move_after_failed_reflow_is_not_overwritten(self):
        self.reflow()
        self.resize(3072)
        self.adapter.fail = True
        with self.assertRaises(DisplayError):
            self.reflow()
        self.adapter.current[1]['x'] = 7000
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 7000)

    def test_custom_lua_placement_is_not_interpreted(self):
        self.config.path.write_text('for name in pairs(outputs) do hl.monitor({output=name}) end\n')
        self.resize(3072)
        self.reflow()
        self.assertEqual(self.adapter.calls, [])

    def test_automatic_position_becomes_durable_edge_on_keep(self):
        self.config.path.write_text(self.source.replace('position="4608x0"', 'position="auto-right"'))
        doc = dict(version=1, displays=self.adapter.displays(), workspaces={})
        doc['displays'][0]['scale'] = 2
        doc['displays'][1]['x'] = 3072
        preview = self.service.preview(doc, watchdog=False)
        self.service.keep(preview['token'])
        self.reflow()
        self.resize(3072)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 1536)

    def test_failure_recovers_from_journal_without_resizing_modes(self):
        self.reflow()
        self.resize(3072)
        self.adapter.fail = True
        with self.assertRaises(DisplayError):
            self.reflow()
        self.assertIn('applying', read(self.service.directory / 'placement.json'))
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.assertEqual([d['width'] for d in self.adapter.current], [3072, 3072])
        self.assertNotIn('applying', read(self.service.directory / 'placement.json'))

    def test_keep_new_arrangement_replaces_relationship_and_revert_retains_it(self):
        self.reflow()
        doc = dict(version=1, displays=self.adapter.displays(), workspaces={})
        doc['displays'][1]['x'] = 7000
        transaction = self.service.preview(doc, watchdog=False)
        self.assertFalse(self.reflow())
        self.service.revert(transaction['token'])
        self.resize(3072)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        doc = dict(version=1, displays=self.adapter.displays(), workspaces={})
        doc['displays'][1]['x'] = 7000
        transaction = self.service.preview(doc, watchdog=False)
        self.service.keep(transaction['token'])
        self.reflow()
        self.resize(6144)
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 7000)

    def test_watcher_waits_for_both_outputs_to_settle_and_updates_with_no_hotplug(self):
        watcher = Watcher(self.service)
        watcher.tick([], 0)
        watcher.tick([], .5)
        watcher.tick([], 1)
        self.adapter.current[0]['width'] = 3072
        watcher.tick([], 6)
        watcher.tick([], 6.5)
        self.assertEqual(self.adapter.current[1]['x'], 4608)
        self.adapter.current[1]['width'] = 3072
        watcher.tick([], 7)
        watcher.tick([], 7.5)
        self.assertEqual(self.adapter.current[1]['x'], 4608)
        watcher.tick([], 8)
        self.assertEqual(self.adapter.current[1]['x'], 2304)
        self.resize(6144)
        watcher.tick([], 13)
        watcher.tick([], 14)
        self.assertEqual(self.adapter.current[1]['x'], 4608)

    def test_watcher_reconciles_only_after_a_change_or_reload(self):
        watcher = Watcher(self.service)
        self.service.reflow = Mock(wraps=self.service.reflow)
        watcher.tick([], 0)
        watcher.tick([], 1)
        self.assertEqual(self.service.reflow.call_count, 1, 'one pass after start-up')
        atomic(self.service.power_path, dict(original=self.adapter.wake_options(), apply={}))
        self.adapter.current[1]['awake'] = False
        for now in (1.5, 2, 6, 11):
            watcher.tick(['createworkspace>>5'], now)
        self.assertEqual(self.service.reflow.call_count, 1, 'a settled desktop is not reconciled again')
        watcher.tick(['configreloaded>>'], 12)
        watcher.tick([], 13)
        self.assertEqual(self.service.reflow.call_count, 2)
        self.adapter.current[1]['awake'] = True
        self.resize(3072)
        watcher.tick([], 18)
        watcher.tick([], 19)
        self.assertEqual((self.service.reflow.call_count, self.adapter.current[1]['x']), (3, 2304))

    def test_watcher_survives_a_failing_reflow_and_backs_off(self):
        watcher = Watcher(self.service)
        watcher.tick([], 0)
        self.service.reflow = Mock(side_effect=DisplayError('readback timed out'))
        self.service.settle_power = Mock(wraps=self.service.settle_power)
        attempts = []
        for now in (1, 1.5, 2, 2.5, 3, 3.5, 6, 6.5, 7, 7.5, 14.5, 15):
            try:
                watcher.tick([], now)
            except DisplayError:
                attempts.append(now)
                self.assertIsNotNone(watcher.previous)
        self.assertEqual(attempts, [1, 3, 7, 15], 'retries double their distance')
        self.assertEqual(self.service.settle_power.call_count, 5, 'power settles on every pass, failed or due')
        self.service.reflow = Mock(return_value=True)
        watcher.tick([], 30.5)
        self.service.reflow.assert_not_called()
        watcher.tick([], 31)
        self.service.reflow.assert_called_once()
        self.assertFalse(watcher.tick([], 31.5), 'settled again')

    def test_idle_has_no_writes_or_mode_requests_and_unplug_retains_reference(self):
        self.reflow()
        with patch('service.atomic') as write:
            self.reflow()
            write.assert_not_called()
        unplugged = self.adapter.current.pop()
        self.reflow()
        self.resize(3072)
        self.reflow()
        self.adapter.current.append(dict(unplugged, width=3072))
        self.reflow()
        self.assertEqual(self.adapter.current[1]['x'], 2304)


if __name__ == '__main__':
    unittest.main()
