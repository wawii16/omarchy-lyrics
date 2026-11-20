#!/usr/bin/env python3
"""Run the actual overlay with isolated theme/service fixtures and Qt rendering."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class OverlayGeometryTest(unittest.TestCase):
    def test_long_lines_expand_without_eliding(self):
        repo = Path(__file__).resolve().parents[1]
        if not shutil.which('quickshell'):
            self.skipTest('quickshell is required')
        if not os.environ.get('WAYLAND_DISPLAY'):
            self.skipTest('a Wayland session is required for PanelWindow')
        with tempfile.TemporaryDirectory(prefix='adam-overlay-') as tmp:
            temp = Path(tmp)
            plugin = temp / 'plugin'
            plugin.mkdir()
            shutil.copy(repo / 'Overlay.qml', plugin / 'Overlay.qml')
            commons = temp / 'qs' / 'Commons'
            commons.mkdir(parents=True)
            (commons / 'qmldir').write_text('module qs.Commons\nsingleton Color 1.0 Color.qml\nsingleton Style 1.0 Style.qml\n')
            (commons / 'Color.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject { readonly property color foreground: "white"; readonly property color background: "black"; readonly property var popups: ({background:"black", border:"white", text:"white"}) }\n')
            (commons / 'Style.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject { readonly property var font: ({family:"Sans"}) }\n')
            (temp / 'shell.qml').write_text('''import QtQuick
import Quickshell
import "plugin" as Plugin
ShellRoot {
    QtObject { id: svc; property bool userVisible: true; property string mode: "overlay"; property bool editMode: false; property bool hasContent: true; property string lyric: "A reasonably long lyric line that needs more than the old fixed width to be fully visible"; property string nextLyric: "next"; property int offsetX: 9999; property int offsetY: 0 }
    Plugin.Overlay { id: overlay; service: svc }
    property int stage: 0
    Timer { interval: 500; running: true; repeat: true; onTriggered: {
        let l = overlay.currentLine, n = overlay.nextLine
        let screenWidth = Quickshell.screens[0].width
        let panelWidth = l.width + 20
        if (l.elide !== Text.ElideNone || n.elide !== Text.ElideNone || l.wrapMode !== Text.NoWrap || n.wrapMode !== Text.NoWrap || l.contentWidth * l.scale > l.width + 0.5 || n.contentWidth * n.scale > n.width + 0.5 || overlay.positionX + panelWidth > screenWidth + 1) {
            console.log("GEOMETRY_FAIL stage=" + stage + " width=" + l.width + " current=" + l.contentWidth + " next=" + n.contentWidth + " x=" + overlay.positionX + " screen=" + screenWidth)
            Qt.quit(); return
        }
        if (stage === 0) {
            if (l.width <= 500) { console.log("GEOMETRY_FAIL not expanded"); Qt.quit(); return }
            svc.lyric = "short"; svc.nextLyric = "Wide next line ".repeat(20); stage = 1
        } else if (stage === 1) {
            if (l.width <= 500) { console.log("GEOMETRY_FAIL next did not expand"); Qt.quit(); return }
            svc.lyric = "W".repeat(10000); svc.nextLyric = "M".repeat(10000); stage = 2
        } else if (stage === 2) {
            if (panelWidth !== screenWidth || overlay.positionX !== 0) { console.log("GEOMETRY_FAIL not screen constrained"); Qt.quit(); return }
            svc.lyric = "short"; svc.nextLyric = ""; stage = 3
        } else {
            if (panelWidth !== 520 || overlay.positionX !== screenWidth - 520) { console.log("GEOMETRY_FAIL not restored"); Qt.quit(); return }
            console.log("GEOMETRY_PASS"); Qt.quit()
        }
    } }
}
''')
            env = dict(os.environ, HOME=str(temp), XDG_CONFIG_HOME=str(temp / 'config'),
                       QT_QPA_PLATFORM='wayland', QT_QPA_PLATFORMTHEME='',
                       QT_IM_MODULE='', QML2_IMPORT_PATH=str(temp))
            result = subprocess.run(['quickshell', '-p', str(temp / 'shell.qml')], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn('GEOMETRY_PASS', result.stdout)
            self.assertNotIn('GEOMETRY_FAIL', result.stdout)


if __name__ == '__main__':
    unittest.main()
