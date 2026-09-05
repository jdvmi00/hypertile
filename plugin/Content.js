// Presentation helpers shared by the overlay and its tests. No side effects.
function status(value) {
  var labels = { none: "No active scene", ready: "Ready", restored: "Previous workspace restored",
    partial: "Some content needs attention", stopping: "Finishing previous connections", layout: "Applying layout",
    connecting: "Connecting", preflight: "Checking host", preparing: "Preparing display", "preparing-display": "Preparing display",
    "window-ready": "Window ready", "startup-window": "Starting window", reconnecting: "Reconnecting",
    disconnected: "Disconnected", restoring: "Restoring display", "restore-pending": "Display restoration pending",
    "needs-attention": "Needs attention", degraded: "Connection needs attention", pending: "Pending" }
  return labels[value] || value || "Local windows"
}

function audio(value) {
  return value === "continuous" ? "Audio continues when you use local apps" :
    value === "host" ? "Use the host headset; local stream playback is muted" :
    "Audio plays while this desktop is focused"
}

function source(catalog, workspace, zone, active) {
  if (!active || !catalog) return null
  var streams = catalog.streams || []
  for (var i = 0; i < streams.length; i++) {
    var r = streams[i]
    if (r.desired && r.assignment.workspace === workspace && r.assignment.zone === zone)
      return { type: "stream", computer: r.computer, profile: r.profile, status: r.observed, error: r.error, runtime: r }
  }
  var sources = (catalog.current || {}).sources || []
  if ((catalog.current || {}).phase === "restored") return null
  for (var j = 0; j < sources.length; j++) if (sources[j].zone === zone) {
    var item = sources[j]
    if (item.type === "stream") {
      for (var k = 0; k < streams.length; k++) if (streams[k].computer === item.computer)
        return { type: item.type, computer: item.computer, profile: item.profile, status: item.status, error: item.error, runtime: streams[k] }
    }
    return item
  }
  return null
}

function label(source) {
  if (!source) return "Local windows"
  if (source.type === "empty") return "Empty"
  if (source.type === "local") return source.app_class || "Local windows"
  return source.computer + " · " + status(source.status)
}
