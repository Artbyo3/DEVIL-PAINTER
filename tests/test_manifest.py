import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_manifest_metadata(self):
        manifest = tomllib.loads((ROOT / 'devil_painter' / 'blender_manifest.toml').read_text(encoding='utf-8'))
        self.assertEqual(manifest['id'], 'devil_painter')
        self.assertEqual(manifest['name'], 'Devil Painter')
        self.assertEqual(manifest['version'], '0.5.0')
        self.assertEqual(manifest['blender_version_min'], '5.2.0')
        self.assertEqual(manifest['type'], 'add-on')
