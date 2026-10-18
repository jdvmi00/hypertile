"""Hypertile and Omarchy's workspace modes sharing workspaces, nested Hyprland.

Run from a Wayland desktop on Omarchy: python3 test/omarchy_modes_integration.py.
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

    with tempfile.TemporaryDirectory(prefix='ht-om-') as directory:
        root = pathlib.Path(directory)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        hypr = root / 'config' / 'hypr'
        (hypr / 'layouts').mkdir(parents=True)
        for src in ROOT.glob('hypertile*.lua'):
            shutil.copy(src, hypr / src.name)
        (hypr / 'layouts' / 'probe.lua').write_text(
            'require("hypr.hypertile").layout("probe", { columns = { { name = "a" }, { name = "b" } } })\n')
        (hypr / 'hyprland.lua').write_text(ENTRY)
        rules = root / 'state' / 'hypertile' / 'workspace-rules'
        modes = root / 'state' / 'omarchy' / 'workspace-layouts'
        rules.mkdir(parents=True)
        modes.mkdir(parents=True)

        def save(path, text, age):
            path.write_text(text)
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))

        def rule(ws):
            return f'hl.workspace_rule({{ workspace = "{ws}", layout = "lua:probe" }})\n'

        def mode(ws, name):
            return f'o.workspace_mode({{ workspace = "{ws}", mode = "{name}" }})\n'

        save(modes / '2.lua', mode(2, 'floating'), 60)
        save(rules / '3.lua', rule(3), 60)
        save(rules / '4.lua', rule(4), 30)
        save(modes / '4.lua', mode(4, 'floating'), 60)
        save(rules / '5.lua', rule(5), 60)
        save(modes / '5.lua', mode(5, 'scrolling'), 30)
        shell_log = root / 'shell.log'
        shell = root / 'fake-shell'
        shell.write_text(f'#!/bin/sh\necho "$*" >> {shell_log}\n')
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

                def live(ws):
                    for entry in json.loads(hypertile('workspaces', '--json', '--live'))['workspaces']:
                        if entry['id'] == ws:
                            return entry
                    return {}

                def windows(ws):
                    return [c for c in json.loads(ctl('clients', '-j')) if c['workspace']['id'] == ws]

                def wait(predicate, seconds=6):
                    end = time.time() + seconds
                    while time.time() < end:
                        if predicate():
                            return True
                        time.sleep(0.1)
                    return predicate()

                def settled():
                    # Removing a file the config loaded reloads it; let that run first.
                    time.sleep(1.2)
                    wait(lambda: ctl('eval', 'return 1') == 'ok')

                def spawn(ws):
                    ctl('eval', f"hl.dispatch(hl.dsp.focus({{ workspace = '{ws}' }}))")
                    before = len(windows(ws))
                    children.append(subprocess.Popen(['foot', '--app-id', f'modes-{ws}', 'sh', '-c', 'sleep 300'], env=env,
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    wait(lambda: len(windows(ws)) > before)
                    time.sleep(0.3)
                    return windows(ws)[-1]['address']

                def window(address):
                    return next((c for c in json.loads(ctl('clients', '-j')) if c['address'] == address), {})

                def claimed(address):
                    return 'omarchy-mode-floated' in window(address).get('tags', [])

                def toggle(ws, name):
                    # What omarchy-hyprland-workspace-layout-toggle does with the default at dwindle.
                    ctl('eval', f'o.workspace_mode({{ workspace = "{ws}", mode = "{name}" }})')
                    if name == 'dwindle':
                        (modes / f'{ws}.lua').unlink(missing_ok=True)
                    else:
                        (modes / f'{ws}.lua').write_text(mode(ws, name))
                    time.sleep(0.4)

                settled()
                check(not ctl('configerrors'), 'config loads without errors: ' + ctl('configerrors'))
                check(not (modes / '4.lua').exists() and (rules / '4.lua').exists(), 'a newer hypertile rule wins over an older Omarchy mode')
                check((modes / '5.lua').exists() and not (rules / '5.lua').exists(), 'a newer Omarchy mode wins over an older hypertile rule')

                on2, on4 = spawn(2), spawn(4)
                check(window(on2).get('floating') and claimed(on2), 'Omarchy floats a window opened on its floating workspace')
                check(live(2).get('floating') is True and live(2).get('layout') == 'dwindle', 'workspace 2 reads back floating over dwindle: ' + json.dumps(live(2)))
                check(not window(on4).get('floating') and live(4).get('layout') == 'lua:probe' and live(4).get('floating') is False,
                      'workspace 4 kept the hypertile layout from the conflict: ' + json.dumps(live(4)))

                toggle(4, 'floating')
                check(not (rules / '4.lua').exists(), "Omarchy's toggle removes hypertile's saved rule")
                check(window(on4).get('floating') and live(4).get('floating') is True, "Omarchy's toggle floats a hypertile workspace")
                check('hypertile-bar refresh' in shell_log.read_text(), "the bar hears about Omarchy's toggle")
                check(hypertile('current').endswith('\tfloating'), 'hypertile-ctl current marks the floating workspace: ' + hypertile('current'))

                shell_log.write_text('')
                result = hypertile('apply', 'probe', '--workspace', '2', '--quiet')
                check(result.startswith('workspace 2 -> lua:probe'), 'apply on a floating workspace succeeds: ' + result)
                settled()
                check(not window(on2).get('floating') and not claimed(on2), 'a hypertile pick tiles the floating workspace')
                check(live(2).get('floating') is False and live(2).get('layout') == 'lua:probe', 'workspace 2 reads back the pick: ' + json.dumps(live(2)))
                check(not (modes / '2.lua').exists() and (rules / '2.lua').exists(), "the pick replaces Omarchy's saved mode")
                told = shell_log.read_text()
                check('omarchy.workspaces refresh' in told and 'omarchy.dock refresh' in told, "Omarchy's bar and dock hear about the pick: " + told)

                hypertile('apply', 'dwindle', '--workspace', '4', '--no-persist', '--quiet')
                time.sleep(0.4)
                check(window(on4).get('floating') and live(4).get('floating') is True and live(4).get('layout') == 'dwindle',
                      'a transient apply changes the layout under a floating workspace and keeps it floating')

                ctl('eval', 'require("hypr.hypertile-session").place({ address = "%s", saved = { workspace = "4", floating = true,'
                    ' pinned = false, at = { x = 100, y = 100 }, size = { x = 400, y = 300 } } })' % on2)
                time.sleep(0.5)
                check(window(on2).get('workspace', {}).get('id') == 4 and window(on2).get('floating') and claimed(on2),
                      'a restored window lands on the floating workspace in Omarchy\'s care: ' + json.dumps(window(on2).get('tags')))
                toggle(4, 'dwindle')
                check(not window(on2).get('floating') and not window(on4).get('floating'), 'leaving floating mode tiles the restored window too')

                hypertile('apply', 'probe', '--workspace', '4', '--quiet')
                ctl('reload')
                settled()
                check(live(4).get('layout') == 'lua:probe' and live(4).get('floating') is False
                      and not window(on2).get('floating') and not window(on4).get('floating'), 'the pick survives a reload: ' + json.dumps(live(4)))
                (modes / '4.lua').write_text(mode(4, 'dwindle'))
                ctl('reload')
                settled()
                check((rules / '4.lua').exists() and (modes / '4.lua').exists() and live(4).get('layout') == 'lua:probe',
                      "a busy workspace Omarchy kept through a default change stays on hypertile's rule: " + json.dumps(live(4)))
                hypertile('apply', 'probe', '--workspace', '6', '--quiet')
                check((rules / '6.lua').exists(), 'apply saves a rule for workspace 6')
                toggle(6, 'scrolling')
                check(not (rules / '6.lua').exists(), "after a reload Omarchy's toggle still removes hypertile's rule")
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
