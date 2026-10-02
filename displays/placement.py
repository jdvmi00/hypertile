"""Keep saved, touching display edges attached as logical sizes change.

The reference rectangles describe placement intent, not modes to restore. All
dimensions and output state in the result come from the current compositor.
"""
from collections import deque

from adapter import bounds, independent, match
from handoff import place


def active(display):
    return (display.get('connected', True) and independent(display)
            and display['width'] > 0 and display['height'] > 0 and display['scale'] > 0)


def snapshot(displays):
    """Only geometry/identity belongs in the placement journal, not mode lists."""
    keys = ('id', 'identity', 'connector', 'description', 'explicit_match', 'ambiguous',
            'connected', 'enabled', 'mirror_of', 'mirror_connector',
            'width', 'height', 'scale', 'transform', 'x', 'y')
    return sorted(({key: d[key] for key in keys if key in d} for d in displays),
                  key=lambda d: d['connector'])


def shape(displays):
    # IPC scale rounding must not look like a resize. Positions are deliberately
    # excluded so a manual move can establish a new reference arrangement.
    return [(d['id'], d.get('identity'), d['connector'], d['enabled'],
             d.get('mirror_connector') or d.get('mirror_of'),
             bounds(d)[2:] if active(d) else None) for d in snapshot(displays)]


def edge(a, b):
    ax, ay, aw, ah = bounds(a)
    bx, by, bw, bh = bounds(b)
    if min(ay + ah, by + bh) > max(ay, by):
        if abs(ax + aw - bx) <= 1:
            return 'right'
        if abs(bx + bw - ax) <= 1:
            return 'left'
    if min(ax + aw, bx + bw) > max(ax, bx):
        if abs(ay + ah - by) <= 1:
            return 'down'
        if abs(by + bh - ay) <= 1:
            return 'up'
    return None


def aligned(start, size, old_start, old_size, other_start, other_size, new_size):
    """Retain top/left, bottom/right, center, or an intentional edge offset."""
    if abs(other_start - old_start) <= 1:
        return start
    if abs(other_start + other_size - old_start - old_size) <= 1:
        return start + size - new_size
    if abs(2 * other_start + other_size - 2 * old_start - old_size) <= 1:
        return round(start + (size - new_size) / 2)
    return start + other_start - old_start


def project(reference, current, fixed=()):
    """Resolve a deterministic forest of adjoining edges, without moving modes.

    Unattached/manual positions are fixed. Missing, disabled and mirrored
    outputs do not occupy space or become anchors. In an overconstrained layout
    (e.g. an uneven grid after rotation), keep the closest free edge position.
    Always solve from the reference so repeated size changes cannot drift.
    Connectors in `fixed` cannot be moved: they stay where they are and anchor
    their neighbours.
    """
    refs, live = {}, {}
    used = set()
    for saved in reference:
        actual = match(saved, current)
        if not active(dict(saved, connected=True)) or not actual or not active(actual) or actual['connector'] in used:
            continue
        # A connector-derived id alone must not match replacement hardware.
        if saved.get('identity') != actual.get('identity'):
            continue
        refs[saved['id']] = saved
        live[saved['id']] = dict(actual)
        used.add(actual['connector'])
    links = {key: [(other, direction) for other in refs if other != key
                   and (direction := edge(refs[key], refs[other]))] for key in refs}
    managed = {key for key in refs if links[key]}
    connectors = {live[key]['connector'] for key in managed}
    movable = {key for key in managed if live[key]['connector'] not in fixed}
    obstacles = [d for d in current if active(d)
                 and d['connector'] not in connectors] + [live[key] for key in managed - movable]
    order = sorted(managed, key=lambda key: (key in movable, abs(refs[key]['x']) + abs(refs[key]['y']),
                                            refs[key]['x'], refs[key]['y'], refs[key]['connector']))
    seen = set()
    for root in order:
        if root in seen:
            continue
        if root in movable:
            live[root].update(x=refs[root]['x'], y=refs[root]['y'])
        seen.add(root)
        queue = deque([root])
        while queue:
            key = queue.popleft()
            parent = live[key]
            if key in movable:
                place(parent, obstacles)
                obstacles.append(parent)
            x, y, width, height = bounds(parent)
            ox, oy, ow, oh = bounds(refs[key])
            for child, direction in sorted(links[key]):
                if child in seen:
                    continue
                seen.add(child)
                queue.append(child)
                if child not in movable:
                    continue
                target = live[child]
                cx, cy, cw, ch = bounds(refs[child])
                _, _, nw, nh = bounds(target)
                if direction in ('left', 'right'):
                    target['x'] = x + width if direction == 'right' else x - nw
                    target['y'] = aligned(y, height, oy, oh, cy, ch, nh)
                else:
                    target['y'] = y + height if direction == 'down' else y - nh
                    target['x'] = aligned(x, width, ox, ow, cx, cw, nw)
    resolved = {live[key]['connector']: live[key] for key in managed}
    return [resolved.get(d['connector'], dict(d)) for d in current]


def rebase(reference, current, fixed=()):
    """Restate the reference at the current sizes, so that outputs repositioned
    in the configuration join it in one frame. Outputs that are absent,
    disabled or mirrored now keep their entry until they return."""
    held = [d for d in reference if not ((actual := match(d, current)) and active(actual))]
    return snapshot([d for d in project(reference, current, fixed) if active(d)] + held)
