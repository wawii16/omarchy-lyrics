#!/usr/bin/env python3
"""Exercise the real Service.qml with isolated files and a Quickshell host."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class UnavailableNoticeTest(unittest.TestCase):
    def test_notice_tracks_identity_and_legacy_title(self):
        root = Path(__file__).resolve().parents[1]
        if not shutil.which('quickshell'):
            self.skipTest('quickshell is required')
        with tempfile.TemporaryDirectory(prefix='adam-notice-test-') as tmp:
            temp = Path(tmp)
            plugin = temp / 'plugin'
            plugin.mkdir()
            shutil.copy(root / 'Service.qml', plugin / 'Service.qml')
            # The service owns these processes. Keep them inert for this test.
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
    function writeState(id, title) {
        let s = {updated: Date.now()/1000, playback: "Playing", unavailable: true, track: title}
        if (id !== null) s.track_id = id
        fixture.setText(JSON.stringify(s))
    }
    function fail(message) { console.log("NOTICE_FAIL " + message); Qt.quit() }
    Timer {
        interval: 100; running: true; repeat: true
        onTriggered: {
            root.ticks++
            if (root.ticks > 160) { root.fail("timeout at stage " + root.stage); return }
            if (root.stage === 0 && root.ticks >= 5) {
                root.writeState("first-id", "Same title"); root.stage = 1
            } else if (root.stage === 1 && svc.unavailableVisible) {
                root.stage = 2
            } else if (root.stage === 2 && !svc.unavailableVisible) {
                root.writeState("second-id", "Same title"); root.stage = 3; root.ticks = 0
            } else if (root.stage === 3 && svc.unavailableVisible) {
                // Repeated updates to the same track must not re-open the notice.
                svc.unavailableVisible = false
                root.writeState("second-id", "Same title"); root.stage = 4; root.ticks = 0
            } else if (root.stage === 3 && root.ticks > 20) {
                root.fail("same-title second track did not show a notice")
            } else if (root.stage === 4 && root.ticks > 15) {
                if (svc.unavailableVisible) { root.fail("same track reopened notice"); return }
                root.writeState(null, "Legacy title"); root.stage = 5; root.ticks = 0
            } else if (root.stage === 5 && svc.unavailableVisible) {
                svc.unavailableVisible = false
                root.writeState(null, "Legacy title"); root.stage = 6; root.ticks = 0
            } else if (root.stage === 5 && root.ticks > 20) {
                root.fail("legacy title did not show a notice")
            } else if (root.stage === 6 && root.ticks > 15) {
                if (svc.unavailableVisible) { root.fail("legacy track reopened notice"); return }
                root.writeState(null, "Other legacy title"); root.stage = 7; root.ticks = 0
            } else if (root.stage === 7 && svc.unavailableVisible) {
                console.log("NOTICE_PASS"); Qt.quit()
            } else if (root.stage === 7 && root.ticks > 20) {
                root.fail("changed legacy title did not show a notice")
            }
        }
    }
}
''')
            env = dict(os.environ, HOME=str(temp), XDG_CONFIG_HOME=str(temp / 'config'),
                       XDG_RUNTIME_DIR=str(temp), QT_QPA_PLATFORM='offscreen',
                       QT_QPA_PLATFORMTHEME='', QT_IM_MODULE='',
                       ADAM_LYRICS_PLUGIN_STATE=str(temp / 'state.json'))
            result = subprocess.run(['quickshell', '-p', str(temp / 'shell.qml')], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn('NOTICE_PASS', result.stdout)
            self.assertNotIn('NOTICE_FAIL', result.stdout)


if __name__ == '__main__':
    unittest.main()
