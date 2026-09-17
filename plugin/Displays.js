// The diagram uses compositor logical coordinates: rotate before scaling.
function bounds(display) {
    var rotated = Number(display.transform || 0) % 2 === 1
    var scale = Number(display.scale) || 1
    return {
        x: Number(display.x) || 0,
        y: Number(display.y) || 0,
        w: (rotated ? display.height : display.width) / scale,
        h: (rotated ? display.width : display.height) / scale
    }
}

function extent(displays) {
    var active = displays.filter(function(display) {
        return display.connected && display.enabled
    })
    if (!active.length) return {x: 0, y: 0, w: 1920, h: 1080}

    var left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
    active.forEach(function(display) {
        var rect = bounds(display)
        left = Math.min(left, rect.x)
        top = Math.min(top, rect.y)
        right = Math.max(right, rect.x + rect.w)
        bottom = Math.max(bottom, rect.y + rect.h)
    })
    return {x: left, y: top, w: Math.max(1, right - left), h: Math.max(1, bottom - top)}
}

// Snap both adjoining edges and aligned edges. The caller converts a fixed
// visual snap distance into logical pixels so every arrangement feels alike.
function snap(displays, index, x, y, threshold) {
    var rect = bounds(displays[index])
    var bestX = threshold, bestY = threshold, snappedX = x, snappedY = y
    displays.forEach(function(display, otherIndex) {
        if (otherIndex === index || !display.enabled || !display.connected) return
        var other = bounds(display)
        var xs = [other.x, other.x + other.w, other.x - rect.w, other.x + other.w - rect.w]
        var ys = [other.y, other.y + other.h, other.y - rect.h, other.y + other.h - rect.h]
        xs.forEach(function(value) {
            if (Math.abs(value - x) < bestX) {
                bestX = Math.abs(value - x)
                snappedX = value
            }
        })
        ys.forEach(function(value) {
            if (Math.abs(value - y) < bestY) {
                bestY = Math.abs(value - y)
                snappedY = value
            }
        })
    })
    return {x: Math.round(snappedX), y: Math.round(snappedY)}
}

function clone(value) {
    return JSON.parse(JSON.stringify(value))
}

function modeLabel(mode) {
    var parsed = parseMode(mode)
    if (!parsed) return String(mode)
    return parsed.width + '×' + parsed.height + ' @ ' + parsed.refresh.toFixed(2) + ' Hz'
}

function parseMode(mode) {
    if (typeof mode !== 'string') {
        return {
            width: Number(mode.width),
            height: Number(mode.height),
            refresh: Number(mode.refresh || mode.refreshRate)
        }
    }
    var match = mode.match(/(\d+)[x×](\d+)[@\s]+([\d.]+)/)
    return match ? {width: Number(match[1]), height: Number(match[2]), refresh: Number(match[3])} : null
}

// An identical display must be chosen by connector, never by enumeration order.
function matchCandidates(document, index) {
    var saved = document.displays[index]
    if (!saved || saved.connected || !saved.identity) return []
    return document.displays.filter(function(display) {
        return display.connected && display.identity === saved.identity
    })
}

function matchSavedDisplay(document, index, connector) {
    var saved = document.displays[index]
    var candidates = matchCandidates(document, index).filter(function(display) {
        return display.connector === connector
    })
    if (!saved || !saved.id || candidates.length !== 1)
        throw new Error('Choose one connected display with the same identity to match these saved settings.')

    var live = candidates[0]
    var next = clone(document)
    // Saved identity, layout defaults, geometry and initial workspace win.
    // Only connection metadata comes from the explicitly selected output.
    var matched = Object.assign({}, clone(live), clone(saved), {
        connector: live.connector,
        connected: true,
        modes: clone(live.modes || []),
        awake: live.awake,
        ambiguous: live.ambiguous,
        explicit_match: true
    })
    matched.mode_available = matched.modes.some(function(mode) {
        var parsed = parseMode(mode)
        return parsed && parsed.width === Number(saved.width)
            && parsed.height === Number(saved.height)
            && Math.abs(parsed.refresh - Number(saved.refresh)) < 0.1
    })
    next.displays = next.displays.filter(function(display, otherIndex) {
        return otherIndex === index || !(display.connected && display.connector === live.connector)
    }).map(function(display) {
        return display.id === saved.id && !display.connected ? matched : display
    })
    Object.keys(next.workspaces || {}).forEach(function(workspace) {
        var preference = next.workspaces[workspace]
        if (preference.monitor === live.id) preference.monitor = saved.id
    })
    return next
}
