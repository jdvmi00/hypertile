import QtQuick
import qs.Commons

// A small label pill: constraints on a zone, rules in the inspector, the
// dirty marker in the header. `strong` fills it with the accent color.
Rectangle {
  id: chip
  property string text: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.caption
  property bool strong: false
  property bool bold: false
  property bool dim: false

  implicitWidth: label.implicitWidth + Style.space(12)
  implicitHeight: label.implicitHeight + Style.space(6)
  radius: height / 2
  color: strong ? Color.accent : Util.alpha(Color.menu.background, 0.72)
  border.width: strong ? 0 : 1
  border.color: Util.alpha(chip.foreground, 0.22)

  Text {
    id: label
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: chip.text
    color: chip.strong ? Color.menu.background : Util.alpha(chip.foreground, chip.dim ? 0.6 : 0.92)
    font.family: chip.fontFamily
    font.pixelSize: chip.fontSize
    font.bold: chip.bold || chip.strong
  }
}
