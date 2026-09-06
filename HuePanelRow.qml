import QtQuick
import qs.Commons
import qs.Ui

// Slider row for the Omarchue panel — lava-lamp's PanelRow extracted.
// Hover 1s without moving -> English hint tooltip below the row.
Item {
  id: row

  property string label: ""
  property string detail: ""
  property string hint: ""
  property real minimum: 0
  property real maximum: 1
  property real step: 0.05
  property bool integer: false
  property real value: 0

  signal moved(real v)
  signal released()

  implicitHeight: Math.max(labelText.implicitHeight, slider.implicitHeight)
  // z-lift while the tooltip is visible so it draws over the rows below.
  z: tip.visible ? 2 : 0

  HoverHandler {
    onHoveredChanged: {
      if (hovered && row.hint !== "") hintTimer.restart()
      else { hintTimer.stop(); tip.visible = false }
    }
  }

  Timer {
    id: hintTimer
    interval: 1000
    onTriggered: tip.visible = row.hint !== ""
  }

  Rectangle {
    id: tip
    visible: false
    x: 0
    y: parent.height + Style.space(4)
    width: Math.min(tipText.implicitWidth + Style.space(20), row.width)
    height: tipText.implicitHeight + Style.space(12)
    radius: Style.cornerRadius
    color: Color.popups.background
    border.width: Style.normalBorderWidth
    border.color: Color.popups.border

    Text {
      id: tipText
      anchors.centerIn: parent
      width: Math.min(implicitWidth, tip.width - Style.space(16))
      wrapMode: Text.WordWrap
      text: row.hint
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }

  Text {
    id: labelText
    anchors.left: parent.left
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(92)
    text: row.label
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.letterSpacing: 0.5
    elide: Text.ElideRight
  }

  PanelSlider {
    id: slider
    anchors.left: labelText.right
    anchors.leftMargin: Style.space(12)
    anchors.right: detailText.left
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    minimum: row.minimum
    maximum: row.maximum
    step: row.step
    integer: row.integer
    value: row.value
    onMoved: function(v) { row.moved(v) }
    onReleased: function(v) { row.released() }
  }

  Text {
    id: detailText
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(44)
    horizontalAlignment: Text.AlignRight
    text: row.detail
    color: Qt.darker(Color.popups.text, 1.35)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}