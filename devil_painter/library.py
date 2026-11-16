import json
import re
from pathlib import Path
import bpy
from .blending import CHANNEL
from .compositing import assign_image_colorspace
from .document import SLOT_FIELDS

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.bmp', '.webp'}
MAX_FILES = 600
CHANNEL_WORDS = {'base_color': {'basecolor', 'albedo', 'diffuse', 'diff', 'color', 'col'}, 'roughness': {'roughness', 'rough'},
                 'metallic': {'metallic', 'metalness', 'metal'}, 'normal': {'normal', 'normalgl', 'nor', 'nrm'},
                 'height': {'height', 'displacement', 'disp', 'bump'}, 'emission': {'emission', 'emissive'}, 'opacity': {'opacity', 'alpha'}}
DIRECTX_WORDS = {'dx', 'normaldx'}
SETTINGS_FILE = 'library.json'
_cache = {}


def plain(value, blend='MIX'):
    return dict(source='VALUE', value=value, blend=blend)


def pattern(key, value, second, scale=8.0, detail=.5, contrast=.3):
    return dict(source='PATTERN', pattern=key, value=value, second=second, scale=scale, detail=detail, contrast=contrast)


def texture(path):
    return dict(source='IMAGE', image=str(path))


def material(name, projection='UV', tiling=1.0, **slots):
    return dict(name=name, projection=projection, tiling=tiling, slots=slots)


BUILTIN_MATERIALS = (
    material('Red Plastic', base_color=plain((.5, .02, .02)), roughness=plain(.3), metallic=plain(0.0)),
    material('White Ceramic', base_color=plain((.8, .8, .78)), roughness=plain(.08), metallic=plain(0.0)),
    material('Black Rubber', 'TRIPLANAR', base_color=plain((.02, .02, .02)), roughness=plain(.9), metallic=plain(0.0),
             height=pattern('NOISE', .45, .55, 220.0, .2, 0.0)),
    material('Steel', base_color=plain((.56, .57, .58)), roughness=plain(.3), metallic=plain(1.0)),
    material('Gold', base_color=plain((1.0, .766, .336)), roughness=plain(.2), metallic=plain(1.0)),
    material('Copper', base_color=plain((.955, .637, .538)), roughness=plain(.25), metallic=plain(1.0)),
    material('Brushed Aluminium', 'TRIPLANAR', base_color=plain((.91, .92, .92)), metallic=plain(1.0),
             roughness=pattern('STRIPES', .2, .45, 300.0, .3, 0.0)),
    material('Rust', 'TRIPLANAR', base_color=pattern('GRUNGE', (.3, .08, .02), (.1, .025, .01), 5.0, .8, .2), roughness=plain(.85),
             metallic=plain(0.0), height=pattern('GRUNGE', .4, .6, 5.0, .8, .2)),
    material('Wood', 'TRIPLANAR', base_color=pattern('WOOD', (.35, .17, .06), (.16, .06, .02), 2.0, .6, .1), roughness=plain(.6),
             metallic=plain(0.0)),
    material('Concrete', 'TRIPLANAR', base_color=pattern('NOISE', (.35, .35, .33), (.2, .2, .19), 18.0, .9, .1), roughness=plain(.9),
             metallic=plain(0.0), height=pattern('NOISE', .45, .55, 40.0, .9, 0.0)),
    material('Tiles', 'TRIPLANAR', base_color=pattern('BRICKS', (.75, .75, .72), (.25, .25, .25), 3.0, .4, 0.0), roughness=plain(.25),
             metallic=plain(0.0), height=pattern('BRICKS', 1.0, 0.0, 3.0, .4, 0.0)),
    material('Leather', 'TRIPLANAR', base_color=plain((.12, .05, .02)), roughness=plain(.6), metallic=plain(0.0),
             height=pattern('CELLS', .4, .6, 60.0, 1.0, .2)),
    material('Lava', 'TRIPLANAR', base_color=plain((.02, .02, .02)), roughness=plain(.8), metallic=plain(0.0),
             emission=pattern('CRACKS', (1.0, .25, 0.0), (0.0, 0.0, 0.0), 4.0, 1.0, .6)),
)


def library_root():
    return Path(bpy.utils.user_resource('CONFIG', path='devil_painter', create=True))


def settings():
    if 'settings' not in _cache:
        path = library_root() / SETTINGS_FILE
        values = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        _cache['settings'] = dict(texture_folder=values.get('texture_folder', ''), materials=values.get('materials', []))
    return _cache['settings']


def save_settings():
    (library_root() / SETTINGS_FILE).write_text(json.dumps(settings(), indent=1), encoding='utf-8')


def user_materials():
    return settings()['materials']


def add_user_material(definition):
    names = {item['name'] for item in user_materials()}
    base, number = definition['name'], 1
    while definition['name'] in names:
        number += 1
        definition['name'] = f'{base} {number}'
    user_materials().append(definition)
    save_settings()
    return definition['name']


def remove_user_material(index):
    name = user_materials().pop(index)['name']
    save_settings()
    return name


def texture_folder():
    return settings()['texture_folder']


def set_texture_folder(folder):
    settings()['texture_folder'] = folder.strip()
    _cache.pop('scan', None)
    save_settings()


def tokens(stem):
    return [token for token in re.split(r'[\s_\-.]+', stem.lower()) if token]


def channel_of(words):
    for index in range(len(words) - 1, -1, -1):
        for key, names in CHANNEL_WORDS.items():
            if words[index] in names:
                return key, index
    return None, -1


def texture_sets(files):
    sets = {}
    for path in files:
        words = tokens(path.stem)
        key, index = channel_of(words)
        if key is None:
            continue
        rest = [word for position, word in enumerate(words) if position != index and word not in DIRECTX_WORDS and word != 'gl']
        group = sets.setdefault((str(path.parent), ' '.join(rest)), {})
        directx = bool(DIRECTX_WORDS & set(words))
        if key not in group or (key == 'normal' and not directx):
            group[key] = path
    result = []
    for (_, name), maps in sorted(sets.items()):
        if 'base_color' in maps and len(maps) > 1:
            result.append(material(name.title() or maps['base_color'].stem, **{key: texture(path) for key, path in maps.items()}))
    return result


def scan():
    folder = texture_folder()
    if _cache.get('scan', (None,))[0] != folder:
        root = Path(folder) if folder else None
        files = []
        if root is not None and root.is_dir():
            for path in sorted(root.rglob('*')):
                if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
                    files.append(path)
                    if len(files) >= MAX_FILES:
                        break
        _cache['scan'] = (folder, files, texture_sets(files))
    return _cache['scan'][1:]


def rescan():
    _cache.pop('scan', None)


def load_image(path, channel):
    image = bpy.data.images.load(str(path), check_existing=True)
    assign_image_colorspace(image, channel)
    return image


def apply_definition(layer, definition):
    layer.projection = definition.get('projection', 'UV')
    layer.tiling = definition.get('tiling', 1.0)
    for slot in layer.slots:
        values = definition['slots'].get(slot.name)
        slot.enabled = values is not None
        if values is None:
            continue
        channel = CHANNEL[slot.name]
        slot.source = values.get('source', 'VALUE')
        slot.blend = values.get('blend', 'MIX')
        for field in ('pattern', 'scale', 'detail', 'contrast'):
            if field in values:
                setattr(slot, field, values[field])
        for field, target in (('value', ''), ('second', '_b')):
            if field in values:
                value = values[field]
                if channel.width == 3:
                    setattr(slot, 'color' + target, value)
                else:
                    setattr(slot, 'value' + target, float(value))
        if slot.source == 'IMAGE':
            path = Path(values.get('image', ''))
            if path.is_file():
                slot.image = load_image(path, channel)
            else:
                slot.source = 'VALUE'


def capture(layer):
    slots = {}
    for slot in layer.slots:
        if not slot.enabled:
            continue
        channel = CHANNEL[slot.name]
        values = {field: getattr(slot, field) for field in SLOT_FIELDS if field not in {'enabled', 'color', 'value', 'color_b', 'value_b'}}
        values['value'] = list(slot.color) if channel.width == 3 else slot.value
        values['second'] = list(slot.color_b) if channel.width == 3 else slot.value_b
        if slot.source == 'IMAGE':
            filepath = bpy.path.abspath(slot.image.filepath) if slot.image and slot.image.filepath else ''
            if filepath:
                values['image'] = filepath
            else:
                values['source'] = 'VALUE'
        slots[slot.name] = values
    return material(layer.name, layer.projection, layer.tiling, **slots)
