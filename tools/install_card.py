import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.workspace import read_manifest

REPOSITORY_URL = 'https://artbyo3.github.io/DEVIL-PAINTER/repo/index.json'
CARD_PAGES = ('index.html', 'install/index.html')
CARD_HREF = re.compile(r'href="https://github\.com/Artbyo3/DEVIL-PAINTER/releases/download/[^"]*"')
VERSION_PLACEHOLDER = '{{VERSION}}'
VERSIONED_DOCS = ('README.md', 'SPEC.md')


class CardError(Exception):
    pass


def card_href(index):
    if len(index.get('data') or []) != 1:
        raise CardError('the repository index must list exactly one release')
    entry = index['data'][0]
    if not entry['archive_url'].endswith('.zip'):
        raise CardError(f'the archive URL {entry["archive_url"]} is not a .zip')
    return f'{entry["archive_url"]}?repository={quote(REPOSITORY_URL, safe="")}&blender_version_min={entry["blender_version_min"]}'


def stamp_version(site, root=None):
    source_root = ROOT if root is None else Path(root)
    version = read_manifest(source_root)['version']
    for page in sorted(site.rglob('*.html')):
        text = page.read_text(encoding='utf-8')
        if VERSION_PLACEHOLDER in text:
            page.write_text(text.replace(VERSION_PLACEHOLDER, version), encoding='utf-8')
    for name in VERSIONED_DOCS:
        text = (source_root / name).read_text(encoding='utf-8')
        if VERSION_PLACEHOLDER not in text:
            raise CardError(f'{name} has no {VERSION_PLACEHOLDER} placeholder')
        (site / name).write_text(text.replace(VERSION_PLACEHOLDER, version), encoding='utf-8')
    return version


def stamp_cards(site):
    href = card_href(json.loads((site / 'repo' / 'index.json').read_text(encoding='utf-8')))
    attribute = f'href="{html.escape(href)}"'
    for name in CARD_PAGES:
        page = site / name
        text, count = CARD_HREF.subn(lambda _match: attribute, page.read_text(encoding='utf-8'))
        if count == 0:
            raise CardError(f'{name} has no drag-and-drop install card')
        page.write_text(text, encoding='utf-8')
    return href


def main():
    if len(sys.argv) != 2:
        print('usage: python tools/install_card.py SITE_FOLDER')
        return 2
    try:
        site = Path(sys.argv[1])
        print(stamp_version(site))
        print(stamp_cards(site))
    except (CardError, OSError, KeyError, ValueError) as error:
        print(f'ERROR: install card not built: {error}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
