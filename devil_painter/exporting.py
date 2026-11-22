import copy
import re
import struct
from dataclasses import dataclass
from pathlib import Path
import bpy
import numpy
from . import baking, compositing, tiles
from .blending import CHANNEL, USER_CHANNELS, linear_to_srgb
from .compositing import DIELECTRIC_F0
from .document import channel_depth, set_channels, shown_layers
from .filters import NORMAL_DEPTH
from .library import save_settings, settings
from .meshmaps import MESH_MAP, MESH_MAPS

FORMATS = {'PNG': ('png', ('8', '16')), 'TARGA': ('tga', ('8',)), 'TIFF': ('tif', ('8', '16')), 'OPEN_EXR': ('exr', ('16', '32'))}
FORMAT_LABELS = {'PNG': 'PNG', 'TARGA': 'TGA', 'TIFF': 'TIFF', 'OPEN_EXR': 'EXR'}
DEPTHS = ('TEMPLATE', '8', '16', '32')
SIZES = (0, 512, 1024, 2048, 4096)
PADDINGS = (0, 4, 16, 64, -1)
PADDING_STYLES = {'DILATION': 'Dilation', 'TRANSPARENT': 'Transparent', 'DIFFUSION': 'Diffusion'}
WHITE = (1.0, 1.0, 1.0, 1.0)
INFINITE_PADDING = -1
SOURCES = {'base_color.r': ('Base R', 'base_color', 0), 'base_color.g': ('Base G', 'base_color', 1), 'base_color.b': ('Base B', 'base_color', 2),
           'roughness': ('Roughness', 'roughness', 0), 'smoothness': ('Smoothness', 'roughness', 0), 'metallic': ('Metallic', 'metallic', 0),
           'normal.r': ('Normal X', 'normal', 0), 'normal.g': ('Normal Y', 'normal', 1), 'normal.g_dx': ('Normal Y DirectX', 'normal', 1),
           'normal.b': ('Normal Z', 'normal', 2), 'height': ('Height', 'height', 0), 'emission.r': ('Emit R', 'emission', 0),
           'emission.g': ('Emit G', 'emission', 1), 'emission.b': ('Emit B', 'emission', 2), 'opacity': ('Opacity', 'opacity', 0),
           'ao': ('Ambient occlusion', 'ambient_occlusion', 0), 'flow.r': ('Flow X', 'flow', 0), 'flow.g': ('Flow Y', 'flow', 1),
           'diffuse.r': ('Diffuse R', 'diffuse', 0), 'diffuse.g': ('Diffuse G', 'diffuse', 1), 'diffuse.b': ('Diffuse B', 'diffuse', 2),
           'specular.r': ('Specular R', 'specular', 0), 'specular.g': ('Specular G', 'specular', 1), 'specular.b': ('Specular B', 'specular', 2),
           'glossiness': ('Glossiness', 'glossiness', 0), 'displacement': ('Displacement', 'displacement', 0),
           'anisotropy_level': ('Anisotropy level', 'anisotropy_level', 0), 'anisotropy_angle': ('Anisotropy angle', 'anisotropy_angle', 0),
           'transmission': ('Transmission', 'transmission', 0), 'scattering': ('Scattering', 'scattering', 0), 'sheen': ('Sheen', 'sheen', 0),
           'coat': ('Coat', 'coat', 0), 'ior': ('IOR', 'ior', 0),
           **{f'user{number}': (f'User {number}', f'user{number}', 0) for number in range(1, USER_CHANNELS + 1)}, 'white': ('White', None, 0), 'black': ('Black', None, 0)}
GRAY_MESH_MAPS = frozenset({'ao', 'curvature', 'thickness', 'height', 'uv_border'})
SHORT_MESH_LABELS = {'ao': 'AO', 'world_normal': 'World N', 'uv_border': 'UV border'}


def mesh_source_entries(item):
    label = 'Mesh ' + SHORT_MESH_LABELS.get(item.key, item.label)
    if item.key in GRAY_MESH_MAPS:
        return [(f'map:{item.key}', label, item.key, 0)]
    return [(f'map:{item.key}.{letter}', f'{label} {letter.upper()}', item.key, component) for component, letter in enumerate('rgb')]


MESH_SOURCES = tuple(entry for item in MESH_MAPS for entry in mesh_source_entries(item))
MAP_SOURCES = {key: (map_key, component) for key, _, map_key, component in MESH_SOURCES}
SOURCES.update({key: (label, None, component) for key, label, _, component in MESH_SOURCES})


def diffuse_from_metal(base, metallic):
    return base * (1 - metallic)


def specular_from_metal(base, metallic):
    return DIELECTRIC_F0 * (1 - metallic) + base * metallic


def glossiness_from_roughness(roughness):
    return 1 - roughness


CONVERSIONS = {'diffuse': (('base_color', 'metallic'), diffuse_from_metal), 'specular': (('base_color', 'metallic'), specular_from_metal),
               'glossiness': (('roughness',), glossiness_from_roughness)}


def converted_entries(target):
    label = 'Converted ' + CHANNEL[target].label
    if CHANNEL[target].width == 1:
        return [(f'converted_{target}', label, target, 0)]
    return [(f'converted_{target}.{letter}', f'{label} {letter.upper()}', target, component) for component, letter in enumerate('rgb')]


CONVERTED_SOURCES = tuple(entry for target in CONVERSIONS for entry in converted_entries(target))
CONVERTED = {key: (target, component) for key, _, target, component in CONVERTED_SOURCES}
SOURCES.update({key: (label, None, component) for key, label, _, component in CONVERTED_SOURCES})
INVERTED = {'smoothness', 'normal.g_dx'}
PSD_BLENDS = {'MIX': b'norm', 'MULTIPLY': b'mul ', 'DIVIDE': b'fdiv', 'DARKEN': b'dark', 'LIGHTEN': b'lite', 'ADD': b'lddg', 'SUBTRACT': b'fsub',
              'DIFFERENCE': b'diff', 'EXCLUSION': b'smud', 'OVERLAY': b'over', 'SCREEN': b'scrn', 'LINEAR_BURN': b'lbrn', 'BURN': b'idiv',
              'DODGE': b'div ', 'SOFT_LIGHT': b'sLit', 'HARD_LIGHT': b'hLit', 'VIVID_LIGHT': b'vLit', 'LINEAR_LIGHT': b'lLit', 'PIN_LIGHT': b'pLit',
              'HUE': b'hue ', 'SATURATION': b'sat ', 'COLOR': b'colr', 'VALUE': b'lum '}
PSD_NORMAL = b'norm'
PSD_HIDDEN = 2
TOKENS = ('{mesh}', '{set}', '{output}', '{udim}', '{material}', '{resolution}')
BASE = ['base_color.r', 'base_color.g', 'base_color.b']
NORMAL_GL = ['normal.r', 'normal.g', 'normal.b']
NORMAL_DX = ['normal.r', 'normal.g_dx', 'normal.b']
EMISSION = ['emission.r', 'emission.g', 'emission.b']
DIFFUSE = ['diffuse.r', 'diffuse.g', 'diffuse.b']
SPECULAR = ['specular.r', 'specular.g', 'specular.b']
CONVERTED_DIFFUSE = ['converted_diffuse.r', 'converted_diffuse.g', 'converted_diffuse.b']
CONVERTED_SPECULAR = ['converted_specular.r', 'converted_specular.g', 'converted_specular.b']


def output(name, sources, file_format='PNG', depth='8', srgb=False):
    return dict(name=name, sources=list(sources), format=file_format, depth=depth, srgb=srgb)


BUILTIN_TEMPLATES = (
    dict(name='Standard PBR', outputs=[output('BaseColor', BASE, srgb=True), output('Roughness', ['roughness']), output('Metallic', ['metallic']),
                                       output('Normal', NORMAL_GL, depth='16'), output('Height', ['height'], depth='16'),
                                       output('Emission', EMISSION, srgb=True), output('Opacity', ['opacity']), output('AO', ['ao']),
                                       output('Diffuse', DIFFUSE, srgb=True), output('Specular', SPECULAR, srgb=True), output('Glossiness', ['glossiness']),
                                       output('Displacement', ['displacement'], depth='16'), output('AnisotropyLevel', ['anisotropy_level']),
                                       output('AnisotropyAngle', ['anisotropy_angle']), output('Transmission', ['transmission']),
                                       output('Scattering', ['scattering']), output('Sheen', ['sheen']), output('Coat', ['coat']), output('IOR', ['ior'])]),
    dict(name='glTF', outputs=[output('BaseColor', BASE + ['opacity'], srgb=True), output('OcclusionRoughnessMetallic', ['ao', 'roughness', 'metallic']),
                               output('Normal', NORMAL_GL), output('Emissive', EMISSION, srgb=True)]),
    dict(name='Unreal Engine', outputs=[output('BaseColor', BASE, srgb=True), output('OcclusionRoughnessMetallic', ['ao', 'roughness', 'metallic']),
                                        output('Normal', NORMAL_DX), output('Emissive', EMISSION, srgb=True)]),
    dict(name='Unity HDRP', outputs=[output('BaseMap', BASE + ['opacity'], srgb=True), output('MaskMap', ['metallic', 'ao', 'black', 'smoothness']),
                                     output('Normal', NORMAL_GL), output('Emission', EMISSION, srgb=True)]),
    dict(name='Unity URP', outputs=[output('BaseMap', BASE + ['opacity'], srgb=True), output('MetallicSmoothness', ['metallic', 'black', 'black', 'smoothness']),
                                    output('Normal', NORMAL_GL), output('Occlusion', ['ao']), output('Emission', EMISSION, srgb=True)]),
    dict(name='USD Preview Surface', outputs=[output('diffuseColor', BASE, srgb=True), output('roughness', ['roughness']), output('metallic', ['metallic']),
                                              output('normal', NORMAL_GL), output('occlusion', ['ao']), output('emissiveColor', EMISSION, srgb=True),
                                              output('opacity', ['opacity'])]),
    dict(name='Linear EXR', outputs=[output('BaseColor', BASE, 'OPEN_EXR', '32'), output('Roughness', ['roughness'], 'OPEN_EXR', '32'),
                                     output('Metallic', ['metallic'], 'OPEN_EXR', '32'), output('Normal', NORMAL_GL, 'OPEN_EXR', '32'),
                                     output('Height', ['height'], 'OPEN_EXR', '32'), output('Emission', EMISSION, 'OPEN_EXR', '32')]),
    dict(name='Spec-Gloss from Metal-Rough', outputs=[output('Diffuse', CONVERTED_DIFFUSE, srgb=True), output('Specular', CONVERTED_SPECULAR, srgb=True),
                                                      output('Glossiness', ['converted_glossiness'])]),
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


def source_channels(key):
    if key in CONVERTED:
        return CONVERSIONS[CONVERTED[key][0]][0]
    channel = SOURCES[key][1]
    return (channel,) if channel else ()


def deepest(data, item, present):
    depths = [int(channel_depth(data, channel)) for key in item['sources'] for channel in source_channels(key) if channel in present]
    return str(max([int(item['depth']), *depths]))


def file_name(pattern, tokens, multi_tile):
    if multi_tile and '{udim}' not in pattern:
        pattern += '.{udim}'
    name = pattern
    for key, value in tokens.items():
        name = name.replace('{' + key + '}', str(value))
    return re.sub(r'[\\/:*?"<>|]+', '_', name).strip() or 'texture'


def source_available(data, key, ao):
    present = {item.key for item in set_channels(data)}
    if key == 'ao':
        return ao is not None or 'ambient_occlusion' in present
    channels = source_channels(key)
    return not channels or any(channel in present for channel in channels)


def needed_channels(template):
    return {channel for item in template['outputs'] for key in item['sources'] for channel in source_channels(key)}


def map_image(data, key, number):
    item = data.maps.get(key)
    if item is None or item.image is None:
        return None
    return tiles.variant(data, item.image, number)


def ao_image(data, number):
    return map_image(data, 'ao', number)


def ao_pixels(data, number, size):
    image = ao_image(data, number)
    return None if image is None else baking.resized(baking.read_pixels(image)[..., 0], (size, size))


def unbaked_maps(data, number, item):
    keys = dict.fromkeys(MAP_SOURCES[key][0] for key in item['sources'] if key in MAP_SOURCES)
    return [MESH_MAP[key].label for key in keys if map_image(data, key, number) is None]


def mesh_pixels(data, number, item, cache, size):
    for key in item['sources']:
        if key in MAP_SOURCES and MAP_SOURCES[key][0] not in cache:
            map_key = MAP_SOURCES[key][0]
            cache[map_key] = baking.resized(baking.read_pixels(map_image(data, map_key, number)), (size, size))
    return cache


def channel_plane(channel, component, baked, size, present):
    if channel not in present:
        return numpy.full((size, size), CHANNEL[channel].default[component], dtype=numpy.float32)
    return numpy.clip(baked[channel][..., component], 0, 1)


def converted_plane(key, baked, size, encode, present):
    target, component = CONVERTED[key]
    channels, formula = CONVERSIONS[target]
    values = formula(*(channel_plane(channel, component if CHANNEL[channel].width == 3 else 0, baked, size, present) for channel in channels))
    return numpy.clip(linear_to_srgb(values) if encode and CHANNEL[target].srgb else values, 0, 1)


def plane(key, baked, ao, size, srgb, linear_file, present, normal_format, meshes):
    _, channel, component = SOURCES[key]
    if key in CONVERTED:
        return converted_plane(key, baked, size, srgb and not linear_file, present)
    if key in MAP_SOURCES:
        map_key, component = MAP_SOURCES[key]
        return meshes[map_key][..., component]
    if key == 'white':
        return numpy.ones((size, size), dtype=numpy.float32)
    if key == 'black':
        return numpy.zeros((size, size), dtype=numpy.float32)
    if key == 'ao' and channel not in present:
        return ao if ao is not None else numpy.ones((size, size), dtype=numpy.float32)
    if channel not in present:
        return numpy.full((size, size), CHANNEL[channel].default[component], dtype=numpy.float32)
    values = baked[channel][..., component]
    if srgb and CHANNEL[channel].srgb and not linear_file:
        values = linear_to_srgb(values)
    values = numpy.clip(values, 0, 1)
    inverted = (key in INVERTED) != (channel == 'normal' and component == 1 and normal_format == 'DIRECTX')
    return 1 - values if inverted else values


def unit(vectors):
    length = numpy.sqrt((vectors * vectors).sum(axis=-1, keepdims=True))
    return vectors / numpy.maximum(length, 1e-12)


def fold_height(normal, height, strength, normal_format):
    across = numpy.roll(height, -1, 1) - numpy.roll(height, 1, 1)
    up = numpy.roll(height, -1, 0) - numpy.roll(height, 1, 0)
    if strength == 0 or not (across.any() or up.any()):
        return normal
    gain = -strength * NORMAL_DEPTH * height.shape[0] / 2
    detail = unit(numpy.stack([across * gain, up * gain, numpy.ones_like(height)], axis=-1))
    flip = numpy.array([1.0, -1.0 if normal_format == 'DIRECTX' else 1.0, 1.0], dtype=numpy.float32)
    painted = (normal * 2 - 1) * flip
    combined = unit(numpy.stack([painted[..., 0] + detail[..., 0], painted[..., 1] + detail[..., 1], painted[..., 2] * detail[..., 2]], axis=-1))
    return (combined * flip * .5 + .5).astype(numpy.float32)


def write(path, planes, file_format, depth, target):
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
    view = scene.view_settings
    view.view_transform, view.look, view.exposure, view.gamma = 'Standard', 'None', 0.0, 1.0
    image = bpy.data.images.new(path.stem, size, size, alpha=True, float_buffer=True)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.pixels.foreach_set(pixels.ravel())
        if target and target != size:
            image.scale(target, target)
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


def planned_files(obj, project, template, wanted, folder, pattern, size):
    planned = []
    for index in wanted:
        data = project.sets[index]
        set_tiles = tiles.numbers(data)
        for number in set_tiles:
            ao = ao_image(data, number)
            for item in template['outputs']:
                varying = [key for key in item['sources'] if key not in {'white', 'black'} and key not in MAP_SOURCES]
                if varying and not any(source_available(data, key, ao) for key in varying):
                    continue
                if unbaked_maps(data, number, item):
                    continue
                tokens = dict(mesh=bpy.path.clean_name(obj.name), set=bpy.path.clean_name(data.name), output=item['name'], udim=number,
                              material=bpy.path.clean_name(data.material.name), resolution=size or data.resolution)
                path = folder / (file_name(pattern, tokens, len(set_tiles) > 1) + '.' + FORMATS[item['format']][0])
                planned.append((path, index, number, item))
    return planned


def skipped_outputs(project, template, wanted):
    skipped = []
    for index in wanted:
        data = project.sets[index]
        for item in template['outputs']:
            labels = [label.lower() for label in dict.fromkeys(label for number in tiles.numbers(data) for label in unbaked_maps(data, number, item))]
            if labels:
                names = labels[0] if len(labels) == 1 else ', '.join(labels[:-1]) + ' and ' + labels[-1]
                skipped.append(f'{item["name"]} for {data.name} needs the {names} {"map" if len(labels) == 1 else "maps"} baked')
    return skipped


def refuse_collisions(planned, project):
    owners = {}
    for path, index, _, _ in planned:
        key = str(path).casefold()
        if key not in owners:
            owners[key] = index
        elif owners[key] != index:
            raise ValueError(f'{project.sets[owners[key]].name} and {project.sets[index].name} would both export {path.name}. Add {{set}} to the file name pattern.')
        else:
            raise ValueError(f'Two outputs would both export {path.name}. Give every output its own name, or add {{output}} to the file name pattern.')


def with_alpha(planes, coverage):
    if len(planes) == 4:
        return [*planes[:3], planes[3] * coverage]
    return [*(planes * 3 if len(planes) == 1 else planes), coverage]


def island_coverage(context, obj, project, wanted):
    def prepare(data):
        baking.emission_tree(data.material.node_tree, WHITE)
    return {key: (pixels[..., 3] >= .5).astype(numpy.float32) for key, pixels in baking.bake_pass(context, obj, project, wanted, prepare, margin=0).items()}


def export(context, obj, project, template, wanted, directory, pattern, override, size=0, padding=baking.BAKE_MARGIN, style='DILATION'):
    planned = planned_files(obj, project, template, wanted, Path(directory), pattern, size)
    refuse_collisions(planned, project)
    present_anywhere = {item.key for index in wanted for item in set_channels(project.sets[index])}
    needed = needed_channels(template)
    channels = (needed | ({'height'} if 'normal' in needed else set())) & present_anywhere
    baked = {}
    for key in channels:
        margin = max(project.sets[index].resolution for index in wanted) if padding == INFINITE_PADDING else padding
        for (index, number), values in baking.bake_channel(context, obj, project, wanted, CHANNEL[key], margin, style).items():
            baked.setdefault((index, number), {})[key] = values
    for (index, number), maps in baked.items():
        if 'normal' in maps and 'height' in maps:
            maps['normal'] = fold_height(maps['normal'], maps['height'][..., 0], project.sets[index].bump_strength, project.normal_format)
    coverage = island_coverage(context, obj, project, wanted) if style == 'TRANSPARENT' else {}
    ao = {}
    meshes = {}
    for path, index, number, item in planned:
        data = project.sets[index]
        if (index, number) not in ao:
            ao = {(index, number): ao_pixels(data, number, data.resolution)}
            meshes = {}
        file_format = item['format']
        present = {channel.key for channel in set_channels(data)}
        mesh = mesh_pixels(data, number, item, meshes, data.resolution)
        planes = [plane(key, baked.get((index, number), {}), ao[(index, number)], data.resolution, item['srgb'], file_format == 'OPEN_EXR', present, project.normal_format, mesh)
                  for key in item['sources']]
        if coverage:
            planes = with_alpha(planes, coverage[(index, number)])
        write(path, planes, file_format, effective_depth(file_format, deepest(data, item, present), override), size)
    return [path for path, *_ in planned]


class FlatSlot:
    def __init__(self, slot):
        self.slot = slot

    def __getattr__(self, name):
        return getattr(self.slot, name)

    @property
    def blend(self):
        return 'MIX' if compositing.blended(self.slot) else self.slot.blend

    @property
    def opacity(self):
        return 1.0


class FlatSlots:
    def __init__(self, slots):
        self.items = [FlatSlot(slot) for slot in slots]

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, key):
        return next(item for item in self.items if item.name == key)


class Contribution(compositing.Rooted):
    @property
    def opacity(self):
        return 1.0

    @property
    def slots(self):
        return FlatSlots(self.layer.slots)


@dataclass(frozen=True)
class PsdLayer:
    name: str
    pixels: numpy.ndarray
    opacity: int
    blend: bytes
    hidden: bool


def contribution_tree(data, layer, key, background):
    tree = data.material.node_tree
    build = compositing.set_build(data, tree, raw=True)
    tree.nodes.clear()
    build.sampler.cache.clear()
    build.layer_map = {item.uid: item for item in compositing.resolved(data.layers)}
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    emission = tree.nodes.new('ShaderNodeEmission')
    tree.links.new(emission.outputs[0], output.inputs['Surface'])
    channels = set_channels(data)
    start = {}
    for channel in channels:
        node = tree.nodes.new('ShaderNodeRGB')
        node.outputs[0].default_value = (background, background, background, 1.0)
        start[channel.key] = node.outputs[0]
    results = compositing.compose(build, channels, [layer], '', start, [0])
    compositing.write_values(tree.nodes, channels, [layer])
    tree.links.new(results[key], emission.inputs['Color'])


def encoded(values, channel):
    return linear_to_srgb(values) if channel.srgb else numpy.clip(values, 0, 1)


def unmixed(dark, light, channel):
    factor = numpy.clip(1 - (light[..., :3] - dark[..., :3]).mean(axis=-1), 0, 1)
    factor[(dark[..., 3] < .5) | (light[..., 3] < .5)] = 0
    color = dark[..., :3] / numpy.maximum(factor, 1e-6)[..., None]
    return numpy.dstack([encoded(color, channel), factor])


def contribution(context, obj, project, index, layer, channel, margin):
    passes = []
    for background in (0.0, 1.0):
        def prepare(data, background=background):
            contribution_tree(data, Contribution(layer), channel.key, background)
        passes.append(baking.bake_pass(context, obj, project, [index], prepare, margin=margin))
    return {number: unmixed(dark, passes[1][(index, number)], channel) for (_, number), dark in passes[0].items()}


def psd_stack(data, key):
    layers = compositing.resolved(data.layers)
    shown = {layer.uid for layer in shown_layers(layers)}
    return [(layer, layer.uid not in shown) for layer in layers if layer.kind != 'FOLDER' and compositing.blended(layer.slots[key])]


def bytes8(values):
    return numpy.round(numpy.clip(values, 0, 1) * 255).astype(numpy.uint8)[::-1]


def pascal_name(name):
    raw = name.encode('mac_roman', 'replace')[:255]
    record = bytes([len(raw)]) + raw
    return record + bytes(-len(record) % 4)


def unicode_name(name):
    text = name.encode('utf-16-be')
    body = struct.pack('>I', len(text) // 2) + text
    body += bytes(-len(body) % 4)
    return b'8BIMluni' + struct.pack('>I', len(body)) + body


def layer_record(layer):
    height, width = layer.pixels.shape[:2]
    channels = b''.join(struct.pack('>hI', ident, height * width + 2) for ident in (-1, 0, 1, 2))
    extra = struct.pack('>II', 0, 0) + pascal_name(layer.name) + unicode_name(layer.name)
    flags = PSD_HIDDEN if layer.hidden else 0
    return (struct.pack('>iiiiH', 0, 0, height, width, 4) + channels + b'8BIM' + layer.blend + struct.pack('>BBBB', layer.opacity, 0, flags, 0)
            + struct.pack('>I', len(extra)) + extra)


def layer_pixels(layer):
    return b''.join(bytes(2) + numpy.ascontiguousarray(layer.pixels[..., index]).tobytes() for index in (3, 0, 1, 2))


def write_psd(path, layers, composite):
    height, width = composite.shape[:2]
    info = struct.pack('>h', len(layers)) + b''.join(layer_record(layer) for layer in layers) + b''.join(layer_pixels(layer) for layer in layers)
    info += bytes(-len(info) % 4)
    masks = struct.pack('>I', len(info)) + info + struct.pack('>I', 0)
    header = b'8BPS' + struct.pack('>H6xHIIHH', 1, 3, height, width, 8, 3)
    image = bytes(2) + b''.join(numpy.ascontiguousarray(composite[..., index]).tobytes() for index in range(3))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + struct.pack('>II', 0, 0) + struct.pack('>I', len(masks)) + masks + image)


def export_psd(context, obj, project, index, key, directory, pattern, padding, style):
    data = project.sets[index]
    channel = CHANNEL[key]
    margin = data.resolution if padding == INFINITE_PADDING else padding
    stack = psd_stack(data, key)
    renders = [contribution(context, obj, project, index, layer, channel, margin if style == 'DILATION' else 0) for layer, _ in stack]
    flat = baking.bake_channel(context, obj, project, [index], channel, margin, style)
    set_tiles = tiles.numbers(data)
    written = []
    for number in set_tiles:
        layers = [PsdLayer(layer.name, bytes8(render[number]), round(255 * layer.opacity * layer.slots[key].opacity),
                           PSD_BLENDS.get(layer.slots[key].blend, PSD_NORMAL), hidden) for (layer, hidden), render in zip(stack, renders)]
        tokens = dict(mesh=bpy.path.clean_name(obj.name), set=bpy.path.clean_name(data.name), output=channel.suffix, udim=number,
                      material=bpy.path.clean_name(data.material.name), resolution=data.resolution)
        path = Path(directory) / (file_name(pattern, tokens, len(set_tiles) > 1) + '.psd')
        write_psd(path, layers, bytes8(encoded(flat[(index, number)], channel)))
        written.append(path)
    return written
