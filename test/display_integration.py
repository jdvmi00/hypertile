"""Opt-in real Hyprland adapter smoke in an isolated compositor.

Run from a Wayland session: python3 test/display_integration.py.
Use --workspace-only for immediate workspace switching without mode changes.
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
                    assert result.returncode == 0, result.stdout + result.stderr
                    return result.stdout

                def display(*args, input=None):
                    result = subprocess.run([str(ROOT / 'bin/hypertile-displays'), *args], input=input,
                                            env=env, text=True, capture_output=True, timeout=25)
                    assert result.returncode == 0, result.stdout + result.stderr
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
                    assert display('status')['pending']['token'] == pending['token']
                    deadline = time.monotonic() + 18
                    while time.monotonic() < deadline and display('status')['pending']:
                        time.sleep(.25)
                    assert not display('status')['pending'], 'Watchdog did not recover after daemon SIGKILL'
                    assert next(m for m in json.loads(ctl('-j', 'monitors', 'all')) if m['name'] == 'WAYLAND-2')['transform'] == 1, display('status')
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
