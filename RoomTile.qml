import QtQuick
import qs.Commons
import qs.Ui

// One room tile in the Android-style grid: class glyph, room name, on/off
// dot, background tinted with the room's average chromaticity (tintHex).
Rectangle {
  id: root

  property var room: null
  signal openRoom(var room)

  width: parent ? (parent.width - parent.spacing) / 2 : 160
  height: Style.space(64)
  radius: Style.cornerRadius
  color: {
    if (!room) return Color.popups.background
    if (!room.on) return Qt.darker(Color.popups.background, 1.15)
    return Qt.tint(Qt.rgba(0.08, 0.08, 0.08, 0.9), Qt.rgba(
      (parseInt(room.tintHex.slice(1, 3), 16) / 255) * 0.55,
      (parseInt(room.tintHex.slice(3, 5), 16) / 255) * 0.55,
      (parseInt(room.tintHex.slice(5, 7), 16) / 255) * 0.55, 1.0))
  }
  border.width: Style.normalBorderWidth
  border.color: tileMouse.containsMouse ? Color.accent : Color.popups.border
  opacity: room && room.on ? 1.0 : 0.75

  Text {
    id: glyph
    anchors.left: parent.left
    anchors.leftMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    text: root.classGlyph(root.room ? root.room.class : "")
    color: root.room && root.room.on ? "#ffffff" : Qt.darker(Color.popups.text, 1.4)
    // monospace resolves to a Nerd Font, so FontAwesome glyphs draw here.
    font.family: Style.font.family
    font.pixelSize: Style.font.title
  }

  Text {
    anchors.left: glyph.right
    anchors.leftMargin: Style.space(10)
    anchors.right: dot.left
    anchors.rightMargin: Style.space(6)
    anchors.verticalCenter: parent.verticalCenter
    text: root.room ? root.room.name : ""
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    elide: Text.ElideRight
  }

  Rectangle {
    id: dot
    anchors.right: parent.right
    anchors.rightMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(8)
    height: width
    radius: width / 2
    color: root.room && root.room.on ? Color.accent : "#555555"
  }

  MouseArea {
    id: tileMouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.openRoom(root.room)
  }

  function classGlyph(cls) {
    var c = String(cls || "").toLowerCase()
    if (c.indexOf("living") !== -1) return "\uf4c6"   // sofa
    if (c.indexOf("kitchen") !== -1) return "\uf2e7"  // utensils
    if (c.indexOf("bed") !== -1) return "\uf236"      // bed
    if (c.indexOf("bath") !== -1) return "\uf2cd"     // bath
    if (c.indexOf("office") !== -1) return "\uf328"   // desk/laptop
    if (c.indexOf("garden") !== -1 || c.indexOf("terrace") !== -1) return "\uf06c" // leaf
    if (c.indexOf("hall") !== -1 || c.indexOf("entry") !== -1 || c.indexOf("corridor") !== -1)
      return "\uf52b"                                  // door open
    if (c.indexOf("garage") !== -1) return "\uf1b9"   // car
    return "\uf015"                                    // home
  }
}