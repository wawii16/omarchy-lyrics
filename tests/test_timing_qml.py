#!/usr/bin/env python3
"""Exercise timing persistence and validation in an isolated Quickshell."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class TimingTest(unittest.TestCase):
    def test_restart_and_invalid_config(self):
        if not shutil.which('quickshell'):
            self.skipTest('quickshell is required')
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='adam-timing-') as tmp:
            temp = Path(tmp)
            plugin = temp / 'plugin'
            plugin.mkdir()
            shutil.copy(root / 'Service.qml', plugin / 'Service.qml')
            for name in ('backend.py', 'tray.py'):
                (plugin / name).write_text('import time\ntime.sleep(30)\n')
            (temp / 'shell.qml').write_text('''import QtQuick
import Quickshell
import "plugin" as Plugin
ShellRoot {
    Plugin.Service { id: svc }
    Timer { interval: 50; running: true; repeat: true; onTriggered: {
        if (!svc.ready) return
        console.log("TIMING_VALUE " + svc.advanceMs)
        if (Quickshell.env("ADAM_TEST_WRITE") === "1") svc.adjustTiming(100, false)
        Qt.quit()
    } }
}
''')
            env = dict(os.environ, HOME=str(temp), XDG_CONFIG_HOME=str(temp / 'config'),
                       XDG_RUNTIME_DIR=str(temp), QT_QPA_PLATFORM='offscreen',
                       QT_QPA_PLATFORMTHEME='', QT_IM_MODULE='',
                       ADAM_LYRICS_PLUGIN_STATE=str(temp / 'state.json'))
            timing = temp / 'config/adam-lyrics/timing.json'
            def run(expected, write=False):
                result = subprocess.run(['quickshell', '-p', str(temp / 'shell.qml')],
                                        env=dict(env, ADAM_TEST_WRITE='1' if write else '0'),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn('TIMING_VALUE ' + str(expected), result.stdout)
            run(0, True)
            self.assertEqual(json.loads(timing.read_text()), {'advance_ms': 100})
            run(100)
            for contents, expected in (('{bad', 0), ('{"advance_ms":true}', 0),
                                       ('{"advance_ms":1.5}', 0), ('{"advance_ms":3000}', 2000)):
                timing.write_text(contents)
                run(expected)


if __name__ == '__main__':
    unittest.main()
