import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
    id: root
    moduleName: "io.github.wawii16.omarchy-lyrics"
    readonly property var service: bar && bar.shell ? bar.shell.serviceFor("io.github.wawii16.omarchy-lyrics") : null
    readonly property bool showLyric: !!service && service.mode === "bar" && service.userVisible && !vertical && service.hasContent
    readonly property alias currentLine: label
    readonly property alias nextLine: upcoming
    visible: showLyric
    implicitWidth: showLyric ? Math.min(400, metrics.advanceWidth + (upcoming.visible ? nextMetrics.advanceWidth + 12 : 0) + 20) : 0
    implicitHeight: barSize
    TextMetrics { id: metrics; text: label.text; font: label.font }
    TextMetrics { id: nextMetrics; text: upcoming.text; font: upcoming.font }
    Item {
        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
        Text {
            id: label
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            width: upcoming.visible ? Math.min(metrics.advanceWidth, Math.max(parent.width / 2, parent.width - nextMetrics.advanceWidth - 12)) : parent.width
            text: "♪  " + (root.service ? root.service.lyric : "")
            textFormat: Text.PlainText
            color: root.bar ? root.bar.barForeground : Color.foreground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body; font.bold: true
            elide: Text.ElideRight
        }
        Text {
            id: upcoming
            visible: text.length > 0
            anchors.left: label.right; anchors.leftMargin: 12; anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.service ? root.service.nextLyric : ""
            textFormat: Text.PlainText
            color: root.bar ? root.bar.barForeground : Color.foreground
            opacity: 0.62
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
        }
    }
}
