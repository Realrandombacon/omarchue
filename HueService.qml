import QtQuick
import Quickshell
import Quickshell.Io

// Omarchue state owner. The shell destroys panels when they close, so all
// bridge state lives here: the panel and the bar widget are pure views on
// this service (injected as `service` into the panel, reached via
// bar.shell.serviceFor(...) from the bar widget).
//
// Bridge transport is hue_api.py, driven through three one-shot Processes
// (ambient status, full state, serialized actions) plus a streaming pair
// process. Exit codes: 0 ok, 1 network, 2 unpaired, 3 bad response, 4 usage.
// On any failure the previous model is kept — a network blip must never
// look like "all lights deleted".
Item {
  id: root

  // Injected by the shell's ensureService.
  property var shell: null
  property var manifest: null

  // ---- Model -----------------------------------------------------------
  property bool isPaired: false
  property var bridge: ({})
  property var groups: []
  property var lights: ({})
  property var scenes: []
  property string lastError: ""
  property string pairingEvent: ""      // "" | discovering | press-button | paired
  property int pairingSecondsLeft: 0
  property bool pairingActive: false
  property bool refreshing: false
  property bool editing: false          // true while the user drags a slider

  // Defaults from defaults.json in the plugin dir.
  property int pollIntervalSec: 15
  property int ambientPollSec: 30
  property int resyncMs: 700
  property int sceneRefetchMs: 900
  property int debouncedSendMs: 120

  // The plugin dir comes from the manifest the shell injects. It must be
  // read imperatively at call time: bindings on a var property that is
  // assigned right after createObject (ensureService) have not necessarily
  // propagated by the time onManifestChanged handlers run, and a stale
  // binding produced spawns of "/hue_api.py" (python exits 2 — which this
  // service reads as "unpaired"). Every spawn site goes through helperCmd.
  function helperCmd(args) {
    var dir = (manifest && manifest.__sourceDir)
              ? String(manifest.__sourceDir) : ""
    return ["python3", dir + "/hue_api.py"].concat(args)
  }

  // The shell injects `manifest` AFTER createObject, so Component.onCompleted
  // runs with pluginDir still empty — everything that needs the plugin dir
  // (defaults.json, hue_api.py) must wait for the injection.
  onManifestChanged: {
    if (!manifest) return
    defaultsFile.path = (manifest && manifest.__sourceDir
                         ? String(manifest.__sourceDir) : "") + "/defaults.json"
    defaultsFile.reload()
    // After a shell restart the service starts with isPaired=false even
    // though saved credentials exist — the ambient poll only runs once
    // paired, so without a startup probe it would never discover them.
    probePaired()
  }

  FileView {
    id: defaultsFile
    // Path is set imperatively in onManifestChanged — a binding here would
    // still be empty when reload() is called (see helperCmd comment).
    path: ""
    watchChanges: false
    printErrors: false
    onLoaded: {
      try {
        var d = JSON.parse(text())
        if (typeof d.pollIntervalSec === "number") root.pollIntervalSec = d.pollIntervalSec
        if (typeof d.ambientPollSec === "number") root.ambientPollSec = d.ambientPollSec
        if (typeof d.resyncMs === "number") root.resyncMs = d.resyncMs
        if (typeof d.sceneRefetchMs === "number") root.sceneRefetchMs = d.sceneRefetchMs
        if (typeof d.debouncedSendMs === "number") root.debouncedSendMs = d.debouncedSendMs
      } catch (e) {
        console.warn("omarchue: defaults.json unreadable, using built-ins:", e)
      }
    }
  }

  // ---- Ambient poll (bar widget honesty) --------------------------------
  Timer {
    id: ambientTimer
    interval: Math.max(5, root.ambientPollSec) * 1000
    running: root.isPaired && !root.pairingActive
    repeat: true
    triggeredOnStart: false
    onTriggered: root.pollStatus()
  }

  // ---- Full-state poll (panel open) --------------------------------------
  Timer {
    id: stateTimer
    interval: Math.max(5, root.pollIntervalSec) * 1000
    running: root.isPaired && root.panelOpen && !root.editing && !root.pairingActive
    repeat: true
    onTriggered: root.refresh()
  }

  Timer {
    id: resyncTimer
    interval: root.resyncMs
    onTriggered: root.refresh()
  }

  Timer {
    id: sceneRefetchTimer
    interval: root.sceneRefetchMs
    onTriggered: root.refresh()
  }

  property bool panelOpen: false

  function setPanelOpen(open) {
    panelOpen = open
    if (open) refresh()
  }

  // ---- Polling -----------------------------------------------------------
  property bool _startupProbe: false

  function probePaired() {
    _startupProbe = true
    statusProc.command = helperCmd(["get-status"])
    statusProc.running = true
  }

  function pollStatus() {
    if (!isPaired || statusProc.running) return
    statusProc.command = helperCmd(["get-status"])
    statusProc.running = true
  }

  function refresh() {
    if (!isPaired || stateProc.running || editing) return
    refreshing = true
    stateProc.command = helperCmd(["get-state"])
    stateProc.running = true
  }

  // ---- Pairing -----------------------------------------------------------
  function beginPairing() {
    if (pairProc.running) return
    pairingActive = true
    pairingEvent = "discovering"
    pairingSecondsLeft = 0
    pairProc.command = helperCmd(["pair"])
    pairProc.running = true
  }

  function cancelPairing() {
    if (pairProc.running) pairProc.running = false
    pairingActive = false
    pairingEvent = ""
  }

  function unpair() {
    cancelPairing()
    isPaired = false
    groups = []
    scenes = []
    lights = ({})
    bridge = ({})
    lastError = ""
    unpairProc.command = helperCmd(["unpair"])
    unpairProc.running = true
  }

  Process {
    id: pairProc
    command: []
    stdout: SplitParser {
      onRead: function(data) {
        root.handlePairLine(data)
      }
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (String(text).trim() !== "") console.warn("omarchue pair:", String(text).trim())
      }
    }
    onExited: function(exitCode) {
      root.pairingActive = false
      if (exitCode !== 0) {
        root.pairingEvent = ""
        if (root.pairingError !== "") {
          root.lastError = root.pairingError
          root.pairingError = ""
        } else if (!root.isPaired) {
          root.lastError = "Pairing failed"
        }
      }
    }
  }

  property string pairingError: ""

  function handlePairLine(line) {
    line = String(line || "").trim()
    if (line === "") return
    var ev
    try { ev = JSON.parse(line) } catch (e) { return }
    if (ev.event === "discovering") {
      pairingEvent = "discovering"
    } else if (ev.event === "press-button") {
      pairingEvent = "press-button"
      pairingSecondsLeft = ev.secondsLeft || 0
    } else if (ev.event === "paired") {
      pairingEvent = "paired"
      pairingActive = false
      isPaired = true
      lastError = ""
      if (ev.bridge) bridge = ev.bridge
      // CLIP v2 probe: the v1 username doubles as the v2 app key. Fire and
      // forget — v2 support is recorded, not required.
      probeProc.command = helperCmd(["probe-v2"])
      probeProc.running = true
      refresh()
      pollStatus()
    } else if (ev.ok === false && ev.code !== undefined) {
      // Final failure JSON emitted on the same stream.
      pairingError = ev.error || "Pairing failed"
      pairingActive = false
      pairingEvent = ""
    }
  }

  Process {
    id: probeProc
    command: []
  }

  Process {
    id: unpairProc
    command: []
  }

  // ---- Action queue (serialized, coalesced) ------------------------------
  //
  // Slider drags emit many onMoved events; entries targeting the same
  // group/light merge in place so the bridge sees one request per settle.
  property var _queue: []
  property var _resyncPending: false

  function sendAction(cmd, id, body, opts) {
    opts = opts || {}
    var key = cmd + ":" + (id || "")
    var merged = false
    for (var i = 0; i < _queue.length; i++) {
      var entry = _queue[i]
      if (entry.key === key && !entry.body.scene && !body.scene) {
        for (var k in body) entry.body[k] = body[k]
        merged = true
        break
      }
    }
    if (!merged) _queue.push({ key: key, cmd: cmd, id: id, body: body })
    if (opts.scene) _resyncPending = true
    _queueTimer.interval = debouncedSendMs
    _queueTimer.restart()
  }

  Timer {
    id: _queueTimer
    interval: 120
    onTriggered: root._drainQueue()
  }

  function _drainQueue() {
    if (_queue.length === 0 || actionProc.running || !isPaired) return
    var entry = _queue.shift()
    var args = helperCmd([entry.cmd])
    if (entry.id) args.push(entry.id)
    // Quickshell 0.3's Process.write() + stdinEnabled=false does not
    // deliver stdin data (verified empirically), so the body rides on
    // argv instead. It holds no secrets — the username stays in the
    // 0600 credentials file.
    args.push("--body")
    args.push(JSON.stringify(entry.body))
    actionProc.command = args
    actionProc.running = true
  }

  Process {
    id: actionProc
    command: []
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var out = JSON.parse(text)
          if (out.errors && out.errors.length > 0)
            root.lastError = out.errors.join("; ")
        } catch (e) {
          console.warn("omarchue action:", String(text).trim(), e)
        }
      }
    }
    onExited: function(exitCode) {
      if (exitCode === 1) root.lastError = "Bridge unreachable"
      else if (exitCode === 2) { root.isPaired = false; root.lastError = "Bridge rejected the key" }
      else if (exitCode === 0 || exitCode === 3) {
        // Success (or per-light partial): schedule a resync so reality
        // catches up — scene recall especially reshuffles states.
        resyncTimer.restart()
        if (root._resyncPending) { sceneRefetchTimer.restart(); root._resyncPending = false }
      }
      root._drainQueue()
    }
  }

  // ---- Status/state processes ---------------------------------------------
  Process {
    id: statusProc
    command: []
    stdout: StdioCollector {
      onStreamFinished: root.applySnapshot(text)
    }
    onExited: function(exitCode) { root.handleFetchExit(exitCode) }
  }

  Process {
    id: stateProc
    command: []
    stdout: StdioCollector {
      onStreamFinished: root.applySnapshot(text)
    }
    onExited: function(exitCode) {
      refreshing = false
      root.handleFetchExit(exitCode)
    }
  }

  function handleFetchExit(exitCode) {
    if (exitCode === 1) {
      // Keep the model; just surface the problem.
      lastError = "Bridge unreachable"
      isPaired = true  // still paired, just offline
    } else if (exitCode === 2) {
      isPaired = false
      // "Not paired" is not an error — the pairing view is the UI for it;
      // the banner would just be noise on every startup probe.
      lastError = ""
    } else if (exitCode === 0) {
      lastError = ""
      if (!isPaired) isPaired = true
    }
    _startupProbe = false
  }

  function applySnapshot(raw) {
    raw = String(raw || "").trim()
    if (raw === "") return
    var snap
    try { snap = JSON.parse(raw) } catch (e) {
      console.warn("omarchue: malformed snapshot:", e)
      return
    }
    if (snap.ok !== true) {
      if (snap.code === 2) {
        // Unpaired is a UI state (PairingView), not an error banner.
        isPaired = false
        lastError = ""
      }
      else lastError = snap.error || "Bridge error"
      return
    }
    if (snap.groups !== undefined) groups = snap.groups
    if (snap.scenes !== undefined) scenes = snap.scenes
    if (snap.lights !== undefined) lights = snap.lights
    if (snap.bridge) bridge = snap.bridge
    lastError = ""
    isPaired = true
  }

  // ---- Public API (panel + bar widget) ------------------------------------

  function lightsFor(groupId) {
    var out = []
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].id !== groupId) continue
      var ids = groups[i].lightIds || []
      for (var j = 0; j < ids.length; j++) {
        var light = lights[ids[j]]
        if (light) out.push(light)
      }
      break
    }
    return out
  }

  function sceneById(sceneId) {
    for (var i = 0; i < scenes.length; i++)
      if (scenes[i].id === sceneId) return scenes[i]
    return null
  }

  function scenesFor(groupId) {
    var out = []
    for (var i = 0; i < scenes.length; i++)
      if (!scenes[i].group || scenes[i].group === groupId) out.push(scenes[i])
    return out
  }

  function patchGroup(groupId, patch) {
    for (var i = 0; i < groups.length; i++) {
      if (groups[i].id !== groupId) continue
      var next = []
      for (var g = 0; g < groups.length; g++) next.push(groups[g])
      for (var k in patch) next[i][k] = patch[k]
      groups = next
      return
    }
  }

  function patchLight(lightId, patch) {
    var light = lights[lightId]
    if (!light) return
    var next = {}
    for (var id in lights) next[id] = lights[id]
    var copy = {}
    for (var k in light) copy[k] = light[k]
    for (k in patch) copy[k] = patch[k]
    next[lightId] = copy
    lights = next
  }

  // ---- Edits (drag session) ----------------------------------------------
  function beginEdits() { editing = true }

  function endEdits() {
    editing = false
    resyncTimer.restart()
  }

  // ---- Commands ----------------------------------------------------------
  function setGroupOn(groupId, on) {
    patchGroup(groupId, { on: on })
    var members = lightsFor(groupId)
    for (var i = 0; i < members.length; i++)
      if (members[i].reachable) patchLight(members[i].id, { on: on })
    sendAction("put-group", groupId, { on: on })
  }

  function setGroupBri(groupId, bri) {
    bri = Math.round(Math.max(1, Math.min(254, bri)))
    patchGroup(groupId, { bri: bri })
    var members = lightsFor(groupId)
    for (var i = 0; i < members.length; i++)
      if (members[i].reachable && members[i].hasBri)
        patchLight(members[i].id, { bri: bri })
    sendAction("put-group", groupId, { bri: bri })
  }

  function recallScene(sceneId, groupId) {
    // Optimistic: apply the scene's own name to the group, then let the
    // 900ms refetch reconcile colors/brightness.
    patchGroup(groupId, { on: true })
    sendAction("put-group", groupId, { scene: sceneId }, { scene: true })
    sceneRefetchTimer.restart()
  }

  function setLightOn(lightId, on) {
    patchLight(lightId, { on: on })
    sendAction("put-light", lightId, { on: on })
  }

  function setLightBri(lightId, bri) {
    bri = Math.round(Math.max(1, Math.min(254, bri)))
    patchLight(lightId, { bri: bri })
    sendAction("put-light", lightId, { bri: bri })
  }

  function setLightColor(lightId, xy, bri) {
    var body = { xy: [Math.round(xy[0] * 10000) / 10000,
                      Math.round(xy[1] * 10000) / 10000] }
    if (bri !== undefined && bri !== null)
      body.bri = Math.round(Math.max(1, Math.min(254, bri)))
    patchLight(lightId, { xy: body.xy, bri: body.bri })
    sendAction("put-light", lightId, body)
  }

  function setLightCt(lightId, ct) {
    patchLight(lightId, { ct: Math.round(ct) })
    sendAction("put-light", lightId, { ct: Math.round(ct) })
  }

  function setAllOn(on) {
    for (var i = 0; i < groups.length; i++) setGroupOn(groups[i].id, on)
  }

  // ---- IPC (headless control) ---------------------------------------------
  IpcHandler {
    target: "omarchue"

    // omarchy-shell omarchue set '{"allOn": false}'
    // omarchy-shell omarchue set '{"group":"1","on":false,"bri":120}'
    // omarchy-shell omarchue set '{"scene":"s1"}'
    function set(json: string): void {
      var req
      try { req = JSON.parse(json) } catch (e) {
        console.warn("omarchue IPC: bad JSON:", json)
        return
      }
      if (req.allOn !== undefined) { root.setAllOn(!!req.allOn); return }
      if (req.scene !== undefined) { root.recallScene(String(req.scene), String(req.group || "")); return }
      if (req.group !== undefined) {
        if (req.on !== undefined) root.setGroupOn(String(req.group), !!req.on)
        if (req.bri !== undefined) root.setGroupBri(String(req.group), Number(req.bri))
      }
    }

    function status(): string {
      return JSON.stringify({ paired: root.isPaired, groups: root.groups.length,
                              error: root.lastError })
    }
  }
}