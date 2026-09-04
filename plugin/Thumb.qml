import QtQuick
import qs.Commons
import "Geometry.js" as Geometry

// A small picture of a layout: its zones in the monitor's proportions, the
// first fill number in each zone that has room for it. Used by the rail's
// layout list so a shape can be recognised before it is browsed to.
Item {
  id: thumb
  required property var overlay
  property var spec: null
  property bool current: false
  property color foreground: overlay.foreground
  property color accent: overlay.accent

  // Until the monitor is known (the first read is in flight), draw 16:9.
  readonly property real ratio: (overlay.current && overlay.current.monitor && overlay.current.monitor.width > 0)
    ? overlay.current.monitor.height / overlay.current.monitor.width : 9 / 16
  readonly property int gap: 2
  readonly property var boxes: spec ? Geometry.zones(spec, { x: 0, y: 0, w: width, h: height }) : []

  height: Math.round(width * ratio)

  Rectangle {
    anchors.fill: parent
    radius: Style.space(3)
    color: Util.alpha(thumb.foreground, 0.05)
    border.width: 1
    border.color: Util.alpha(thumb.current ? thumb.accent : thumb.foreground, thumb.current ? 0.9 : 0.2)
  }

  // Where the window lands: the fitted box when aspect or scale shrink the
  // zone, so the picture matches what the layout does on screen.
  Repeater {
    model: thumb.boxes
    Rectangle {
      required property var modelData
      readonly property bool spacer: modelData.spacer === true
      readonly property var box: modelData.fitted ? modelData.fit : modelData
      x: box.x + thumb.gap
      y: box.y + thumb.gap
      width: Math.max(1, box.w - thumb.gap * 2)
      height: Math.max(1, box.h - thumb.gap * 2)
      radius: Style.space(2)
      color: spacer ? "transparent" : Util.alpha(thumb.accent, thumb.current ? 0.35 : 0.22)
      border.width: 1
      border.color: Util.alpha(spacer ? thumb.foreground : thumb.accent, spacer ? 0.25 : 0.7)
      Text {
        anchors.centerIn: parent
        visible: !parent.spacer && parent.width > implicitWidth + 4 && parent.height > implicitHeight + 2 && modelData.numbers.length > 0
        textFormat: Text.PlainText
        text: modelData.numbers.length > 0 ? String(modelData.numbers[0]) : ""
        color: Util.alpha(thumb.foreground, 0.85)
        font.family: thumb.overlay.fontFamily
        font.pixelSize: Math.max(8, Math.min(thumb.overlay.uiCaption, parent.height * 0.6))
        font.bold: true
      }
    }
  }
}
