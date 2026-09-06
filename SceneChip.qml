import QtQuick
import qs.Commons
import qs.Ui

// Pill button recalling one scene — used in the room view (and anywhere a
// compact scene selector fits).
Rectangle {
  id: root

  property var scene: null
  signal recalled(var scene)

  width: chipText.width + Style.space(20)
  height: Style.space(26)
  radius: height / 2
  color: chipMouse.containsMouse ? Qt.darker(Color.popups.background, 0.85) : Color.popups.background
  border.width: Style.normalBorderWidth
  border.color: chipMouse.containsMouse ? Color.accent : Color.popups.border

  Text {
    id: chipText
    anchors.centerIn: parent
    text: root.scene ? root.scene.name : ""
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

  MouseArea {
    id: chipMouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.recalled(root.scene)
  }
}