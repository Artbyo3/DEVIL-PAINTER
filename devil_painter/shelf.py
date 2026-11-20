from dataclasses import dataclass
from pathlib import Path
import bpy
import numpy
from . import packs, thumbnails
from .brushes import ALPHAS, PRESETS, alpha_path, preview_path, user_presets
from .filters import FILTER, FILTERS
from .library import (BUILTIN_MATERIALS, blend_definition, blend_materials, library_root, managed_files, material, pattern, plain, save_settings, scan,
                      pack_alphas, scanned_blends, settings, texture, user_materials, vector_files)
from .vectors import preview_file
from .masks import GENERATOR, GENERATORS, SMART_MASKS
from .smart import BUILTIN_SMART, smart_masks, smart_materials, write_pixels
from .procedural import PATTERN, PATTERNS

TABS = (('MATERIALS', 'Materials'), ('SMART', 'Smart'), ('TEXTURES', 'Textures'), ('PATTERNS', 'Patterns'), ('MASKS', 'Masks'),
        ('GENERATORS', 'Generators'), ('FILTERS', 'Filters'), ('BRUSHES', 'Brushes'), ('ALPHAS', 'Alphas'), ('ENVIRONMENTS', 'Lighting'),
        ('PACKS', 'Packs'))
TAB_ICONS = {'MASKS': 'MASK'}
SCOPES = (('ALL', 'All'), ('BUILTIN', 'Built-in'), ('MINE', 'Mine'))
FILTER_BASE = 'filter_base.png'
FILTER_BASE_SIZE = 64


@dataclass(frozen=True)
class Item:
    label: str
    kind: str
    payload: object
    user_index: int = -1
    preview_file: str = ''
    managed: bool = False
    mine: bool = False


def pattern_definition(key):
    return material(PATTERN[key].label, 'TRIPLANAR', base_color=pattern(key, (.005, .005, .005), (.6, .6, .6), 3.0, .5, .5),
                    roughness=plain(.95))


def mask_definition(preset):
    return dict(name=preset['name'], layers=[material('Base', base_color=plain((.02, .02, .02)), roughness=plain(.7)),
                                             dict(material(preset['name'], base_color=plain((.85, .85, .85)), roughness=plain(.4)),
                                                  generator={key: value for key, value in preset.items() if key != 'name'})])


def filter_base():
    path = library_root() / 'previews' / FILTER_BASE
    if not path.is_file():
        path.parent.mkdir(exist_ok=True)
        rows, columns = numpy.mgrid[0:FILTER_BASE_SIZE, 0:FILTER_BASE_SIZE] / FILTER_BASE_SIZE
        pixels = numpy.ones((FILTER_BASE_SIZE, FILTER_BASE_SIZE, 4), dtype=numpy.float32)
        checker = ((rows * 4).astype(int) + (columns * 4).astype(int)) % 2
        pixels[..., 0] = .15 + .7 * checker
        pixels[..., 1] = .2 + .6 * columns
        pixels[..., 2] = .8 - .6 * rows
        write_pixels(pixels.ravel(), FILTER_BASE_SIZE, FILTER_BASE_SIZE, path, False)
    return path


def filter_definition(key):
    effect = dict(kind='FILTER', target='CONTENT', filter=key, enabled=True, opacity=1.0, channel='ALL')
    return dict(material(FILTER[key].label, base_color=texture(filter_base()), roughness=plain(.5)), effects=[effect])


def generator_definition(key):
    return mask_definition(dict(name=GENERATOR[key].label, generator=key, gen_level=.3, gen_contrast=.6, gen_noise=.2, gen_scale=20.0, gen_invert=False))


def environments():
    return [light for light in bpy.context.preferences.studio_lights if light.type == 'WORLD']


def blend_items():
    return [Item(name, 'MATERIAL', dict(name=name, blend=str(path)), mine=True) for path in scanned_blends() for name in blend_materials(path)]


def resolved(definition):
    return blend_definition(definition['blend'], definition['name']) if 'blend' in definition else definition


def texture_definition(path):
    return material(Path(path).stem, base_color=texture(path))


def items(tab):
    if tab == 'MATERIALS':
        _, sets = scan()
        return ([Item(definition['name'], 'MATERIAL', definition) for definition in BUILTIN_MATERIALS]
                + [Item(definition['name'], 'MATERIAL', definition, index, mine=True) for index, definition in enumerate(user_materials())]
                + [Item(definition['name'], 'MATERIAL', definition, preview_file=definition['slots']['base_color']['image'], mine=True) for definition in sets]
                + blend_items())
    if tab == 'TEXTURES':
        files, _ = scan()
        managed = managed_files()
        return ([Item(path.stem, 'TEXTURE', path, managed=path in managed, mine=True) for path in files]
                + [Item(path.stem, 'VECTOR', path, preview_file=preview_file(path, library_root() / 'vector_previews'), mine=True) for path in vector_files()])
    if tab == 'SMART':
        return ([Item(definition['name'], 'SMART', definition) for definition in BUILTIN_SMART]
                + [Item(definition['name'], 'SMART', definition, index, mine=True) for index, definition in enumerate(smart_materials())])
    if tab == 'MASKS':
        return ([Item(preset['name'], 'MASK', preset) for preset in SMART_MASKS]
                + [Item(definition['name'], 'MASK', definition, index, definition['preview'], mine=True) for index, definition in enumerate(smart_masks())])
    if tab == 'GENERATORS':
        return [Item(generator.label, 'GENERATOR', generator.key) for generator in GENERATORS]
    if tab == 'FILTERS':
        return [Item(item.label, 'FILTER', item.key) for item in FILTERS]
    if tab == 'ENVIRONMENTS':
        return [Item(light.name.rsplit('.', 1)[0], 'ENVIRONMENT', light.name, preview_file=light.path) for light in environments()]
    if tab == 'BRUSHES':
        return ([Item(preset['name'], 'BRUSH', preset, preview_file=str(preview_path(preset))) for preset in PRESETS]
                + [Item(preset['name'], 'BRUSH', preset, index, str(preview_path(preset)), mine=True) for index, preset in enumerate(user_presets())])
    if tab == 'ALPHAS':
        return ([Item('No alpha', 'ALPHA', '')] + [Item(name, 'ALPHA', name, preview_file=str(alpha_path(name))) for name in ALPHAS]
                + [Item(path.stem, 'ALPHA', str(path), preview_file=str(path), mine=True) for path in pack_alphas()])
    if tab == 'PACKS':
        opened = packs.open_entry()
        if opened is not None:
            return [Item(Path(name).stem, 'PACKFILE', (opened, name), preview_file=packs.preview(opened, name), mine=True) for name in packs.files(opened)]
        return [Item(entry['name'], 'PACK', entry, preview_file=packs.preview(entry, packs.first_file(entry)), mine=True) for entry in packs.catalog()]
    return [Item(entry.label, 'PATTERN', entry.key) for entry in PATTERNS]


def visible(tab, query='', scope='ALL'):
    words = query.lower().split()
    return [item for item in items(tab) if all(word in item.label.lower() for word in words)
            and (scope == 'ALL' or item.mine == (scope == 'MINE'))]


def saved_searches():
    return settings().setdefault('saved_searches', [])


def save_search(tab, query):
    entry = dict(tab=tab, query=query.strip())
    if entry['query'] and entry not in saved_searches():
        saved_searches().append(entry)
        save_settings()
    return entry['query']


def remove_search(index):
    query = saved_searches().pop(index)['query']
    save_settings()
    return query


def preview_source(item):
    if item.kind == 'TEXTURE':
        return 'FILE', item.payload
    if item.preview_file:
        return 'FILE', item.preview_file
    if item.kind in {'ALPHA', 'PACK', 'PACKFILE'}:
        return None
    if item.kind == 'PATTERN':
        return 'MATERIAL', pattern_definition(item.payload)
    if item.kind == 'MASK':
        return 'MATERIAL', mask_definition(item.payload)
    if item.kind == 'GENERATOR':
        return 'MATERIAL', generator_definition(item.payload)
    if item.kind == 'FILTER':
        return 'MATERIAL', filter_definition(item.payload)
    if item.kind == 'MATERIAL':
        return 'MATERIAL', resolved(item.payload)
    if item.kind == 'SMART':
        if any(entry['kind'] == 'FILL' for entry in item.payload['layers']):
            return 'MATERIAL', item.payload
        paints = [entry['paint'] for entry in item.payload['layers'] if entry['paint']]
        return ('FILE', paints[0]) if paints else None
    return 'MATERIAL', item.payload


def thumbnail(item):
    source = preview_source(item)
    if source is None:
        return None
    return thumbnails.file_texture(source[1]) if source[0] == 'FILE' else thumbnails.material_texture(source[1])


def prefetch(item):
    if item.kind not in {'PACK', 'PACKFILE'}:
        thumbnail(item)


def pack_preview(item):
    return (item.payload, packs.first_file(item.payload)) if item.kind == 'PACK' else item.payload


def failed(item):
    if item.kind in {'PACK', 'PACKFILE'}:
        return packs.preview_failed(*pack_preview(item))
    source = preview_source(item)
    if source is None:
        return False
    return thumbnails.failed_file(source[1]) if source[0] == 'FILE' else thumbnails.failed_material(source[1])
