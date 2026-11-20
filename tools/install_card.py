import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

REPOSITORY_URL = 'https://artbyo3.github.io/DEVIL-PAINTER/repo/index.json'
CARD_PAGES = ('index.html', 'install/index.html')
CARD_HREF = re.compile(r'data-blender-drop href="[^"]*"')


class CardError(Exception):
    pass


def card_href(index):
    if len(index.get('data') or []) != 1:
        raise CardError('the repository index must list exactly one release')
    entry = index['data'][0]
    if not entry['archive_url'].endswith('.zip'):
        raise CardError(f'the archive URL {entry["archive_url"]} is not a .zip')
    return f'{entry["archive_url"]}?repository={quote(REPOSITORY_URL, safe="")}&blender_version_min={entry["blender_version_min"]}'


def stamp_cards(site):
    href = card_href(json.loads((site / 'repo' / 'index.json').read_text(encoding='utf-8')))
    attribute = f'data-blender-drop href="{html.escape(href)}"'
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
        print(stamp_cards(Path(sys.argv[1])))
    except (CardError, OSError, KeyError, ValueError) as error:
        print(f'ERROR: install card not built: {error}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
