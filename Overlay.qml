import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland

Item {
    id: root
    property var shell: null
    property var service: null
    readonly property bool opened: service ? service.userVisible && service.mode === "overlay" : false
    function open(payload) { if (service) service.setMode("overlay") }
    function close() { if (service) { service.userVisible = false; service.editMode = false } }
    readonly property string mode: service ? service.mode : "overlay"
    readonly property bool userVisible: service ? service.userVisible : false
    readonly property bool editMode: service ? service.editMode : false
    readonly property bool hasContent: service ? service.hasContent : false
    readonly property string lyric: service ? service.lyric : ""
    readonly property int offsetX: service ? service.offsetX : -1
    readonly property int offsetY: service ? service.offsetY : -1
    property bool fullscreen: false
    readonly property bool displayed: panel.visible
    readonly property int positionX: Math.min(Math.max(0, (panel.screen ? panel.screen.width : 520) - panel.implicitWidth), offsetX >= 0 ? offsetX : Math.max(0, Math.round(((panel.screen ? panel.screen.width : 520) - panel.implicitWidth) / 2)))
    readonly property int positionY: Math.min(Math.max(0, (panel.screen ? panel.screen.height : 1200) - panel.implicitHeight), offsetY >= 0 ? offsetY : Math.max(0, (panel.screen ? panel.screen.height : 1200) - panel.implicitHeight - 80))
    Timer { interval: 1000; running: true; repeat: true; onTriggered: { Hyprland.refreshToplevels(); Hyprland.refreshMonitors() } }
    Timer {
        interval: 500; running: true; repeat: true
        onTriggered: {
            let monitors = Hyprland.monitors.values;
            let monitor = null;
            for (let i = 0; i < monitors.length; ++i) {
                if (panel.screen && monitors[i].name === panel.screen.name) { monitor = monitors[i]; break; }
            }
            let workspace = monitor ? monitor.activeWorkspace : null;
            // Hyprland reports the currently visible special workspace per monitor.
            // ID 0 means that no special workspace is open.
            let special = monitor && monitor.lastIpcObject ? monitor.lastIpcObject.specialWorkspace : null;
            let items = Hyprland.toplevels.values;
            let found = false;
            for (let i = 0; i < items.length; ++i) {
                let t = items[i];
                let visibleWorkspace = t.workspace && ((workspace && t.workspace.id === workspace.id) || (special && special.id !== 0 && t.workspace.id === special.id));
                if (visibleWorkspace && t.lastIpcObject && (Number(t.lastIpcObject.fullscreen) & 2)) found = true;
            }
            root.fullscreen = found;
        }
    }
    PanelWindow {
        id: panel
        visible: root.mode === "overlay" && root.userVisible && !root.fullscreen && (root.editMode || root.hasContent)
        anchors { top: true; left: true }
        margins { top: root.positionY; left: root.positionX }
        implicitWidth: 520; implicitHeight: 74
        exclusionMode: ExclusionMode.Ignore
        color: "transparent"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "adam-lyrics"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        mask: Region { item: root.editMode ? background : null }
        Rectangle {
            id: background
            anchors.fill: parent
            radius: 12
            color: root.editMode ? "#e62b3548" : "transparent"
            border.color: root.editMode ? "#8cbeff" : "transparent"
            border.width: root.editMode ? 1 : 0
            Text {
                visible: root.editMode
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 10; height: 15
                text: "DRAG TO REPOSITION • Select edit again to lock"
                color: "#aebcd0"; font.pixelSize: 10; font.bold: true
                elide: Text.ElideRight
            }
            Text {
                anchors.fill: parent
                anchors.topMargin: root.editMode ? 24 : 0
                anchors.leftMargin: 10; anchors.rightMargin: 10
                text: root.lyric; color: "white"; font.pixelSize: 18; font.bold: true
                style: Text.Raised; styleColor: "#b0000000"
                textFormat: Text.PlainText; elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            }
            MouseArea {
                anchors.fill: parent; enabled: root.editMode; cursorShape: Qt.SizeAllCursor
                property real pressX
                property real pressY
                onPressed: function(mouse) { pressX = mouse.x; pressY = mouse.y; root.service.offsetX = root.positionX; root.service.offsetY = root.positionY; }
                onPositionChanged: function(mouse) {
                    if (!pressed) return;
                    root.service.offsetX = Math.max(0, root.offsetX + Math.round(mouse.x - pressX));
                    root.service.offsetY = Math.max(0, root.offsetY + Math.round(mouse.y - pressY));
                }
                onReleased: root.service.savePrefs()
            }
        }
    }
}
