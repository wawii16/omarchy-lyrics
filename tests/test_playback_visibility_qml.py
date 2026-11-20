#!/usr/bin/env python3
"""Exercise playback visibility using the real Service.qml in Quickshell."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PlaybackVisibilityTest(unittest.TestCase):
    def test_play_pause_resume_stop_gap_and_unavailable(self):
        root = Path(__file__).resolve().parents[1]
        if not shutil.which('quickshell'):
            self.skipTest('quickshell is required')
        with tempfile.TemporaryDirectory(prefix='adam-playback-') as tmp:
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
    function fail(s) { console.log("PLAYBACK_FAIL " + s); Qt.quit() }
    Timer { interval: 100; running: true; repeat: true; onTriggered: {
        root.ticks++
        if (root.ticks > 100) { root.fail("timeout at " + root.stage); return }
        if (root.stage === 0 && root.ticks > 5) {
            root.writeState({playback:"Playing", text:"line", next_text:"next"}); root.stage = 1
        } else if (root.stage === 1 && svc.playback === "Playing") {
            if (!svc.hasContent || svc.lyric !== "line" || svc.nextLyric !== "next") { root.fail("playing lines"); return }
            root.writeState({playback:"Paused", text:"line", next_text:"next"}); root.stage = 2
        } else if (root.stage === 2 && svc.playback === "Paused") {
            if (svc.hasContent || svc.lyric !== "" || svc.nextLyric !== "") { root.fail("paused lines visible"); return }
            root.writeState({playback:"Playing", text:"line", next_text:"next"}); root.stage = 3
        } else if (root.stage === 3 && svc.playback === "Playing") {
            if (!svc.hasContent || svc.lyric !== "line" || svc.nextLyric !== "next") { root.fail("resume lines"); return }
            // Backend supplies the previous line during an instrumental gap.
            root.writeState({playback:"Playing", text:"line", next_text:"after gap"}); root.stage = 4
        } else if (root.stage === 4 && svc.nextLyric === "after gap") {
            if (!svc.hasContent || svc.lyric !== "line") { root.fail("playing gap hidden"); return }
            root.writeState({playback:"Stopped", text:"line", next_text:"next"}); root.stage = 5
        } else if (root.stage === 5 && svc.playback === "Stopped") {
            if (svc.hasContent || svc.lyric !== "" || svc.nextLyric !== "") { root.fail("stopped lines visible"); return }
            root.writeState({playback:"Playing", unavailable:true, track_id:"missing"}); root.stage = 6
        } else if (root.stage === 6 && svc.unavailable) {
            if (!svc.hasContent || svc.lyric !== "Lyrics unavailable") { root.fail("unavailable notice missing"); return }
            root.writeState({playback:"Paused", unavailable:true, track_id:"missing"}); root.stage = 7
        } else if (root.stage === 7 && svc.playback === "Paused") {
            if (svc.hasContent || svc.lyric !== "") { root.fail("paused notice visible"); return }
            root.writeState({playback:"Playing", unavailable:true, track_id:"missing"}); root.stage = 8
        } else if (root.stage === 8 && svc.playback === "Playing") {
            if (!svc.hasContent || svc.lyric !== "Lyrics unavailable") { root.fail("resumed notice missing"); return }
            console.log("PLAYBACK_PASS"); Qt.quit()
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
            self.assertIn('PLAYBACK_PASS', result.stdout)
            self.assertNotIn('PLAYBACK_FAIL', result.stdout)


if __name__ == '__main__':
    unittest.main()
