#!/bin/bash
# Deploy the Omarchue plugin sources to the live Omarchy plugin dir.
# Dev-only helper (users install with `omarchy plugin add <git-url>`):
# copies the plugin files (not symlinks, so the shell's inotify watcher
# reliably picks changes up), compiles shaders with qsb, forces a rescan.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.config/omarchy/plugins/io.github.realrandombacon.omarchue"
QSB=/usr/lib/qt6/bin/qsb

# Exactly the files a plugin install ships; everything else (tests, docs,
# .git) stays in the dev checkout.
FILES=(manifest.json HueService.qml Panel.qml PairingView.qml RoomGrid.qml
       RoomTile.qml RoomView.qml LightRow.qml ColorWheel.qml SceneChip.qml
       HuePanelRow.qml BarWidget.qml SyncView.qml defaults.json hue_api.py
       hue_bridge_cacert.pem
       colorwheel.frag colorwheel.frag.qsb preview.png)

# Vendored hue-entertainment DTLS transport (Apache-2.0, see vendor/ LICENSE).
mkdir -p "$DEST/vendor/hue_entertainment"
for f in __init__.py constants.py models.py dtls.py LICENSE; do
  [[ -f "$HERE/vendor/hue_entertainment/$f" ]] && \
    cp -f "$HERE/vendor/hue_entertainment/$f" "$DEST/vendor/hue_entertainment/"
done

mkdir -p "$DEST"

# Compile GLSL -> .qsb (Qt6 RHI shader pack) if the source changed
if [[ -f "$HERE/colorwheel.frag" ]]; then
  out="$HERE/colorwheel.frag.qsb"
  if [[ ! -f $out || $HERE/colorwheel.frag -nt $out ]]; then
    # GLSL variants must stay "100 es,120": a 440 fragment variant fails to
    # link against Qt's built-in default vertex shader (no matching output).
    "$QSB" --glsl "100 es,120" -o "$out" "$HERE/colorwheel.frag"
    echo "compiled: colorwheel.frag"
  fi
fi

for f in "${FILES[@]}"; do
  [[ -f "$HERE/$f" ]] && cp -f "$HERE/$f" "$DEST/"
done
omarchy-shell -q shell rescanPlugins || true
# NOTE: inotify hot-reload is unreliable for shader (.qsb) changes — the shell
# keeps serving the old binary. Pass --restart after editing a .frag file.
if [[ "${1:-}" == "--restart" ]]; then
  omarchy restart shell
  echo "shell restarted"
fi
echo "deployed -> $DEST"