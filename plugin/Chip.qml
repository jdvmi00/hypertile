import QtQuick
import qs.Commons
import qs.Commons as Commons
import "Readability.js" as Readability

// A small label pill: constraints on a zone, rules in the inspector, the
// dirty marker in the header. `strong` fills it with the accent color.
Rectangle {
  id: chip
  property string text: ""
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.caption
  property bool strong: false
  property bool bold: false
  property bool dim: false

  implicitWidth: label.implicitWidth + Style.space(12)
  implicitHeight: label.implicitHeight + Style.space(6)
  radius: height / 2
  color: strong ? Qt.rgba(Commons.Color.accent.r, Commons.Color.accent.g, Commons.Color.accent.b, 1)
    : Qt.rgba(Commons.Color.menu.background.r, Commons.Color.menu.background.g, Commons.Color.menu.background.b, 1)
  border.width: strong ? 0 : 1
  border.color: Util.alpha(chip.foreground, 0.22)

  Text {
    id: label
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: chip.text
    color: Readability.textColor(chip.strong ? Commons.Color.menu.background : chip.foreground, chip.color, chip.dim ? 0.72 : 1)
    font.family: chip.fontFamily
    font.pixelSize: chip.fontSize
    font.bold: chip.bold || chip.strong
  }
}
