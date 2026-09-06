import QtQuick
import qs.Commons
import qs.Ui

// One light inside a room: name + power toggle, brightness slider when the
// bulb supports it, then color controls gated by capability flags — a
// linear temperature gradient for White Ambiance bulbs, the shader color
// wheel for RGB ones. All feedback is optimistic (service patches local
// state and sends the bridge command asynchronously).
Column {
  id: root

  property var light: null
  property var service: null
  property bool expanded: false

  width: parent ? parent.width : 0
  spacing: Style.space(6)

  readonly property bool controllable: light && light.reachable

  // Pre-set the wheel knob to the bulb's current chromaticity whenever the
  // row expands or the service patches the light's xy.
  onExpandedChanged: if (expanded && light) wheel.xyToWheel(light.xy)
  onLightChanged: if (expanded && light) wheel.xyToWheel(light.xy)

  Item {
    width: parent.width
    height: Style.space(28)

    Rectangle {
      id: bulbDot
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(10)
      height: width
      radius: width / 2
      visible: root.controllable
      color: {
        if (!root.light || !root.light.on) return "#555555"
        if (root.light.hex) return root.light.hex
        return Color.accent
      }
      opacity: root.light && root.light.on ? 1.0 : 0.5
    }

    Text {
      id: nameText
      anchors.left: root.controllable ? bulbDot.right : parent.left
      anchors.leftMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - Style.space(80)
      text: {
        if (!root.light) return ""
        var n = root.light.name
        if (!root.light.reachable) n += " (unreachable)"
        return n
      }
      color: root.light && root.light.reachable ? Color.popups.text : Qt.darker(Color.popups.text, 1.6)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }

    Text {
      id: chevron
      anchors.right: toggle.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      text: root.expanded ? "▾" : "▸"
      visible: root.light && (root.light.hasColor || root.light.hasCt) && root.controllable
      color: Qt.darker(Color.popups.text, 1.35)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption

      MouseArea {
        anchors.fill: parent
        anchors.margins: -Style.space(8)
        cursorShape: Qt.PointingHandCursor
        onClicked: root.expanded = !root.expanded
      }
    }

    ToggleSwitch {
      id: toggle
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      checked: root.light ? root.light.on : false
      interactive: root.controllable && root.service !== null
      onToggled: {
        if (root.light) root.service.setLightOn(root.light.id, !root.light.on)
      }
    }
  }

  // Brightness — shown while expanded (or always for dimmable bulbs when
  // the light is on, which is the common case).
  HuePanelRow {
    width: parent.width
    visible: root.expanded && root.light && root.light.hasBri && root.controllable
    label: "Bright"
    hint: "Brightness of " + (root.light ? root.light.name : "this light") +
          ". The bulb itself sets the range; 1% is the dimmest it can go."
    detail: root.light && root.light.bri !== null
            ? Math.round(root.light.bri / 254 * 100) + " %" : ""
    minimum: 1
    maximum: 254
    step: 1
    integer: true
    value: root.light && root.light.bri !== null ? root.light.bri : 1
    onMoved: function(v) {
      if (!root.light) return
      root.service.beginEdits()
      root.service.setLightBri(root.light.id, v)
    }
    onReleased: root.service.endEdits()
  }

  // White Ambiance: a horizontal temperature gradient, tap/drag to pick.
  Rectangle {
    id: ctBar
    width: parent.width
    height: Style.space(22)
    radius: height / 2
    visible: root.expanded && root.light && root.light.hasCt && !root.light.hasColor && root.controllable
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0.0; color: "#ffb46e" }  // warm (~2000K)
      GradientStop { position: 0.5; color: "#ffe9c4" }
      GradientStop { position: 1.0; color: "#cfe4ff" }  // cool (~6500K)
    }

    Rectangle {
      id: ctKnob
      width: Style.space(14)
      height: width
      radius: width / 2
      anchors.verticalCenter: parent.verticalCenter
      x: {
        if (!root.light || !root.light.ct) return 0
        var span = (root.light.ctMax || 500) - (root.light.ctMin || 153)
        var frac = (root.light.ct - (root.light.ctMin || 153)) / Math.max(span, 1)
        return frac * (ctBar.width - width)
      }
      color: "#ffffff"
      border.width: 1
      border.color: "#80000000"
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: function(mouse) { root.commitCt(mouse.x) }
      onPositionChanged: function(mouse) {
        if (pressed) root.commitCt(mouse.x)
      }
    }

    function commitCt(x) {
      if (!root.light) return
      var min = root.light.ctMin || 153, max = root.light.ctMax || 500
      var frac = Math.max(0, Math.min(1, x / ctBar.width))
      root.service.beginEdits()
      root.service.setLightCt(root.light.id, min + frac * (max - min))
      root.service.endEdits()
    }
  }

  // RGB: the shader color wheel, centered, with the current color pre-set.
  Item {
    width: parent.width
    height: visible ? Style.space(140) : 0
    visible: root.expanded && root.light && root.light.hasColor && root.controllable

    ColorWheel {
      id: wheel
      anchors.centerIn: parent
      width: Style.space(128)
      height: width
      onPicked: function(xy, hex) {
        if (!root.light) return
        root.service.beginEdits()
        root.service.setLightColor(root.light.id, [xy.x, xy.y], null)
        root.service.patchLight(root.light.id, { hex: hex })
      }
      onPickCommitted: {
        root.service.endEdits()
      }
    }
  }

  PanelSeparator {
    visible: root.light && root.expanded
  }
}