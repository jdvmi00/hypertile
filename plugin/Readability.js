// Text colors for opaque overlay surfaces. Inputs are QML color values.
function luminance(color) {
  function linear(value) { return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4) }
  return 0.2126 * linear(color.r) + 0.7152 * linear(color.g) + 0.0722 * linear(color.b)
}
function contrast(a, b) {
  var x = luminance(a), y = luminance(b)
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}
function mix(foreground, background, amount) {
  return {r: background.r + (foreground.r - background.r) * amount,
    g: background.g + (foreground.g - background.g) * amount,
    b: background.b + (foreground.b - background.b) * amount}
}
function hex(color) {
  function channel(value) { return Math.round(Math.max(0, Math.min(1, value)) * 255).toString(16).padStart(2, "0") }
  return "#" + channel(color.r) + channel(color.g) + channel(color.b)
}
function textColor(foreground, background, amount) {
  var target = foreground
  if (contrast(target, background) < 4.6) {
    var black = {r: 0, g: 0, b: 0}, white = {r: 1, g: 1, b: 1}
    target = contrast(black, background) >= contrast(white, background) ? black : white
  }
  // A small margin survives rounding to 8-bit channels.
  var opacity = Math.max(0, Math.min(1, amount))
  for (; opacity < 1; opacity = Math.min(1, opacity + 0.02)) {
    var candidate = mix(target, background, opacity)
    if (contrast(candidate, background) >= 4.6) return hex(candidate)
  }
  return hex(target)
}
