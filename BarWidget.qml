import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// Bar icon for Omarchue. Left click opens/closes the control panel; right
// click is the house shortcut: every light off, no panel needed.
BarWidget {
  id: root
  moduleName: "io.github.realrandombacon.omarchue"

  readonly property string panelId: "io.github.realrandombacon.omarchue"

  // The service singleton (created by the shell for the service kind in
  // this same plugin); may be null until the shell finishes ensureService.
  readonly property var hue: root.bar && root.bar.shell
                             ? root.bar.shell.serviceFor(panelId) : null

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // Lit while the control panel is open (the panel routes through the
    // shell's openPanelIds set, not through this widget).
    active: root.bar && root.bar.shell
            ? root.bar.shell.openPanelIds[root.panelId] === true : false
    text: "\uf0eb"   // fa-lightbulb
    tooltipText: {
      if (!root.hue) return "Hue lights"
      if (root.hue.lastError !== "") return "Hue: " + root.hue.lastError
      return "Hue lights"
    }

    onPressed: function(buttonCode) {
      if (!root.bar || !root.bar.shell) return
      if (buttonCode === Qt.RightButton) {
        if (root.hue && root.hue.isPaired) {
          root.hue.beginEdits()
          root.hue.setAllOn(false)
          root.hue.endEdits()
        }
        return
      }
      root.bar.shell.toggle(root.panelId)
    }
  }
}