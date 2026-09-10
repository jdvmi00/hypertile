// Session saving feedback shared by the bar and overlay.
function parse(text) {
  try {
    var value = JSON.parse(text)
    return value && ["watching", "restoring", "partial", "frozen", "disabled"].indexOf(value.mode) !== -1 ? value : null
  } catch (e) { return null }
}

function attention(state, available, checked) {
  if (!checked) return false
  if (!available) return true
  if (!state || state.mode === "disabled") return false
  return state.mode !== "watching" || !!state.error || !!(state.saving && state.saving.warning)
    || !!(state.scene_delivery && state.scene_delivery.pending)
}

function summary(state, available, checked) {
  if (!checked) return "Checking session saving…"
  if (!available) return "Session saving is unavailable"
  if (!state || state.mode === "disabled") return "Session saving is disabled"
  var count = Number(state.matched || 0) + " of " + Number(state.total || 0) + " windows restored"
  if (state.mode === "partial") return "Saving paused: " + count
  if (state.mode === "frozen") return "Saving paused: session frozen"
  if (state.mode === "restoring") return "Saving paused during recovery: " + count
  if (state.error) return "Saving paused: " + state.error
  if (state.scene_delivery && state.scene_delivery.pending)
    return "Saving continues; " + state.scene_delivery.pending + " scene recovery request(s) waiting to be delivered"
  if (state.saving && state.saving.warning) return state.saving.warning
  return "Session saving is active"
}

function canResume(state) {
  return !!(state && state.saving && state.saving.can_resume)
}
