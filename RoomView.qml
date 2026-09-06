import QtQuick
import qs.Commons
import qs.Ui

// Detail level for one room: back navigation, room power + brightness,
// scene chips, then one LightRow per bulb. Same width as the home grid;
// the panel's Flickable provides the scrolling.
Column {
  id: root

  property var service: null
  property var room: null
  signal back()

  width: parent ? parent.width : 0
  spacing: Style.space(10)

  // Header: back arrow, room name, room power toggle.
  Item {
    width: parent.width
    height: Style.space(30)

    Text {
      id: backArrow
      anchors.left: parent.left
      anchors.leftMargin: Style.space(2)
      anchors.verticalCenter: parent.verticalCenter
      text: "\u25c0"  // left arrow
      color: backMouse.containsMouse ? Color.accent : Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.title

      MouseArea {
        id: backMouse
        anchors.fill: parent
        anchors.margins: -Style.space(10)
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.back()
      }
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - Style.space(120)
      text: root.room ? root.room.name : ""
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.title
      horizontalAlignment: Text.AlignHCenter
      elide: Text.ElideRight
    }

    ToggleSwitch {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      checked: root.room ? root.room.on : false
      interactive: root.service !== null
      onToggled: {
        if (root.room) root.service.setGroupOn(root.room.id, !root.room.on)
      }
    }
  }

  // Room brightness — derived from the members by the service, so it moves
  // as soon as any bulb is dragged.
  HuePanelRow {
    width: parent.width
    visible: root.room && root.room.on && root.room.bri !== null
    label: "Bright"
    hint: "Brightness of every bulb in " + (root.room ? root.room.name : "this room") +
          ". Bulbs that are off stay off."
    detail: root.room && root.room.bri !== null
            ? Math.round(root.room.bri / 254 * 100) + " %" : ""
    minimum: 1
    maximum: 254
    step: 1
    integer: true
    value: root.room && root.room.bri !== null ? root.room.bri : 1
    onMoved: function(v) {
      if (!root.room) return
      root.service.beginEdits()
      root.service.setGroupBri(root.room.id, v)
    }
    onReleased: root.service.endEdits()
  }

  PanelSectionHeader { text: "Scenes" }

  Flow {
    width: parent.width
    spacing: Style.space(6)

    Repeater {
      model: root.room && root.service ? root.service.scenesFor(root.room.id) : []

      SceneChip {
        required property int index
        required property var modelData
        scene: modelData
        dynamic: root.service && root.service.sceneIsDynamic(modelData.id)
        playing: root.service && root.service.playingSceneId === modelData.id
        onRecalled: function(scene) {
          if (root.room) root.service.recallScene(scene.id, root.room.id)
        }
      }
    }
  }

  Text {
    visible: root.room && root.service && root.service.scenesFor(root.room.id).length === 0
    width: parent.width
    text: "No scenes yet — create them in the Hue app."
    color: Qt.darker(Color.popups.text, 1.4)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

  PanelSectionHeader { text: "Lights" }

  Column {
    width: parent.width
    spacing: Style.space(4)

    Repeater {
      model: root.room && root.service ? root.service.lightsFor(root.room.id) : []

      LightRow {
        required property int index
        required property var modelData
        light: modelData
        service: root.service
      }
    }
  }
}