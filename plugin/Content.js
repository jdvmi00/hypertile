// Presentation helpers shared by the overlay and its tests. No side effects.

// One short phrase for an app's state or a scene's phase. The
// empty string means there is nothing to say (no scene, no state).
var STATUS = {
  "waiting-session": "Waiting for session recovery", "waiting-window": "Opening app…",
  moved: "Moved", closed: "Closed", ready: "Ready", restored: "Previous arrangement restored",
  partial: "Some content needs attention", stopping: "Clearing previous placement…",
  layout: "Applying layout…", connecting: "Placing apps…", "needs-attention": "Needs attention",
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
  if (source.type === "app") return source.app_name || source.desktop_id
  return "Unknown source"
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
// is in, and whether the saved definition is behind.
function sceneTitle(scene) {
  if (!scene || !scene.phase || scene.phase === "none" || scene.phase === "restored") return "No scene"
  return (scene.document && scene.document.name) || "Unsaved scene"
}

function sceneModified(scene) {
  return !!(scene && scene.document && scene.document.name && scene.modified && scene.phase !== "restored")
}

function sceneMeta(scene, layout, workspace) {
  var bits = []
  if (layout) bits.push(layout + (workspace ? " on workspace " + workspace : ""))
  var s = scene ? status(scene.phase) : ""
  if (s !== "") bits.push(s)
  return bits.join("  ·  ")
}
