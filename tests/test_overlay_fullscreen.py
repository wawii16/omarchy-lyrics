import json
import re
import subprocess
import unittest
from pathlib import Path


class OverlayFullscreenTest(unittest.TestCase):
    def test_visible_workspaces_only(self):
        source = (Path(__file__).resolve().parents[1] / 'Overlay.qml').read_text()
        match = re.search(r'interval: 500; running: true; repeat: true\s*onTriggered: \{(.*?)\n        \}', source, re.S)
        self.assertIsNotNone(match, 'fullscreen polling timer missing')
        # Execute the actual QML timer JavaScript with Hyprland IPC-shaped fixtures.
        script = '''
const run = new Function('Hyprland', 'panel', 'root', CODE);
const fullscreen = (workspace, mode = 2) => ({workspace: {id: workspace}, lastIpcObject: {fullscreen: mode}});
function check(name, special, items, expected) {
  const monitor = {name: 'screen', activeWorkspace: {id: 3}, lastIpcObject: {specialWorkspace: special}};
  const hypr = {monitors: {values: [monitor]}, toplevels: {values: items}};
  const root = {};
  run(hypr, {screen: {name: 'screen'}}, root);
  if (root.fullscreen !== expected) throw Error(name + ': expected ' + expected + ', got ' + root.fullscreen);
}
check('active special fullscreen', {id: -98, name: 'special:test'}, [fullscreen(-98)], true);
check('inactive special', {id: 0, name: ''}, [fullscreen(-98)], false);
check('active regular fullscreen', {id: 0, name: ''}, [fullscreen(3)], true);
check('other workspace', {id: -98, name: 'special:test'}, [fullscreen(4)], false);
check('maximized only', {id: -98, name: 'special:test'}, [fullscreen(-98, 1)], false);
check('empty IPC object', null, [fullscreen(3)], true);
'''.replace('CODE', json.dumps(match.group(1)))
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
