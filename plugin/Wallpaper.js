// Wallpaper preferences are separate from monitor geometry and themes.
function groupFor(config, output) {
    return (config.groups || []).find(function (g) { return g.outputs.indexOf(output) >= 0; })
        || { outputs: [output], mode: "repeat", image: null, fit: "crop" };
}
function setGroup(config, output, group) {
    var next = JSON.parse(JSON.stringify(config));
    var claimed = group.outputs;
    next.groups = (next.groups || []).map(function (g) {
        var remaining = g.outputs.filter(function (name) { return claimed.indexOf(name) < 0 && name !== output; });
        return Object.assign({}, g, {outputs: remaining, mode: remaining.length < 2 ? "repeat" : g.mode});
    }).filter(function (g) { return g.outputs.length > 0; });
    next.groups.push(JSON.parse(JSON.stringify(group)));
    return next;
}
// Screen geometry is in logical desktop pixels, including negative origins.
// Missing outputs are excluded; reconnect automatically restores the full span.
function frame(config, output, screens) {
    var screen = screens.find(function (s) { return s.name === output; });
    if (!screen) return {x: 0, y: 0, width: 1, height: 1};
    var group = groupFor(config, output);
    var members = group.mode === "span" ? screens.filter(function (s) { return group.outputs.indexOf(s.name) >= 0; }) : [screen];
    var left = Math.min.apply(null, members.map(function (s) { return s.x; }));
    var top = Math.min.apply(null, members.map(function (s) { return s.y; }));
    var right = Math.max.apply(null, members.map(function (s) { return s.x + s.width; }));
    var bottom = Math.max.apply(null, members.map(function (s) { return s.y + s.height; }));
    return {x: left - screen.x, y: top - screen.y, width: right - left, height: bottom - top};
}
