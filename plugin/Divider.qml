import QtQuick
import qs.Commons

// One draggable boundary between sibling zones. Visual only: the overlay's
// single pointer handler does the hit-testing and dragging, so this item is
// never destroyed under the pointer while the model changes.
Item {
  id: divider
  required property var overlay
  required property var modelData

  readonly property bool columns: modelData.kind === "columns"
  readonly property bool hot: {
    var d = overlay.dragDivider || overlay.hoverDivider
    return d && d.kind === modelData.kind && d.pos === modelData.pos && d.path.join() === modelData.path.join() && d.index === modelData.index
  }
  property int thickness: hot ? Math.max(3, Style.space(3)) : 1
  Behavior on thickness { NumberAnimation { duration: overlay.motionFast; easing.type: Easing.OutCubic } }
  readonly property int handleLength: Style.space(44)
  readonly property int handleThickness: Math.max(5, Style.space(6))

  x: columns ? modelData.x - thickness / 2 : modelData.x
  y: columns ? modelData.y : modelData.y - thickness / 2
  width: columns ? thickness : modelData.w
  height: columns ? modelData.h : thickness

  Rectangle {
    anchors.fill: parent
    color: divider.hot ? divider.overlay.accent : Util.alpha(divider.overlay.foreground, 0.28)
    Behavior on color { ColorAnimation { duration: divider.overlay.motionFast } }
  }

  // Grip that appears on hover, centered on the boundary.
  Rectangle {
    opacity: divider.hot ? 1 : 0
    scale: divider.hot ? 1 : 0.6
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: divider.overlay.motionFast; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: divider.overlay.motionFast; easing.type: Easing.OutBack } }
    anchors.centerIn: parent
    width: divider.columns ? divider.handleThickness : divider.handleLength
    height: divider.columns ? divider.handleLength : divider.handleThickness
    radius: Math.min(width, height) / 2
    color: divider.overlay.accent
    border.width: 1
    border.color: Util.alpha(Color.menu.background, 0.8)
  }
}
