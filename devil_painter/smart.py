import re
import time
import bpy
import numpy
from .blending import CHANNEL
from .document import add_slots, children, texture_set
from .effects import EFFECT_FIELDS
from .tiles import adopt
from .library import (BUILTIN_MATERIALS, apply_definition, apply_generator, capture, library_root, load_image, material, pattern, plain, save_settings,
                      settings)
from .masks import GENERATOR_FIELDS, SMART_MASKS

PRESET = {item['name']: item for item in SMART_MASKS}
BASE = {item['name']: item for item in BUILTIN_MATERIALS}


def masked(definition, mask_name, **changes):
    preset = dict(PRESET[mask_name], **changes)
    return dict(definition, generator={key: preset[key] for key in GENERATOR_FIELDS})


def entry(definition, parent=-1):
    return dict(definition, kind='FILL', parent=parent, opacity=1.0, visible=True, mask='', paint='')


BUILTIN_SMART = (
    dict(name='Worn Paint', layers=[entry(BASE['Steel']),
                                    entry(masked(material('Paint', base_color=plain((.45, .03, .03)), roughness=plain(.45), metallic=plain(0.0)), 'Clean faces'))]),
    dict(name='Rusty Iron', layers=[entry(material('Iron', base_color=plain((.25, .25, .26)), roughness=plain(.55), metallic=plain(1.0))),
                                    entry(masked(BASE['Rust'], 'Grime')),
                                    entry(masked(BASE['Rust'], 'Cavity'))]),
    dict(name='Dusty Plastic', layers=[entry(material('Plastic', base_color=plain((.05, .12, .35)), roughness=plain(.35), metallic=plain(0.0))),
                                       entry(masked(material('Dust', base_color=plain((.55, .5, .42)), roughness=plain(.95), metallic=plain(0.0)), 'Ground dust'))]),
    dict(name='Scuffed Gold', layers=[entry(BASE['Gold']),
                                      entry(masked(material('Scuffs', 'TRIPLANAR', roughness=pattern('STRIPES', .25, .6, 120.0, .4, 0.0)), 'Soft edges'))]),
    dict(name='Dirty Concrete', layers=[entry(BASE['Concrete']),
                                        entry(masked(material('Grime', base_color=plain((.06, .05, .04)), roughness=plain(.9), metallic=plain(0.0)), 'Dirt'))]),
)


def smart_materials():
    return settings().setdefault('smart_materials', [])


def write_png(image, path, data_values):
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return write_pixels(pixels, width, height, path, data_values)


def write_pixels(pixels, width, height, path, data_values):
    copy = bpy.data.images.new(path.stem, width, height, alpha=True)
    try:
        if data_values:
            copy.colorspace_settings.name = 'Non-Color'
        copy.pixels.foreach_set(pixels)
        copy.filepath_raw = str(path)
        copy.file_format = 'PNG'
        copy.save()
    finally:
        bpy.data.images.remove(copy)
    return str(path)


def smart_masks():
    return settings().setdefault('smart_masks', [])


def plain_value(value):
    return value if isinstance(value, (str, int, float, bool)) else list(value)


def effect_entry(effect, folder):
    values = {field: plain_value(getattr(effect, field)) for field in EFFECT_FIELDS if field != 'texture'}
    values['image'] = write_png(effect.image, folder / f'{effect.uid}.png', False) if effect.image is not None else ''
    values['texture'] = bpy.path.abspath(effect.texture.filepath) if effect.texture is not None and effect.texture.filepath else ''
    return values


def portable(effect):
    return effect.kind not in {'COMPARE', 'ANCHOR'}


def add_effects(obj, data, layer, entries):
    for entry in entries:
        data.serial += 1
        effect = layer.effects.add()
        effect.uid = f'E{data.serial}'
        for field, value in entry.items():
            if field not in {'image', 'texture'}:
                setattr(effect, field, value)
        if entry['image']:
            effect.image = owned_image(data, entry['image'], f'DP {obj.name} {data.name} {layer.uid} {effect.uid}', False)
        if entry['texture']:
            effect.texture = load_image(entry['texture'], CHANNEL['roughness'])


def unique_name(definitions, name):
    names = {item['name'] for item in definitions}
    base, number = name, 1
    while name in names:
        number += 1
        name = f'{base} {number}'
    return name


def save_mask(layer, preview):
    slug = re.sub(r'[^A-Za-z0-9]+', '_', layer.name).strip('_') or 'mask'
    folder = library_root() / 'smart_masks' / f'{slug}_{int(time.time() * 1000)}'
    folder.mkdir(parents=True)
    definition = dict(name=unique_name(smart_masks(), layer.name + ' mask'), generator={field: getattr(layer, field) for field in GENERATOR_FIELDS},
                      mask=write_png(layer.mask, folder / 'mask.png', False) if layer.mask is not None else '',
                      effects=[effect_entry(effect, folder) for effect in layer.effects if effect.target == 'MASK' and portable(effect)],
                      preview=write_pixels(preview.ravel(), preview.shape[1], preview.shape[0], folder / 'preview.png', True))
    smart_masks().append(definition)
    save_settings()
    return definition['name']


def remove_mask(index):
    name = smart_masks().pop(index)['name']
    save_settings()
    return name


def apply_mask(obj, data, layer, definition):
    apply_generator(layer, definition['generator'])
    for index in reversed(range(len(layer.effects))):
        if layer.effects[index].target == 'MASK':
            layer.effects.remove(index)
    layer.mask = owned_image(data, definition['mask'], f'DP {obj.name} {layer.uid} mask', False, (1.0, 1.0, 1.0, 1.0)) if definition['mask'] else None
    add_effects(obj, data, layer, definition['effects'])


def subtree(layers, root):
    found = []

    def walk(uid):
        for layer in children(layers, uid):
            found.append(layer)
            walk(layer.uid)
    walk(root.uid)
    return found


def layer_entry(layer, folder, parent):
    if layer.kind == 'FILL':
        result = capture(layer)
    else:
        result = dict(name=layer.name, projection=layer.projection, tiling=layer.tiling, slots={})
        if layer.generator != 'NONE':
            result['generator'] = {field: getattr(layer, field) for field in GENERATOR_FIELDS}
    result.update(kind=layer.kind, parent=parent, opacity=layer.opacity, visible=layer.visible, mask='', paint='')
    if layer.kind == 'PAINT':
        result['paint'] = write_png(layer.image, folder / f'{layer.uid}.png', False)
        for slot in layer.slots:
            if slot.enabled:
                values = dict(source='VALUE', value=list(slot.color) if CHANNEL[slot.name].width == 3 else slot.value, blend=slot.blend, opacity=slot.opacity)
                if slot.source == 'IMAGE' and slot.image is not None:
                    values.update(source='IMAGE', image=write_png(slot.image, folder / f'{layer.uid}_{slot.name}.png', True))
                result['slots'][slot.name] = values
    if layer.mask is not None:
        result['mask'] = write_png(layer.mask, folder / f'{layer.uid}_mask.png', False)
    result['effects'] = [effect_entry(effect, folder) for effect in layer.effects if portable(effect)]
    return result


def save_smart(layer):
    slug = re.sub(r'[^A-Za-z0-9]+', '_', layer.name).strip('_') or 'smart'
    folder = library_root() / 'smart' / f'{slug}_{int(time.time() * 1000)}'
    folder.mkdir(parents=True)
    layers = [layer] if layer.kind != 'FOLDER' else subtree(texture_set(layer.id_data).layers, layer)
    entries, index = [], {}
    for item in layers:
        parent = index.get(item.parent, -1)
        index[item.uid] = len(entries)
        entries.append(layer_entry(item, folder, parent))
    definition = dict(name=layer.name, layers=entries)
    if layer.kind == 'FOLDER':
        definition['root'] = dict(opacity=layer.opacity, mask=write_png(layer.mask, folder / 'root_mask.png', False) if layer.mask else '',
                                  generator={field: getattr(layer, field) for field in GENERATOR_FIELDS})
    definition['name'] = unique_name(smart_materials(), definition['name'])
    smart_materials().append(definition)
    save_settings()
    return definition['name']


def remove_smart(index):
    name = smart_materials().pop(index)['name']
    save_settings()
    return name


def owned_image(data, path, name, data_values, fill=(0.0, 0.0, 0.0, 0.0)):
    image = bpy.data.images.load(path)
    image.name = name
    image.alpha_mode = 'STRAIGHT'
    if data_values:
        image.colorspace_settings.name = 'Non-Color'
    if tuple(image.size) != (data.resolution, data.resolution):
        image.scale(data.resolution, data.resolution)
    image.pack()
    return adopt(data, image, fill)


def build(obj, data, definition, root, blank):
    uids = []
    for item in definition['layers']:
        data.serial += 1
        layer = data.layers.add()
        layer.uid, layer.kind, layer.name = f'L{data.serial}', item['kind'], item['name']
        layer.parent = root.uid if item['parent'] < 0 else uids[item['parent']]
        layer.opacity, layer.visible = item['opacity'], item['visible']
        uid = layer.uid
        if layer.kind == 'FOLDER':
            apply_generator(layer, item.get('generator', dict(generator='NONE')))
        else:
            add_slots(layer)
            apply_definition(layer, item)
        if layer.kind == 'PAINT':
            layer.image = owned_image(data, item['paint'], f'DP {obj.name} {uid}', False) if item['paint'] else blank(obj, data, uid, False)
            for slot in layer.slots:
                if slot.source == 'IMAGE' and slot.image is not None:
                    slot.image = owned_image(data, slot.image.filepath, f'DP {obj.name} {uid} {slot.name}', True, (0.5, 0.5, 0.5, 1.0))
        if item['mask']:
            layer.mask = owned_image(data, item['mask'], f'DP {obj.name} {uid} mask', False, (1.0, 1.0, 1.0, 1.0))
        add_effects(obj, data, layer, item.get('effects', ()))
        uids.append(uid)
    settings_root = definition.get('root')
    if settings_root:
        root.opacity = settings_root['opacity']
        apply_generator(root, settings_root['generator'])
        if settings_root['mask']:
            root.mask = owned_image(data, settings_root['mask'], f'DP {obj.name} {root.uid} mask', False, (1.0, 1.0, 1.0, 1.0))
