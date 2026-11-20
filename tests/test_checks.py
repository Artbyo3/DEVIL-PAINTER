import tomllib
import unittest
from pathlib import Path
from tools.check_comments import check_repository
from tools.check_dead_code import check_dead_code, check_import_integrity, find_dead_code, find_missing_imports


ROOT = Path(__file__).resolve().parents[1]


class RepositoryChecksTests(unittest.TestCase):
    def test_zero_comments_and_docstrings(self):
        self.assertGreater(check_repository(ROOT), 0)

    def test_package_has_no_dead_code_or_unused_imports(self):
        self.assertGreater(check_dead_code(ROOT), 0)
        self.assertEqual(find_dead_code(ROOT), [])

    def test_package_import_integrity(self):
        self.assertGreater(check_import_integrity(ROOT), 0)
        self.assertEqual(find_missing_imports(ROOT), [])

    def test_manifest_metadata(self):
        manifest = tomllib.loads((ROOT / 'devil_painter' / 'blender_manifest.toml').read_text(encoding='utf-8'))
        self.assertEqual(manifest['id'], 'devil_painter')
        self.assertEqual(manifest['name'], 'Devil Painter')
        self.assertEqual(manifest['version'], '0.4.0')
        self.assertEqual(manifest['blender_version_min'], '5.2.0')
        self.assertEqual(manifest['type'], 'add-on')
