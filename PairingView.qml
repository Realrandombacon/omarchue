import QtQuick
import qs.Commons
import qs.Ui

// Pairing flow: discover -> "press the link button" countdown (90s, streamed
// from hue_api.py pair) -> paired. Shown inside the panel card when the
// service is not paired.
Column {
  id: root

  // The service (injected by Panel).
  property var service: null

  signal pairingDone()

  width: parent ? parent.width : 0
  spacing: Style.space(14)

  readonly property bool pressing: service && service.pairingEvent === "press-button"
  readonly property bool discovering: service && service.pairingEvent === "discovering"

  Text {
    width: parent.width
    text: "Philips Hue"
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.subtitle
    font.bold: true
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    text: {
      if (!service) return ""
      if (service.pairingEvent === "paired")
        return "Paired. Loading your lights…"
      if (root.pressing)
        return "Press the round link button on your Hue Bridge. You have " +
               service.pairingSecondsLeft + " seconds."
      if (root.discovering)
        return "Looking for a Hue Bridge on this network…"
      return "Connect your Hue Bridge to control your lights from the bar."
    }
  }

  // Countdown ring while waiting for the button press.
  Item {
    width: parent.width
    height: root.pressing ? Style.space(48) : 0
    visible: root.pressing

    Rectangle {
      id: ring
      width: Style.space(36)
      height: width
      radius: width / 2
      anchors.verticalCenter: parent.verticalCenter
      color: "transparent"
      border.width: Style.normalBorderWidth * 2
      border.color: Color.accent

      RotationAnimation on rotation {
        from: 0
        to: 360
        duration: 1500
        loops: Animation.Infinite
        running: root.pressing
      }
    }

    Text {
      anchors.left: ring.right
      anchors.leftMargin: Style.space(14)
      anchors.verticalCenter: parent.verticalCenter
      text: "Waiting for the bridge button…"
      color: Qt.darker(Color.popups.text, 1.2)
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }

  Text {
    width: parent.width
    visible: root.pressing
    wrapMode: Text.WordWrap
    color: Qt.darker(Color.popups.text, 1.35)
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    text: "The button is on the bridge itself, next to the network cable. " +
          "One press is enough — you do not need to hold it."
  }

  Text {
    width: parent.width
    visible: service && service.lastError !== "" && service.pairingEvent === ""
    wrapMode: Text.WordWrap
    color: "#e0654f"
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    text: service ? service.lastError : ""
  }

  Row {
    spacing: Style.space(12)

    Button {
      text: {
        if (!service) return "Pair"
        if (service.pairingActive) return "Cancel"
        if (service.pairingEvent === "paired") return "Done"
        return "Pair"
      }
      onClicked: {
        if (!service) return
        if (service.pairingEvent === "paired") {
          root.pairingDone()
        } else if (service.pairingActive) {
          service.cancelPairing()
        } else {
          service.beginPairing()
        }
      }
    }
  }
}