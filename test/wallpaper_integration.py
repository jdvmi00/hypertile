"""Opt-in adapter test using installed Omarchy/QML in an isolated compositor.

Run from a Wayland desktop: python3 test/wallpaper_integration.py.
Requires Hyprland, Quickshell, Omarchy and ImageMagick. User settings and
physical outputs are never changed. The production renderer is instrumented
only with test IPC and panel references; its image/transition code is intact.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'displays'))
import wallpaper


def main():
    stock = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell'
    with tempfile.TemporaryDirectory(prefix='htw-') as directory:
        root = Path(directory)
        runtime = root / 'r'
        runtime.mkdir(mode=0o700)
        config = root / '.config'
        config.mkdir()
        entry = config / 'hyprland.lua'
        entry.write_text('hl.monitor({output="",mode="1280x720@60",position="0x0",scale=1})\n'
                         'hl.config({animations={enabled=false},xwayland={enabled=false}})\n')
        shell = root / 'shell'
        shell.mkdir()
        for name in ('Commons', 'Ui', 'services'):
            (shell / name).symlink_to(stock / name)
        source = wallpaper.render((stock / 'plugins/background/Background.qml').read_text())
        source = source.replace('  id: root', '  id: root\n  property var testPanels: []', 1)
        source = source.replace('      id: panel', '      id: panel\n      Component.onCompleted: root.testPanels = root.testPanels.concat([panel])', 1)
        source = source.replace('      property bool maskReady:', '''      function testState() {
        return {name: screen.name, frame: wallpaperFrame, failed: customImageFailed,
          screen: {x: screen.x, y: screen.y, width: screen.width, height: screen.height},
          decode: {width: base.decode.width, height: base.decode.height},
          size: {width: base.sourceSize.width, height: base.sourceSize.height},
          status: base.status, source: String(base.source), fit: base.fillMode, alpha: color.a,
          old: String(oldFrame.source), incoming: String(incomingFrame.source)}
      }
      property bool maskReady:''', 1)
        source = source.replace('    target: "background"', '''    target: "background"
    function configure(value: string): void { root.wallpaperConfig = JSON.parse(value) }
    function state(): string {
      return JSON.stringify({panels: root.testPanels.map(p => p.testState()),
        finishing: root.finishingTransition, progress: root.revealProgress,
        incoming: root.incomingBackground, prepared: root.preparedBackground,
        sizes: root.nativeSizes, displayed: root.displayedBackground})
    }''', 1)
        (shell / 'Background.qml').write_text(source)
        shutil.copy(ROOT / 'plugin/Wallpaper.js', shell)
        (shell / 'shell.qml').write_text('import Quickshell\nShellRoot { Background {} }\n')
        large, small, broken = [root / name for name in ('large.png', 'small.png', 'broken.png')]
        for path, size, color in ((large, '4096x2304', '#1260a0'), (small, '64x32', '#ea9631')):
            subprocess.run(['magick', '-size', size, 'xc:' + color, str(path)], check=True)
        broken.write_text('not an image')
        link = root / '.local/state/omarchy/current/background'
        link.parent.mkdir(parents=True)
        link.symlink_to(large)
        parent = Path(os.environ['WAYLAND_DISPLAY'])
        if not parent.is_absolute():
            parent = Path(os.environ['XDG_RUNTIME_DIR']) / parent
        env = dict(os.environ, HOME=str(root), XDG_RUNTIME_DIR=str(runtime),
                   XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(root / '.local/state'),
                   WAYLAND_DISPLAY=str(parent), HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1',
                   QT_QPA_PLATFORM='wayland', QT_QPA_PLATFORMTHEME='', QT_STYLE_OVERRIDE='Fusion')
        for name in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET'):
            env.pop(name, None)

        def wait_for(fn, label):
            deadline = time.monotonic() + 15
            value = None
            while time.monotonic() < deadline:
                value = fn()
                if value:
                    return value
                time.sleep(.1)
            raise AssertionError(label + ': timed out')

        children = []
        with (root / 'log').open('w+') as log:
            try:
                compositor = subprocess.Popen(['Hyprland', '--config', str(entry)], env=env, stdout=log, stderr=log)
                children.append(compositor)

                def instance():
                    result = subprocess.run(['hyprctl', 'instances', '-j'], env=env, capture_output=True, text=True)
                    try:
                        matches = [i for i in json.loads(result.stdout) if i['pid'] == compositor.pid]
                    except ValueError:
                        return None
                    return matches[0] if matches and (runtime / 'hypr' / matches[0]['instance'] / '.socket.sock').exists() else None

                active = wait_for(instance, 'compositor startup')
                env.update(HYPRLAND_INSTANCE_SIGNATURE=active['instance'], WAYLAND_DISPLAY=active['wl_socket'])
                subprocess.run(['hyprctl', 'output', 'create', 'wayland', 'WAYLAND-2'], env=env,
                               check=True, capture_output=True, timeout=5)
                subprocess.run(['hyprctl', 'eval', 'hl.monitor({output="WAYLAND-2",mode="1280x720@60",position="1280x0",scale=1})'],
                               env=env, check=True, capture_output=True, timeout=5)
                children.append(subprocess.Popen(['qs', '--no-color', '-p', str(shell)], env=env, stdout=log, stderr=log))

                def ipc(method, *args, check=True):
                    result = subprocess.run(['qs', '-p', str(shell), 'ipc', 'call', 'background', method, *args],
                                            env=env, capture_output=True, text=True, timeout=5)
                    if check:
                        assert result.returncode == 0, result.stdout + result.stderr
                    return result.stdout.strip()

                wait_for(lambda: ipc('state', check=False).startswith('{'), 'renderer startup')

                def state():
                    return json.loads(ipc('state'))

                def ready():
                    s = state()
                    return s if s['panels'] and all(p['status'] == 1 for p in s['panels']) else None

                initial = wait_for(ready, 'theme image ready')
                panel = initial['panels'][0]
                assert 0 < panel['decode']['width'] < 4096, panel
                assert panel['old'] == panel['incoming'] == '', panel

                def configure(image, fit='fit', mode='repeat'):
                    ipc('configure', json.dumps({'version': 1, 'groups': [dict(
                        outputs=[p['name'] for p in state()['panels']], mode=mode, image=image, fit=fit)]}))

                assert len(initial['panels']) == 2, initial
                configure(str(large), 'crop', 'span')
                span = wait_for(ready, 'spanned image ready')['panels']
                left = min(p['screen']['x'] for p in span)
                right = max(p['screen']['x'] + p['screen']['width'] for p in span)
                for p in span:
                    assert p['frame']['width'] == right - left and p['frame']['x'] == left - p['screen']['x'], span
                    assert p['decode']['width'] >= min(right - left, 4096), span

                configure(str(small))
                custom = wait_for(lambda: (s := ready()) and all(p['source'].endswith('/small.png') for p in s['panels']) and s,
                                  'custom image ready')
                assert all(p['decode'] == {'width': 64, 'height': 32} and p['fit'] == 1 and p['alpha'] == 1 for p in custom['panels']), custom
                assert all(p['old'] == p['incoming'] == '' for p in custom['panels']), custom

                # A custom image's URL stays the same during theme transitions.
                ipc('prepare', str(small))
                ipc('transition', str(large), str(small))
                settled = wait_for(lambda: (s := state()) and s['displayed'] == str(small)
                                   and not s['finishing'] and not s['incoming'] and not s['prepared'] and s,
                                   'fixed-image transition cleanup')
                assert str(small) in settled['sizes'], settled
                configure(str(broken))
                wait_for(lambda: (s := ready()) and all(p['failed'] and p['source'].endswith('/small.png') for p in s['panels']) and s,
                         'broken custom image fallback')
                configure(None, 'crop')
                ipc('prepare', str(large))
                ipc('transition', str(small), str(large))
                wait_for(lambda: (s := ready()) and s['displayed'] == str(large) and not s['incoming'] and not s['finishing'],
                         'theme image transition')
                ipc('setInstant', str(root / 'video.mp4'))
                wait_for(lambda: all(p['source'] == '' and p['alpha'] == 0 for p in state()['panels']), 'video layer passthrough')
                print('PASS: installed renderer loads on two outputs, bounds decoding, spans and fits custom images, releases transition frames, falls back on errors, and excludes video')
            except BaseException:
                if 'state' in locals():
                    print('Renderer state:', state(), file=sys.stderr)
                log.flush()
                log.seek(0)
                print(log.read()[-12000:], file=sys.stderr)
                raise
            finally:
                for child in reversed(children):
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()


if __name__ == '__main__':
    main()
