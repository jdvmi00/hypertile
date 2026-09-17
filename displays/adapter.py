"""Hyprland 0.56 Lua display adapter. No user configuration files are rewritten."""
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path


class DisplayError(ValueError):
    pass


def lua_string(value):
    # JSON's ASCII quoting is compatible except Unicode escapes: emit Lua byte escapes.
    return '"' + ''.join(('\\%03d' % b) if b < 32 or b > 126 else ('\\' + chr(b) if chr(b) in '\\"' else chr(b)) for b in str(value).encode()) + '"'


def identity(monitor):
    serial = str(monitor.get('serial', '')).strip()
    if serial and serial not in ('0', 'Unknown'):
        value = '\0'.join(str(monitor.get(k, '')) for k in ('make', 'model', 'serial'))
        return 'edid:' + hashlib.sha256(value.encode()).hexdigest()[:24]
    return 'connector:' + monitor['name']


def normalized(monitors):
    counts = {}
    for m in monitors:
        key = identity(m)
        counts[key] = counts.get(key, 0) + 1
    result = []
    for m in monitors:
        key = identity(m)
        ambiguous = counts[key] > 1
        result.append(dict(id=key + ('@' + m['name'] if ambiguous else ''), identity=key,
                           connector=m['name'], description=m.get('description', m['name']),
                           connected=True, ambiguous=ambiguous, enabled=not m.get('disabled', False),
                           width=m['width'], height=m['height'], refresh=m['refreshRate'],
                           x=m['x'], y=m['y'], scale=m['scale'], transform=m.get('transform', 0),
                           modes=m.get('availableModes', []), awake=m.get('dpmsStatus', True)))
    return result


def same(a, b):
    if bool(a.get('enabled')) != bool(b.get('enabled')):
        return False
    if not a.get('enabled'):
        return True
    return all(a.get(k) == b.get(k) for k in ('width', 'height', 'x', 'y', 'transform')) and abs(a['scale'] - b['scale']) < .001 and abs(a['refresh'] - b['refresh']) < .1


def bounds(d):
    w, h = d['width'], d['height']
    if d['transform'] % 2:
        w, h = h, w
    return d['x'], d['y'], w / d['scale'], h / d['scale']


def match(saved, current):
    exact = [d for d in current if d['id'] == saved['id']]
    if exact:
        return exact[0]
    explicit = [d for d in current if saved.get('explicit_match') and d['connector'] == saved.get('connector') and d['identity'] == saved.get('identity', saved['id'].split('@')[0])]
    if len(explicit) == 1:
        return explicit[0]
    candidates = [d for d in current if d['identity'] == saved.get('identity', saved['id'].split('@')[0])]
    if len(candidates) == 1 and not candidates[0]['ambiguous'] and '@' not in saved['id']:
        return candidates[0]
    return None


def validate(document, current):
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('displays'), list):
        raise DisplayError('Expected version 1 settings with a displays array.')
    result, seen, connectors = [], set(), set()
    for source in document['displays']:
        if not isinstance(source, dict):
            raise DisplayError('Every display must be a settings object.')
        d = dict(source)
        if not isinstance(d.get('id'), str) or d['id'] in seen:
            raise DisplayError('Every display needs a unique stable id.')
        seen.add(d['id'])
        actual = match(d, current)
        if not isinstance(d.get('enabled'), bool):
            raise DisplayError('Enabled must be true or false.')
        for k in ('width', 'height', 'x', 'y', 'transform'):
            if type(d.get(k)) is not int:
                raise DisplayError(k + ' must be an integer.')
        for k in ('scale', 'refresh'):
            if type(d.get(k)) not in (int, float) or not math.isfinite(d[k]):
                raise DisplayError(k + ' must be a finite number.')
        if not .25 <= d['scale'] <= 8 or d['transform'] not in range(8):
            raise DisplayError('Scale must be 0.25–8 and rotation transform 0–7.')
        if abs(d['x']) > 100000 or abs(d['y']) > 100000:
            raise DisplayError('Display position is outside the supported desktop range.')
        if d['width'] < 0 or d['height'] < 0 or d['refresh'] < 0:
            raise DisplayError('Display dimensions and refresh cannot be negative.')
        if not actual:
            continue  # Keep valid disconnected preferences without testing mode availability.
        if actual['connector'] in connectors:
            raise DisplayError('More than one saved display matches ' + actual['connector'] + '; choose a single explicit match.')
        connectors.add(actual['connector'])
        if actual['ambiguous'] and not d.get('explicit_match'):
            raise DisplayError('Identical displays require an explicit connector match: ' + actual['connector'])
        d['connector'] = actual['connector']
        if d['enabled']:
            modes = [re.fullmatch(r'(\d+)x(\d+)@([\d.]+)Hz', m) for m in actual['modes']]
            current_mode = d['width'] == actual['width'] and d['height'] == actual['height'] and abs(d['refresh'] - actual['refresh']) < .1 and d['width'] > 0 and d['height'] > 0
            if not current_mode and not any(m and int(m[1]) == d['width'] and int(m[2]) == d['height'] and abs(float(m[3]) - d['refresh']) < .1 for m in modes):
                raise DisplayError('Unsupported mode for ' + d['connector'] + '; select an advertised resolution and refresh rate.')
        result.append(d)
    merged = {d['connector']: d for d in current}
    merged.update({d['connector']: d for d in result})
    active = [d for d in merged.values() if d['enabled']]
    if not active:
        raise DisplayError('Cannot disable the last usable display.')
    for i, a in enumerate(active):
        ax, ay, aw, ah = bounds(a)
        for b in active[i + 1:]:
            bx, by, bw, bh = bounds(b)
            if min(ax + aw, bx + bw) - max(ax, bx) > 1 and min(ay + ah, by + bh) - max(ay, by) > 1:
                raise DisplayError('Displays overlap; move their edges apart. Mirroring is not supported.')
    return result


class Adapter:
    def run(self, *args):
        result = subprocess.run(['hyprctl', *args], text=True, capture_output=True, timeout=8)
        if result.returncode or result.stdout.lower().startswith(('error', 'invalid')):
            raise DisplayError(result.stderr.strip() or result.stdout.strip() or 'Hyprland request failed')
        return result.stdout

    def displays(self):
        return normalized(json.loads(self.run('-j', 'monitors', 'all')))

    def workspaces(self):
        return json.loads(self.run('-j', 'workspaces'))

    def apply(self, d):
        fields = ['output=' + lua_string(d['connector'])]
        if d['enabled']:
            fields += ['mode=' + lua_string(f"{d['width']}x{d['height']}@{d['refresh']:.5f}"),
                       'position=' + lua_string(f"{d['x']}x{d['y']}"), 'scale=' + str(d['scale']),
                       'transform=' + str(d['transform']), 'disabled=false']
        else:
            fields += ['disabled=true']
        self.run('eval', 'hl.monitor({' + ','.join(fields) + '})')

    def verify(self, desired):
        for _ in range(15):
            current = {d['connector']: d for d in self.displays()}
            if all(d['connector'] in current and same(d, current[d['connector']]) for d in desired):
                return list(current.values())
            time.sleep(.1)
        raise DisplayError('Hyprland did not apply the requested display settings. Reverting.')

    def move(self, workspace, connector):
        name = str(workspace)
        selector = name if name.isdigit() or name.startswith('name:') else 'name:' + name
        self.dispatch('workspace.move', '{workspace=' + lua_string(selector) + ',monitor=' + lua_string(connector) + '}')

    def dispatch(self, operation, arguments):
        self.run('eval', 'local r=hl.dispatch(hl.dsp.' + operation + '(' + arguments + ')); if type(r)=="table" and r.error then error(r.error) end')

    def power(self, connector, awake):
        fields = 'action=' + lua_string('on' if awake else 'off')
        if connector:
            fields += ',monitor=' + lua_string(connector)
        self.dispatch('dpms', '{' + fields + '}')

    def conflicts(self):
        import os
        root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'hypr'
        result = []
        for path in root.rglob('*.lua'):
            if path.name.startswith('hypertile'):
                continue
            try:
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    code = line.split('--', 1)[0]
                    if re.search(r'hl\.(monitor|workspace|workspace_rule)\s*\(', code):
                        result.append(dict(path=str(path), line=number, text=code.strip()))
            except (OSError, UnicodeError):
                continue
        return result
