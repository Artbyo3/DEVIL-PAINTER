import json
import os
import re
import shutil
import tempfile
from pathlib import Path
import bpy
from .blending import CHANNEL
from .compositing import assign_image_colorspace
from .document import SLOT_FIELDS
from .masks import GENERATOR_FIELDS

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.bmp', '.webp'}
MAX_FILES = 600
CHANNEL_WORDS = {'base_color': {'basecolor', 'albedo', 'color', 'col'}, 'roughness': {'roughness', 'rough'},
                 'metallic': {'metallic', 'metalness', 'metal'}, 'normal': {'normal', 'normalgl', 'nor', 'nrm'},
                 'height': {'height', 'bump'}, 'emission': {'emission', 'emissive'}, 'opacity': {'opacity', 'alpha'},
                 'diffuse': {'diffuse', 'diff'}, 'specular': {'specular', 'spec'}, 'glossiness': {'glossiness', 'gloss', 'glossy'},
                 'displacement': {'displacement', 'disp'}, 'anisotropy_level': {'anisotropy', 'aniso', 'anisotropylevel', 'anisolevel'},
                 'anisotropy_angle': {'anisotropyangle', 'anisoangle'}, 'transmission': {'transmission', 'transmissive'},
                 'scattering': {'scattering', 'sss', 'subsurface'}, 'sheen': {'sheen'}, 'coat': {'coat', 'clearcoat'}, 'ior': {'ior'}}
FALLBACK_CHANNELS = (('diffuse', 'base_color'), ('displacement', 'height'))
JOINED_WORDS = re.compile(r'(anisotropy|aniso)[\s_\-.]+(level|angle)')
DIRECTX_WORDS = {'dx', 'normaldx'}
SETTINGS_FILE = 'library.json'
DAMAGED_SUFFIX = '.damaged'
PACK_MARKER = '.installed'
PACK_KINDS = ('Textures', 'Alphas', 'Materials', 'Brushes', 'Generators')
BLEND_SUFFIX = '.blend'
VECTOR_SUFFIX = '.svg'
IMPORT_SUFFIXES = IMAGE_SUFFIXES | {BLEND_SUFFIX, VECTOR_SUFFIX}
BLEND_INPUTS = (('base_color', 'Base Color'), ('roughness', 'Roughness'), ('metallic', 'Metallic'), ('normal', 'Normal'),
                ('emission', 'Emission Color'), ('opacity', 'Alpha'))
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
    if 'root' not in _cache:
        _cache['root'] = Path(bpy.utils.user_resource('CONFIG', path='devil_painter', create=True))
    return _cache['root']


def library_folder(name):
    key = 'folder ' + name
    if key not in _cache:
        folder = library_root() / name
        folder.mkdir(parents=True, exist_ok=True)
        _cache[key] = folder
    return _cache[key]


def read_settings(path):
    if not path.is_file():
        return {}
    try:
        values = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        values = None
    if isinstance(values, dict):
        return values
    damaged = path.with_name(path.name + DAMAGED_SUFFIX)
    os.replace(path, damaged)
    _cache['notice'] = f'Settings were damaged and reset. Old file kept as {damaged.name}.'
    return {}


def settings():
    if 'settings' not in _cache:
        values = read_settings(library_root() / SETTINGS_FILE)
        _cache['settings'] = dict(values, texture_folder=values.get('texture_folder', ''), materials=values.get('materials', []))
    return _cache['settings']


def settings_notice():
    return _cache.pop('notice', '')


def save_settings():
    path = library_root() / SETTINGS_FILE
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as handle:
        json.dump(settings(), handle, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)


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
    return [token for token in re.split(r'[\s_\-.]+', JOINED_WORDS.sub(lambda found: found.group(1) + found.group(2), stem.lower())) if token]


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
        for source, target in FALLBACK_CHANNELS:
            if source in maps and target not in maps:
                maps[target] = maps[source]
        if 'base_color' in maps and len(maps) > 1:
            result.append(material(name.title() or maps['base_color'].stem, **{key: texture(path) for key, path in maps.items()}))
    return result


def managed_folder():
    return library_folder('textures')


def image_files(root):
    files = []
    if root is not None and root.is_dir():
        for path in sorted(root.rglob('*')):
            if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
                files.append(path)
                if len(files) >= MAX_FILES:
                    break
    return files


def scan():
    folder = texture_folder()
    if _cache.get('scan', (None,))[0] != folder or 'scan' not in _cache:
        managed = image_files(managed_folder())
        browsed = [path for root in library_roots() for path in image_files(root) if path not in managed]
        files = list(dict.fromkeys(managed + browsed))
        roots = [managed_folder(), *library_roots()]
        _cache['scan'] = (folder, files, texture_sets(files), suffix_files(roots, BLEND_SUFFIX), frozenset(managed), suffix_files(roots, VECTOR_SUFFIX))
    return _cache['scan'][1:3]


def suffix_files(roots, suffix):
    found = []
    for root in roots:
        if root.is_dir():
            found += [path for path in sorted(root.rglob('*' + suffix)) if path.is_file()]
    return list(dict.fromkeys(found))[:MAX_FILES]


def vector_files():
    scan()
    return _cache['scan'][5]


def managed_files():
    scan()
    return _cache['scan'][4]


def scanned_blends():
    scan()
    return _cache['scan'][3]


def is_managed(path):
    return Path(path).resolve().parent == managed_folder().resolve()


def import_textures(paths):
    folder = managed_folder()
    imported = 0
    for source in paths:
        source = Path(source)
        if source.suffix.lower() not in IMPORT_SUFFIXES or not source.is_file():
            continue
        target, number = folder / source.name, 1
        while target.exists():
            number += 1
            target = folder / f'{source.stem} {number}{source.suffix}'
        shutil.copyfile(source, target)
        imported += 1
    rescan()
    return imported


def remove_texture(path):
    if not is_managed(path):
        raise ValueError('Only imported textures can be removed from the library.')
    Path(path).unlink()
    rescan()
    return Path(path).stem


def rescan():
    _cache.pop('scan', None)


def libraries():
    return settings().setdefault('libraries', [])


def add_library(folder):
    folder = folder.strip()
    if not folder or folder in libraries() or not Path(folder).is_dir():
        return False
    libraries().append(folder)
    save_settings()
    rescan()
    return True


def remove_library(index):
    folder = libraries().pop(index)
    save_settings()
    rescan()
    return folder


def packs_folder():
    return library_folder('packs')


def installed_packs():
    return [folder for folder in sorted(packs_folder().iterdir()) if folder.is_dir() and folder.name != 'downloads' and not folder.name.endswith('.partial')
            and ((folder / PACK_MARKER).is_file() or any((folder / kind).is_dir() for kind in PACK_KINDS))]


def pack_texture_roots():
    return [folder / 'Textures' if (folder / 'Textures').is_dir() else folder for folder in installed_packs()
            if (folder / 'Textures').is_dir() or not (folder / 'Alphas').is_dir()]


def pack_alphas():
    return [path for folder in installed_packs() for path in sorted((folder / 'Alphas').glob('*')) if path.suffix.lower() in IMAGE_SUFFIXES]


def library_roots():
    return [Path(folder) for folder in dict.fromkeys([texture_folder(), *libraries()]) if folder] + pack_texture_roots()


def blend_materials(path):
    key = ('blend', str(path), path.stat().st_mtime)
    if key not in _cache:
        with bpy.data.libraries.load(str(path)) as (source, _):
            _cache[key] = sorted(source.materials)
    return _cache[key]


def upstream_image(socket, depth=4):
    if not socket.is_linked or depth == 0:
        return None
    node = socket.links[0].from_node
    if node.type == 'TEX_IMAGE':
        return node.image
    return next((image for item in node.inputs if (image := upstream_image(item, depth - 1)) is not None), None)


def image_file(image):
    path = Path(bpy.path.abspath(image.filepath)) if image.filepath else None
    if path is not None and path.is_file():
        return str(path)
    folder = library_root() / 'blend_textures'
    folder.mkdir(exist_ok=True)
    target = folder / (re.sub(r'[^A-Za-z0-9]+', '_', image.name).strip('_') + '.png')
    image.filepath_raw = str(target)
    image.file_format = 'PNG'
    image.save()
    return str(target)


def convert_material(item):
    shader = next((node for node in item.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'), None) if item.node_tree is not None else None
    if shader is None:
        return dict(base_color=plain(tuple(item.diffuse_color[:3])), roughness=plain(item.roughness), metallic=plain(item.metallic))
    slots = {}
    for key, name in BLEND_INPUTS:
        socket = shader.inputs[name]
        image = upstream_image(socket)
        if image is not None:
            slots[key] = texture(image_file(image))
        elif key in {'base_color', 'roughness', 'metallic'}:
            value = socket.default_value
            slots[key] = plain(tuple(value[:3]) if key == 'base_color' else float(value))
    return slots


def blend_definition(path, name):
    key = ('blend_definition', str(path), Path(path).stat().st_mtime, name)
    if key not in _cache:
        with bpy.data.libraries.load(str(path)) as (_, target):
            target.materials = [name]
        loaded = target.materials[0]
        images = {node.image for node in loaded.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image is not None} if loaded.node_tree else set()
        try:
            _cache[key] = material(name, **convert_material(loaded))
        finally:
            bpy.data.batch_remove([loaded, *images])
    return _cache[key]


def load_image(path, channel):
    image = bpy.data.images.load(str(path), check_existing=True)
    assign_image_colorspace(image, channel)
    return image


def generator_entry(values):
    return dict(kind='GENERATOR', target='MASK', blend='MULTIPLY', opacity=1.0, **{field: values[field] for field in GENERATOR_FIELDS if field in values})


def definition_effects(definition):
    values = definition.get('generator', {})
    legacy = [generator_entry(values)] if values.get('generator', 'NONE') != 'NONE' else []
    return legacy + list(definition.get('effects', ()))


def generator_values(effect):
    return dict(kind='GENERATOR', target=effect.target, enabled=effect.enabled, blend=effect.blend, opacity=effect.opacity,
                **{field: getattr(effect, field) for field in GENERATOR_FIELDS})


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
        for field in ('pattern', 'scale', 'detail', 'contrast', 'opacity', 'wrap', 'filtering'):
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
        values = {field: getattr(slot, field) for field in SLOT_FIELDS if field not in {'enabled', 'switched_off', 'color', 'value', 'color_b', 'value_b'}}
        values['value'] = list(slot.color) if channel.width == 3 else slot.value
        values['second'] = list(slot.color_b) if channel.width == 3 else slot.value_b
        if slot.source == 'IMAGE':
            filepath = bpy.path.abspath(slot.image.filepath) if slot.image and slot.image.filepath else ''
            if filepath:
                values['image'] = filepath
            else:
                values['source'] = 'VALUE'
        slots[slot.name] = values
    result = material(layer.name, layer.projection, layer.tiling, **slots)
    generators = [generator_values(effect) for effect in layer.effects if effect.kind == 'GENERATOR']
    if generators:
        result['effects'] = generators
    return result
