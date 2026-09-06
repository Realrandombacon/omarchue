import QtQuick
import qs.Commons
import qs.Ui

// Hue Sync section on the home level: entertainment-area chips that stream
// the screen's colors to their channels (bridge-native 30 fps streaming),
// a monitor picker and an intensity slider. Needs the one-time streaming-key
// pairing (bridge button) before any area chip shows.
Column {
  id: root

  property var service: null

  width: parent ? parent.width : 0
  spacing: Style.space(10)

  readonly property bool pairing: service && service.syncPairEvent === "press-button"

  PanelSectionHeader { text: "Hue Sync" }

  // One-time streaming-key pairing: the bridge only issues a clientkey
  // during a link-button pairing, so this is its own inline flow.
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: root.service && !root.service.clientKeyReady

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      text: {
        if (!root.service) return ""
        if (root.service.syncPairEvent === "paired")
          return "Key paired. Loading areas…"
        if (root.pairing)
          return "Press the round link button on your Hue Bridge. You have " +
                 root.service.syncPairSecondsLeft + " seconds."
        return "Screen sync streams your monitor's colors to the lights, " +
               "at the bridge's own streaming rate. It pairs a dedicated " +
               "streaming key once — press the bridge's link button."
      }
    }

    Button {
      text: root.pairing ? "Cancel" : "Pair"
      visible: root.service && root.service.syncPairEvent !== "paired"
      onClicked: {
        if (!root.service) return
        if (root.pairing) root.service.cancelSyncPairing()
        else root.service.beginSyncPairing()
      }
    }
  }

  // Area chips: tap to start streaming, tap again to stop. FA glyphs,
  // same play/pause pair as the dynamic scene chips.
  Flow {
    width: parent.width
    spacing: Style.space(6)
    visible: root.service && root.service.clientKeyReady

    Repeater {
      model: root.service ? root.service.syncAreas : []

      Rectangle {
        id: chip
        required property int index
        required property var modelData

        readonly property bool active: root.service &&
              root.service.syncActiveId === modelData.v1Id &&
              (root.service.syncStatus === "starting" ||
               root.service.syncStatus === "streaming")

        width: chipText.width + Style.space(20)
        height: Style.space(26)
        radius: height / 2
        color: chipMouse.containsMouse ? Qt.darker(Color.popups.background, 0.85)
                                       : Color.popups.background
        border.width: Style.normalBorderWidth
        border.color: chip.active || chipMouse.containsMouse
                      ? Color.accent : Color.popups.border

        Text {
          id: chipText
          anchors.centerIn: parent
          // FA glyphs: play triangle when idle, pause bars while streaming.
          text: (chip.active ? "\uf04c " : "\uf04b ") + chip.modelData.name
          color: chip.active ? Color.accent : Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        MouseArea {
          id: chipMouse
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            if (!root.service) return
            if (chip.active) root.service.stopSync()
            else root.service.startSync(chip.modelData.v1Id)
          }
        }
      }
    }
  }

  // Monitor picker — which screen feeds the colors.
  Row {
    width: parent.width
    spacing: Style.space(6)
    visible: root.service && root.service.clientKeyReady &&
             root.service.outputs.length > 1

    Repeater {
      model: root.service ? root.service.outputs : []

      Rectangle {
        id: outChip
        required property int index
        required property var modelData

        readonly property bool selected: root.service &&
              root.service.syncOutput === modelData

        width: outText.width + Style.space(16)
        height: Style.space(24)
        radius: height / 2
        color: selected ? Qt.darker(Color.accent, 2.2) : Color.popups.background
        border.width: Style.normalBorderWidth
        border.color: selected ? Color.accent : Color.popups.border

        Text {
          id: outText
          anchors.centerIn: parent
          text: outChip.modelData
          color: outChip.selected ? Color.accent : Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: if (root.service) root.service.syncOutput = outChip.modelData
        }
      }
    }
  }

  // Intensity — read when a stream starts, so dragging mid-stream applies
  // to the next start.
  HuePanelRow {
    width: parent.width
    visible: root.service && root.service.clientKeyReady
    label: "Intensité"
    hint: "How strongly the lights follow the screen. Applies when the next sync starts."
    detail: Math.round((root.service ? root.service.syncIntensity : 0.8) * 100) + " %"
    minimum: 10
    maximum: 100
    step: 1
    integer: true
    value: Math.round((root.service ? root.service.syncIntensity : 0.8) * 100)
    onMoved: function(v) {
      if (root.service) root.service.syncIntensity = v / 100
    }
  }
}