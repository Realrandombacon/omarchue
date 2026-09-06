import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Omarchue control panel — two-level Android-app navigation: a home grid
// of room tiles (plus a global "Tout" on/off tile), then one room's detail
// view with scene chips and per-light color controls. The service injects
// all state; the panel is a pure view.
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

  // Two-level navigation: null = home (room grid), a room id = detail view.
  // Sibling Items with visible-swap (not StackView/Loader) so scroll and
  // drag state survive navigation; the room object is re-resolved by id on
  // every snapshot so the detail view never shows stale state.
  property var currentRoomId: null

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

          // ---- Paired: two-level navigation (home grid | room detail)
          Item {
            width: parent.width
            visible: service && service.isPaired
            height: visible ? (root.currentRoomId ? roomView.implicitHeight
                                                  : homeView.implicitHeight) : 0

            RoomGrid {
              id: homeView
              anchors.top: parent.top
              anchors.left: parent.left
              anchors.right: parent.right
              visible: !root.currentRoomId
              service: root.service
              onOpenRoom: function(room) { root.currentRoomId = room ? room.id : null }
            }

            RoomView {
              id: roomView
              anchors.top: parent.top
              anchors.left: parent.left
              anchors.right: parent.right
              visible: root.currentRoomId !== null
              service: root.service
              room: root.currentRoomId && root.service
                    ? root.service.roomById(root.currentRoomId) : null
              onBack: root.currentRoomId = null
            }
          }

          Connections {
            target: service
            // The room vanished from the bridge while its view was open —
            // fall back to the grid instead of showing an empty detail page.
            function onGroupsChanged() {
              if (root.currentRoomId && root.service &&
                  !root.service.roomById(root.currentRoomId))
                root.currentRoomId = null
            }
          }
        }
      }
    }
  }
}