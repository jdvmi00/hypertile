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
from placement import project, snapshot
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

    def test_reposition_preserves_native_mode_and_other_live_settings(self):
        self.reflow()
        self.resize(3072)
        self.adapter.current[1]['awake'] = False
        original = self.adapter.apply
        self.adapter.apply = Mock(wraps=original)
        self.reflow()
        self.adapter.apply.assert_called_once()
        args, kwargs = self.adapter.apply.call_args
        self.assertEqual(kwargs, dict(preserve_mode=True))
        self.assertEqual((args[0]['width'], args[0]['mode_policy']), (3072, 'highres'))
        self.assertFalse(self.adapter.current[1]['awake'])

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
