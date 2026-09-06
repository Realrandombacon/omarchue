# Changelog

## 1.1.0 — 2026-09-06

Hue Sync: native entertainment streaming.

- Screen sync on any entertainment area: the panel lists the bridge's
  areas (CLIP v2) as chips; tap to start, tap again to stop.
- Bridge-native streaming: DTLS 1.2 PSK over UDP (vendored
  music-assistant/hue-entertainment transport, Apache-2.0) at the
  bridge's own streaming rate — same protocol as the Hue Sync app.
- Channel-aware sampling: area channel positions map onto a 5x3 grid
  of the screen, so left lights follow the left of the screen.
- wf-recorder captures the chosen monitor at 30 fps, downsampled to a
  64x36 rgb24 feed through a FIFO (stdout streaming is broken with
  wf-recorder 0.6 + ffmpeg 9).
- Streaming-key pairing through the panel (one bridge-button press),
  credentials stored with the main pair, 0600.
- Clean teardown: stream deactivated and the pre-stream state restored
  on stop, SIGTERM or capture death.
- Monitor picker (Hyprland) and intensity slider.

Requires `python-cryptography` and `wf-recorder` (pacman).

## 1.0.0 — 2026-09-06

First release.

- Bridge pairing through the panel UI: mDNS discovery, link-button
  flow with countdown, credentials stored 0600.
- Two-level Android-app navigation: tinted room-tile grid ("Tout"
  whole-house tile) with per-room detail views.
- Per-bulb control gated by capability flags: power, brightness,
  white-temperature gradient (White Ambiance) or shader color wheel
  (RGB).
- Static and dynamic scene support: dynamic scenes play their animated
  palette via CLIP v2 (`dynamic_palette` recall); tap toggles playback,
  state resyncs with the bridge.
- Bar widget: amber bulb while any light is on, red on bridge errors,
  right-click all-off.
- Bridge outage resilience: errors surface without wiping the model;
  automatic resync on reconnect.
- IPC for headless control (`omarchy-shell omarchue set/status`).
- 54 headless tests against an in-process fake bridge.