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

function performance(report) {
  if (!report) return "Reconnect once to start collecting measurements."
  var current = report.current || {}, lines = []
  if (typeof current.window_ready_ms === "number")
    lines.push("Window ready in " + (current.window_ready_ms / 1000).toFixed(2) + " s · " + current.reason)
  var last = report.last_measurement
  if (last && last.metrics) {
    var m = last.metrics
    lines.push("Last decoder summary · " + last.profile)
    if (typeof m.decode_ms === "number") lines.push("Decode " + m.decode_ms.toFixed(2) + " ms")
    if (m.host_processing_ms) lines.push("Host processing " + m.host_processing_ms.average.toFixed(1) + " ms (includes more than encoding)")
    if (typeof m.network_rtt_ms === "number") lines.push("Network RTT " + m.network_rtt_ms + " ms")
    if (typeof m.rendered_fps === "number") lines.push("Rendered " + m.rendered_fps.toFixed(1) + " FPS")
    if (typeof m.network_drop_pct === "number") lines.push("Network loss " + m.network_drop_pct.toFixed(2) + "% · jitter loss " + m.jitter_drop_pct.toFixed(2) + "%")
  } else lines.push("No completed decoder measurements yet.")
  lines.push("Readability: " + (report.readability || "unverified"))
  return lines.concat(report.advice || []).join("\n")
}
