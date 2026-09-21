"""Exercise native dragging against installed Hyprland in a temporary nested session.

Run from a Wayland desktop: python3 test/drag_integration.py.
Requires Hyprland, hyprctl, foot and wtype. Creates two disposable windows.
The mouse binding callback is mapped to F12 so wtype can exercise real press
and release dispatcher context without access to physical input devices.
The shell is stubbed; highlight assertions check its runtime data source.
"""
import os, json, subprocess, time, tempfile, pathlib, shutil
ROOT = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ht-drag-') as directory:
    root = pathlib.Path(directory)
    runtime = root / 'r'
    runtime.mkdir(mode=448)
    config = root / 'config' / 'hypr'
    config.mkdir(parents=True)
    for src in ROOT.glob('hypertile*.lua'):
        shutil.copy(src, config / src.name)
    entry = config / 'hyprland.lua'
    entry.write_text('package.path = os.getenv("XDG_CONFIG_HOME") .. "/?.lua;" .. package.path\nhl.config({general={layout="lua:dragtest"}, animations={enabled=false}, xwayland={enabled=false}})\nhl.monitor({output="", mode="1280x720@60", position="auto", scale=1})\nhl.device({name="hl-virtual-keyboard-wtype", keybinds=true, resolve_binds_by_sym=true})\nlocal e = require("hypr.hypertile")\ne.layout("dragtest", {columns={{name="a"},{name="b"}}, empty="collapse",single="collapse"})\no = {bind=function(keys, desc, callback, options)\n if keys == "SUPER + mouse:272" then keys = "F12"\n elseif keys == "mouse:272" then keys = "F12" end\n hl.bind(keys, callback, options)\nend}\nhl.exec_cmd = function() end -- No shell or notifications in the isolated test.\nrequire("hypr.hypertile-navigation").bind()\n')
    parent = pathlib.Path(os.environ['WAYLAND_DISPLAY'])
    if not parent.is_absolute():
        parent = pathlib.Path(os.environ['XDG_RUNTIME_DIR']) / parent
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'), HYPRLAND_HEADLESS_ONLY='1', HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', WAYLAND_DISPLAY=str(parent))
    for key in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET'):
        env.pop(key, None)
    children = []
    with (root / 'log').open('w+') as log:
        compositor = subprocess.Popen(['Hyprland', '--config', str(entry)], env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    instances = json.loads(subprocess.check_output(['hyprctl', 'instances', '-j'], env=env))
                except ValueError:
                    instances = []
                matches = [i for i in instances if i['pid'] == compositor.pid]
                if matches and (runtime / 'hypr' / matches[0]['instance'] / '.socket.sock').exists():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('compositor startup failed')
            env['HYPRLAND_INSTANCE_SIGNATURE'] = matches[0]['instance']
            env['WAYLAND_DISPLAY'] = matches[0]['wl_socket']

            def ctl(*args):
                return subprocess.check_output(['hyprctl', *args], env=env, text=True).strip()

            def clients():
                return json.loads(ctl('clients', '-j'))
            assert not ctl('configerrors'), ctl('configerrors')
            for name in ['drag-a', 'drag-b']:
                children.append(subprocess.Popen(['foot', '--app-id', name, 'sh', '-c', 'sleep 120'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            for _ in range(80):
                if len(clients()) == 2:
                    break
                time.sleep(0.1)
            before = sorted(clients(), key=lambda w: w['at'][0])
            print('before', [(w['address'], w['at'], w['size']) for w in before], flush=True)
            a, b = before
            x, y = a['at']
            sx, sy = a['size']
            print(ctl('eval', f'hl.dispatch(hl.dsp.cursor.move({{x={x + sx // 2}, y={y + sy // 2}}}))'))
            key = subprocess.Popen(['wtype', '-P', 'F12', '-s', '2500', '-p', 'F12'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            children.append(key)
            time.sleep(0.4)
            print('press', [(w['address'], w['floating'], w['at']) for w in clients()], flush=True)
            x, y = b['at']
            sx, sy = b['size']
            print(ctl('eval', f'hl.dispatch(hl.dsp.cursor.move({{x={x + sx // 2}, y={y + sy // 2}}}))'))
            time.sleep(0.3)
            mid = {w['address']: w for w in clients()}
            print('drag', [(w['address'], w['floating'], w['at']) for w in clients()], flush=True)
            assert mid[a['address']]['floating'], 'native drag did not start'
            assert mid[b['address']]['at'] == b['at'] and mid[b['address']]['size'] == b['size'], 'neighbor moved during drag'
            drag = json.loads((runtime / 'hypertile-tile-drag.json').read_text())
            print('highlight', drag, flush=True)
            assert drag['active'] and drag['zone'] == 'b', 'destination not highlighted'
            key.communicate(timeout=5)
            time.sleep(0.4)
            after = {w['address']: w for w in clients()}
            print('after', [(w['address'], w['floating'], w['at']) for w in clients()], flush=True)
            assert after[a['address']]['at'] == b['at'] and after[b['address']]['at'] == a['at'], 'release did not swap'
            assert not json.loads((runtime / 'hypertile-tile-drag.json').read_text())['active']
            print('PASS installed-compositor drag, neighbor stability, highlight, release swap', flush=True)
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
            compositor.terminate()
            compositor.wait(timeout=10)
            log.seek(0)
            lines = log.read().splitlines()
            print('\n'.join((l for l in lines if 'error' in l.lower() or 'hypertile' in l.lower()))[-4000:])
