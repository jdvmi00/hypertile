"""Opt-in real Hyprland adapter smoke in an isolated compositor.

Run from a Wayland session: python3 test/display_integration.py.
Use --workspace-only for immediate workspace switching without mode changes.
Use --removal-only for immediate disconnected-profile removal.
Use --disable-only for workspace/window migration and rollback.
Use --mode-safety-only for partial mode preservation and virtual-output guards.
Use --placement-only for external resizing, adjoining edges and watcher restarts.
No physical output or user configuration is changed.
"""
import copy
import json
import signal
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="htd-") as directory:
        root = Path(directory)
        runtime = root / "r"
        runtime.mkdir(mode=0o700)
        (root / 'config/hypr').mkdir(parents=True)
        (root / 'config/hypr/looknfeel.lua').write_text('hl.config({general={layout="dwindle"}})\n')
        config = root / "config/hypr/hyprland.lua"
        monitors = root / "config/hypr/monitors.lua"
        monitors.write_text('hl.monitor({output="WAYLAND-1",mode="1280x720@60",position="0x0",scale=1,disabled=false})\n'
                          'hl.monitor({output="WAYLAND-2",mode="1280x720@60",position="1280x0",scale=1,disabled=false})\n'
                          'hl.config({animations={enabled=false},xwayland={enabled=false}})\n')
        config.write_text('package.path = os.getenv("XDG_CONFIG_HOME") .. "/?.lua;" .. package.path\nrequire("hypr.monitors")\nhl.config({animations={enabled=false},xwayland={enabled=false}})\n')
        env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_STATE_HOME=str(root / "state"),
                   XDG_CONFIG_HOME=str(root / "config"), HYPERTILE_SRC=str(ROOT),
                   HYPRLAND_NO_SD_VARS="1", HYPRLAND_NO_SD_NOTIFY="1")
        parent = Path(os.environ["WAYLAND_DISPLAY"])
        if not parent.is_absolute():
            parent = Path(os.environ["XDG_RUNTIME_DIR"]) / parent
        env["WAYLAND_DISPLAY"] = str(parent)
        for name in ("DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "NOTIFY_SOCKET"):
            env.pop(name, None)
        with (root / "compositor.log").open("w+") as log:
            process = subprocess.Popen(["Hyprland", "--config", str(config)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    result = subprocess.run(["hyprctl", "instances", "-j"], env=env, text=True, capture_output=True)
                    try:
                        instances = [v for v in json.loads(result.stdout) if v['pid'] == process.pid]
                    except (ValueError, TypeError):
                        instances = []
                    if instances and (runtime / "hypr" / instances[0]['instance'] / '.socket.sock').exists():
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError("Isolated Hyprland did not start")
                env['HYPRLAND_INSTANCE_SIGNATURE'] = instances[0]['instance']
                env['WAYLAND_DISPLAY'] = instances[0]['wl_socket']

                def ctl(*args):
                    result = subprocess.run(['hyprctl', *args], env=env, text=True, capture_output=True, timeout=10)
                    assert result.returncode == 0, str(args) + ': ' + result.stdout + result.stderr
                    return result.stdout

                def display(*args, input=None):
                    result = subprocess.run([str(ROOT / 'bin/hypertile-displays'), *args], input=input,
                                            env=env, text=True, capture_output=True, timeout=25)
                    assert result.returncode == 0, str(args) + ': ' + result.stdout + result.stderr + '\nMonitor config:\n' + monitors.read_text()
                    return json.loads(result.stdout)

                names = {m['name'] for m in json.loads(ctl('-j', 'monitors', 'all'))}
                for name in ('WAYLAND-1', 'WAYLAND-2'):
                    if name not in names:
                        ctl('output', 'create', 'wayland', name)
                # Parent tiling otherwise resizes nested output windows behind
                # the test's back. Float only windows owned by this test process.
                clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], text=True))
                for client in clients:
                    if client.get('pid') == process.pid:
                        selector = json.dumps('address:' + client['address'])
                        subprocess.run(['hyprctl', 'eval', 'hl.dispatch(hl.dsp.window.float({window=' + selector + ',action="on"})); hl.dispatch(hl.dsp.window.resize({window=' + selector + ',x=1280,y=720}))'],
                                       check=True, capture_output=True, timeout=5)
                for index, name in enumerate(('WAYLAND-1', 'WAYLAND-2')):
                    ctl('eval', 'hl.monitor({output="' + name + '",mode="1280x720@60",position="' + str(index * 1280) + 'x0",scale=1,disabled=false})')
                time.sleep(.5)
                initial = display('list')
                assert all(d['connector'].startswith('WAYLAND-') for d in initial['displays'] if d['enabled']), initial
                outputs = [d for d in initial['displays'] if d['connector'].startswith('WAYLAND-')]
                assert len(outputs) == 2, initial
                if '--placement-only' in sys.argv:
                    # Physical PBP switches change modes without a position edit.
                    # Exercise the same transition with isolated virtual outputs.
                    full = '''hl.monitor({output="WAYLAND-1", mode="1280x720@60", position="0x0", scale=1})
hl.monitor({output="WAYLAND-2", mode="1280x720@60", position="1280x0", scale=1})
'''
                    monitors.write_text(full)
                    ctl('reload')
                    time.sleep(.5)
                    daemon = None
                    def start_watcher():
                        return subprocess.Popen([str(ROOT / 'bin/hypertile-displays'), 'watch'],
                                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    def stop_watcher():
                        if daemon and daemon.poll() is None:
                            daemon.terminate()
                            daemon.wait(timeout=5)
                    def settled(width, right):
                        deadline = time.monotonic() + 12
                        while time.monotonic() < deadline:
                            actual = {m['name']: m for m in json.loads(ctl('-j', 'monitors'))}
                            a, b = actual['WAYLAND-1'], actual['WAYLAND-2']
                            if (a['width'], b['width'], a['x'], b['x']) == (width, width, 0, right):
                                return
                            time.sleep(.2)
                        error = root / 'state/hypertile/displays/daemon-error.json'
                        raise AssertionError(('placement did not settle', actual,
                                              error.read_text() if error.exists() else 'no daemon error'))
                    try:
                        daemon = start_watcher()
                        journal = root / 'state/hypertile/displays/placement.json'
                        deadline = time.monotonic() + 10
                        while not journal.exists() and time.monotonic() < deadline:
                            time.sleep(.2)
                        assert journal.exists(), 'watcher did not capture the initial arrangement'
                        for width in (640, 1280, 640):
                            for name in ('WAYLAND-1', 'WAYLAND-2'):
                                ctl('eval', f'hl.monitor({{output="{name}",mode="{width}x720@60"}})')
                            settled(width, width)
                            assert monitors.read_text() == full, 'reflow must not write the configuration'
                        # Reload restores old coordinates with the new mode.
                        monitors.write_text(full.replace('1280x720', '640x720'))
                        ctl('reload')
                        settled(640, 640)
                        # Keep split geometry, stop the watcher, expand and restart.
                        document = dict(version=1, displays=display('list')['displays'], workspaces={})
                        pending = display('preview', '--json', json.dumps(document))
                        display('keep', pending['token'])
                        stop_watcher()
                        for name in ('WAYLAND-1', 'WAYLAND-2'):
                            ctl('eval', f'hl.monitor({{output="{name}",mode="1280x720@60"}})')
                        daemon = start_watcher()
                        settled(1280, 1280)
                        assert not ctl('configerrors').strip(), ctl('configerrors')
                        print('PASS: full/split/full placement, external mode preservation, reload and watcher restart', flush=True)
                    finally:
                        stop_watcher()
                    return
                if '--mode-safety-only' in sys.argv:
                    # Wayland outputs advertise no modes. Exercise real partial
                    # rules with a fixed mode, and reject unsupported selectors.
                    outputs[0]['scale'] = 2
                    document = dict(version=1, displays=outputs, workspaces={})
                    pending = display('preview', '--json', json.dumps(document))
                    display('keep', pending['token'])
                    assert monitors.read_text().count('mode="1280x720@60"') == 2
                    ctl('reload')
                    after = display('list')['displays']
                    assert after[0]['scale'] == 2, after
                    after[0]['scale'] = 1
                    pending = display('preview', '--json', json.dumps(dict(version=1, displays=after)))
                    display('revert', pending['token'])
                    assert display('list')['displays'][0]['scale'] == 2
                    after = display('list')['displays']
                    assert not after[0]['modes'], after
                    after[0]['mode_policy'] = 'highres'
                    source = monitors.read_text()
                    result = subprocess.run([str(ROOT / 'bin/hypertile-displays'), 'preview', '--json',
                                             json.dumps(dict(version=1, displays=after))],
                                            env=env, text=True, capture_output=True, timeout=10)
                    assert result.returncode != 0 and 'needs advertised modes' in result.stdout, result
                    assert not display('status')['pending'] and monitors.read_text() == source
                    assert not ctl('configerrors').strip()
                    print('PASS: native geometry updates preserve mode through Keep/reload/Revert; unsupported automatic selectors are rejected without mutation')
                    return
                if '--disable-only' in sys.argv:
                    applications = []
                    source, target = outputs
                    try:
                        for workspace in ('81', 'name:research', 'special:scratchpad'):
                            if workspace.startswith('special:'):
                                ctl('eval', 'hl.dispatch(hl.dsp.workspace.toggle_special("scratchpad"))')
                            else:
                                display('show-workspace', source['connector'], workspace)
                            applications.append(subprocess.Popen(
                                ['foot', '--app-id=hypertile-disable-test', 'sh', '-c', 'sleep 120'],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline:
                                if len(json.loads(ctl('-j', 'clients'))) == len(applications):
                                    break
                                time.sleep(.1)
                            else:
                                raise AssertionError('Disposable test windows did not appear')
                        ctl('eval', 'hl.dispatch(hl.dsp.workspace.toggle_special("scratchpad"))')
                        original = json.loads(ctl('-j', 'clients'))

                        def check_desktop(connector):
                            workspaces = json.loads(ctl('-j', 'workspaces'))
                            expected = {'81', 'research', 'special:scratchpad'}
                            assert {w['name'] for w in workspaces if w['name'] in expected and w['monitor'] == connector} == expected, workspaces
                            windows = json.loads(ctl('-j', 'clients'))
                            assert {(w['address'], w['workspace']['name']) for w in windows} == {
                                (w['address'], w['workspace']['name']) for w in original}, windows
                            monitor_id = next(m['id'] for m in json.loads(ctl('-j', 'monitors')) if m['name'] == connector)
                            assert all(w['monitor'] == monitor_id for w in windows), windows

                        check_desktop(source['connector'])
                        disabled = dict(version=1, displays=outputs,
                                        workspaces={'81': {'monitor': source['id'], 'layout': None}})
                        source['enabled'] = False
                        pending = display('preview', '--json', json.dumps(disabled))
                        check_desktop(target['connector'])
                        result = display('revert', pending['token'])
                        assert not result['errors'], result
                        check_desktop(source['connector'])
                        pending = display('preview', '--json', json.dumps(disabled))
                        display('keep', pending['token'])
                        check_desktop(target['connector'])
                        ctl('reload')
                        check_desktop(target['connector'])
                        assert not display('status')['pending']
                        assert display('list')['confirmed']['workspaces'] == disabled['workspaces']
                        print('PASS: disabling moves numbered, named and scratchpad workspaces with all windows; Revert restores them, Keep/reload preserves migration')
                        return
                    finally:
                        for app in applications:
                            app.terminate()
                            try:
                                app.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                app.kill()
                                app.wait()
                if '--removal-only' in sys.argv:
                    document = dict(version=1, displays=outputs, workspaces={})
                    pending = display('preview', '--json', json.dumps(document))
                    display('keep', pending['token'])
                    removed = next(d for d in outputs if d['connector'] == 'WAYLAND-2')
                    ctl('output', 'remove', removed['connector'])
                    # Reproduce a saved mirror rule whose absent source makes
                    # the compositor report an independent remaining output.
                    monitors.write_text(monitors.read_text().replace('output="WAYLAND-1",', 'output="WAYLAND-1",mirror="WAYLAND-2",'))
                    ctl('reload')
                    before = display('list')
                    live = next(d for d in before['displays'] if d['connected'])
                    assert not live['mirror_of'], live
                    result = display('remove-display', removed['id'])
                    assert result['removed'] == removed['id'] and 'token' not in result, result
                    after = display('list')
                    assert not after['pending'] and len(after['displays']) == len(after['confirmed']['displays']) == 1, after
                    for key in ('width', 'height', 'refresh', 'scale', 'transform', 'x', 'y'):
                        assert after['displays'][0][key] == live[key], key
                    assert 'mirror=""' in monitors.read_text()
                    assert 'output="WAYLAND-2"' not in monitors.read_text()
                    assert not ctl('configerrors').strip()
                    print('PASS: real CLI immediate removal of a disconnected profile and stale mirror rule; no pending preview, preserved native geometry and clean config reload')
                    return
                if '--handoff-only' in sys.argv:
                    applications = []
                    try:
                        for client in json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], text=True)):
                            if client.get('pid') == process.pid and client.get('title', '').endswith('WAYLAND-2'):
                                address = json.dumps('address:' + client['address'])
                                subprocess.run(['hyprctl', 'eval', 'hl.dispatch(hl.dsp.window.resize({window=' + address + ',x=960,y=540}))'],
                                               check=True, capture_output=True, timeout=5)
                        monitors.write_text(monitors.read_text().replace('output="WAYLAND-2",mode="1280x720@60"',
                                                                         'output="WAYLAND-2",mode="960x540@60"'))
                        ctl('reload')
                        time.sleep(.5)
                        mirror = dict(version=1, displays=display('list')['displays'], workspaces={})
                        source, target = mirror['displays']
                        assert target['width'] == 960 and target['height'] == 540, target
                        target['mirror_of'] = source['id']
                        pending = display('preview', '--json', json.dumps(mirror))
                        display('keep', pending['token'])
                        for workspace in ('81', '82', 'special:scratchpad'):
                            if workspace.startswith('special:'):
                                ctl('eval', 'hl.dispatch(hl.dsp.workspace.toggle_special("scratchpad"))')
                            else:
                                display('show-workspace', source['connector'], workspace)
                            app = subprocess.Popen(['foot', '--app-id=hypertile-handoff-test', 'sh', '-c', 'sleep 120'],
                                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            applications.append(app)
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline:
                                if len(json.loads(ctl('-j', 'clients'))) == len(applications):
                                    break
                                time.sleep(.1)
                            else:
                                raise AssertionError('Disposable test windows did not appear')
                        ctl('eval', 'hl.dispatch(hl.dsp.workspace.toggle_special("scratchpad"))')
                        display('show-workspace', source['connector'], '81')
                        original_windows = json.loads(ctl('-j', 'clients'))
                        focused = json.loads(ctl('-j', 'activewindow'))['address']
                        result = display('use-display', target['connector'])
                        assert result['previous_source'] == source['connector'], result
                        live = display('list')
                        assert not live['pending'], live
                        assert next(d for d in live['displays'] if d['connector'] == source['connector'])['mirror_connector'] == target['connector']
                        assert {(d['connector'], d['width'], d['height']) for d in live['displays']} == {
                            (source['connector'], 1280, 720), (target['connector'], 960, 540)}
                        assert all(w['monitor'] == target['connector'] for w in json.loads(ctl('-j', 'workspaces')) if w['id'] in (81, 82))
                        assert next(w for w in json.loads(ctl('-j', 'workspaces')) if w['name'] == 'special:scratchpad')['monitor'] == target['connector']
                        assert json.loads(ctl('-j', 'activewindow'))['address'] == focused
                        smaller = json.loads(ctl('-j', 'clients'))
                        assert {w['address'] for w in smaller} == {w['address'] for w in original_windows}
                        assert all(w['size'][0] <= 960 and w['size'][1] <= 540 for w in smaller), smaller
                        ctl('reload')
                        assert next(d for d in display('list')['displays'] if d['connector'] == source['connector'])['mirror_connector'] == target['connector']
                        result = display('use-display', 'next')
                        assert result['connector'] == source['connector'], result
                        assert json.loads(ctl('-j', 'activewindow'))['address'] == focused
                        assert all(w['monitor'] == source['connector'] for w in json.loads(ctl('-j', 'workspaces')) if w['id'] in (81, 82))
                        assert next(w for w in json.loads(ctl('-j', 'workspaces')) if w['name'] == 'special:scratchpad')['monitor'] == source['connector']
                        assert not display('status')['pending']
                        original_config = monitors.read_text()
                        for failure in ('raise', 'crash'):
                            script = '''import os, sys
sys.path.insert(0, sys.argv[1])
from service import Service
from adapter import DisplayError
service = Service()
service.PREVIEW_SECONDS = 1
def fail_save(plan, before_write=None):
    if sys.argv[3] == 'crash': os._exit(23)
    raise DisplayError('Injected handoff save failure')
service.configuration.commit = fail_save
try:
    service.use_display(sys.argv[2])
except DisplayError as error:
    assert 'Injected handoff' in str(error), error
'''
                            failed = subprocess.run([sys.executable, '-c', script, str(ROOT / 'displays'), target['connector'], failure],
                                                    env=env, capture_output=True, text=True, timeout=15)
                            assert failed.returncode == (23 if failure == 'crash' else 0), failed.stdout + failed.stderr
                            deadline = time.monotonic() + 8
                            while display('status')['pending'] and time.monotonic() < deadline:
                                time.sleep(.1)
                            restored = display('status')
                            assert not restored['pending'], restored
                            assert not restored['recovery']['errors'], restored['recovery']
                            assert monitors.read_text() == original_config
                            assert next(d for d in restored['displays'] if d['connector'] == target['connector'])['mirror_connector'] == source['connector']
                            assert all(w['monitor'] == source['connector'] for w in json.loads(ctl('-j', 'workspaces')) if w['id'] in (81, 82))
                            assert next(w for w in json.loads(ctl('-j', 'workspaces')) if w['name'] == 'special:scratchpad')['monitor'] == source['connector']
                            assert json.loads(ctl('-j', 'activewindow'))['address'] == focused
                        print('PASS: handoff save failure and independent watchdog after process crash restore topology, configuration, windows and focus')
                        print('PASS: immediate mirror source handoff at 1280×720 and 960×540, native modes, all windows/workspaces, focus, resize, saved reload and next/switch-back')
                        return
                    finally:
                        for app in applications:
                            app.terminate()
                            try:
                                app.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                app.kill()
                                app.wait()
                if '--workspace-only' in sys.argv:
                    before_show = display('list')['confirmed']
                    # Immediate Show creates, moves and selects workspaces without a saved preference.
                    display('show-workspace', 'WAYLAND-1', '81')
                    assert json.loads(ctl('-j', 'activeworkspace'))['id'] == 81
                    display('show-workspace', 'WAYLAND-2', '81')
                    active = json.loads(ctl('-j', 'activeworkspace'))
                    assert active['id'] == 81 and active['monitor'] == 'WAYLAND-2', active
                    display('show-workspace', 'WAYLAND-1', 'name:research')
                    active = json.loads(ctl('-j', 'activeworkspace'))
                    assert active['name'] == 'research' and active['monitor'] == 'WAYLAND-1', active
                    assert display('list')['confirmed'] == before_show, 'Show must not save placement'
                    print('PASS: isolated workspace creation, cross-monitor movement, named workspaces and unchanged saved preferences')
                    return
                document = dict(version=1, displays=outputs)
                # The scale written on Keep must be the one actually previewed,
                # including compositor normalization and a real config reload.
                scaled = copy.deepcopy(document)
                scaled['displays'][0]['scale'] = 1.4
                scaled['displays'][1]['x'] = 960
                pending = display('preview', '--json', json.dumps(scaled))
                display('keep', pending['token'])
                assert abs(display('status')['confirmed']['displays'][0]['scale'] - 4 / 3) < .000001
                assert 'scale = 1.4,' not in monitors.read_text()
                ctl('reload')
                assert abs(next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-1')['scale'] - 4 / 3) < .001
                pending = display('preview', '--json', json.dumps(document))
                display('keep', pending['token'])
                # Reverting a mirror enabled from Disabled must disable the
                # mirror again while retaining its independent source.
                disabled = copy.deepcopy(document)
                disabled['displays'][1]['enabled'] = False
                pending = display('preview', '--json', json.dumps(disabled))
                display('keep', pending['token'])
                mirror_from_disabled = dict(version=1, displays=display('list')['displays'], workspaces={})
                mirror_from_disabled['displays'][1].update(enabled=True, mirror_of=outputs[0]['id'])
                pending = display('preview', '--json', json.dumps(mirror_from_disabled))
                display('revert', pending['token'])
                restored = display('list')
                assert restored['displays'][0]['enabled'] and not restored['displays'][1]['enabled'], restored
                assert not restored['recovery']['errors'], restored['recovery']
                pending = display('preview', '--json', json.dumps(document))
                display('keep', pending['token'])
                # Geometry preview must not strand confirmation on a sleeping
                # destination after disabling the last awake screen.
                display('sleep', 'WAYLAND-2')
                asleep_destination = copy.deepcopy(document)
                asleep_destination['displays'][0]['enabled'] = False
                refused = subprocess.run([str(ROOT / 'bin/hypertile-displays'), 'preview', '--json', json.dumps(asleep_destination)],
                                         env=env, text=True, capture_output=True, timeout=25)
                assert refused.returncode != 0 and 'Wake an extended display' in refused.stdout, refused.stdout
                assert not display('status')['pending']
                display('wake', 'WAYLAND-2')
                print('PASS: normalized scale Keep/reload, disabled mirror rollback and sleeping destination protection')
                # Mirror preview, rollback to Extended, persistence, and explicit clear.
                mirrored = dict(version=1, displays=display('list')['displays'], workspaces={})
                source, target = mirrored['displays']
                target['mirror_of'] = source['id']
                pending = display('preview', '--json', json.dumps(mirrored))
                assert next(d for d in display('list')['displays'] if d['connector'] == target['connector'])['mirror_of'] == source['id']
                display('revert', pending['token'])
                assert not display('status')['recovery']['errors'], display('status')['recovery']
                pending = display('preview', '--json', json.dumps(mirrored))
                display('keep', pending['token'])
                assert 'mirror' in monitors.read_text()
                ctl('reload')
                assert next(d for d in display('list')['displays'] if d['connector'] == target['connector'])['mirror_of'] == source['id']
                extended = dict(version=1, displays=display('list')['displays'], workspaces={})
                extended['displays'][1].update(mirror_of=None, x=1280, y=0)
                pending = display('preview', '--json', json.dumps(extended))
                display('keep', pending['token'])
                assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == target['connector'])['mirrorOf'] == 'none'
                print('PASS: mirror preview, rollback, Keep, reload and return to Extended')
                # Retain current modes, test rotation, placement, readback and rollback.
                second = next(d for d in document['displays'] if d['connector'] == 'WAYLAND-2')
                second.update(x=1280, y=0, transform=1)
                response = display('preview', '--json', json.dumps(document))
                token = response.get('token', response.get('pending', {}).get('token'))
                assert token, response
                actual = json.loads(ctl('-j', 'monitors', 'all'))
                assert next(m for m in actual if m['name'] == 'WAYLAND-2')['transform'] == 1
                display('revert', token)
                actual = json.loads(ctl('-j', 'monitors', 'all'))
                assert next(m for m in actual if m['name'] == 'WAYLAND-2')['transform'] == 0
                assert not display('status').get('pending')
                assert not display('status')['recovery']['errors'], display('status')['recovery']
                # Exercise the real Lua dispatch API, including named selectors.
                assignment = copy.deepcopy(document)
                original_workspaces = json.loads(ctl('-j', 'workspaces'))
                workspace = next(w for w in original_workspaces if w['monitor'] == 'WAYLAND-1')
                assignment['workspaces'] = {str(workspace['id']): {'monitor': 'connector:WAYLAND-2'}}
                pending = display('preview', '--json', json.dumps(assignment))
                moved = next(w for w in json.loads(ctl('-j', 'workspaces')) if w['id'] == workspace['id'])
                assert moved['monitor'] == 'WAYLAND-2', moved
                display('revert', pending['token'])
                restored = next(w for w in json.loads(ctl('-j', 'workspaces')) if w['id'] == workspace['id'])
                assert restored['monitor'] == 'WAYLAND-1', restored
                assert not display('status')['recovery']['errors'], display('status')['recovery']
                # Policy uses the live Lua layout value, including an empty
                # workspace (Hyprland JSON can retain its cached tiledLayout).
                def layout_ctl(*args):
                    result = subprocess.run([str(ROOT / 'bin/hypertile-ctl'), *args], env=env,
                                            text=True, capture_output=True, timeout=10)
                    assert result.returncode == 0, result.stdout + result.stderr
                    return result.stdout

                def live_workspace(key):
                    return next(w for w in json.loads(layout_ctl('workspaces', '--json'))['workspaces']
                                if w.get('selector') == key)

                ctl('eval', 'hl.dispatch(hl.dsp.focus({workspace="97"}))')
                inherited = copy.deepcopy(document)
                inherited['displays'][0]['default_layout'] = 'dwindle'
                inherited['displays'][1]['default_layout'] = 'master'
                inherited['workspaces'] = {'97': {'monitor': 'connector:WAYLAND-2', 'layout': None}}
                pending = display('preview', '--json', json.dumps(inherited))
                assert live_workspace('97')['layout'] == 'master', live_workspace('97')
                display('keep', pending['token'])
                assert live_workspace('97')['layout_source'] == 'monitor'
                # A choice through the existing CLI becomes explicit and follows
                # the workspace even when the monitor default differs.
                layout_ctl('apply', 'dwindle', '--workspace', '97', '--quiet')
                assert live_workspace('97')['layout_source'] == 'explicit'
                ctl('eval', 'hl.dispatch(hl.dsp.workspace.move({workspace="97",monitor="WAYLAND-1"}))')
                assert live_workspace('97')['layout'] == 'dwindle'
                layout_ctl('apply', 'monitor-default', '--workspace', '97', '--quiet')
                assert live_workspace('97')['layout_source'] == 'monitor'
                # Preference applies to a named workspace created after Keep.
                future = copy.deepcopy(inherited)
                future['workspaces']['name:future'] = {'monitor': 'connector:WAYLAND-2', 'layout': None}
                pending = display('preview', '--json', json.dumps(future))
                display('keep', pending['token'])
                policy_daemon = subprocess.Popen([str(ROOT / 'bin/hypertile-displays'), 'daemon'], env=env,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    time.sleep(.5)
                    ctl('eval', 'hl.dispatch(hl.dsp.focus({monitor="WAYLAND-1"})); hl.dispatch(hl.dsp.focus({workspace="name:future"}))')
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        value = live_workspace('name:future')
                        if value['monitor'] == 'WAYLAND-2' and value['layout'] == 'master':
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError('Future named workspace did not inherit its assigned monitor: ' + repr(value))
                    assert json.loads(ctl('-j', 'activeworkspace'))['name'] == 'future'
                    # A user move after assignment stays put; policy is not a pin.
                    ctl('eval', 'hl.dispatch(hl.dsp.workspace.move({workspace="name:future",monitor="WAYLAND-1"}))')
                    time.sleep(1)
                    assert live_workspace('name:future')['monitor'] == 'WAYLAND-1'
                    assert live_workspace('name:future')['layout'] == 'dwindle'
                finally:
                    policy_daemon.terminate()
                    policy_daemon.wait(timeout=5)
                before_power = [(w['id'], w['monitor']) for w in json.loads(ctl('-j', 'workspaces'))]
                display('sleep', 'WAYLAND-2')
                assert not next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['dpmsStatus']
                display('wake', 'WAYLAND-2')
                assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['dpmsStatus']
                assert [(w['id'], w['monitor']) for w in json.loads(ctl('-j', 'workspaces'))] == before_power
                # Keep, reload, and restart share exactly the production CLI path.
                document['displays'] = display('list')['displays']
                document['displays'][1]['transform'] = 1
                response = display('preview', '--json', json.dumps(document))
                display('keep', response['token'])
                assert display('status')['confirmed']['displays'][1]['transform'] == 1
                assert 'transform' in monitors.read_text()
                assert display('status')['confirmed']['configuration_backed']
                ctl('reload')
                display('restore')
                assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['transform'] == 1, display('status')
                daemon = subprocess.Popen([str(ROOT / 'bin/hypertile-displays'), 'daemon'], env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    time.sleep(.5)
                    ctl('reload')
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        actual = json.loads(ctl('-j', 'monitors', 'all'))
                        if next(m for m in actual if m['name'] == 'WAYLAND-2')['transform'] == 1:
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError('Daemon did not restore confirmed rotation after reload')
                    # A manual config edit wins even with the watcher running.
                    saved_source = monitors.read_text()
                    monitors.write_text(saved_source.replace('transform = 1', 'transform = 0'))
                    ctl('reload')
                    time.sleep(1)
                    assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['transform'] == 0
                    monitors.write_text(saved_source)
                    ctl('reload')
                    time.sleep(.5)
                    # A SIGKILL cannot strand a preview: the independent process owns timeout.
                    transient = copy.deepcopy(document)
                    transient['displays'][1]['transform'] = 0
                    transient['displays'][1]['mirror_of'] = transient['displays'][0]['id']
                    pending = display('preview', '--json', json.dumps(transient))
                    daemon.kill()
                    daemon.wait(timeout=5)
                    applying = display('status')['pending']
                    assert applying['token'] == pending['token']
                    deadline = time.monotonic() + 18
                    while time.monotonic() < deadline and display('status')['pending']:
                        time.sleep(.25)
                    assert not display('status')['pending'], 'Watchdog did not recover after daemon SIGKILL'
                    assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['transform'] == 1, (display('status'), applying['expected'])
                    assert display('status')['confirmed']['displays'][1]['transform'] == 1
                finally:
                    if daemon.poll() is None:
                        daemon.terminate()
                        daemon.wait(timeout=5)
                # Recover a pending operation at startup before replaying saved intent.
                pending = display('preview', '--json', json.dumps(transient))
                display('restore')
                assert not display('status')['pending']
                assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['transform'] == 1, display('status')
                # Recreate a confirmed disabled output. The Wayland backend
                # advertises no modes; Hyprland may retain the old monitor's
                # dimensions until a compositor restart (zero-mode startup is
                # covered by the transaction unit suite).
                cold = dict(version=1, displays=display('list')['displays'], workspaces={})
                cold['displays'][1]['enabled'] = False
                pending = display('preview', '--json', json.dumps(cold))
                display('keep', pending['token'])
                ctl('output', 'remove', 'WAYLAND-2')
                ctl('output', 'create', 'wayland', 'WAYLAND-2')
                time.sleep(.3)
                raw = next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')
                assert raw['disabled'] and not raw['availableModes'], raw
                cold = dict(version=1, displays=display('list')['displays'], workspaces={})
                target = next(d for d in cold['displays'] if d['connector'] == 'WAYLAND-2')
                assert target['width'] == 1280 and target['height'] == 720, target
                target['enabled'] = True
                pending = display('preview', '--json', json.dumps(cold))
                display('keep', pending['token'])
                assert not next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['disabled']
                print('PASS: disabled output reconnect and re-enable without advertised modes')
                # Physically remove the nested source during preview; recovery must
                # leave the remaining output usable without persisting the preview.
                pending = display('preview', '--json', json.dumps(transient))
                ctl('output', 'remove', 'WAYLAND-1')
                time.sleep(.3)
                display('revert', pending['token'])
                remaining = display('list')
                assert not remaining['pending']
                assert any(d['connected'] and d['enabled'] and not d.get('mirror_of') for d in remaining['displays']), remaining
                print('PASS: mirror watchdog and source removal recovery')
                print('PASS: isolated two-display rotation, power, placement, inherited/explicit layouts, future named workspaces, Keep, reload, startup recovery, independent watchdog after daemon SIGKILL')
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-8000:], file=sys.stderr)
                for detail in runtime.glob('hypr/*/hyprland.log'):
                    print('\n'.join(line for line in detail.read_text().splitlines() if 'ERR' in line or 'WARN' in line)[-4000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
