import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from tools import extension_repo as repo
from tools.vt_release_gate import GateError

MANIFEST = '''schema_version = "1.0.0"
id = "devil_painter"
version = "{version}"
name = "Devil Painter"
tagline = "Layer-based texture painting inside Blender"
maintainer = "Artbyo3"
type = "add-on"
website = "https://artbyo3.github.io/DEVIL-PAINTER/"
tags = ["Paint", "3D View"]
license = ["SPDX:GPL-3.0-or-later"]
blender_version_min = "5.2.0"

[permissions]
files = "Save and load texture layers"

[build]
paths_exclude_pattern = [".*"]
'''
SITE = 'https://github.com/Artbyo3/DEVIL-PAINTER/releases/download'


def fixture_release(folder, version):
    path = Path(folder) / f'devil_painter-{version}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('blender_manifest.toml', MANIFEST.format(version=version))
        archive.writestr('__init__.py', f'VERSION = "{version}"\n')
    return path, f'{SITE}/v{version}/{path.name}'


class ExtensionRepositoryTests(unittest.TestCase):
    def test_index_lists_every_release_newest_first_with_the_real_hash_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            packages = [fixture_release(folder, version) for version in ('0.2.0', '0.10.0', '0.2.1')]
            repo.write_repository(Path(folder) / 'repo', repo.repository_index(packages))
            index = json.loads((Path(folder) / 'repo' / 'index.json').read_text(encoding='utf-8'))
            self.assertEqual((index['version'], index['blocklist'], index['assetlib_auth_method']), ('v1', [], 'PER_LIBRARY'))
            self.assertEqual([entry['version'] for entry in index['data']], ['0.10.0', '0.2.1', '0.2.0'])
            for path, url in packages:
                entry = next(item for item in index['data'] if item['archive_url'] == url)
                self.assertEqual(entry['archive_hash'], 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(entry['archive_size'], len(path.read_bytes()))
                self.assertEqual(entry['permissions'], dict(files='Save and load texture layers'))
                self.assertNotIn('build', entry)

    def test_entries_keep_the_server_generate_field_order(self):
        with tempfile.TemporaryDirectory() as folder:
            entry = repo.repository_index([fixture_release(folder, '0.2.1')])['data'][0]
            self.assertEqual(list(entry), ['schema_version', 'id', 'name', 'tagline', 'version', 'type', 'maintainer', 'license',
                                           'blender_version_min', 'website', 'permissions', 'tags', 'archive_url', 'archive_size', 'archive_hash'])

    def test_a_published_release_without_its_zip_or_with_a_foreign_address_fails(self):
        name = 'devil_painter-0.2.1.zip'
        good = dict(tag_name='v0.2.1', assets=[dict(name=name, browser_download_url=f'{SITE}/v0.2.1/{name}')])
        self.assertEqual(repo.release_asset('Artbyo3/DEVIL-PAINTER', good)[1], f'{SITE}/v0.2.1/{name}')
        for release in (dict(tag_name='v0.2.1', assets=[]), dict(tag_name='v0.2.1', assets=[dict(name='other.zip')]),
                        dict(tag_name='latest', assets=good['assets']),
                        dict(tag_name='v0.2.1', assets=[dict(name=name, browser_download_url='https://evil.example/x.zip')])):
            with self.assertRaises(GateError):
                repo.release_asset('Artbyo3/DEVIL-PAINTER', release)

    def test_an_archive_without_a_manifest_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'devil_painter-0.2.1.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('__init__.py', '')
            with self.assertRaises(GateError):
                repo.repository_index([(path, f'{SITE}/v0.2.1/{path.name}')])
