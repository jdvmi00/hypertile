"""Display mode intent and capability checks, independent of hardware access."""
import hashlib
import json
import re


AUTOMATIC = {
    'preferred': 'Automatic (display default)',
    'highres': 'Automatic (highest resolution)',
    'highrr': 'Automatic (highest refresh rate)',
    'maxwidth': 'Automatic (widest resolution)',
}


def parse(value):
    match = re.fullmatch(r'(\d+)x(\d+)@(\d+(?:\.\d+)?)Hz', value)
    if not match:
        return None
    return dict(width=int(match[1]), height=int(match[2]), refresh=float(match[3]))


def same_mode(a, b):
    return (a.get('width'), a.get('height')) == (b.get('width'), b.get('height')) and isinstance(a.get('refresh'), (int, float)) and isinstance(b.get('refresh'), (int, float)) and abs(a['refresh'] - b['refresh']) < .1


def signature(display):
    # Enumeration order and harmless formatting changes are not capability changes.
    modes = sorted({(m['width'], m['height'], round(m['refresh'], 2))
                    for value in display.get('modes', []) if (m := parse(value))})
    identity = display.get('identity', display['id'].split('@')[0])
    return hashlib.sha256(json.dumps([identity, modes]).encode()).hexdigest()


def value(display):
    policy = display.get('mode_policy', 'fixed')
    return policy if policy in AUTOMATIC else f"{display['width']}x{display['height']}@{display['refresh']:.5f}"


def automatic_options(display):
    """Preview estimates; the compositor owns selection and verifies the result."""
    modes = [mode for raw in display.get('modes', []) if (mode := parse(raw))]
    options = []
    if modes:
        best = max(modes, key=lambda m: (m['width'] * m['height'], m['width'], m['refresh']))
        options.append(dict(best, mode_policy='highres', label=AUTOMATIC['highres']))
    policy = display.get('mode_policy')
    if policy in AUTOMATIC and policy != 'highres' and display.get('width', 0) > 0:
        # Preserve existing native policies, without guessing the display's
        # preferred flag from an IPC list that does not include that flag.
        options.insert(0, dict(width=display['width'], height=display['height'],
                               refresh=display['refresh'], mode_policy=policy, label=AUTOMATIC[policy]))
    return options
