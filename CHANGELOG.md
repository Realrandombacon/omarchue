# Changelog

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