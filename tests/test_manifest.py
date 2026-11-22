import unittest
from pathlib import Path
import devil_painter
from tools.vt_release_gate import valid_tag
from tools.workspace import read_manifest


ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_manifest_metadata(self):
        manifest = read_manifest(ROOT)
        expected_version = tuple(int(part) for part in manifest['version'].split('-', 1)[0].split('+', 1)[0].split('.'))
        self.assertEqual(manifest['id'], 'devil_painter')
        self.assertEqual(manifest['name'], 'Devil Painter')
        self.assertTrue(valid_tag('v' + manifest['version']))
        self.assertEqual(devil_painter.bl_info['version'], expected_version)
        self.assertEqual(manifest['blender_version_min'], '5.2.0')
        self.assertEqual(manifest['type'], 'add-on')
