"""Hyprland 0.56 Lua display adapter. Runtime preview and configuration reload operations."""
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path

from modes import AUTOMATIC, parse as parse_mode, same_mode, signature, value as mode_value


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
                           make=m.get('make', ''), model=m.get('model', ''),
                           connected=True, ambiguous=ambiguous, enabled=not m.get('disabled', False),
                           width=m['width'], height=m['height'], refresh=m['refreshRate'],
                           x=m['x'], y=m['y'], scale=m['scale'], transform=m.get('transform', 0),
                           modes=m.get('availableModes', []), awake=m.get('dpmsStatus', True),
                           active_workspace=m.get('activeWorkspace', {})))
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


def clean_scale(width, height, scale):
    # Hyprland accepts only scales that divide the mode into whole logical pixels.
    # Otherwise it rounds to 1/120, then searches outward in 1/120 steps and silently
    # substitutes the first clean value. Make the same substitution here so the
    # readback matches the request instead of failing and reverting.
    def clean(value):
        return value > 0 and all(abs(size / value - round(size / value)) < 1e-6 for size in (width, height))
    if width <= 0 or height <= 0 or clean(scale):
        return scale
    base = round(scale * 120)
    for step in range(90):
        for candidate in ((base + step) / 120, (base - step) / 120):
            if clean(candidate):
                return candidate
    return scale


def automatic_readback(requested, actual):
    """Recognize a native automatic choice without relaxing other settings."""
    if (requested.get('mode_policy') not in AUTOMATIC or not requested['enabled']
            or not actual['enabled'] or requested['connector'] != actual['connector']
            or any(actual[key] <= 0 for key in ('width', 'height', 'refresh'))):
        return False
    if not any(same_mode(actual, mode) for raw in actual.get('modes', [])
               if (mode := parse_mode(raw))):
        return False
    scale = clean_scale(actual['width'], actual['height'], requested['scale'])
    if not .25 <= scale <= 8 or any(abs(size / scale - round(size / scale)) > 1e-6
                                  for size in (actual['width'], actual['height'])):
        return False
    resolved = dict(requested, width=actual['width'], height=actual['height'],
                    refresh=actual['refresh'], scale=scale)
    return same(resolved, actual)


def bounds(d):
    w, h = d['width'], d['height']
    if d['transform'] % 2:
        w, h = h, w
    # CMonitor stores rounded logical dimensions, including fractional scales
    # represented with limited precision in IPC.
    return d['x'], d['y'], round(w / d['scale']), round(h / d['scale'])


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


def validate(document, current, known=()):
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('displays'), list):
        raise DisplayError('Expected version 1 settings with a displays array.')
    result, seen, connectors = [], set(), set()
    for source in document['displays']:
        if not isinstance(source, dict):
            raise DisplayError('Every display must be a settings object.')
        d = dict(source)
        if d.get('mode_policy', 'fixed') not in ('fixed', *AUTOMATIC):
            raise DisplayError('Choose an automatic mode or an advertised resolution and refresh rate.')
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
        d['scale'] = clean_scale(d['width'], d['height'], d['scale'])
        if not actual:
            continue  # Keep valid disconnected preferences without testing mode availability.
        if d.get('capability_signature') and d['capability_signature'] != signature(actual):
            raise DisplayError('Display connections or available modes changed. Refresh displays and preview again.')
        if actual['connector'] in connectors:
            raise DisplayError('More than one saved display matches ' + actual['connector'] + '; choose a single explicit match.')
        connectors.add(actual['connector'])
        if actual['ambiguous'] and not d.get('explicit_match'):
            raise DisplayError('Identical displays require an explicit connector match: ' + actual['connector'])
        d['connector'] = actual['connector']
        if d['enabled']:
            if (d.get('mode_policy') in AUTOMATIC and not actual['modes']
                    and d.get('mode_policy') != actual.get('mode_policy')):
                raise DisplayError('Automatic mode selection needs advertised modes for ' + d['connector'] + '; keep its current mode or choose a supported resolution.')
            if d['width'] <= 0 or d['height'] <= 0 or d['refresh'] <= 0:
                raise DisplayError('Select a supported resolution and refresh rate before enabling ' + d['connector'] + '.')
            if not .25 <= d['scale'] <= 8 or any(abs(size / d['scale'] - round(size / d['scale'])) > 1e-6 for size in (d['width'], d['height'])):
                raise DisplayError('Select a scale that divides the resolution into whole logical pixels.')
            modes = [re.fullmatch(r'(\d+)x(\d+)@([\d.]+)Hz', m) for m in actual['modes']]
            current_mode = d['width'] == actual['width'] and d['height'] == actual['height'] and abs(d['refresh'] - actual['refresh']) < .1 and d['width'] > 0 and d['height'] > 0
            # Virtual backends can advertise no modes and initialize none while
            # disabled. A previously confirmed mode is still safe to preview;
            # arbitrary unadvertised modes remain rejected.
            known_mode = not actual['enabled'] and not actual['modes'] and any(
                match(saved, current) == actual and saved['width'] == d['width'] and saved['height'] == d['height']
                and abs(saved['refresh'] - d['refresh']) < .1 for saved in known)
            if not current_mode and not known_mode and not any(m and int(m[1]) == d['width'] and int(m[2]) == d['height'] and abs(float(m[3]) - d['refresh']) < .1 for m in modes):
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
            if min(ax + aw, bx + bw) > max(ax, bx) and min(ay + ah, by + bh) > max(ay, by):
                raise DisplayError('Displays overlap; move their edges apart or choose a mirror source.')
    return result


class Adapter:
    def verify_outputs(self, displays, timeout=2.0):
        """IPC geometry alone does not prove the desktop is usable by clients."""
        from wayland import outputs
        required = {d['connector'] for d in displays if independent(d)}
        if not required:
            return
        deadline = time.monotonic() + timeout
        detail = ''
        while time.monotonic() < deadline:
            try:
                missing = required - outputs(timeout=max(.001, deadline - time.monotonic()))
                if not missing:
                    return
                detail = 'Missing: ' + ', '.join(sorted(missing)) + '.'
            except (OSError, ValueError) as error:
                detail = str(error)
            time.sleep(.05)
        raise DisplayError('Hyprland has not made the display available to desktop apps. '
                           + detail + ' The display change cannot safely continue.')

    def run(self, *args):
        result = subprocess.run(['hyprctl', *args], text=True, capture_output=True, timeout=8)
        if result.returncode or result.stdout.lower().startswith(('error', 'invalid')):
            raise DisplayError(result.stderr.strip() or result.stdout.strip() or 'Hyprland request failed')
        return result.stdout

    def displays(self):
        return normalized(json.loads(self.run('-j', 'monitors', 'all')))

    def workspaces(self):
        return json.loads(self.run('-j', 'workspaces'))

    def apply(self, d, *, preserve_mode=False, mode=None):
        fields = ['output=' + lua_string(d['connector'])]
        if d['enabled']:
            if not preserve_mode:
                fields.append('mode=' + lua_string(mode if mode is not None else mode_value(d)))
            fields += ['position=' + lua_string(f"{d['x']}x{d['y']}"), 'scale=' + str(d['scale']),
                       'transform=' + str(d['transform']), 'disabled=false',
                       'mirror=' + lua_string(d.get('mirror_connector') or '')]
        else:
            fields += ['disabled=true']
        self.run('eval', 'hl.monitor({' + ','.join(fields) + '})')

    def reposition(self, d):
        # hl.monitor merges a partial request into the rule of the same name
        # and keeps its other fields. Without such a rule the omitted settings
        # fall back to defaults, so callers send this only to an output whose
        # own connector rule is the one Hyprland applies.
        self.run('eval', 'hl.monitor({output=' + lua_string(d['connector']) +
                 ',position=' + lua_string(f"{d['x']}x{d['y']}") + '})')

    def verify(self, desired, *, resolve_modes=False):
        # A modeset or mirror can take a few seconds to show in the readback,
        # on real panels and on a loaded compositor alike; exact matches return
        # immediately, while automatic fallbacks get the full settling window.
        previous, stable = {}, 0
        for _ in range(50):
            current = {d['connector']: d for d in self.displays()}
            if all(d['connector'] in current and same(d, current[d['connector']]) for d in desired):
                return list(current.values())
            if resolve_modes and all(d['connector'] in current and
                    (same(d, current[d['connector']]) or automatic_readback(d, current[d['connector']])) for d in desired):
                stable = stable + 1 if all(d['connector'] in previous and
                    same(previous[d['connector']], current[d['connector']]) for d in desired) else 1
            else:
                stable = 0
            previous = current
            time.sleep(.1)
        # Give the estimate the usual settling interval before accepting an
        # advertised fallback. An early read can still describe the old mode.
        if resolve_modes and stable >= 3:
            return list(current.values())
        fields = ('enabled', 'width', 'height', 'refresh', 'x', 'y', 'scale', 'transform', 'mirror_of', 'mirror_connector')
        detail = '; '.join(d['connector'] + ': requested ' + str({k: d.get(k) for k in fields}) +
                           ', received ' + str({k: current.get(d['connector'], {}).get(k) for k in fields})
                           for d in desired if d['connector'] not in current or not same(d, current[d['connector']]))
        raise DisplayError('Hyprland did not apply the requested display settings. Reverting. ' + detail)

    def move(self, workspace, connector):
        name = str(workspace)
        selector = name if name.isdigit() or name.startswith(('name:', 'special:')) else 'name:' + name
        self.dispatch('workspace.move', '{workspace=' + lua_string(selector) + ',monitor=' + lua_string(connector) + '}')

    def dispatch(self, operation, arguments):
        self.run('eval', 'local r=hl.dispatch(hl.dsp.' + operation + '(' + arguments + ')); if type(r)=="table" and r.error then error(r.error) end')

    def power(self, connector, awake):
        fields = 'action=' + lua_string('on' if awake else 'off')
        if connector:
            fields += ',monitor=' + lua_string(connector)
        self.dispatch('dpms', '{' + fields + '}')

    # Hyprland keeps one global DPMS flag. Sleeping a single output clears it, after
    # which these options wake every output on the next key press or mouse move.
    WAKE_OPTIONS = ('key_press_enables_dpms', 'mouse_move_enables_dpms')

    def wake_options(self):
        return {name: bool(json.loads(self.run('-j', 'getoption', 'misc:' + name)).get('bool'))
                for name in self.WAKE_OPTIONS}

    def set_wake_options(self, options):
        fields = ','.join(name + '=' + ('true' if options[name] else 'false') for name in self.WAKE_OPTIONS)
        self.run('eval', 'hl.config({misc={' + fields + '}})')

    def reload(self):
        self.run('reload')
        errors = self.run('configerrors').strip()
        if errors:
            raise DisplayError('Hyprland configuration error: ' + errors)
