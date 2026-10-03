#!/usr/bin/env python3
"""Isolated mirror-output regression. Requires a live Wayland parent.

Default: verify Hypertile rejects the bug on the installed, unpatched compositor.
--fixed --binary PATH: verify promotion/reconnect and guarded transactions succeed.
Only nested WAYLAND-* outputs and private config/state are modified.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', default='Hyprland')
    parser.add_argument('--fixed', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ht-mo-') as directory:
        root = Path(directory)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        config = root / 'c/hypr'
        config.mkdir(parents=True)
        entry = config / 'hyprland.lua'
        entry.write_text('package.path=os.getenv("XDG_CONFIG_HOME").."/?.lua;"..package.path\n'
                         'require("hypr.monitors")\nhl.config({animations={enabled=false},xwayland={enabled=false}})\n')
        (config / 'looknfeel.lua').write_text('hl.config({general={layout="dwindle"}})\n')
        monitors = config / 'monitors.lua'
        initial = ('hl.monitor({output="WAYLAND-1",mode="1280x720@60",position="0x0",scale=1,disabled=false,mirror=""})\n'
                   'hl.monitor({output="WAYLAND-2",mode="1280x720@60",position="1280x0",scale=1,disabled=false,mirror="WAYLAND-1"})\n')
        monitors.write_text(initial)
        parent = Path(os.environ['WAYLAND_DISPLAY'])
        if not parent.is_absolute():
            parent = Path(os.environ['XDG_RUNTIME_DIR']) / parent
        env = dict(os.environ, WAYLAND_DISPLAY=str(parent), XDG_RUNTIME_DIR=str(runtime),
                   XDG_CONFIG_HOME=str(root / 'c'), XDG_STATE_HOME=str(root / 's'), HYPERTILE_SRC=str(ROOT),
                   HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1')
        for key in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET', 'WAYLAND_SOCKET'):
            env.pop(key, None)
        app = None
        with (root / 'log').open('w+') as log:
            process = subprocess.Popen([args.binary, '--config', str(entry)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    result = subprocess.run(['hyprctl', '-j', 'instances'], env=env, capture_output=True, text=True, timeout=3)
                    try:
                        instances = [i for i in json.loads(result.stdout) if i['pid'] == process.pid]
                    except ValueError:
                        instances = []
                    if instances and (runtime / 'hypr' / instances[0]['instance'] / '.socket.sock').exists():
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('Nested compositor did not start')
                env.update(HYPRLAND_INSTANCE_SIGNATURE=instances[0]['instance'], WAYLAND_DISPLAY=instances[0]['wl_socket'])

                def run(*command, check=True):
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=25)
                    if check:
                        assert result.returncode == 0, (command, result.stdout, result.stderr)
                    return result

                def ctl(*command):
                    return run('hyprctl', *command).stdout

                def state():
                    return {d['name']: d for d in json.loads(ctl('-j', 'monitors', 'all'))}

                def outputs():
                    code = 'import sys,json;sys.path.insert(0,sys.argv[1]);from wayland import outputs;print(json.dumps(sorted(outputs())))'
                    return set(json.loads(run(sys.executable, '-c', code, str(ROOT / 'displays')).stdout))

                def wait_outputs(expected):
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        actual = outputs()
                        if actual == expected:
                            return
                        time.sleep(.1)
                    raise AssertionError(('outputs', expected, actual, state()))

                if 'WAYLAND-2' not in state():
                    ctl('output', 'create', 'wayland', 'WAYLAND-2')
                # Parent tiling can resize nested output windows; float only ours.
                def float_outputs():
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], text=True))
                        owned = [c for c in clients if c.get('pid') == process.pid]
                        if len(owned) >= 2:
                            break
                        time.sleep(.05)
                    else:
                        raise AssertionError('Nested output windows did not map')
                    for client in owned:
                        target = json.dumps('address:' + client['address'])
                        subprocess.run(['hyprctl', 'eval', f'hl.dispatch(hl.dsp.window.float({{window={target},action="on"}}));'
                                        f'hl.dispatch(hl.dsp.window.resize({{window={target},x=1280,y=720}}))'],
                                       check=True, capture_output=True, timeout=5)
                float_outputs()
                time.sleep(.5)
                # The host can resize the first frames while tiling the nested
                # windows. Reapply the test modes after floating them, including
                # the initially mirrored output whose readback can lag its host.
                for _ in range(2):
                    ctl('eval', initial)
                    time.sleep(.3)
                wait_outputs({'WAYLAND-1'})
                app = subprocess.Popen(['foot', '--app-id=hypertile-mirror-test', 'sleep', '300'], env=env, stdout=log, stderr=log)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    clients = json.loads(ctl('-j', 'clients'))
                    if clients:
                        break
                    time.sleep(.1)
                assert len(clients) == 1, clients
                address = clients[0]['address']
                before = json.loads(ctl('-j', 'workspaces'))
                command = [str(ROOT / 'bin/hypertile-displays'), 'use-display', 'WAYLAND-2']
                result = run(*command, check=args.fixed)
                if not args.fixed:
                    assert result.returncode != 0 and 'available to desktop apps' in result.stdout, result.stdout + result.stderr
                    wait_outputs({'WAYLAND-1'})
                    current = state()
                    assert current['WAYLAND-1']['mirrorOf'] == 'none', current
                    assert current['WAYLAND-2']['mirrorOf'] != 'none', current
                    assert monitors.read_text() == initial
                    assert not (root / 's/hypertile/displays/pending.json').exists()
                    after = json.loads(ctl('-j', 'workspaces'))
                    assert [(w['id'], w['monitor']) for w in after] == [(w['id'], w['monitor']) for w in before]
                    print('PASS: unpatched mirror promotion refused; source, app, workspaces and config preserved', flush=True)
                    # Demonstrate why a geometry-only success was unsafe.
                    for _ in range(2):
                        ctl('eval', 'hl.monitor({output="WAYLAND-2",mirror="",position="1280x0"})')
                        time.sleep(.2)
                    assert state()['WAYLAND-2']['mirrorOf'] == 'none'
                    wait_outputs({'WAYLAND-1'})
                    ctl('eval', 'hl.monitor({output="WAYLAND-1",mirror="WAYLAND-2"})')
                    wait_outputs(set())
                    print('PASS: direct unguarded handoff reproduces zero wl_output globals', flush=True)
                else:
                    wait_outputs({'WAYLAND-2'})
                    for target in ['WAYLAND-1', 'WAYLAND-2'] * 3:
                        run(str(ROOT / 'bin/hypertile-displays'), 'use-display', target)
                        wait_outputs({target})
                        ctl('reload')
                        wait_outputs({target})
                    # Reconnect as a mirror, then promote it again.
                    ctl('output', 'remove', 'WAYLAND-1')
                    ctl('output', 'create', 'wayland', 'WAYLAND-1')
                    float_outputs()
                    time.sleep(.5)
                    wait_outputs({'WAYLAND-2'})
                    run(str(ROOT / 'bin/hypertile-displays'), 'use-display', 'WAYLAND-1')
                    wait_outputs({'WAYLAND-1'})
                    print('PASS: fixed startup mirror, repeated guarded handoffs, saved reload, mirrored reconnect and promotion', flush=True)
                assert any(c['address'] == address for c in json.loads(ctl('-j', 'clients')))
                assert app.poll() is None, 'existing client disconnected'
                assert not ctl('configerrors').strip()
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-5000:], file=sys.stderr)
                raise
            finally:
                for child in (app, process):
                    if child and child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()


if __name__ == '__main__':
    main()
