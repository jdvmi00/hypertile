// Presentation helpers shared by the overlay and its tests. No side effects.

// One short phrase for an app's state or a scene's phase. The
// empty string means there is nothing to say (no scene, no state).
var STATUS = {
  "waiting-session": "Waiting for session recovery", "waiting-window": "Opening app…",
  moved: "Moved", closed: "Closed", ready: "Ready", restored: "Previous arrangement restored",
  partial: "Some content needs attention", stopping: "Clearing previous placement…",
  layout: "Using layout…", connecting: "Placing apps…", "needs-attention": "Needs attention",
  pending: "Pending", "waiting-workspace": "Waiting for the workspace", "restore-builtin": "Restoring…"
}

function status(value) {
  if (!value || value === "none") return ""
  return STATUS[value] || value
}

// States that want the user's attention (drawn in the urgent color).
function troubled(value) {
  return ["partial", "needs-attention"].indexOf(value) !== -1
}

function managed(scene) {
  return !!(scene && scene.phase && ["none", "restored", "waiting-session"].indexOf(scene.phase) === -1)
}

function retrySummary(scene) {
  var apps = ((scene && scene.sources) || []).filter(function(s) { return s.type === "app" })
  var names = appNames(apps)
  return names.length ? "Retry uses this scene's layout and opens or reuses " + names.join(", ") + "."
    : "Retry uses this scene's layout and zone assignments. It opens no apps."
}

// The content assigned to a zone from the active scene. Null means the zone holds local windows by fill order.
function source(catalog, workspace, zone, active) {
  if (!active || !catalog) return null
  var sources = (catalog.current || {}).sources || []
  if ((catalog.current || {}).phase === "restored") return null
  for (var j = 0; j < sources.length; j++) if (sources[j].zone === zone) {
    var item = sources[j]
    return item
  }
  return null
}

// What the zone holds, as a name: "Local windows", "Empty", an app class,
// or an installed app name.
function label(source) {
  if (!source) return "Local windows"
  if (source.type === "empty") return "Empty"
  if (source.type === "local") return source.app_class || "Local windows"
  if (source.type === "app") return displayName(source.app_name || source.desktop_id)
  return "Unknown source"
}

// Remote Desktops installs one launcher per computer, named "X (Remote
// Desktop)"; the picker groups them apart and drops the suffix.
function isRemoteDesktop(app) {
  return !!app && (String(app.desktop_id || "").indexOf("remote-desktops-") === 0 || !!app.app_title)
}

function displayName(name) {
  return String(name || "").replace(/\s*\(Remote Desktop\)\s*$/, "")
}

// The zone card's chip shows its assigned content.
function chip(source) {
  if (!source) return ""
  return label(source)
}

// The state of a zone's content in a few words, and whether it is a problem.
function state(source) {
  if (!source) return { text: "", urgent: false }
  if (source.type === "empty") return { text: "", urgent: false }
  if (source.type === "local") return source.status === "needs-attention"
    ? { text: "Pending", urgent: true } : { text: "", urgent: false }
  var s = source.status
  return { text: status(s) || "Pending", urgent: troubled(s) }
}

// A sentence under the zone's title.
function detail(source) {
  if (!source) return "Windows open here in fill order"
  if (source.type === "empty") return "Nothing opens here; the zone stays empty"
  if (source.type === "local") return source.status === "needs-attention"
    ? (source.error || "No matching window on this workspace yet")
    : "One matching window is pinned here"
  if (source.type === "app") return source.error || (source.status === "moved"
    ? "Moved by you; apply the scene again to place it here"
    : source.status === "closed" ? "Closed by you; apply the scene again to open it"
    : source.status === "waiting-window" ? "Waiting for the app window"
    : "Placed here once; you can move it to any workspace")
  return source.error || "Unknown source"
}

// The header for the workspace's scene: what it is called, what state it
// is in, and whether the saved definition is behind. Without a scene the
// header is about the workspace itself.
function sceneTitle(scene, workspace) {
  if (!scene || !scene.phase || scene.phase === "none" || scene.phase === "restored") return workspace ? "Workspace " + workspace : "No scene"
  return (scene.document && scene.document.name) || "Unsaved scene"
}

function sceneModified(scene) {
  return !!(scene && scene.document && scene.document.name && scene.modified && scene.phase !== "restored")
}

// How far the scene has come: "2 of 3 placed" while apps are placed, then
// the phase in words.
function sceneProgress(scene) {
  var phase = scene ? scene.phase : ""
  var sources = (scene && scene.sources) || []
  var n = 0, placed = 0, trouble = 0
  for (var i = 0; i < sources.length; i++) {
    var s = sources[i]
    if (s.type !== "app" && !(s.type === "local" && s.app_class)) continue
    n++
    if (s.status === "ready") placed++
    else if (troubled(s.status) || s.error) trouble++
  }
  if (n > 0 && ["connecting", "partial", "ready"].indexOf(phase) !== -1) {
    var t = placed + " of " + n + " placed"
    if (trouble > 0) t += "  ·  " + trouble + (trouble === 1 ? " needs attention" : " need attention")
    return t
  }
  return status(phase)
}

function sceneMeta(scene, layout, workspace) {
  var bits = []
  if (layout) bits.push(layout)
  var active = !!(scene && scene.phase && scene.phase !== "none" && scene.phase !== "restored")
  if (!active) {
    if (scene && scene.phase === "restored") bits.push(status("restored"))
    else if (layout) bits.push("local windows in every zone")
    return bits.join("  ·  ")
  }
  if (workspace) bits.push("workspace " + workspace)
  if (scene.deleted) bits.push("Deleted scene")
  var p = sceneProgress(scene)
  if (p !== "") bits.push(p)
  return bits.join("  ·  ")
}

// The apps a scene places, by name, and a short form for a card's meta
// line: "Chrome, Cursor +2".
function appNames(sources) {
  var out = []
  for (var i = 0; i < (sources || []).length; i++) {
    var s = sources[i]
    if (s.type === "app") out.push(displayName(s.app_name || s.desktop_id))
    else if (s.type === "local" && s.app_class) out.push(s.app_class)
  }
  return out
}

function summary(names, max) {
  max = max || 2
  if (names.length <= max) return names.join(", ")
  return names.slice(0, max).join(", ") + " +" + (names.length - max)
}

// Case-insensitive substring match of a search query against any field.
function matches(query, fields) {
  var q = String(query || "").trim().toLowerCase()
  if (q === "") return true
  for (var i = 0; i < fields.length; i++) if (String(fields[i] || "").toLowerCase().indexOf(q) !== -1) return true
  return false
}

// The windows open on a workspace, one entry per class: the one title
// when there is one window, else how many there are.
function openApps(windows, workspace) {
  var by = {}, out = []
  for (var i = 0; i < (windows || []).length; i++) {
    var w = windows[i]
    if (String(w.workspace) !== String(workspace) || !w.class) continue
    if (!by[w.class]) { by[w.class] = { app_class: w.class, count: 0, title: "" }; out.push(by[w.class]) }
    by[w.class].count++
    by[w.class].title = w.title || ""
  }
  out.sort(function(a, b) { return a.app_class < b.app_class ? -1 : a.app_class > b.app_class ? 1 : 0 })
  return out
}

// Where a zone sits, in words: "Top left", "Right", "Full screen". A word
// is used only when it tells zones apart, so a column that fills the
// height is just "Left". Zones whose words would collide get "" and are
// shown by their layout name instead.
function positionLabel(zone, area) {
  var tol = Math.max(2, Math.min(area.w, area.h) * 0.02)
  var left = zone.x <= area.x + tol, right = zone.x + zone.w >= area.x + area.w - tol
  var top = zone.y <= area.y + tol, bottom = zone.y + zone.h >= area.y + area.h - tol
  var h = (left && right) ? "" : left ? "left" : right ? "right" : "center"
  var v = (top && bottom) ? "" : top ? "top" : bottom ? "bottom" : "middle"
  var words = (v + " " + h).trim()
  if (words === "") return "Full screen"
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function positionLabels(zones, area) {
  var labels = {}, counts = {}
  if (!area) return labels
  for (var i = 0; i < zones.length; i++) {
    var l = positionLabel(zones[i], area)
    labels[zones[i].name] = l
    counts[l] = (counts[l] || 0) + 1
  }
  for (var name in labels) if (counts[labels[name]] > 1) labels[name] = ""
  return labels
}

// Action acknowledgements can precede placement by several catalog polls.
function actionFeedback(record, done, zone) {
  if (record.phase === "restored") return done
  if (record.phase === "ready") {
    var source = (record.sources || []).find(function(s) { return s.zone === zone })
    if (zone && source && source.status !== "ready") return status(source.status)
    return done
  }
  return status(record.phase) || "Scene update requested"
}
