import QtQuick
import qs.Commons
import qs.Ui

// Home level of the panel: a full-width "Tout" tile (global on/off), then
// the 2-column grid of room tiles, Android Hue app style.
Column {
  id: root

  property var service: null
  signal openRoom(var room)

  width: parent ? parent.width : 0
  spacing: Style.space(10)

  function anyOn() {
    if (!service) return false
    for (var i = 0; i < service.groups.length; i++)
      if (service.groups[i].on) return true
    return false
  }

  // "Tout" — one tap kills or lights the whole house.
  Rectangle {
    width: parent.width
    height: Style.space(44)
    radius: Style.cornerRadius
    color: allMouse.containsMouse ? Qt.darker(Color.popups.background, 0.85) : Color.popups.background
    border.width: Style.normalBorderWidth
    border.color: allMouse.containsMouse ? Color.accent : Color.popups.border

    Text {
      anchors.left: parent.left
      anchors.leftMargin: Style.space(14)
      anchors.verticalCenter: parent.verticalCenter
      text: "\uf015"  // house
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.title
    }

    Text {
      anchors.left: parent.left
      anchors.leftMargin: Style.space(46)
      anchors.verticalCenter: parent.verticalCenter
      text: root.anyOn() ? "Tout éteindre" : "Tout allumer"
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Rectangle {
      anchors.right: parent.right
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(8)
      height: width
      radius: width / 2
      color: root.anyOn() ? Color.accent : "#555555"
    }

    MouseArea {
      id: allMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.service.setAllOn(!root.anyOn())
    }
  }

  Flow {
    width: parent.width
    spacing: Style.space(10)

    Repeater {
      model: root.service ? root.service.groups : []

      RoomTile {
        required property int index
        required property var modelData
        room: modelData
        onOpenRoom: function(room) { root.openRoom(room) }
      }
    }
  }
}