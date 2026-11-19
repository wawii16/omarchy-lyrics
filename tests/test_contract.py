import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Contract(unittest.TestCase):
    def test_native_plugin_exposes_all_entry_points(self):
        path = ROOT / 'manifest.json'
        self.assertTrue(path.exists(), 'native plugin manifest missing')
        m = json.loads(path.read_text())
        self.assertEqual(m['id'], 'io.github.wawii16.omarchy-lyrics')
        self.assertTrue((ROOT / 'tray.py').is_file())
        self.assertEqual(set(m['kinds']), {'service', 'overlay', 'bar-widget'})
        for name in ('service', 'overlay', 'barWidget'):
            self.assertTrue((ROOT / m['entryPoints'][name]).is_file())
