import json
from pathlib import Path

from PIL import Image

from tools.prepare_blender_icons import make_spans

ADOPTED_ICONS = {'DELETE': 'delete', 'FOLDER': 'folder', 'GENERATOR': 'generator', 'HIDE_OFF': 'hide_on', 'HIDE_ON': 'hide_off', 'LAYER_MATERIAL': 'layer_material', 'MASK': 'mask'}


def prepare():
    folder = Path(__file__).resolve().parents[1] / 'devil_painter' / 'assets' / 'icons' / 'devil-painter'
    geometry = {key: make_spans(Image.open(folder / (name + '.png')).convert('RGBA')) for key, name in ADOPTED_ICONS.items()}
    (folder / 'geometry.json').write_text(json.dumps(geometry, separators=(',', ':')), encoding='utf-8')
    print('Prepared', len(geometry), 'Devil Painter icons')


if __name__ == '__main__':
    prepare()
