"""Hyprland 0.56 Lua display adapter. Runtime preview and configuration reload operations."""
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
    by_name = {d['connector']: d['id'] for d in result}
    by_number = {str(m['id']): m['name'] for m in monitors if 'id' in m}
    for d, m in zip(result, monitors):
        source = str(m.get('mirrorOf', 'none'))
        source = by_number.get(source, source)
        d['mirror_connector'] = source if source and source not in ('none', 'None') else None
        d['mirror_of'] = by_name.get(d['mirror_connector'], 'connector:' + d['mirror_connector'] if d['mirror_connector'] else None)
    return result


def independent(d):
    return d['enabled'] and not (d.get('mirror_of') or d.get('mirror_connector'))


def apply_order(d):
    return 2 if not d['enabled'] else 1 if d.get('mirror_of') or d.get('mirror_connector') else 0


def same(a, b):
    if bool(a.get('enabled')) != bool(b.get('enabled')):
        return False
    if not a.get('enabled'):
        return True
    if (a.get('mirror_connector') or a.get('mirror_of')) != (b.get('mirror_connector') or b.get('mirror_of')):
        return False
    geometry = ('width', 'height', 'transform') if a.get('mirror_of') or a.get('mirror_connector') else ('width', 'height', 'x', 'y', 'transform')
    return all(a.get(k) == b.get(k) for k in geometry) and abs(a['scale'] - b['scale']) < .001 and abs(a['refresh'] - b['refresh']) < .1


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


def runtime_mirrors(document, current):
    """Follow configuration-owned topology without rewriting saved preferences."""
    displays = [dict(d) for d in document.get('displays', [])]
    matches = [(d, match(d, current)) for d in displays]
    ids = {actual['connector']: d['id'] for d, actual in matches if actual}
    for d, actual in matches:
        if actual:
            d['mirror_of'] = ids.get(actual.get('mirror_connector'), actual.get('mirror_of'))
    return dict(document, displays=displays)


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
        position = d.get('extended_position')
        if position is not None and (not isinstance(position, dict) or any(type(position.get(k)) is not int or abs(position[k]) > 100000 for k in ('x', 'y'))):
            raise DisplayError('Saved extended position must contain integer x and y coordinates.')
        target = d.get('mirror_of')
        if target is not None and (not isinstance(target, str) or not target):
            raise DisplayError('Mirror source must be a display id or null.')
        d.pop('mirror_connector', None)  # Resolve trusted runtime connectors below.
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
    by_id = {d['id']: d for d in document['displays']}
    for d in result:
        target = d.get('mirror_of')
        if not target:
            continue
        source = by_id.get(target)
        actual = match(source, current) if source else None
        if target == d['id'] or not source or source.get('mirror_of'):
            raise DisplayError('Choose an independent display as the mirror source; chains and cycles are not supported.')
        if d['enabled'] and (not actual or not source['enabled']):
            raise DisplayError('Mirror source must be connected and enabled.')
        d['mirror_connector'] = actual['connector'] if actual else source['connector']
    active = [d for d in merged.values() if independent(d)]
    if not active:
        raise DisplayError('Cannot disable the last usable display.')
    for i, a in enumerate(active):
        ax, ay, aw, ah = bounds(a)
        for b in active[i + 1:]:
            bx, by, bw, bh = bounds(b)
            if min(ax + aw, bx + bw) - max(ax, bx) > 1 and min(ay + ah, by + bh) - max(ay, by) > 1:
                raise DisplayError('Displays overlap; move their edges apart or choose a mirror source.')
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
                       'transform=' + str(d['transform']), 'disabled=false',
                       'mirror=' + lua_string(d.get('mirror_connector') or '')]
        else:
            fields += ['disabled=true']
        self.run('eval', 'hl.monitor({' + ','.join(fields) + '})')

    def verify(self, desired):
        for _ in range(15):
            current = {d['connector']: d for d in self.displays()}
            if all(d['connector'] in current and same(d, current[d['connector']]) for d in desired):
                return list(current.values())
            time.sleep(.1)
        fields = ('enabled', 'width', 'height', 'refresh', 'x', 'y', 'scale', 'transform', 'mirror_of', 'mirror_connector')
        detail = '; '.join(d['connector'] + ': requested ' + str({k: d.get(k) for k in fields}) +
                           ', received ' + str({k: current.get(d['connector'], {}).get(k) for k in fields})
                           for d in desired if d['connector'] not in current or not same(d, current[d['connector']]))
        raise DisplayError('Hyprland did not apply the requested display settings. Reverting. ' + detail)

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

    def reload(self):
        self.run('reload')
        errors = self.run('configerrors').strip()
        if errors:
            raise DisplayError('Hyprland configuration error: ' + errors)
