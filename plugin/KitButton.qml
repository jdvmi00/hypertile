import QtQuick
import qs.Commons
import qs.Ui

// The overlay's button, on every surface: the shell kit's Button at the
// overlay's type size and corner radius. `primary` marks the one main action
// of a surface (Use, Save, Keep changes) with an accent fill and outline, so
// it never reads like a selected tab or toggle.
Button {
  id: button
  required property var overlay
  property bool primary: false

  bordered: true
  radius: overlay.radiusControl
  foreground: overlay.foreground
  accent: overlay.accent
  fontFamily: overlay.fontFamily
  fontSize: overlay.uiFontSmall
  background: primary && enabled ? Util.alpha(accent, 0.22) : "transparent"
  opacity: enabled ? 1 : 0.45
  Accessible.role: Accessible.Button
  Accessible.name: text

  Rectangle {
    visible: button.primary && button.enabled && !button.hot && !button.activeFocus
    anchors.fill: parent
    radius: button.radius
    color: "transparent"
    border.width: Math.max(1, Style.space(1))
    border.color: button.accent
  }
}
