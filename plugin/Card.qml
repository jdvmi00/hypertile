import QtQuick
import qs.Commons
import qs.Ui

// A floating surface over the canvas, bordered the way the theme borders
// its menu (gradients and uneven widths included). Swallows presses so
// clicking chrome never closes the overlay or deselects a zone, and hands
// keyboard focus back to the overlay's key handler so shortcuts keep
// working after a control was used.
BorderSurface {
  id: card
  required property var overlay
  property bool accented: false
  property bool urgent: false

  radius: overlay.radiusCard
  color: Color.menu.background
  borderSpec: urgent ? Border.flat(Color.urgent, Math.max(1, Style.space(1)))
    : accented ? Border.flat(overlay.accent, Math.max(1, Style.space(1)))
    : Border.surfaceSpec("menu", "border", Color.menu.border, Math.max(1, Style.space(1)))

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onPressed: function(mouse) { mouse.accepted = true; card.overlay.focusKeys() }
  }
}
