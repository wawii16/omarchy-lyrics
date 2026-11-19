import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
    id: root
    moduleName: "io.github.wawii16.omarchy-lyrics"
    readonly property var service: bar && bar.shell ? bar.shell.serviceFor("io.github.wawii16.omarchy-lyrics") : null
    readonly property bool showLyric: !!service && service.mode === "bar" && service.userVisible && !vertical && service.hasContent
    visible: showLyric
    implicitWidth: showLyric ? Math.min(400, metrics.advanceWidth + 20) : 0
    implicitHeight: barSize
    TextMetrics { id: metrics; text: label.text; font: label.font }
    Text {
        id: label
        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
        verticalAlignment: Text.AlignVCenter
        text: "♪  " + (root.service ? root.service.lyric : "")
        textFormat: Text.PlainText
        color: root.bar ? root.bar.barForeground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
    }
}
