// Moving the diagram only makes sense relative to another desktop rectangle.
// Disabled, disconnected and mirrored outputs do not supply one.
function canArrange(displays) {
    return displays.filter(function(display) {
        return display.connected && display.enabled && !display.mirror_of
    }).length > 1
}

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
        return display.connected && display.enabled && !display.mirror_of
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
        if (otherIndex === index || !display.enabled || !display.connected || display.mirror_of) return
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
    next.displays.forEach(function(display) {
        if (display.mirror_of === live.id) display.mirror_of = saved.id
    })
    Object.keys(next.workspaces || {}).forEach(function(workspace) {
        var preference = next.workspaces[workspace]
        if (preference.monitor === live.id) preference.monitor = saved.id
    })
    return next
}

// Diagram numbers follow position, left to right and then top to bottom,
// so the number on a screen says where it stands rather than where the
// compositor listed it. A mirror counts right after its source; displays
// that are not on the desktop (disconnected, disabled, a mirror of an
// absent source) come last in list order. Returns the number of each
// display index.
function numbering(displays) {
    var keys = displays.map(function(d, i) {
        var source = d.mirror_of ? displays.findIndex(function(o) { return o.id === d.mirror_of }) : -1
        var anchor = source >= 0 ? displays[source] : d
        var onDesktop = !!(d.connected && d.enabled && anchor.connected && anchor.enabled && !anchor.mirror_of)
        var b = bounds(anchor)
        return {index: i, shown: onDesktop, x: b.x, y: b.y, mirror: source >= 0 ? 1 : 0}
    })
    keys.sort(function(p, q) {
        if (p.shown !== q.shown) return p.shown ? -1 : 1
        if (!p.shown) return p.index - q.index
        if (p.x !== q.x) return p.x - q.x
        if (p.y !== q.y) return p.y - q.y
        if (p.mirror !== q.mirror) return p.mirror - q.mirror
        return p.index - q.index
    })
    var out = []
    keys.forEach(function(k, n) { out[k.index] = n + 1 })
    return out
}

// Display indices in number order, for lists that should read like the diagram.
function order(numbers) {
    return numbers.map(function(n, i) { return i }).sort(function(p, q) { return numbers[p] - numbers[q] })
}

// Each independent display owns one desktop rectangle, with its mirrors
// grouped: "1 + 2". `numbers` may be handed in so a drag in progress keeps
// the labels it started with.
function groupLabel(displays, index, numbers) {
    var n = numbers || numbering(displays)
    return displays.map(function(d, i) {
        return i === index || (d.enabled && d.connected && d.mirror_of === displays[index].id) ? n[i] : null
    }).filter(function(x) { return x !== null }).sort(function(p, q) { return p - q }).join(" + ")
}

function usageOptions(displays, selected) {
    var options = [{label: "Extended display", value: "extended"}, {label: "Disabled", value: "disabled"}]
    var numbers = numbering(displays)
    displays.forEach(function(d, i) {
        if (d.id !== selected.id && d.connected && d.enabled && !d.mirror_of)
            options.push({label: "Mirror display " + numbers[i] + " · " + d.connector, value: d.id})
    })
    if (selected.mirror_of && !options.some(function(o) { return o.value === selected.mirror_of }))
        options.push({label: "Mirror source unavailable", value: selected.mirror_of})
    return options
}

function setUsage(document, index, value) {
    var next = clone(document), d = next.displays[index]
    if (value !== "extended" && value !== "disabled") {
        if (!d.mirror_of) d.extended_position = {x: d.x, y: d.y}
        d.mirror_of = value
        d.enabled = true
    } else {
        var wasMirror = !!d.mirror_of, wasDisabled = !d.enabled
        if (value === "disabled" && !wasMirror && d.enabled)
            d.extended_position = {x: d.x, y: d.y}
        d.enabled = value === "extended"
        if (value === "extended" && (wasMirror || wasDisabled)) {
            d.mirror_of = null
            if (d.extended_position) {
                d.x = d.extended_position.x
                d.y = d.extended_position.y
            } else if (wasMirror) {
                var rect = extent(next.displays.filter(function(other) { return other.id !== d.id }))
                d.x = Math.round(rect.x + rect.w)
                d.y = Math.round(rect.y)
            }
        }
    }
    return next
}

// Match Omarchy's monitor menu presets and its 1/120 clean-scale calculation.
// Keep the exact value for the compositor; round only the button label.
function scaleOptions(display) {
    if (!display || !(display.width > 0) || !(display.height > 0)) return []
    var a = Math.round(display.width * 120), b = Math.round(display.height * 120)
    while (b) { var remainder = a % b; a = b; b = remainder }
    var values = []
    ;[1, 1.25, 1.6, 2, 3, 4].forEach(function(preset) {
        var units = Math.min(a, Math.round(preset * 120))
        while (a % units !== 0) units++
        var value = units / 120
        if (value > 8 || values.some(function(option) { return option.value === value })) return
        values.push({value: value, label: String(Math.round(value * 100) / 100) + "x"})
    })
    return values
}

function nearestStop(stops, value) {
    var best = 0
    for (var i = 1; i < stops.length; i++)
        if (Math.abs(stops[i] - value) < Math.abs(stops[best] - value)) best = i
    return best
}

// Offer common workspace numbers, plus every live or saved workspace.
function workspaceSelector(workspace) {
    return Number(workspace.id) > 0 ? String(workspace.id) : "name:" + workspace.name;
}
function workspaceOptions(catalog, draft) {
    var keys = [];
    for (var i = 1; i <= 10; i++) keys.push(String(i));
    var live = catalog ? catalog.workspaces || [] : [];
    live.forEach(function (w) {
        if (w.name && w.name.indexOf("special:") !== 0 && w.name !== "special") keys.push(workspaceSelector(w));
    });
    keys = keys.concat(Object.keys(draft.workspaces || {}));
    (draft.displays || []).forEach(function (d) {
        if (d.initial_workspace) keys.push(d.initial_workspace);
    });
    return keys.filter(function (key, index) { return keys.indexOf(key) === index; }).map(function (key) {
        var current = live.find(function (w) { return workspaceSelector(w) === key; });
        return {value: key, label: key.replace(/^name:/, "") + (current ? " · " + current.monitor : "")};
    }).concat([{value: "", label: "Other workspace…"}]);
}
function validWorkspace(value) {
    return (/^[1-9][0-9]*$/.test(value) && Number(value) <= 2147483647) || /^name:[A-Za-z0-9_.:-]{1,128}$/.test(value);
}
