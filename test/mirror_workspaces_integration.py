#!/usr/bin/env python3
"""Mirror reconnect workspace regression in an isolated nested compositor.

--expect-bug proves the original failure; --rescue additionally verifies the
Hypertile safety net on that binary. Default expects the corrected compositor.
Only disposable outputs, a private runtime/config, and one test client are used.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', default='Hyprland')
    parser.add_argument('--expect-bug', action='store_true')
    parser.add_argument('--rescue', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ht-mo-') as directory:
        root = Path(directory)
        (root / 'cache').mkdir()
        control_plugin = root / 'virtual-output-control.so'
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'hyprland'], text=True))
        subprocess.run(['g++', '-std=c++23', '-shared', '-fPIC', '-O2', *flags,
                        str(ROOT / 'docs/diagnostics/mirror-disconnect/virtual-output-control.cpp'),
                        '-o', str(control_plugin)], check=True)
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
                   XDG_CONFIG_HOME=str(root / 'c'), XDG_STATE_HOME=str(root / 's'), XDG_CACHE_HOME=str(root / 'cache'), HYPERTILE_SRC=str(ROOT),
                   HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', HYPERTILE_MIRROR_TEST='1')
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

                def create_output(name, backend='wayland'):
                    ctl('output', 'create', backend, name)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if name in state():
                            return
                        time.sleep(.05)
                    raise AssertionError(('output was not created', name, state()))

                def control(action, *names):
                    reply = ctl('--batch', ' '.join(('hypertile-test', action, *names))).strip()
                    assert reply == 'ok', (action, names, reply)

                def remove_output(*names):
                    control('remove', *names)
                    current = state()
                    assert not set(names).intersection(current), ('outputs were not removed', names, current)

                def assert_client_placed():
                    live = {d['id'] for d in state().values() if not d['disabled'] and d['mirrorOf'] == 'none'}
                    client = next(c for c in json.loads(ctl('-j', 'clients')) if c['address'] == address)
                    assert client['monitor'] in live, ('client stranded on removed output', client['monitor'], live)

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
                    create_output('WAYLAND-2')
                loaded = ctl('plugin', 'load', str(control_plugin))
                assert any(p['name'] == 'hypertile-virtual-output-control'
                           for p in json.loads(ctl('-j', 'plugin', 'list'))), loaded
                # Parent tiling can resize nested output windows; float only ours.
                def float_outputs(count=2):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], text=True))
                        owned = [c for c in clients if c.get('pid') == process.pid]
                        if len(owned) >= count:
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
                # Model the mirror becoming the sole desktop while the source
                # disappears, then reconnecting under its saved mirror rule.
                ctl('eval', 'hl.monitor({output="WAYLAND-2",mirror="",position="1280x0"})')
                time.sleep(.3)
                ctl('eval', 'hl.dispatch(hl.dsp.workspace.move({workspace="1",monitor="WAYLAND-2"}));hl.dispatch(hl.dsp.focus({workspace="1"}))')
                remove_output('WAYLAND-2')
                ctl('reload')
                ctl('eval', initial.splitlines()[0])
                create_output('WAYLAND-2', 'headless')
                time.sleep(.2)
                current = state()
                workspaces = json.loads(ctl('-j', 'workspaces'))
                ws = next(w for w in workspaces if w['id'] == 1)
                print('RECONNECTED:', json.dumps({n: {k:d[k] for k in ('id','mirrorOf','activeWorkspace')} for n,d in current.items()}), flush=True)
                print('WORKSPACE:', json.dumps(ws), flush=True)
                assert current['WAYLAND-2']['mirrorOf'] != 'none', current
                client = next(c for c in json.loads(ctl('-j','clients')) if c['address'] == address)
                if args.expect_bug or args.rescue:
                    assert ws['monitor'] == 'WAYLAND-2', ('bug did not reproduce', ws)
                    assert client['monitor'] == current['WAYLAND-2']['id'], client
                    ctl('eval', 'hl.dispatch(hl.dsp.focus({workspace="1"}))')
                    assert state()['WAYLAND-1']['activeWorkspace']['id'] != 1
                    print('PASS: original reconnect strands workspace and client; normal switching fails', flush=True)
                    if args.rescue:
                        code = """
import copy,json,sys
sys.path.insert(0,sys.argv[1])
from adapter import Adapter
from policy import WorkspacePolicy
adapter=Adapter()
policy=WorkspacePolicy(adapter)
policy._ctl=lambda *args,**kwargs: 'dwindle' if args[0]=='default' else ''
policy._scenes=lambda: {}
document={'version':1,'displays':adapter.displays(),'workspaces':{'1':{'layout':'dwindle'}}}
original=copy.deepcopy(document)
result=policy.reconcile(document,'reconnect')
assert result['moves']==[{'workspace':'1','monitor':'WAYLAND-1'}], result
assert document==original
assert not policy.reconcile(document,'event')['moves']
print('PASS: Hypertile rescues unassigned workspace once without changing saved intent')
"""
                        print(run(sys.executable, '-c', code, str(ROOT / 'displays')).stdout, end='', flush=True)
                        assert_client_placed()
                else:
                    assert ws['monitor'] == 'WAYLAND-1', ('workspace stranded', ws)
                    assert current['WAYLAND-2']['activeWorkspace']['id'] == 0, current
                    assert_client_placed()
                    print('PASS: corrected mirror reconnect keeps workspace and client on source', flush=True)
                if not args.expect_bug or args.rescue:
                    ctl('eval', 'hl.dispatch(hl.dsp.focus({workspace="1"}))')
                    assert state()['WAYLAND-1']['activeWorkspace']['id'] == 1
                    live = next(c for c in json.loads(ctl('-j','clients')) if c['address'] == address)
                    assert live['workspace']['id'] == 1
                    assert next(w for w in json.loads(ctl('-j','workspaces')) if w['id'] == 1)['tiledLayout'] == 'dwindle'
                    print('PASS: normal workspace switching restored; same client and layout preserved', flush=True)
                # A connector returning as independent still gets its remembered
                # workspace. The guard must not disable ordinary recovery.
                extended = initial.replace('mirror="WAYLAND-1"', 'mirror=""')
                monitors.write_text(extended)
                ctl('reload')
                time.sleep(.3)
                ctl('eval', 'hl.dispatch(hl.dsp.workspace.move({workspace="1",monitor="WAYLAND-2"}));hl.dispatch(hl.dsp.focus({workspace="1"}))')
                assert state()['WAYLAND-2']['mirrorOf'] == 'none'
                assert state()['WAYLAND-2']['activeWorkspace']['id'] == 1, state()
                # This replacement is headless, so use the native removal API
                # after promotion. The test plugin removes only Wayland outputs.
                ctl('output', 'remove', 'WAYLAND-2')
                assert 'WAYLAND-2' not in state()
                ctl('reload')
                ctl('eval', extended.splitlines()[0])
                create_output('WAYLAND-2', 'headless')
                time.sleep(.2)
                ws = next(w for w in json.loads(ctl('-j','workspaces')) if w['id'] == 1)
                assert state()['WAYLAND-2']['mirrorOf'] == 'none'
                assert ws['monitor'] == 'WAYLAND-2', ws
                assert_client_placed()
                print('PASS: independent reconnect still restores remembered workspace', flush=True)

            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-5000:], file=sys.stderr)
                for path in runtime.glob('hypr/*/hyprland.log'):
                    print(path.read_text(errors='replace')[-5000:], file=sys.stderr)
                for path in (root / 'cache/hyprland').glob('hyprlandCrashReport*'):
                    print(path.read_text(errors='replace')[:4000], file=sys.stderr)
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
