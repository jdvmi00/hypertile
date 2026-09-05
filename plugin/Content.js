// Presentation helpers shared by the overlay and its tests. No side effects.

// One short phrase for a stream's observed state or a scene's phase. The
// empty string means there is nothing to say (no scene, no state).
var STATUS = {
  ready: "Ready", restored: "Previous arrangement restored", partial: "Some content needs attention",
  stopping: "Finishing previous connections…", layout: "Applying layout…", connecting: "Connecting…",
  preflight: "Checking host…", preparing: "Preparing display…", "preparing-display": "Preparing display…",
  "window-ready": "Connected", "startup-window": "Starting…", reconnecting: "Reconnecting…",
  disconnected: "Disconnected", restoring: "Restoring display…", "restore-pending": "Display restoration pending",
  "needs-attention": "Needs attention", degraded: "Connection needs attention", pending: "Pending",
  idle: "Not connected", "waiting-workspace": "Waiting for the workspace", "restore-builtin": "Restoring…"
}

function status(value) {
  if (!value || value === "none") return ""
  return STATUS[value] || value
}

// States that want the user's attention (drawn in the urgent color).
function troubled(value) {
  return ["partial", "needs-attention", "restore-pending", "degraded", "disconnected"].indexOf(value) !== -1
}

// States in which a stream is on its way to a window.
function inProgress(value) {
  return ["connecting", "preflight", "preparing", "preparing-display", "startup-window", "reconnecting", "restoring", "stopping", "layout", "pending"].indexOf(value) !== -1
}

function streamControls(runtime) {
  var r = runtime || {}, desired = r.desired === true
  var journal = !!r.journal && Object.keys(r.journal).length > 0
  var pending = inProgress(r.observed)
  var connected = desired && !!r.window
  return {
    focus: connected,
    disconnect: desired,
    reconnect: connected && ["window-ready", "degraded"].indexOf(r.observed) !== -1 ? "reconnect"
      : !desired && !r.pid && !r.window && !journal && !pending ? "connect" : "",
    retry: desired && !r.window && !pending,
    restore: !desired && journal && !pending
  }
}

function audio(value) {
  return value === "continuous" ? "Audio continues when you use local apps" :
    value === "host" ? "Use the host headset; local stream playback is muted" :
    "Audio plays while this desktop is focused"
}

function audioShort(value) {
  return value === "continuous" ? "audio continues" : value === "host" ? "host audio" : "audio while focused"
}

// What sets a profile apart from the defaults, for the picker rows.
function traits(profile) {
  var out = []
  if (!profile) return ""
  if (profile.audio === "continuous") out.push("audio continues")
  else if (profile.audio === "host") out.push("host audio")
  if (profile.input === "relative") out.push("captured pointer")
  if (profile.system_keys === "always") out.push("system keys")
  return out.join(" · ")
}

// The content assigned to `zone` on `workspace`: a live stream first, then
// the scene's record. Null means the zone holds local windows by fill order.
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

// What the zone holds, as a name: "Local windows", "Empty", an app class,
// or "computer · profile".
function label(source) {
  if (!source) return "Local windows"
  if (source.type === "empty") return "Empty"
  if (source.type === "local") return source.app_class || "Local windows"
  return source.computer + (source.profile ? " · " + source.profile : "")
}

// The zone card's chip: the name, plus the state while a stream is not
// simply connected.
function chip(source) {
  if (!source) return ""
  if (source.type !== "stream") return label(source)
  var s = status(source.status)
  return source.computer + (s !== "" && source.status !== "window-ready" ? " · " + s : "")
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
  var bits = [status(source.status) || "Pending"]
  var requested = source.runtime && source.runtime.requested ? source.runtime.requested : {}
  if (source.status === "window-ready") bits.push(audioShort(requested.audio))
  return bits.join(" · ")
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
