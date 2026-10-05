"""Real overlay/input regression during mirror-source handoffs.

Run from a Wayland session: python3 test/overlay_display_integration.py.
Requires Quickshell, wtype, Omarchy's QML modules, and the mirror-output
compositor fix documented in docs/diagnostics/mirror-outputs/.
Only nested WAYLAND-* outputs and temporary config/state are changed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='ht-od-') as directory:
        root = Path(directory)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        config = root / 'c/hypr'
        config.mkdir(parents=True)
        for source in ROOT.glob('hypertile*.lua'):
            shutil.copyfile(source, config / source.name)
        (config / 'looknfeel.lua').write_text('hl.config({general={layout="dwindle"}})\n')
        monitors = config / 'monitors.lua'
        rules = ('hl.monitor({output="WAYLAND-1",mode="preferred",position="0x0",scale=1,disabled=false,mirror=""})\n'
                 'hl.monitor({output="WAYLAND-2",mode="preferred",position="1280x0",scale=1,disabled=false,mirror="WAYLAND-1"})\n')
        monitors.write_text(rules)
        entry = config / 'hyprland.lua'
        entry.write_text('package.path=os.getenv("XDG_CONFIG_HOME").."/?.lua;"..package.path\n'
                         'require("hypr.monitors")\n'
                         'hl.config({animations={enabled=false},xwayland={enabled=false}})\n'
                         'hl.device({name="hl-virtual-keyboard-wtype",keybinds=true})\n')
        home = root / 'home'
        (home / '.local/bin').mkdir(parents=True)
        (home / '.local/bin/hypertile-ctl').symlink_to(ROOT / 'bin/hypertile-ctl')
        qml = root / 'qml'
        qml.mkdir()
        for name in ('Commons', 'Ui'):
            (qml / name).symlink_to(Path('/usr/share/omarchy/shell') / name, target_is_directory=True)
        shutil.copytree(ROOT / 'plugin', qml / 'plugin')
        # Instrument the existing private pane/window without changing its
        # lifecycle, rendering, focus, or source-switching code.
        overlay = qml / 'plugin/Overlay.qml'
        source = overlay.read_text()
        marker = '    function displayState(): string {'
        assert source.count(marker) == 1
        source = source.replace(marker,
            '    function displayUse(connector: string): void { displaysPane.useDisplay(connector) }\n'
            '    function displayProbe(): string { return JSON.stringify({opened:root.opened,busy:displaysPane.busy,visible:window.visible,screen:window.screen ? window.screen.name : null,width:window.width,height:window.height}) }\n'
            + marker)
        overlay.write_text(source)
        (qml / 'shell.qml').write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import "plugin" as Hypertile
ShellRoot {
    Hypertile.Overlay { id: overlay }
    IpcHandler {
        target: "driver"
        function open(): void { overlay.open("{}"); overlay.showDisplays() }
        function layouts(): void { overlay.displaysMode = false }
        function state(): string { return JSON.stringify({opened:overlay.opened,error:overlay.errorText}) }
    }
}
''')
        parent = Path(os.environ['WAYLAND_DISPLAY'])
        if not parent.is_absolute():
            parent = Path(os.environ['XDG_RUNTIME_DIR']) / parent
        env = dict(os.environ, HOME=str(home), WAYLAND_DISPLAY=str(parent), XDG_RUNTIME_DIR=str(runtime),
                   XDG_CONFIG_HOME=str(root / 'c'), XDG_STATE_HOME=str(root / 's'), XDG_CACHE_HOME=str(root / 'cache'),
                   HYPERTILE_SRC=str(ROOT), HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1')
        for key in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET', 'WAYLAND_SOCKET'):
            env.pop(key, None)
        shell = None
        with (root / 'compositor.log').open('w+') as compositor_log, (root / 'shell.log').open('w+') as shell_log:
            compositor = subprocess.Popen(['Hyprland', '--config', str(entry)], env=env,
                                          stdout=compositor_log, stderr=compositor_log)
            try:
                def run(*command, timeout=15):
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
                    assert result.returncode == 0, (command, result.stdout, result.stderr)
                    return result.stdout.strip()

                def ctl(*args):
                    return run('hyprctl', *args)

                def wait(condition, label, timeout=10):
                    deadline = time.monotonic() + timeout
                    last = None
                    while time.monotonic() < deadline:
                        try:
                            last = condition()
                            if last:
                                return last
                        except (AssertionError, ValueError):
                            pass
                        time.sleep(.1)
                    raise AssertionError((label, last))

                instance = wait(lambda: next((i for i in json.loads(ctl('-j', 'instances'))
                                             if i['pid'] == compositor.pid), None), 'nested compositor startup')
                env.update(HYPRLAND_INSTANCE_SIGNATURE=instance['instance'], WAYLAND_DISPLAY=instance['wl_socket'])
                if not any(d['name'] == 'WAYLAND-2' for d in json.loads(ctl('-j', 'monitors', 'all'))):
                    ctl('output', 'create', 'wayland', 'WAYLAND-2')
                # Float only this test's host windows so parent tiling cannot
                # resize its virtual outputs while it checks their surfaces.
                def host_windows():
                    clients = json.loads(subprocess.check_output(['hyprctl', '-j', 'clients'], text=True))
                    owned = [c for c in clients if c.get('pid') == compositor.pid]
                    return owned if len(owned) >= 2 else None
                for client in wait(host_windows, 'nested output windows'):
                    target = json.dumps('address:' + client['address'])
                    subprocess.run(['hyprctl', 'eval', f'hl.dispatch(hl.dsp.window.float({{window={target},action="on"}}));'
                                    f'hl.dispatch(hl.dsp.window.resize({{window={target},x=1280,y=720}}))'],
                                   check=True, capture_output=True, timeout=5)
                time.sleep(.3)
                ctl('eval', rules)
                time.sleep(.3)
                ctl('eval', rules)
                wait(lambda: all(d['width'] > 0 and d['height'] > 0
                                 for d in json.loads(ctl('-j', 'monitors', 'all'))), 'usable virtual modes')
                shell = subprocess.Popen(['quickshell', '-p', str(qml)], env=env, stdout=shell_log, stderr=shell_log)

                def ipc(target, method, *args):
                    return run('quickshell', '-p', str(qml), 'ipc', 'call', target, method, *args, timeout=3)

                wait(lambda: json.loads(ipc('driver', 'state')), 'overlay startup')
                ipc('driver', 'open')
                wait(lambda: len(json.loads(ipc('hypertile', 'displayState'))['draft']['displays']) == 2,
                     'display catalog')

                def assert_surface(connector):
                    probe = json.loads(ipc('hypertile', 'displayProbe'))
                    state = json.loads(ipc('hypertile', 'displayState'))
                    layers = json.loads(ctl('-j', 'layers'))
                    monitor = next(d for d in json.loads(ctl('-j', 'monitors')) if d['name'] == connector)
                    width, height = round(monitor['width'] / monitor['scale']), round(monitor['height'] / monitor['scale'])
                    owned = [layer for level in layers.get(connector, {}).get('levels', {}).values()
                             for layer in level if layer['namespace'] == 'hypertile']
                    print('surface', connector, probe, owned, state['error'], flush=True)
                    assert probe['opened'] and probe['visible'] and not probe['busy'], probe
                    assert monitor['mirrorOf'] == 'none', monitor
                    assert len(owned) == 1 and (owned[0]['w'], owned[0]['h']) == (width, height), (probe, layers, monitor)
                    assert (probe['width'], probe['height']) == (width, height), (probe, monitor)
                    assert not state['error'], state

                time.sleep(.5)
                assert_surface('WAYLAND-1')

                def assert_escape():
                    # Real keyboard input must dismiss the fullscreen grab;
                    # successful IPC alone did not detect Jim's input lockup.
                    run('wtype', '-k', 'Escape')
                    wait(lambda: not json.loads(ipc('driver', 'state'))['opened'], 'Escape releases overlay input')
                    wait(lambda: not any(layer['namespace'] == 'hypertile'
                                         for monitor in json.loads(ctl('-j', 'layers')).values()
                                         for level in monitor['levels'].values() for layer in level),
                         'closed overlay releases its layer surface')

                for target in ('WAYLAND-2', 'WAYLAND-1', 'WAYLAND-2'):
                    ipc('hypertile', 'displayUse', target)
                    wait(lambda: not json.loads(ipc('hypertile', 'displayProbe'))['busy'], 'handoff completion')
                    time.sleep(.5)
                    assert_surface(target)
                    assert_escape()
                    ipc('driver', 'open')
                    time.sleep(.3)
                print('PASS: real overlay survives repeated mirror-source handoffs and Escape releases input', flush=True)

                # The same migration must work outside Displays, including a
                # source switch initiated by the CLI while Layouts is open.
                ipc('driver', 'layouts')
                run(str(ROOT / 'bin/hypertile-displays'), 'use-display', 'WAYLAND-1')
                time.sleep(.5)
                assert_surface('WAYLAND-1')
                assert_escape()
                print('PASS: external mirror-source switch preserves the Layouts overlay and keyboard input', flush=True)

                ipc('driver', 'open')
                time.sleep(.3)
                state = json.loads(ipc('hypertile', 'displayState'))
                first = next(i for i, d in enumerate(state['draft']['displays']) if d['connector'] == 'WAYLAND-1')
                second = next(i for i, d in enumerate(state['draft']['displays']) if d['connector'] == 'WAYLAND-2')
                ipc('hypertile', 'displaySet', str(first), 'enabled', 'false')
                ipc('hypertile', 'displaySet', str(second), 'mirror_of', 'null')
                ipc('hypertile', 'displayPreview')
                wait(lambda: json.loads(ipc('hypertile', 'displayState'))['pending'], 'disable-source preview')
                wait(lambda: not json.loads(ipc('hypertile', 'displayProbe'))['busy'], 'preview completion')
                time.sleep(.3)
                assert_surface('WAYLAND-2')
                ipc('hypertile', 'displayRevert')
                wait(lambda: not json.loads(ipc('hypertile', 'displayProbe'))['busy'], 'rollback completion')
                time.sleep(.3)
                assert_surface('WAYLAND-1')
                state = json.loads(ipc('hypertile', 'displayState'))
                assert not state['pending'] and not state['dirty'], state
                assert_escape()
                print('PASS: disabling the source preserves preview controls, rollback, and Escape input', flush=True)
            except Exception:
                print('Shell log:\n' + (root / 'shell.log').read_text()[-6000:])
                print('Compositor log:\n' + (root / 'compositor.log').read_text()[-3000:])
                raise
            finally:
                for process in (shell, compositor):
                    if process and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()


if __name__ == '__main__':
    main()
