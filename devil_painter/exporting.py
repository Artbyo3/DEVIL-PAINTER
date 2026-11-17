import copy
import re
from pathlib import Path
import bpy
import numpy
from . import baking, tiles
from .blending import CHANNEL, linear_to_srgb
from .document import set_channels
from .library import save_settings, settings

FORMATS = {'PNG': ('png', ('8', '16')), 'TARGA': ('tga', ('8',)), 'TIFF': ('tif', ('8', '16')), 'OPEN_EXR': ('exr', ('16', '32'))}
FORMAT_LABELS = {'PNG': 'PNG', 'TARGA': 'TGA', 'TIFF': 'TIFF', 'OPEN_EXR': 'EXR'}
DEPTHS = ('TEMPLATE', '8', '16', '32')
SOURCES = {'base_color.r': ('Base R', 'base_color', 0), 'base_color.g': ('Base G', 'base_color', 1), 'base_color.b': ('Base B', 'base_color', 2),
           'roughness': ('Roughness', 'roughness', 0), 'smoothness': ('Smoothness', 'roughness', 0), 'metallic': ('Metallic', 'metallic', 0),
           'normal.r': ('Normal X', 'normal', 0), 'normal.g': ('Normal Y', 'normal', 1), 'normal.g_dx': ('Normal Y DirectX', 'normal', 1),
           'normal.b': ('Normal Z', 'normal', 2), 'height': ('Height', 'height', 0), 'emission.r': ('Emit R', 'emission', 0),
           'emission.g': ('Emit G', 'emission', 1), 'emission.b': ('Emit B', 'emission', 2), 'opacity': ('Opacity', 'opacity', 0),
           'ao': ('Ambient occlusion', None, 0), 'white': ('White', None, 0), 'black': ('Black', None, 0)}
INVERTED = {'smoothness', 'normal.g_dx'}
TOKENS = ('{mesh}', '{set}', '{output}', '{udim}', '{material}', '{resolution}')
BASE = ['base_color.r', 'base_color.g', 'base_color.b']
NORMAL_GL = ['normal.r', 'normal.g', 'normal.b']
NORMAL_DX = ['normal.r', 'normal.g_dx', 'normal.b']
EMISSION = ['emission.r', 'emission.g', 'emission.b']


def output(name, sources, file_format='PNG', depth='8', srgb=False):
    return dict(name=name, sources=list(sources), format=file_format, depth=depth, srgb=srgb)


BUILTIN_TEMPLATES = (
    dict(name='Standard PBR', outputs=[output('BaseColor', BASE, srgb=True), output('Roughness', ['roughness']), output('Metallic', ['metallic']),
                                       output('Normal', NORMAL_GL, depth='16'), output('Height', ['height'], depth='16'),
                                       output('Emission', EMISSION, srgb=True), output('Opacity', ['opacity']), output('AO', ['ao'])]),
    dict(name='glTF', outputs=[output('BaseColor', BASE + ['opacity'], srgb=True), output('OcclusionRoughnessMetallic', ['ao', 'roughness', 'metallic']),
                               output('Normal', NORMAL_GL), output('Emissive', EMISSION, srgb=True)]),
    dict(name='Unreal Engine', outputs=[output('BaseColor', BASE, srgb=True), output('OcclusionRoughnessMetallic', ['ao', 'roughness', 'metallic']),
                                        output('Normal', NORMAL_DX), output('Emissive', EMISSION, srgb=True)]),
    dict(name='Unity HDRP', outputs=[output('BaseMap', BASE + ['opacity'], srgb=True), output('MaskMap', ['metallic', 'ao', 'black', 'smoothness']),
                                     output('Normal', NORMAL_GL), output('Emission', EMISSION, srgb=True)]),
    dict(name='Unity URP', outputs=[output('BaseMap', BASE + ['opacity'], srgb=True), output('MetallicSmoothness', ['metallic', 'black', 'black', 'smoothness']),
                                    output('Normal', NORMAL_GL), output('Occlusion', ['ao']), output('Emission', EMISSION, srgb=True)]),
    dict(name='Linear EXR', outputs=[output('BaseColor', BASE, 'OPEN_EXR', '32'), output('Roughness', ['roughness'], 'OPEN_EXR', '32'),
                                     output('Metallic', ['metallic'], 'OPEN_EXR', '32'), output('Normal', NORMAL_GL, 'OPEN_EXR', '32'),
                                     output('Height', ['height'], 'OPEN_EXR', '32'), output('Emission', EMISSION, 'OPEN_EXR', '32')]),
)


def custom_templates():
    return settings().setdefault('export_templates', [])


def all_templates():
    return list(BUILTIN_TEMPLATES) + custom_templates()


def find_template(name):
    return next((template for template in all_templates() if template['name'] == name), BUILTIN_TEMPLATES[0])


def is_custom(name):
    return any(template['name'] == name for template in custom_templates())


def duplicate_template(name):
    template = copy.deepcopy(find_template(name))
    names = {item['name'] for item in all_templates()}
    base, number = template['name'] + ' copy', 1
    template['name'] = base
    while template['name'] in names:
        number += 1
        template['name'] = f'{base} {number}'
    custom_templates().append(template)
    save_settings()
    return template['name']


def delete_template(name):
    custom_templates()[:] = [template for template in custom_templates() if template['name'] != name]
    save_settings()


def edit_output(template_name, index, **changes):
    template = find_template(template_name)
    template['outputs'][index].update(changes)
    save_settings()


def set_source(template_name, index, slot, key):
    item = find_template(template_name)['outputs'][index]
    sources = list(item['sources'])
    if key == 'none':
        sources = sources[:3] if slot == 3 else sources[:1]
    else:
        if len(sources) == 1 and slot in (1, 2):
            sources = sources * 3
        while len(sources) <= slot:
            sources.append('black')
        sources[slot] = key
    item['sources'] = sources
    save_settings()


def set_format(template_name, index, file_format):
    item = find_template(template_name)['outputs'][index]
    item['format'] = file_format
    item['depth'] = effective_depth(file_format, item['depth'], 'TEMPLATE')
    save_settings()


def add_output(template_name):
    find_template(template_name)['outputs'].append(output('Output', ['roughness']))
    save_settings()


def remove_output(template_name, index):
    find_template(template_name)['outputs'].pop(index)
    save_settings()


def effective_depth(file_format, depth, override):
    allowed = FORMATS[file_format][1]
    wanted = depth if override == 'TEMPLATE' else override
    if wanted in allowed:
        return wanted
    return allowed[-1] if int(wanted) > int(allowed[-1]) else allowed[0]


def file_name(pattern, tokens, multi_tile):
    if multi_tile and '{udim}' not in pattern:
        pattern += '.{udim}'
    name = pattern
    for key, value in tokens.items():
        name = name.replace('{' + key + '}', str(value))
    return re.sub(r'[\\/:*?"<>|]+', '_', name).strip() or 'texture'


def source_available(data, key, ao):
    channel = SOURCES[key][1]
    if key == 'ao':
        return ao is not None
    return channel is None or channel in {item.key for item in set_channels(data)}


def needed_channels(template):
    return {SOURCES[key][1] for item in template['outputs'] for key in item['sources'] if SOURCES[key][1]}


def ao_pixels(data, number, size):
    item = data.maps.get('ao')
    if item is None or item.image is None:
        return None
    pixels = baking.read_pixels(tiles.variant(data, item.image, number))
    if pixels.shape[0] != size:
        return None
    return pixels[..., 0]


def plane(key, baked, ao, size, srgb, linear_file):
    _, channel, component = SOURCES[key]
    if key == 'white':
        return numpy.ones((size, size), dtype=numpy.float32)
    if key == 'black':
        return numpy.zeros((size, size), dtype=numpy.float32)
    if key == 'ao':
        return ao if ao is not None else numpy.ones((size, size), dtype=numpy.float32)
    values = baked[channel][..., component]
    if srgb and CHANNEL[channel].srgb and not linear_file:
        values = linear_to_srgb(values)
    values = numpy.clip(values, 0, 1)
    return 1 - values if key in INVERTED else values


def write(path, planes, file_format, depth):
    size = planes[0].shape[0]
    pixels = numpy.ones((size, size, 4), dtype=numpy.float32)
    if len(planes) == 1:
        pixels[..., :3] = planes[0][..., None]
        mode = 'BW'
    else:
        for index, values in enumerate(planes):
            pixels[..., index] = values
        mode = 'RGBA' if len(planes) == 4 else 'RGB'
    if mode == 'RGBA' and file_format != 'OPEN_EXR':
        pixels[..., :3] *= pixels[..., 3:]
    scene = bpy.data.scenes.new('DP Export')
    image = bpy.data.images.new(path.stem, size, size, alpha=True, float_buffer=True)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.pixels.foreach_set(pixels.ravel())
        image_settings = scene.render.image_settings
        image_settings.file_format = file_format
        image_settings.color_mode = mode if file_format != 'OPEN_EXR' or mode != 'BW' else 'RGB'
        if len(FORMATS[file_format][1]) > 1:
            image_settings.color_depth = depth
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save_render(str(path), scene=scene)
    finally:
        bpy.data.images.remove(image)
        bpy.data.scenes.remove(scene)


def export(context, obj, project, template, wanted, directory, pattern, override):
    channels = needed_channels(template)
    baked = {}
    for key in channels:
        for (index, number), values in baking.bake_channel(context, obj, project, wanted, CHANNEL[key]).items():
            baked.setdefault((index, number), {})[key] = values
    written = []
    folder = Path(directory)
    for index in wanted:
        data = project.sets[index]
        set_tiles = tiles.numbers(data)
        for number in set_tiles:
            size = data.resolution
            ao = ao_pixels(data, number, size)
            for item in template['outputs']:
                varying = [key for key in item['sources'] if key not in {'white', 'black'}]
                if varying and not any(source_available(data, key, ao) for key in varying):
                    continue
                file_format = item['format']
                depth = effective_depth(file_format, item['depth'], override)
                linear_file = file_format == 'OPEN_EXR'
                planes = [plane(key, baked.get((index, number), {}), ao, size, item['srgb'], linear_file) for key in item['sources']]
                tokens = dict(mesh=bpy.path.clean_name(obj.name), set=bpy.path.clean_name(data.name), output=item['name'], udim=number,
                              material=bpy.path.clean_name(data.material.name), resolution=size)
                path = folder / (file_name(pattern, tokens, len(set_tiles) > 1) + '.' + FORMATS[file_format][0])
                write(path, planes, file_format, depth)
                written.append(path)
    return written
