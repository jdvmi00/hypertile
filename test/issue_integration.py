"""Live regressions for #31/#32 in an isolated Hyprland compositor.

Run from a Wayland session: python3 test/issue_integration.py.
Uses virtual outputs and temporary configuration/state, never physical outputs.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='ht-issues-') as directory:
        root = Path(directory)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        config_home = root / 'config'
        config = config_home / 'hypr'
        config.mkdir(parents=True)
        looknfeel = config / 'looknfeel.lua'
        original = '-- User inherits defaults.\n-- hl.config({general={layout="scrolling"}})\n'
        looknfeel.write_text(original)
        monitors = config / 'monitors.lua'
        original_monitors = '''local scale = 1.33333
hl.monitor({output="", mode="6144x2560@60", position="auto", scale=scale})
hl.monitor({output="WAYLAND-1", disabled=true})
hl.monitor({output="HEADLESS-1", mode="2304x1536@120", position="0x0", scale=scale})
'''
        monitors.write_text(original_monitors)
        entry = config / 'hyprland.lua'
        entry.write_text('''package.path = os.getenv("XDG_CONFIG_HOME") .. "/?.lua;" .. package.path
hl.config({general={layout="dwindle"}, animations={enabled=false}, xwayland={enabled=false}})
require("hypr.monitors")
require("hypr.looknfeel")
''')
        parent = Path(os.environ['WAYLAND_DISPLAY'])
        if not parent.is_absolute():
            parent = Path(os.environ['XDG_RUNTIME_DIR']) / parent
        env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(config_home),
                   XDG_STATE_HOME=str(root / 'state'), HYPERTILE_SRC=str(ROOT),
                   HYPRLAND_HEADLESS_ONLY='1', HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1',
                   WAYLAND_DISPLAY=str(parent))
        for key in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET'):
            env.pop(key, None)
        with (root / 'compositor.log').open('w+') as log:
            process = subprocess.Popen(['Hyprland', '--config', str(entry)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and process.poll() is None:
                    result = subprocess.run(['hyprctl', 'instances', '-j'], env=env, capture_output=True, text=True)
                    try:
                        instances = [i for i in json.loads(result.stdout) if i['pid'] == process.pid]
                    except ValueError:
                        instances = []
                    if instances and (runtime / 'hypr' / instances[0]['instance'] / '.socket.sock').exists():
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('Isolated compositor did not start')
                env['HYPRLAND_INSTANCE_SIGNATURE'] = instances[0]['instance']
                env['WAYLAND_DISPLAY'] = instances[0]['wl_socket']

                def run(*args):
                    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=25)
                    assert result.returncode == 0, result.stdout + result.stderr
                    return result.stdout.strip()

                def ctl(*args):
                    return run('hyprctl', *args)

                def layout(*args):
                    return run(str(ROOT / 'bin/hypertile-ctl'), *args)

                def display(*args):
                    return json.loads(layout('display', *args))

                assert not ctl('configerrors'), ctl('configerrors')
                assert layout('default') == 'dwindle'
                assert looknfeel.read_text() == original
                layout('default', 'master')
                assert layout('default') == 'master'
                assert json.loads(ctl('-j', 'getoption', 'general:layout'))['str'] == 'master'
                assert looknfeel.read_text().startswith(original)
                assert looknfeel.with_suffix('.lua.bak').read_text() == original
                layout('default', 'dwindle')
                assert looknfeel.read_text().count('Default layout saved by Hypertile') == 1
                assert json.loads(ctl('-j', 'getoption', 'general:layout'))['str'] == 'dwindle'
                assert not ctl('configerrors'), ctl('configerrors')
                print('PASS #31: inherited default read; first override saved, reloaded and replaced', flush=True)

                names = {m['name'] for m in json.loads(ctl('-j', 'monitors', 'all'))}
                for name in ('HEADLESS-1', 'HEADLESS-2'):
                    if name not in names:
                        ctl('output', 'create', 'headless', name)
                ctl('reload')
                time.sleep(.5)
                initial = [d for d in display('list')['displays'] if d['connector'].startswith('HEADLESS-')]
                assert len(initial) == 2, initial
                first = next(d for d in initial if d['connector'] == 'HEADLESS-1')
                second = next(d for d in initial if d['connector'] == 'HEADLESS-2')
                assert (first['x'], first['y'], second['x'], second['y']) == (0, 0, 1728, 0), initial
                assert (second['width'], second['height']) == (6144, 2560), second
                first.update(x=6336, y=768)
                document = dict(version=1, displays=initial, workspaces={})
                pending = display('preview', '--json', json.dumps(document))

                def assert_positions():
                    actual = {m['name']: m for m in json.loads(ctl('-j', 'monitors'))}
                    for name, x, y in [('HEADLESS-1', 6336, 768), ('HEADLESS-2', 1728, 0)]:
                        assert (actual[name]['x'], actual[name]['y']) == (x, y), actual

                assert_positions()
                assert display('keep', pending['token'])['kept']
                assert_positions()
                ctl('reload')
                time.sleep(.3)
                assert_positions()
                assert not ctl('configerrors'), ctl('configerrors')
                assert not display('status')['pending']
                saved = monitors.read_text()
                assert 'position="auto"' in saved
                assert 'output = "HEADLESS-2"' in saved and 'position = "1728x0"' in saved
                print('PASS #32: preview, Keep and reload retain 6336,768 / 1728,0 at reported modes/scale', flush=True)

                # Demonstrate the original failure with the same real compositor:
                # move only the explicit output in the original source.
                monitors.write_text(original_monitors.replace('position="0x0"', 'position="6336x768"'))
                ctl('reload')
                time.sleep(.3)
                actual = {m['name']: m for m in json.loads(ctl('-j', 'monitors'))}
                assert actual['HEADLESS-2']['x'] == 8064, actual
                monitors.write_text(saved)
                ctl('reload')
                time.sleep(.3)
                assert_positions()
                assert not ctl('configerrors'), ctl('configerrors')
                print('PASS #32 control: original partial save moves automatic output to X=8064; fixed save restores X=1728', flush=True)
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-8000:])
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    main()
