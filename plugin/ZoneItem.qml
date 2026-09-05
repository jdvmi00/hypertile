import QtQuick
import QtQuick.Effects
import qs.Commons
import qs.Ui

// One zone of the viewed or edited layout, drawn at true scale over the
// windows it will hold. A badge in the corner carries the fill-order
// number(s) and the name, chips carry the constraints, and a faint numeral
// in the middle keeps the zone readable from across the screen. The
// selected zone gets an accent outline with a soft glow. Corners follow
// the layout's window rounding (the global one when it sets none).
Item {
  id: zone
  required property var overlay
  required property string name
  readonly property var modelData: overlay.zoneMap[name] || overlay.noZone
  // Geometry snaps while a divider is dragged and glides otherwise.
  readonly property bool animated: !overlay.dragDivider
  readonly property int motion: overlay.motion

  readonly property color fg: overlay.foreground
  readonly property color accent: overlay.accent
  readonly property bool editing: overlay.editing
  readonly property bool isSelected: (editing || overlay.contentMode) && overlay.selected === modelData.name
  readonly property bool isHovered: (editing || overlay.contentMode) && !overlay.numbering && !overlay.dragDivider && !overlay.hoverDivider && overlay.hoverZone === modelData.name
  readonly property var source: overlay.contentFor(modelData.name)
  readonly property bool isSpacer: modelData.spacer === true || (source !== null && source.type === "empty")
  readonly property bool fitted: modelData.fitted === true && !isSpacer
  readonly property int inset: Style.space(6)
  readonly property int stackCount: modelData.neverSplit ? 1 : Math.max(1, modelData.numbers.length)
  readonly property int pad: Math.max(Style.spacing.lg, Math.round(overlay.uiFont * 0.5))
  readonly property real capacity: {
    var spec = overlay.activeSpec
    return (spec && spec.capacity && spec.capacity[modelData.name]) ? spec.capacity[modelData.name] : 0
  }
  readonly property bool roomy: width > overlay.uiFont * 12 && height > overlay.uiFont * 6
  // Peeking: the card thins to a hairline so the windows underneath are the picture.
  readonly property bool peek: overlay.peeking
  readonly property string numeral: isSpacer ? "∅" : (modelData.numbers.length > 0 ? modelData.numbers.join(" · ") : (overlay.numbering ? "?" : "—"))

  x: modelData.x + inset
  y: modelData.y + inset
  width: Math.max(1, modelData.w - inset * 2)
  height: Math.max(1, modelData.h - inset * 2)
  clip: true

  Behavior on x { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
  Behavior on y { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
  Behavior on width { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
  Behavior on height { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }

  // New zones fade and settle in.
  opacity: 0
  scale: 0.97
  transformOrigin: Item.Center
  Behavior on opacity { NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
  Behavior on scale { NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
  Component.onCompleted: { opacity = 1; scale = 1 }

  // The fill-order badge pops when its number changes.
  onNumeralChanged: if (zone.overlay.editing) pop.restart()

  // The slot: a quiet tinted card with a hairline edge. While browsing the
  // tint is nearly gone: the windows under it are showing the layout.
  Rectangle {
    anchors.fill: parent
    radius: zone.overlay.effectiveRounding
    color: zone.peek ? "transparent" : (zone.isSpacer
      ? Util.alpha(zone.fg, zone.isSelected ? 0.08 : (zone.isHovered ? 0.06 : (zone.editing ? 0.03 : 0.015)))
      : Util.alpha(zone.accent, zone.fitted ? 0.04 : (zone.isSelected ? 0.16 : (zone.isHovered ? 0.12 : (zone.editing ? 0.08 : 0.03)))))
    border.width: zone.isSelected && !zone.peek ? Math.max(2, Style.space(2)) : 1
    border.color: zone.peek ? Util.alpha(zone.isSelected ? zone.accent : zone.fg, zone.isSelected ? 0.7 : 0.25)
      : zone.isSelected ? zone.accent
      : (zone.isHovered ? Util.alpha(zone.accent, 0.8)
      : Util.alpha(zone.isSpacer ? zone.fg : zone.accent, zone.isSpacer ? 0.35 : 0.55))
    Behavior on color { ColorAnimation { duration: overlay.motionFast } }
    Behavior on border.color { ColorAnimation { duration: overlay.motionFast } }
  }

  // Glow behind the selected zone's outline.
  Rectangle {
    opacity: zone.isSelected && !zone.peek ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: overlay.motionFast; easing.type: Easing.OutCubic } }
    anchors.fill: parent
    radius: zone.overlay.effectiveRounding
    color: "transparent"
    border.width: Math.max(2, Style.space(2))
    border.color: zone.accent
    layer.enabled: visible
    layer.effect: MultiEffect {
      shadowEnabled: true
      shadowColor: zone.accent
      shadowOpacity: 0.85
      shadowBlur: 1.0
      blurMax: 32
    }
  }

  // Where the window actually lands when aspect or scale shrink it.
  Rectangle {
    visible: zone.fitted
    x: zone.modelData.fit.x - zone.modelData.x
    y: zone.modelData.fit.y - zone.modelData.y
    width: Math.max(1, zone.modelData.fit.w - zone.inset * 2)
    height: Math.max(1, zone.modelData.fit.h - zone.inset * 2)
    Behavior on x { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
    Behavior on y { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
    Behavior on width { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
    Behavior on height { enabled: zone.animated; NumberAnimation { duration: zone.motion; easing.type: Easing.OutCubic } }
    radius: zone.overlay.effectiveRounding
    color: zone.peek ? "transparent" : Util.alpha(zone.accent, zone.isSelected ? 0.16 : 0.10)
    border.width: 1
    border.color: Util.alpha(zone.accent, zone.peek ? 0.4 : 0.9)
  }

  // One line per extra stacked window.
  Repeater {
    model: zone.stackCount > 1 ? zone.stackCount - 1 : 0
    Rectangle {
      required property int index
      readonly property bool vertical: zone.modelData.stack !== "h"
      readonly property var box: zone.fitted ? zone.modelData.fit : zone.modelData
      x: (box.x - zone.modelData.x) + (vertical ? 0 : Math.round(box.w * (index + 1) / zone.stackCount))
      y: (box.y - zone.modelData.y) + (vertical ? Math.round(box.h * (index + 1) / zone.stackCount) : 0)
      width: vertical ? box.w - zone.inset * 2 : 1
      height: vertical ? 1 : box.h - zone.inset * 2
      color: Util.alpha(zone.accent, 0.4)
    }
  }

  // Faint numeral in the middle.
  Text {
    visible: !zone.peek
    anchors.centerIn: parent
    width: parent.width - zone.pad * 2
    textFormat: Text.PlainText
    text: zone.numeral
    color: Util.alpha(zone.fg, zone.isSpacer ? 0.3 : (zone.isSelected ? 0.85 : (zone.editing ? 0.5 : 0.3)))
    font.family: zone.overlay.fontFamily
    font.bold: true
    font.pixelSize: Math.max(Style.font.heading, Math.min(zone.height * 0.3, zone.width * 0.26, Style.space(150)))
    horizontalAlignment: Text.AlignHCenter
    elide: Text.ElideRight
  }

  // Badge row: number, name (edit mode: names only matter when editing
  // rules or the file), then the constraint chips. The size chip opens the
  // rail's exact size field.
  Column {
    visible: !zone.peek
    x: zone.pad
    y: zone.pad
    width: parent.width - zone.pad * 2
    spacing: Style.spacing.sm

    Chip {
      visible: zone.source !== null || zone.overlay.contentMode
      text: zone.overlay.contentLabel(zone.modelData.name)
      foreground: zone.fg
      fontFamily: zone.overlay.fontFamily
      fontSize: zone.overlay.uiFontSmall
      strong: zone.source !== null && zone.source.type === "stream"
    }

    Row {
      spacing: Style.spacing.sm

      Chip {
        id: badge
        text: zone.numeral
        strong: !zone.isSpacer
        foreground: zone.fg
        fontFamily: zone.overlay.fontFamily
        fontSize: zone.overlay.uiFontSmall
        anchors.verticalCenter: parent.verticalCenter
        transformOrigin: Item.Center
        SequentialAnimation {
          id: pop
          NumberAnimation { target: badge; property: "scale"; to: 1.3; duration: 90; easing.type: Easing.OutCubic }
          NumberAnimation { target: badge; property: "scale"; to: 1; duration: 180; easing.type: Easing.OutBack }
        }
      }
      Chip {
        visible: zone.editing
        text: zone.modelData.name
        bold: true
        foreground: zone.fg
        fontFamily: zone.overlay.fontFamily
        fontSize: zone.overlay.uiFontSmall
        anchors.verticalCenter: parent.verticalCenter
      }
    }

    Flow {
      width: parent.width
      spacing: Style.spacing.xs
      visible: zone.roomy

      Repeater {
        model: {
          var m = zone.modelData
          var out = [m.pctW + "% × " + m.pctH + "%"]
          if (zone.isSpacer) out.push("spacer")
          if (m.neverSplit) out.push("never split")
          if (m.aspect) out.push(zone.overlay.aspectLabel(m.aspect))
          if (m.scale) out.push(Math.round(m.scale * 100) + "%")
          if (zone.capacity > 0) out.push("up to " + zone.capacity)
          if (!zone.isSpacer && m.stack === "h" && zone.stackCount > 1) out.push("side by side")
          return out
        }
        Chip {
          required property var modelData
          required property int index
          readonly property bool sizeChip: index === 0 && zone.editing
          text: modelData
          dim: !sizeChip
          foreground: zone.fg
          fontFamily: zone.overlay.fontFamily
          fontSize: zone.overlay.uiCaption
          MouseArea {
            anchors.fill: parent
            enabled: parent.sizeChip
            cursorShape: Qt.PointingHandCursor
            onClicked: zone.overlay.editSize(zone.modelData.name)
          }
        }
      }
    }
  }

  component ZoneButton: Button {
    bordered: true
    foreground: zone.fg
    accent: zone.accent
    fontFamily: zone.overlay.fontFamily
    fontSize: zone.overlay.uiCaption
    background: Util.alpha(Color.menu.background, 0.7)
    radius: zone.overlay.radiusControl
  }

  // Quick actions on the selected zone.
  Row {
    visible: zone.isSelected && !zone.overlay.numbering && zone.roomy && !zone.peek
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.margins: zone.pad
    spacing: Style.spacing.sm

    ZoneButton { text: "Columns"; tooltipText: "Split into columns (c)"; onClicked: zone.overlay.splitSelected("columns") }
    ZoneButton { text: "Rows"; tooltipText: "Split into rows (r)"; onClicked: zone.overlay.splitSelected("rows") }
    ZoneButton { text: "Delete"; tooltipText: "Delete zone (x, right-click)"; accent: Color.urgent; onClicked: zone.overlay.deleteZone(zone.modelData.name) }
  }
}
