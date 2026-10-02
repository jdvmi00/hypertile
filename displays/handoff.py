"""Plan a mirror source change without changing physical display modes."""
import copy

from adapter import DisplayError, bounds, independent


def source_for(displays, connector):
    selected = next((d for d in displays if d['connector'] == connector and d.get('connected', True)), None)
    if not selected or not selected['enabled'] or not selected.get('awake', True):
        raise DisplayError('Choose a connected, enabled, awake display in a mirror group.')
    source = next((d for d in displays if d['id'] == selected.get('mirror_of')), selected)
    if not source.get('connected', True) or not independent(source):
        raise DisplayError('The mirror source is unavailable. Refresh displays first.')
    group = [d for d in displays if d['id'] == source['id'] or d.get('mirror_of') == source['id']]
    if not any(d['id'] != source['id'] and d.get('connected', True) and d['enabled'] for d in group):
        raise DisplayError('Set up a mirror group before switching its active display.')
    return selected, source, group


def plan(document, connector):
    next_document = copy.deepcopy(document)
    selected, source, group = source_for(next_document['displays'], connector)
    if selected['id'] == source['id']:
        return next_document, source['connector']
    selected.update(mirror_of=None, x=source['x'], y=source['y'])
    for display in group:
        display.pop('mirror_connector', None)
        if display['id'] != selected['id']:
            if display['id'] == source['id']:
                display.setdefault('extended_position', dict(x=source['x'], y=source['y']))
            display['mirror_of'] = selected['id']

    place(selected, [d for d in next_document['displays']
                     if d['id'] != selected['id'] and d.get('connected', True) and independent(d)])
    return next_document, source['connector']


def promotion(display, current):
    """Detach at a free position before moving the shared desktop's anchor."""
    transient = copy.deepcopy(display)
    if transient.get('extended_position'):
        transient.update(transient['extended_position'])
    place(transient, [d for d in current if d['connector'] != transient['connector'] and independent(d)])
    return transient


def place(selected, others):
    # Keep unrelated displays in place when a larger desktop needs free space.
    obstacles = [bounds(d) for d in others]
    x, y, width, height = bounds(selected)
    def free(left, top):
        return not any(min(left + width, ox + ow) > max(left, ox)
                       and min(top + height, oy + oh) > max(top, oy)
                       for ox, oy, ow, oh in obstacles)
    if not free(x, y):
        xs = {x} | {edge for ox, oy, ow, oh in obstacles for edge in (ox - width, ox + ow)}
        ys = {y} | {edge for ox, oy, ow, oh in obstacles for edge in (oy - height, oy + oh)}
        candidates = [(left, top) for left in xs for top in ys
                      if abs(left) <= 100000 and abs(top) <= 100000 and free(left, top)]
        if not candidates:
            raise DisplayError('No free desktop position for this display. Adjust the arrangement first.')
        selected['x'], selected['y'] = min(candidates, key=lambda p: ((p[0] - x) ** 2 + (p[1] - y) ** 2, p))
