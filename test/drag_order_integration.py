"""Exercise Super + left-button tile drags in both press orders, nested Hyprland.

Run from a Wayland desktop: python3 test/drag_order_integration.py.
Requires Hyprland, hyprctl, foot, wtype and PyGObject with GTK 4. Creates
two disposable windows. Unlike drag_integration.py the real mouse:272 binds
stay in place: a zwlr_virtual_pointer_v1 client sends the button and wtype
holds Super, so Hyprland's own modifier matching decides whether the drag
starts. One window is a GTK probe that logs the buttons it receives, since a
window that saw the press must also see the release.
"""
import os, json, subprocess, time, tempfile, pathlib, shutil, socket, struct, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'displays'))
from wayland import words, string, read_string

PROBE = """
import gi, sys
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
log = open(sys.argv[1], 'a', buffering=1)
names = {Gdk.EventType.BUTTON_PRESS: 'press', Gdk.EventType.BUTTON_RELEASE: 'release'}
def activate(app):
    window = Gtk.ApplicationWindow(application=app)
    events = Gtk.EventControllerLegacy()
    events.connect('event', lambda c, *_: log.write(names.get(c.get_current_event().get_event_type(), '') + '\\n') and False)
    window.add_controller(events)
    window.present()
app = Gtk.Application(application_id='drag.probe')
app.connect('activate', activate)
app.run([])
"""


class Pointer:
    def __init__(self, display):
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.settimeout(5)
        self.connection.connect(display)
        self.send(1, 1, words(2))
        found = {}
        for object_id, opcode, data in self.roundtrip(3):
            if object_id == 2 and opcode == 0:
                name, = struct.unpack_from('=I', data)
                interface, offset = read_string(data, 4)
                found[interface] = name
        assert 'zwlr_virtual_pointer_manager_v1' in found, sorted(found)
        self.send(2, 0, words(found['zwlr_virtual_pointer_manager_v1']) + string('zwlr_virtual_pointer_manager_v1') + words(1, 4))
        self.send(4, 0, words(0, 5))
        self.next_id = 6
        self.sync()

    def send(self, object_id, opcode, payload=b''):
        self.connection.sendall(words(object_id, ((8 + len(payload)) << 16) | opcode) + payload)

    def receive(self, size):
        data = b''
        while len(data) < size:
            part = self.connection.recv(size - len(data))
            if not part:
                raise OSError('virtual pointer disconnected')
            data += part
        return data

    def roundtrip(self, callback):
        self.send(1, 0, words(callback))
        while True:
            object_id, header = struct.unpack('=II', self.receive(8))
            data = self.receive((header >> 16) - 8)
            if object_id == 1 and header & 0xffff == 0:
                raise OSError('Wayland error ' + repr(data))
            if object_id == callback:
                return
            yield object_id, header & 0xffff, data

    def sync(self):
        list(self.roundtrip(self.next_id))
        self.next_id += 1

    def nudge(self):
        for dx in (256, -256):
            self.send(5, 0, words(int(time.monotonic() * 1000) & 0xffffffff, dx & 0xffffffff, 0))
            self.send(5, 4)
        self.sync()

    def button(self, pressed):
        self.send(5, 2, words(int(time.monotonic() * 1000) & 0xffffffff, 272, 1 if pressed else 0))
        self.send(5, 4)
        self.sync()


with tempfile.TemporaryDirectory(prefix='ht-do-') as directory:
    root = pathlib.Path(directory)
    runtime = root / 'r'
    runtime.mkdir(mode=448)
    config = root / 'config' / 'hypr'
    config.mkdir(parents=True)
    for src in ROOT.glob('hypertile*.lua'):
        shutil.copy(src, config / src.name)
    entry = config / 'hyprland.lua'
    entry.write_text('package.path = os.getenv("XDG_CONFIG_HOME") .. "/?.lua;" .. package.path\nhl.config({general={layout="lua:dragtest"}, animations={enabled=false}, xwayland={enabled=false}})\nhl.monitor({output="", mode="1280x720@60", position="0x0", scale=1})\nhl.device({name="hl-virtual-keyboard-wtype", keybinds=true, resolve_binds_by_sym=true})\nlocal e = require("hypr.hypertile")\ne.layout("dragtest", {columns={{name="a"},{name="b"}}, empty="collapse",single="collapse"})\no = {bind=function(keys, desc, callback, options) hl.bind(keys, callback, options) end}\nhl.exec_cmd = function() end -- No shell or notifications in the isolated test.\nrequire("hypr.hypertile-navigation").bind()\n')
    parent = pathlib.Path(os.environ['WAYLAND_DISPLAY'])
    if not parent.is_absolute():
        parent = pathlib.Path(os.environ['XDG_RUNTIME_DIR']) / parent
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'), HYPRLAND_HEADLESS_ONLY='1', HYPRLAND_NO_SD_VARS='1', HYPRLAND_NO_SD_NOTIFY='1', WAYLAND_DISPLAY=str(parent))
    for key in ('DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE', 'NOTIFY_SOCKET'):
        env.pop(key, None)
    children = []
    failures = []
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
                return {w['address']: w for w in json.loads(ctl('clients', '-j'))}

            def drag_state():
                path = runtime / 'hypertile-tile-drag.json'
                return json.loads(path.read_text()) if path.exists() else {'active': False}

            def point_at(window):
                x, y = window['at']
                sx, sy = window['size']
                ctl('eval', f'hl.dispatch(hl.dsp.cursor.move({{x={x + sx // 2}, y={y + sy // 2}}}))')
                pointer.nudge()

            def hold_super(seconds):
                key = subprocess.Popen(['wtype', '-M', 'logo', '-P', 'Super_L', '-s', str(int(seconds * 1000)), '-p', 'Super_L', '-m', 'logo'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                children.append(key)
                return key

            assert not ctl('configerrors'), ctl('configerrors')
            pointer = Pointer(str(runtime / env['WAYLAND_DISPLAY']))
            probe_log = root / 'probe.log'
            probe_log.touch()
            children.append(subprocess.Popen([sys.executable, '-c', PROBE, str(probe_log)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            for _ in range(80):
                if len(clients()) == 1:
                    break
                time.sleep(0.1)
            children.append(subprocess.Popen(['foot', '--app-id', 'drag-foot', 'sh', '-c', 'sleep 120'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            for _ in range(80):
                if len(clients()) == 2:
                    break
                time.sleep(0.1)
            assert sorted(w['class'] for w in clients().values()) == ['drag-foot', 'drag.probe'], clients()

            def scenario(name, steps):
                before = sorted(clients().values(), key=lambda w: w['at'][0])
                a, b = before
                point_at(a)
                time.sleep(0.2)
                seen = len(probe_log.read_text().split())
                key = None
                for step in steps:
                    if step == 'super':
                        key = hold_super(1.2)
                        time.sleep(0.4)
                    elif step == 'press':
                        pointer.button(True)
                        time.sleep(0.3)
                    elif step == 'move':
                        point_at(b)
                        time.sleep(0.3)
                    elif step == 'release':
                        pointer.button(False)
                        time.sleep(0.3)
                    elif step == 'unsuper':
                        key.communicate(timeout=5)
                        time.sleep(0.3)
                    print(name, 'after', step, drag_state().get('active'), drag_state().get('zone'), [(w['class'], w['floating'], w['at']) for w in clients().values()], flush=True)
                if key:
                    key.communicate(timeout=5)
                time.sleep(0.4)
                after = clients()
                swapped = after[a['address']]['at'] == b['at'] and after[b['address']]['at'] == a['at']
                settled = not drag_state()['active'] and not any(w['floating'] for w in after.values())
                buttons = probe_log.read_text().split()[seen:]
                # Only a press made before Super reaches the dragged window.
                balanced = steps[0] != 'press' or (a['class'] == 'drag.probe' and buttons.count('press') == buttons.count('release') == 1)
                result = 'PASS' if swapped and settled and balanced else 'FAIL'
                print(result, name, 'swapped' if swapped else 'not swapped', 'settled' if settled else 'drag left active/floating',
                      'probe ' + ('dragged ' + ' '.join(buttons) if a['class'] == 'drag.probe' else 'was the target'), flush=True)
                if result == 'FAIL':
                    failures.append(name)
                    pointer.button(False)

            scenario('button then super, button released first', ['press', 'super', 'move', 'release', 'unsuper'])
            scenario('super then button, button released first', ['super', 'press', 'move', 'release', 'unsuper'])
            scenario('button then super, super released first', ['press', 'super', 'move', 'unsuper', 'release'])
            before = clients()
            hold_super(0.4).communicate(timeout=5)
            time.sleep(0.3)
            lone = not drag_state()['active'] and all(clients()[k]['at'] == w['at'] and not clients()[k]['floating'] for k, w in before.items())
            print('PASS' if lone else 'FAIL', 'super alone after late drags starts nothing', flush=True)
            if not lone:
                failures.append('super alone')
            point_at(sorted(before.values(), key=lambda w: w['at'][0])[0])
            pointer.button(True)
            point_at(sorted(before.values(), key=lambda w: w['at'][0])[1])
            time.sleep(0.3)
            plain_drag = drag_state()['active']
            pointer.button(False)
            time.sleep(0.3)
            unchanged = all(clients()[k]['at'] == w['at'] for k, w in before.items())
            print('PASS' if unchanged and not plain_drag else 'FAIL', 'plain button drag without super leaves tiles alone', flush=True)
            if plain_drag or not unchanged:
                failures.append('plain drag')
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
            compositor.terminate()
            compositor.wait(timeout=10)
            log.seek(0)
            lines = log.read().splitlines()
            print('\n'.join(l for l in lines if 'error' in l.lower() or 'hypertile' in l.lower() or 'ERR' in l)[-4000:])
    sys.exit(1 if failures else 0)
