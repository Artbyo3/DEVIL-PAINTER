from dataclasses import dataclass
from pathlib import Path
from . import thumbnails
from .brushes import ALPHAS, PRESETS, alpha_path, preview_path
from .library import BUILTIN_MATERIALS, is_managed, material, pattern, plain, scan, texture, user_materials
from .masks import SMART_MASKS
from .procedural import PATTERN, PATTERNS

TABS = (('MATERIALS', 'Materials'), ('TEXTURES', 'Textures'), ('PATTERNS', 'Patterns'), ('MASKS', 'Masks'), ('BRUSHES', 'Brushes'),
        ('ALPHAS', 'Alphas'))


@dataclass(frozen=True)
class Item:
    label: str
    kind: str
    payload: object
    user_index: int = -1
    preview_file: str = ''
    managed: bool = False


def pattern_definition(key):
    return material(PATTERN[key].label, 'TRIPLANAR', base_color=pattern(key, (.005, .005, .005), (.6, .6, .6), 3.0, .5, .5),
                    roughness=plain(.95))


def mask_definition(preset):
    return dict(name=preset['name'], layers=[material('Base', base_color=plain((.02, .02, .02)), roughness=plain(.7)),
                                             dict(material(preset['name'], base_color=plain((.85, .85, .85)), roughness=plain(.4)),
                                                  generator={key: value for key, value in preset.items() if key != 'name'})])


def texture_definition(path):
    return material(Path(path).stem, base_color=texture(path))


def items(tab):
    if tab == 'MATERIALS':
        _, sets = scan()
        return ([Item(definition['name'], 'MATERIAL', definition) for definition in BUILTIN_MATERIALS]
                + [Item(definition['name'], 'MATERIAL', definition, index) for index, definition in enumerate(user_materials())]
                + [Item(definition['name'], 'MATERIAL', definition, preview_file=definition['slots']['base_color']['image']) for definition in sets])
    if tab == 'TEXTURES':
        files, _ = scan()
        return [Item(path.stem, 'TEXTURE', path, managed=is_managed(path)) for path in files]
    if tab == 'MASKS':
        return [Item(preset['name'], 'MASK', preset) for preset in SMART_MASKS]
    if tab == 'BRUSHES':
        return [Item(preset['name'], 'BRUSH', preset, preview_file=str(preview_path(preset))) for preset in PRESETS]
    if tab == 'ALPHAS':
        return [Item('No alpha', 'ALPHA', '')] + [Item(name, 'ALPHA', name, preview_file=str(alpha_path(name))) for name in ALPHAS]
    return [Item(entry.label, 'PATTERN', entry.key) for entry in PATTERNS]


def thumbnail(item):
    if item.kind == 'TEXTURE':
        return thumbnails.file_texture(item.payload)
    if item.preview_file:
        return thumbnails.file_texture(item.preview_file)
    if item.kind == 'ALPHA':
        return None
    if item.kind == 'PATTERN':
        return thumbnails.material_texture(pattern_definition(item.payload))
    if item.kind == 'MASK':
        return thumbnails.material_texture(mask_definition(item.payload))
    return thumbnails.material_texture(item.payload)
