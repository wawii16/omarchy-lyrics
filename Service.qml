import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    property var shell: null
    property var manifest: null
    readonly property string runtime: Quickshell.env("XDG_RUNTIME_DIR")
    readonly property string statePath: Quickshell.env("ADAM_LYRICS_PLUGIN_STATE") || runtime + "/adam-lyrics-plugin-state.json"
    readonly property string configDir: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/adam-lyrics"
    readonly property string prefsPath: configDir + "/plugin-preferences.json"
    readonly property string backendPath: decodeURIComponent(String(Qt.resolvedUrl("backend.py")).replace(/^file:\/\//, ""))
    property string mode: "overlay"
    property bool userVisible: true
    property bool editMode: false
    property int offsetX: -1
    property int offsetY: -1
    property string lyric: ""
    property string playback: "Stopped"
    property bool unavailable: false
    property string unavailableTrack: ""
    property bool unavailableVisible: false
    property bool ready: false
    readonly property bool hasContent: playback !== "Stopped" && lyric.length > 0 && (!unavailable || unavailableVisible)
    function applyState() {
        try {
            const s = JSON.parse(stateFile.text())
            if (!s.updated || Date.now()/1000 - Number(s.updated) > 10) { clearState(); return }
            let playing = s.playback && s.playback !== "Stopped"
            let missing = playing && !!s.unavailable
            let track = s.track_id !== undefined && s.track_id !== null && String(s.track_id).length > 0
                ? "id:" + String(s.track_id) : "title:" + String(s.track || "")
            if (missing && (!unavailable || track !== unavailableTrack)) { unavailableVisible = true; unavailableTimer.restart() }
            else if (!missing) { unavailableVisible = false; unavailableTimer.stop() }
            unavailable = !!missing; unavailableTrack = track
            playback = s.playback || "Stopped"
            lyric = missing ? "Lyrics unavailable" : (playing ? String(s.text || "") : "")
        } catch (e) { clearState() }
    }
    function clearState() { lyric = ""; playback = "Stopped"; unavailable = false; unavailableTrack = ""; unavailableVisible = false; unavailableTimer.stop() }
    function applyPrefs() {
        try {
            const p = JSON.parse(prefs.text())
            mode = p.mode === "bar" ? "bar" : "overlay"
            offsetX = Number.isFinite(p.x) && p.x >= 0 ? p.x : -1
            offsetY = Number.isFinite(p.y) && p.y >= 0 ? p.y : -1
        } catch (e) {}
    }
    function savePrefs() { prefs.setText(JSON.stringify({mode: mode, x: offsetX, y: offsetY})) }
    function setMode(value) {
        if (value !== "bar" && value !== "overlay") return "invalid mode"
        mode = value; editMode = false; if (value === "overlay") userVisible = true
        savePrefs(); return "ok"
    }
    function edit() { mode = "overlay"; userVisible = true; editMode = !editMode; savePrefs(); return editMode ? "on" : "off" }
    function toggle() { userVisible = !userVisible; return userVisible ? "shown" : "hidden" }
    Timer { id: unavailableTimer; interval: 5000; onTriggered: root.unavailableVisible = false }
    FileView { id: stateFile; path: root.statePath; watchChanges: true; printErrors: false; onFileChanged: reload(); onLoaded: root.applyState(); onLoadFailed: root.clearState() }
    FileView { id: prefs; path: root.prefsPath; watchChanges: true; atomicWrites: true; printErrors: false; onFileChanged: reload(); onLoaded: root.applyPrefs() }
    Timer { interval: 1000; running: true; repeat: true; onTriggered: stateFile.reload() }
    Process {
        id: worker
        command: ["python3", root.backendPath, "--state", root.statePath]
        running: root.ready
        onExited: function(code, status) { root.clearState(); retry.restart() }
    }
    Process {
        id: setup
        command: ["python3", "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)", root.configDir]
        running: true
        onExited: function(code, status) { if (code === 0) root.ready = true; else console.warn("omarchy-lyrics: cannot create config directory") }
    }
    Timer { id: retry; interval: 3000; onTriggered: if (root.ready) worker.running = true }
    // The tray is a child of this service; its stdout is a private control pipe.
    Process {
        id: tray
        command: ["/usr/bin/python3", decodeURIComponent(String(Qt.resolvedUrl("tray.py")).replace(/^file:\/\//, ""))]
        running: root.ready
        stdout: SplitParser {
            onRead: function(line) {
                if (line === "overlay" || line === "bar") root.setMode(line)
                else if (line === "toggle") root.toggle()
                else if (line === "edit") root.edit()
            }
        }
        onExited: function(code, status) { console.warn("omarchy-lyrics: tray exited", code); trayRetry.restart() }
    }
    Timer { id: trayRetry; interval: 10000; onTriggered: if (root.ready) tray.running = true }
    IpcHandler {
        target: "omarchyLyrics"
        function setMode(value: string): string { return root.setMode(value) }
        function edit(): string { return root.edit() }
        function toggle(): string { return root.toggle() }
        function status(): string { return JSON.stringify({mode:root.mode, edit:root.editMode, visible:root.userVisible, text:root.lyric, playback:root.playback, x:root.offsetX, y:root.offsetY, running:worker.running}) }
    }
}
