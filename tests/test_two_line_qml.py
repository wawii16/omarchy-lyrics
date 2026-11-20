#!/usr/bin/env python3
"""Exercise real Service.qml state transitions in an isolated Quickshell."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class TwoLineStateTest(unittest.TestCase):
    def test_next_line_follows_current_state_and_clears(self):
        root = Path(__file__).resolve().parents[1]
        if not shutil.which('quickshell'):
            self.skipTest('quickshell is required')
        with tempfile.TemporaryDirectory(prefix='adam-two-line-') as tmp:
            temp = Path(tmp)
            plugin = temp / 'plugin'
            plugin.mkdir()
            shutil.copy(root / 'Service.qml', plugin / 'Service.qml')
            for name in ('backend.py', 'tray.py'):
                (plugin / name).write_text('import time\ntime.sleep(30)\n')
            (temp / 'shell.qml').write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import "plugin" as Plugin
ShellRoot {
    id: root
    Plugin.Service { id: svc }
    FileView { id: fixture; path: Quickshell.env("ADAM_LYRICS_PLUGIN_STATE") }
    property int stage: 0
    property int ticks: 0
    function writeState(s) { s.updated = Date.now()/1000; fixture.setText(JSON.stringify(s)) }
    function fail(s) { console.log("TWO_FAIL " + s); Qt.quit() }
    Timer { interval: 100; running: true; repeat: true; onTriggered: {
        root.ticks++
        if (root.ticks > 100) { root.fail("timeout " + root.stage); return }
        if (root.stage === 0 && root.ticks > 5) {
            root.writeState({playback:"Playing", track_id:"one", text:"first", next_text:"second"}); root.stage = 1
        } else if (root.stage === 1 && svc.lyric === "first") {
            if (svc.nextLyric !== "second") { root.fail("next line missing"); return }
            root.writeState({playback:"Playing", track_id:"two", text:"new"}); root.stage = 2
        } else if (root.stage === 2 && svc.lyric === "new") {
            if (svc.nextLyric !== "") { root.fail("stale next on track change"); return }
            root.writeState({playback:"Playing", track_id:"two", unavailable:true, next_text:"stale"}); root.stage = 3
        } else if (root.stage === 3 && svc.unavailable) {
            if (svc.nextLyric !== "") { root.fail("stale next on unavailable"); return }
            root.writeState({playback:"Stopped", text:"old", next_text:"old next"}); root.stage = 4
        } else if (root.stage === 4 && svc.playback === "Stopped") {
            if (svc.lyric !== "" || svc.nextLyric !== "") { root.fail("stale stopped lines"); return }
            console.log("TWO_PASS"); Qt.quit()
        }
    } }
}
''')
            env = dict(os.environ, HOME=str(temp), XDG_CONFIG_HOME=str(temp / 'config'),
                       XDG_RUNTIME_DIR=str(temp), QT_QPA_PLATFORM='offscreen',
                       QT_QPA_PLATFORMTHEME='', QT_IM_MODULE='',
                       ADAM_LYRICS_PLUGIN_STATE=str(temp / 'state.json'))
            result = subprocess.run(['quickshell', '-p', str(temp / 'shell.qml')], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn('TWO_PASS', result.stdout)
            self.assertNotIn('TWO_FAIL', result.stdout)


if __name__ == '__main__':
    unittest.main()
