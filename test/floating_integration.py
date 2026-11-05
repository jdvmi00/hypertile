"""Window size and placement on Omarchy's floating workspaces, nested Hyprland.

Run from a Wayland desktop on Omarchy: python3 test/floating_integration.py.
Requires Hyprland, hyprctl, foot, lua and /usr/share/omarchy.
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMARCHY = pathlib.Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy'))

ENTRY = '''
dofile(os.getenv("OMARCHY_PATH") .. "/default/hypr/bootstrap.lua")
package.path = os.getenv("XDG_CONFIG_HOME") .. "/?.lua;" .. package.path
hl.config({ animations = { enabled = false }, xwayland = { enabled = false } })
hl.monitor({ output = "", mode = "1280x720@60", position = "0x0", scale = 1 })
require("default.hypr.helpers")
require("hypr.hypertile-layouts")
require("default.hypr.apps.browser")
require("default.hypr.workspace-layouts")
'''


def main():
    if not (OMARCHY / 'default/hypr/workspace-modes.lua').exists():
        print('SKIP: no Omarchy workspace modes at ' + str(OMARCHY))
        return 0
    failures = []

    def check(condition, message):
        print(('ok    ' if condition else 'FAIL  ') + message)
        if not condition:
            failures.append(message)

    with tempfile.TemporaryDirectory(prefix='ht-fl-') as directory:
        root = pathlib.Path(directory)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        hypr = root / 'config' / 'hypr'
        (hypr / 'layouts').mkdir(parents=True)
        for src in ROOT.glob('hypertile*.lua'):
            shutil.copy(src, hypr / src.name)
        (hypr / 'hyprland.lua').write_text(ENTRY)
        modes = root / 'state' / 'omarchy' / 'workspace-layouts'
        modes.mkdir(parents=True)
        (modes / '2.lua').write_text('o.workspace_mode({ workspace = "2", mode = "floating" })\n')
        saved = root / 'state' / 'hypertile' / 'floating-size.json'
        shell = root / 'fake-shell'
        shell.write_text('#!/bin/sh\nexit 0\n')
        shell.chmod(0o755)

        parent = pathlib.Path(os.environ['WAYLAND_DISPLAY'])
        if not parent.is_absolute():
            parent = pathlib.Path(os.environ['XDG_RUNTIME_DIR']) / parent
        env = dict(os.environ, HOME=str(root), XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(root / 'config'),
                   XDG_STATE_HOME=str(root / 'state'), OMARCHY_PATH=str(OMARCHY), HYPERTILE_SHELL_BIN=str(shell),
                   HYPERTILE_SRC=str(ROOT), HYPRLAND_HEADLESS_ONLY='1', HYPRLAND_NO_SD_VARS='1',
                   HYPRLAND_NO_SD_NOTIFY='1', WAYLAND_DISPLAY=str(parent))
        for key in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET', 'HYPERTILE_RULES_DIR',
                    'HYPERTILE_LAYOUTS_DIR', 'HYPERTILE_HYPRCTL_BIN', 'HYPERTILE_DISPLAYS_PATH'):
            env.pop(key, None)
        children = []
        with (root / 'hyprland.log').open('w+') as log:
            compositor = subprocess.Popen(['Hyprland', '--config', str(hypr / 'hyprland.lua')], env=env, stdout=log, stderr=log)
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
                    return subprocess.run(['hyprctl', *args], env=env, text=True, capture_output=True).stdout.strip()

                def hypertile(*args):
                    result = subprocess.run(['lua', str(ROOT / 'bin/hypertile-ctl'), *args], env=env, text=True, capture_output=True)
                    return result.stdout.strip() if result.returncode == 0 else 'error: ' + result.stderr.strip()

                def clients():
                    return json.loads(ctl('clients', '-j'))

                def windows(ws):
                    return [c for c in clients() if c['workspace']['id'] == ws]

                def window(address):
                    return next((c for c in clients() if c['address'] == address), {})

                def box(address):
                    found = window(address)
                    return tuple(found.get('at', [])) + tuple(found.get('size', []))

                def wait(predicate, seconds=6):
                    end = time.time() + seconds
                    while time.time() < end:
                        if predicate():
                            return True
                        time.sleep(0.1)
                    return predicate()

                def settled():
                    time.sleep(1.2)
                    wait(lambda: ctl('eval', 'return 1') == 'ok')

                def focus_workspace(ws):
                    ctl('eval', f"hl.dispatch(hl.dsp.focus({{ workspace = '{ws}' }}))")

                def spawn(ws, app_id=None):
                    focus_workspace(ws)
                    before = {c['address'] for c in windows(ws)}
                    children.append(subprocess.Popen(['foot', '--app-id', app_id or f'floating-{ws}', 'sh', '-c', 'sleep 300'], env=env,
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    wait(lambda: any(c['address'] not in before for c in windows(ws)))
                    time.sleep(0.4)
                    return next(c['address'] for c in windows(ws) if c['address'] not in before)

                def dispatch(action):
                    ctl('eval', f'hl.dispatch(hl.dsp.window.{action})')
                    time.sleep(0.3)

                def inside(address, top=0):
                    x, y, w, h = box(address)
                    monitor = next(m for m in json.loads(ctl('monitors', '-j')) if m['id'] == window(address)['monitor'])
                    mx, my = monitor['x'], monitor['y']
                    mw, mh = monitor['width'] / monitor['scale'], monitor['height'] / monitor['scale']
                    return x >= mx and y >= my + top and x + w <= mx + mw and y + h <= my + mh

                def screen():
                    # The nested output follows its host window, so sizes are read, not assumed.
                    main = next(m for m in json.loads(ctl('monitors', '-j')) if m['name'] != 'SIDE')
                    return (round(main['width'] / main['scale']), round(main['height'] / main['scale']),
                            main['reserved'][1] + 30, main['reserved'][3])

                def omarchy_size():
                    width, height, top, bottom = screen()
                    return min(1100, width * 0.64), min(760, height * 0.68)

                def near(size, expected):
                    return all(abs(a - b) <= 1 for a, b in zip(size, expected))

                settled()
                check(not ctl('configerrors'), 'config loads without errors: ' + ctl('configerrors'))
                check(hypertile('floating-size').endswith("Omarchy's size."), 'no saved size at first')

                first = spawn(2)
                check(near(box(first)[2:], omarchy_size()), "without a saved size Omarchy's open size stands: " + str(box(first)))

                width, height = screen()[:2]
                size = (round(width * 0.5), round(height * 0.6))
                dispatch(f"resize({{ x = {size[0]}, y = {size[1]}, relative = false, window = 'address:{first}' }})")
                check(box(first)[2:] == size, 'the window is resized by hand: ' + str(box(first)))
                said = hypertile('floating-size', 'save')
                check('50% × 60%' in said, 'save takes the focused window\'s share: ' + said)
                stored = json.loads(saved.read_text())
                check(abs(stored['width'] - 0.5) < 0.001 and abs(stored['height'] - 0.6) < 0.001, 'saved to the state file: ' + saved.read_text())

                second = spawn(2)
                x, y, w, h = box(second)
                check(near((w, h), size), 'a new window opens at the saved size: ' + str(box(second)))
                check(abs(x + w / 2 - width / 2) <= 48 and inside(second, 30), 'centered on the screen, on it: ' + str(box(second)))
                third = spawn(2)
                check(near(box(third)[2:], size) and box(third)[:2] != box(second)[:2], 'the next one steps on: ' + str(box(third)))
                # Omarchy's browser rule tiles Chrome, so the open rule cannot size
                # it; Omarchy floats it as it opens, at its own size.
                browser = spawn(2, 'chromium')
                check('chromium-based-browser*' in window(browser).get('tags', []), 'the browser rule tags it')
                check(window(browser).get('floating') and near(box(browser)[2:], size) and inside(browser, 30),
                      'a browser opens at the saved size too: ' + str(box(browser)))

                tiled = spawn(3)
                check(not window(tiled).get('floating'), 'workspace 3 tiles')
                ctl('eval', 'o.workspace_mode({ workspace = "3", mode = "floating" })')
                time.sleep(0.5)
                check(window(tiled).get('floating') and near(box(tiled)[2:], size),
                      'a workspace starting to float gives its windows the saved size: ' + str(box(tiled)))
                fresh = spawn(3)
                check(window(fresh).get('floating') and near(box(fresh)[2:], size),
                      'a window opened after the workspace starts to float takes the saved size: ' + str(box(fresh)))

                carried = spawn(4)
                check(not window(carried).get('floating'), 'workspace 4 tiles')
                dispatch(f"move({{ workspace = '2', follow = false, window = 'address:{carried}' }})")
                time.sleep(0.3)
                check(window(carried).get('floating') and near(box(carried)[2:], size),
                      'a window carried onto a floating workspace takes the saved size: ' + str(box(carried)))

                # Input switch: the workspace leaves for another screen and comes back.
                ctl('output', 'create', 'headless', 'SIDE')
                settled()
                side = next((m for m in json.loads(ctl('monitors', '-j')) if m['name'] == 'SIDE'), None)
                check(side is not None, 'a second output joins: ' + ctl('monitors'))
                ctl('eval', "hl.dispatch(hl.dsp.workspace.move({ workspace = '2', monitor = 'SIDE' }))")
                time.sleep(0.4)
                local_x = side['width'] - size[0] // 3
                dispatch(f"move({{ x = {side['x'] + local_x}, y = {side['y'] + 100}, relative = false, window = 'address:{second}' }})")
                check(window(second).get('monitor') == side['id'], 'the window is on the second output: ' + json.dumps(window(second).get('at')))
                ctl('output', 'remove', 'SIDE')
                check(wait(lambda: len(json.loads(ctl('monitors', '-j'))) == 1), 'the second output leaves')
                check(wait(lambda: window(second).get('workspace', {}).get('id') == 2 and inside(second, 30)),
                      'back on the first screen the window is inside it, title bar too: ' + str(box(second)))
                width, height, top, bottom = screen()
                check(near(box(second)[2:], (min(size[0], width), min(size[1], height - top - bottom))),
                      'fitting it back shrinks it only as far as the screen needs: ' + str(box(second)) + ' on ' + str(screen()))

                said = hypertile('floating-size', 'reset')
                check("Omarchy's size" in said and not saved.exists(), 'reset goes back to Omarchy\'s size: ' + said)
                last = spawn(2)
                check(near(box(last)[2:], omarchy_size()), "after reset Omarchy's open size returns: " + str(box(last)))

                ctl('reload')
                settled()
                check(not ctl('configerrors'), 'a reload stays clean: ' + ctl('configerrors'))
            finally:
                for child in children:
                    child.kill()
                compositor.terminate()
                try:
                    compositor.wait(10)
                except subprocess.TimeoutExpired:
                    compositor.kill()
    print(f'{len(failures)} failures')
    return 1 if failures else 0


sys.exit(main())
