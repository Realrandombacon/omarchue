import QtQuick
import Quickshell

// Hue/saturation color wheel: the shader draws the wheel, a draggable knob
// reports hue (angle) and sat (radius). Emits picked(xy, hex) with CIE xy
// chromaticity the bridge understands directly, plus pickCommitted() when
// the drag ends so the service can stop suppressing polls.
ShaderEffect {
  id: root

  property real uValue: 0.8
  property real uInner: 0.22
  property vector2d selected: Qt.vector2d(0.4573, 0.4053)  // warm white
  property bool showKnob: true

  signal picked(vector2d xy, string hex)
  signal pickCommitted()

  fragmentShader: "colorwheel.frag.qsb"
  implicitWidth: 128
  implicitHeight: 128

  // -- xy (CIE chromaticity) -> wheel coords. Exact inversion needs gamut
  // data; the display approximation (sRGB -> HSV, radius sqrt(sat)) is fine
  // for a control: pick() always sends the exact xy computed from geometry.
  function xyToWheel(xy) {
    if (!xy || xy.length !== 2) return
    var x = xy[0], y = xy[1]
    if (y <= 0.000001) return
    var X = x / y, Z = (1 - x - y) / y
    var r0 = 3.2406 * X - 1.5372 - 0.4986 * Z
    var g0 = -0.9689 * X + 1.8758 + 0.0415 * Z
    var b0 = 0.0557 * X - 0.2040 + 1.0570 * Z
    var mx = Math.max(r0, g0, b0)
    if (mx <= 0.000001) return
    var r = Math.max(0, r0) / mx, g = Math.max(0, g0) / mx, b = Math.max(0, b0) / mx
    var max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min
    var h = 0, s = max > 0 ? d / max : 0
    if (d > 0) {
      if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6
      else if (max === g) h = ((b - r) / d + 2) / 6
      else h = ((r - g) / d + 4) / 6
    }
    var rad = Math.sqrt(s) * 0.48
    selected = Qt.vector2d(0.5 + Math.cos(h * 2 * Math.PI) * rad,
                           0.5 + Math.sin(h * 2 * Math.PI) * rad)
  }

  // -- wheel coords -> xy chromaticity + sRGB hex (BT.709 matrices).
  function wheelToXy(px, py) {
    var dx = px - 0.5, dy = py - 0.5
    var rad = Math.min(1, Math.sqrt(dx * dx + dy * dy) * 2)
    var h = (Math.atan2(dy, dx) / (2 * Math.PI) + 1) % 1
    var s = rad, v = 1
    var i = Math.floor(h * 6), f = h * 6 - i
    var p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s)
    var rgb
    switch (i % 6) {
      case 0: rgb = [v, t, p]; break
      case 1: rgb = [q, v, p]; break
      case 2: rgb = [p, v, t]; break
      case 3: rgb = [p, q, v]; break
      case 4: rgb = [t, p, v]; break
      default: rgb = [v, p, q]
    }
    var X = 0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]
    var Y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    var Z = 0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]
    if (Y <= 0.000001) return { xy: [0.4573, 0.4053], hex: "#746e5d" }
    var sum = X + Y + Z
    return { xy: [X / sum, Y / sum], hex: packHex(rgb) }
  }

  function packHex(rgb) {
    function c(x) {
      var s = Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16)
      return s.length < 2 ? "0" + s : s
    }
    return "#" + c(rgb[0]) + c(rgb[1]) + c(rgb[2])
  }

  MouseArea {
    id: drag
    anchors.fill: parent
    cursorShape: Qt.CrossCursor
    onPositionChanged: function(mouse) { root.commitAt(mouse.x, mouse.y) }
    onClicked: function(mouse) { root.commitAt(mouse.x, mouse.y) }
    onReleased: root.pickCommitted()
  }

  function commitAt(px, py) {
    var spot = wheelToXy(px / Math.max(width, 1), py / Math.max(height, 1))
    selected = Qt.vector2d(px / Math.max(width, 1), py / Math.max(height, 1))
    picked(Qt.vector2d(spot.xy[0], spot.xy[1]), spot.hex)
  }

  Rectangle {
    id: knob
    visible: root.showKnob
    width: 18
    height: width
    radius: width / 2
    x: root.selected.x * root.width - width / 2
    y: root.selected.y * root.height - height / 2
    color: "transparent"
    border.width: 2
    border.color: "#ffffff"
  }

  Rectangle {
    anchors.fill: knob
    anchors.margins: -4
    radius: width / 2
    color: "transparent"
    border.width: 1
    border.color: "#80000000"
    visible: knob.visible
  }
}