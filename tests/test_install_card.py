import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from tools import install_card

ZIP_URL = 'https://github.com/Artbyo3/DEVIL-PAINTER/releases/download/v0.3.0/devil_painter-0.3.0.zip'
CARD = '<a href="https://github.com/Artbyo3/DEVIL-PAINTER/releases/download/v0.2.1/devil_painter-0.2.1.zip?repository=x&amp;blender_version_min=5.2.0">Download</a>'


def fixture_site(folder, pages):
    site = Path(folder)
    (site / 'repo').mkdir()
    index = dict(version='v1', blocklist=[], data=[dict(id='devil_painter', version='0.3.0', blender_version_min='5.2.0', archive_url=ZIP_URL)])
    (site / 'repo' / 'index.json').write_text(json.dumps(index), encoding='utf-8')
    for name, body in pages.items():
        (site / name).parent.mkdir(parents=True, exist_ok=True)
        (site / name).write_text(f'<p>{body}</p>', encoding='utf-8')
    return site


class InstallCardTests(unittest.TestCase):
    def test_cards_point_at_the_newest_release_with_the_repository_and_minimum_blender(self):
        with tempfile.TemporaryDirectory() as folder:
            site = fixture_site(folder, {'index.html': CARD, 'install/index.html': CARD + CARD})
            href = install_card.stamp_cards(site)
            parts = urlsplit(href)
            self.assertEqual(f'{parts.scheme}://{parts.netloc}{parts.path}', ZIP_URL)
            self.assertEqual(parse_qsl(parts.query), [('repository', install_card.REPOSITORY_URL), ('blender_version_min', '5.2.0')])
            self.assertIn('repository=https%3A%2F%2Fartbyo3.github.io%2FDEVIL-PAINTER%2Frepo%2Findex.json&', href)
            escaped = href.replace('&', '&amp;')
            self.assertEqual((site / 'index.html').read_text(encoding='utf-8').count(f'href="{escaped}"'), 1)
            self.assertEqual((site / 'install' / 'index.html').read_text(encoding='utf-8').count(f'href="{escaped}"'), 2)
            self.assertNotIn('v0.2.1', (site / 'install' / 'index.html').read_text(encoding='utf-8'))

    def test_a_page_without_its_card_fails_the_build(self):
        with tempfile.TemporaryDirectory() as folder:
            site = fixture_site(folder, {'index.html': CARD, 'install/index.html': 'no card'})
            with self.assertRaises(install_card.CardError):
                install_card.stamp_cards(site)

    def test_an_index_without_exactly_one_release_fails_the_build(self):
        with tempfile.TemporaryDirectory() as folder:
            site = fixture_site(folder, {'index.html': CARD, 'install/index.html': CARD})
            (site / 'repo' / 'index.json').write_text(json.dumps(dict(data=[])), encoding='utf-8')
            with self.assertRaises(install_card.CardError):
                install_card.stamp_cards(site)

    def test_version_is_stamped_from_manifest_into_site_and_docs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'repo'
            site = Path(folder) / 'site'
            (root / 'devil_painter').mkdir(parents=True)
            site.mkdir()
            (root / 'devil_painter' / 'blender_manifest.toml').write_text('id = "devil_painter"\nversion = "1.2.3"\n', encoding='utf-8')
            (root / 'README.md').write_text('v{{VERSION}}/devil_painter-{{VERSION}}.zip', encoding='utf-8')
            (root / 'SPEC.md').write_text('Version {{VERSION}} is the public announcement', encoding='utf-8')
            (site / 'index.html').write_text('<a href="https://github.com/Artbyo3/DEVIL-PAINTER/releases/download/v{{VERSION}}/devil_painter-{{VERSION}}.zip">Download</a>', encoding='utf-8')
            self.assertEqual(install_card.stamp_version(site, root), '1.2.3')
            self.assertIn('v1.2.3/devil_painter-1.2.3.zip', (site / 'index.html').read_text(encoding='utf-8'))
            self.assertEqual((site / 'README.md').read_text(encoding='utf-8'), 'v1.2.3/devil_painter-1.2.3.zip')
            self.assertEqual((site / 'SPEC.md').read_text(encoding='utf-8'), 'Version 1.2.3 is the public announcement')
            (root / 'SPEC.md').write_text('No placeholder here', encoding='utf-8')
            with self.assertRaises(install_card.CardError):
                install_card.stamp_version(site, root)


if __name__ == '__main__':
    unittest.main()
