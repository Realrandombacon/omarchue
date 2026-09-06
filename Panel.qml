import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Omarchue control panel — M1: a flat list. One row per room/zone with a
// power toggle and brightness slider, plus global all-on/all-off and scene
// chips. The Android-style room tiles come in M2; navigation stays flat so
// the service contract gets exercised first.
Item {
  id: root

  // Injected by the shell's panel loader.
  property var shell: null
  property var manifest: null
  property var service: null

  property bool opened: false

  function open(payloadJson) {
    opened = true
    if (service) service.setPanelOpen(true)
  }

  function close() {
    opened = false
    if (service) service.setPanelOpen(false)
  }

  function dismiss() {
    // User-initiated closes route through shell.hide so the host's
    // open-panel state stays consistent; close() is the fallback.
    if (shell && typeof shell.hide === "function")
      shell.hide((manifest && manifest.id) || "io.github.realrandombacon.omarchue")
    else
      close()
  }

  onOpenedChanged: {
    if (service) service.setPanelOpen(opened)
  }

  function toggleGroup(group) {
    if (!service) return
    service.setGroupOn(group.id, !group.on)
  }

  function setGroupBrightness(group, v) {
    if (!service) return
    service.setGroupBri(group.id, v)
  }

  function releaseGroupBrightness(group) {
    if (!service) return
    service.endEdits()
  }

  function allOn(on) {
    if (!service) return
    service.beginEdits()
    service.setAllOn(on)
    service.endEdits()
  }

  PanelWindow {
    id: win
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "omarchue-panel"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
    exclusionMode: ExclusionMode.Ignore

    // Click anywhere outside the card to dismiss.
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.ArrowCursor
      onClicked: root.dismiss()
    }

    Shortcut {
      sequence: "Escape"
      onActivated: root.dismiss()
    }

    Rectangle {
      id: card
      anchors.top: parent.top
      anchors.right: parent.right
      anchors.topMargin: Style.space(52)   // clear of the bar
      anchors.rightMargin: Style.space(12)
      width: Style.space(360)
      // Never taller than the screen: taller content scrolls inside.
      height: Math.min(contentCol.implicitHeight + Style.space(44),
                       parent.height - Style.space(72))
      radius: Style.cornerRadius
      color: Color.popups.background
      border.width: Style.normalBorderWidth
      border.color: Color.popups.border

      // Swallow clicks on the card itself so they don't reach the scrim.
      MouseArea { anchors.fill: parent }

      Flickable {
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: contentCol.implicitHeight + Style.space(44)
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: contentCol
          x: Style.space(22)
          y: Style.space(22)
          width: card.width - Style.space(44)
          spacing: Style.space(14)

          // ---- Header
          Item {
            width: parent.width
            height: titleText.implicitHeight

            Text {
              id: titleText
              text: "Omarchue"
              color: Color.popups.text
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
              font.bold: true
            }

            Text {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: "✕"
              color: closeMouse.containsMouse ? Color.accent : Color.popups.text
              font.family: Style.font.family
              font.pixelSize: Style.font.body

              MouseArea {
                id: closeMouse
                anchors.fill: parent
                anchors.margins: -Style.space(8)
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.dismiss()
              }
            }
          }

          // ---- Error banner (kept models intact: purely informational)
          Text {
            width: parent.width
            visible: service && service.lastError !== ""
            wrapMode: Text.WordWrap
            text: service ? service.lastError : ""
            color: "#e0654f"
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          // ---- Not paired: pairing flow
          PairingView {
            width: parent.width
            visible: !service || !service.isPaired
            service: root.service
            onPairingDone: root.dismiss()
          }

          // ---- Paired: global controls + one row per room
          Column {
            width: parent.width
            spacing: Style.space(14)
            visible: service && service.isPaired

            Row {
              spacing: Style.space(12)

              Button {
                text: "All on"
                onClicked: root.allOn(true)
              }

              Button {
                text: "All off"
                onClicked: root.allOn(false)
              }
            }

            PanelSeparator {}

            Repeater {
              model: service ? service.groups : []

              delegate: Column {
                id: groupBlock
                width: parent.width
                spacing: Style.space(6)
                required property int index
                required property var modelData

                // Room header: tint dot, name, power toggle.
                Item {
                  width: parent.width
                  height: Style.space(30)

                  Rectangle {
                    id: dot
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: Style.space(12)
                    height: width
                    radius: width / 2
                    color: groupBlock.modelData.tintHex || "#444444"
                    opacity: groupBlock.modelData.on ? 1.0 : 0.35
                  }

                  Text {
                    anchors.left: dot.right
                    anchors.leftMargin: Style.space(10)
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - Style.space(70)
                    text: groupBlock.modelData.name
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                  }

                  ToggleSwitch {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    checked: groupBlock.modelData.on
                    interactive: root.service !== null
                    onToggled: root.toggleGroup(groupBlock.modelData)
                  }
                }

                // Room brightness (any controllable member ⇒ useful).
                HuePanelRow {
                  width: parent.width
                  visible: root.service && groupBlock.modelData.bri !== null
                  label: "Bright"
                  hint: "Brightness of every reachable bulb in " +
                        groupBlock.modelData.name + ". Off or unreachable bulbs are skipped."
                  detail: groupBlock.modelData.bri !== null
                          ? Math.round(groupBlock.modelData.bri / 254 * 100) + " %" : ""
                  minimum: 1
                  maximum: 254
                  step: 1
                  integer: true
                  value: groupBlock.modelData.bri !== null ? groupBlock.modelData.bri : 1
                  onMoved: function(v) {
                    root.service.beginEdits()
                    root.setGroupBrightness(groupBlock.modelData, v)
                  }
                  onReleased: function(v) { root.releaseGroupBrightness(groupBlock.modelData) }
                }

                // Scene chips for this room.
                Flow {
                  width: parent.width
                  spacing: Style.space(8)
                  visible: root.service && root.service.scenesFor(groupBlock.modelData.id).length > 0

                  Repeater {
                    model: root.service ? root.service.scenesFor(groupBlock.modelData.id) : []

                    delegate: Rectangle {
                      width: chipText.implicitWidth + Style.space(20)
                      height: chipText.implicitHeight + Style.space(10)
                      radius: height / 2
                      required property var modelData
                      color: chipMouse.containsMouse
                             ? Qt.darker(Color.popups.background, 1.2)
                             : Color.popups.background
                      border.width: Style.normalBorderWidth
                      border.color: chipMouse.containsMouse ? Color.accent : Color.popups.border

                      Text {
                        id: chipText
                        anchors.centerIn: parent
                        text: parent.modelData.name
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                      }

                      MouseArea {
                        id: chipMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.service.recallScene(parent.modelData.id,
                                                            groupBlock.modelData.id)
                      }
                    }
                  }
                }

                PanelSeparator {
                  visible: index < (service ? service.groups.length : 0) - 1
                }
              }
            }
          }
        }
      }
    }
  }
}