import colorsys
import re
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
import bpy
import numpy
from mathutils import Vector
from .baking import BAKE_SAMPLES, bake_pass, emission_tree, read_pixels, resized
from .caches import touch
from .document import (BAKE_ANTIALIAS, BAKE_AO_DISTANCE, BAKE_AO_SPREAD, BAKE_CURVATURES, BAKE_THICKNESS_RANGE, map_extrusion, map_samples)
from .sets import uv_island_labels
from .signals import map_signal
from .tiles import create, release, variant

FLAT_NORMAL = (0.5, 0.5, 1.0, 1.0)
EDGE_ROUNDING = .02
LOW_SUFFIX = re.compile(r'[ _.\-]*(low|lp|lo)$', re.IGNORECASE)
COPY_SUFFIX = re.compile(r'\.\d+$')
HIGH_WORDS = ('high', 'hp', 'hi')
BORDER_SHARE = 1 / 32
GOLDEN_RATIO = .618033988749895
FULL_REACH = .999
BAKE_PAINT_FILL = {'CAGE': (1.0, 1.0, 1.0, 1.0), 'SKEW': (0.0, 0.0, 0.0, 1.0)}
ISLAND_ATTRIBUTE = 'dp_uv_islands'
RAY_TRACED = {'ao', 'thickness', 'curvature'}
PER_MAP_BAKE = ('ao', 'curvature', 'thickness', 'id', 'normal', 'height')
EXTRUSION_MAPS = {'id', 'normal', 'height'}


@dataclass(frozen=True)
class MeshMap:
    key: str
    label: str
    needs_source: bool = False


MESH_MAPS = (MeshMap('ao', 'Ambient occlusion'), MeshMap('curvature', 'Curvature'), MeshMap('thickness', 'Thickness'),
             MeshMap('position', 'Position'), MeshMap('world_normal', 'World normal'), MeshMap('id', 'ID'),
             MeshMap('normal', 'Normal'), MeshMap('height', 'Height', needs_source=True), MeshMap('uv_border', 'UV border distance'))
MESH_MAP = {item.key: item for item in MESH_MAPS}


@dataclass(frozen=True)
class Sources:
    high: tuple
    cage: object

    def reach(self, distance):
        options = dict(use_selected_to_active=True, cage_extrusion=distance, max_ray_distance=2.0 * distance)
        if self.cage is not None:
            options.update(use_cage=True, cage_object=self.cage.name)
        return options


def object_size(obj):
    return max(max(obj.dimensions), 1e-3)


def base_name(obj):
    return LOW_SUFFIX.sub('', COPY_SUFFIX.sub('', obj.name)).lower()


def name_role(obj, item):
    base = base_name(obj)
    name = COPY_SUFFIX.sub('', item.name).lower()
    if not base or not name.startswith(base):
        return None
    rest = name[len(base):].lstrip(' _.-')
    if rest.startswith('cage'):
        return 'cage'
    return 'high' if rest.startswith(HIGH_WORDS) else None


def matched(context, obj):
    meshes = [item for item in context.view_layer.objects if item.type == 'MESH' and item != obj]
    high = tuple(item for item in meshes if name_role(obj, item) == 'high')
    cage = next((item for item in meshes if name_role(obj, item) == 'cage'), None)
    return Sources(high, cage)


def bake_sources(context, obj, data):
    if data.bake_match:
        return matched(context, obj)
    high = (data.bake_source,) if data.bake_source is not None and data.bake_source != obj else ()
    return Sources(high, data.bake_cage if data.bake_cage != obj else None)


def id_color(name):
    hue = zlib.crc32(name.encode()) * GOLDEN_RATIO % 1.0
    return (*colorsys.hsv_to_rgb(hue, .75, .9), 1.0)


def island_color(order):
    return (*colorsys.hsv_to_rgb(order * GOLDEN_RATIO % 1.0, (.95, .55)[order % 2], (.95, .65)[order // 2 % 2]), 1.0)


def emission_input(tree):
    return next(node for node in tree.nodes if node.type == 'EMISSION').inputs['Color']


@contextmanager
def island_colors(objects):
    made = []
    try:
        for item in objects:
            mesh = item.data
            if not mesh.uv_layers:
                continue
            labels = uv_island_labels(mesh, mesh.uv_layers.active.name)
            palette = {label: island_color(order) for order, label in enumerate(dict.fromkeys(labels.tolist()))}
            totals = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
            mesh.polygons.foreach_get('loop_total', totals)
            colors = numpy.array([palette[label] for label in numpy.repeat(labels, totals).tolist()], dtype=numpy.float32)
            attribute = mesh.color_attributes.new(ISLAND_ATTRIBUTE, 'FLOAT_COLOR', 'CORNER')
            attribute.data.foreach_set('color', colors.ravel())
            made.append(mesh)
        yield
    finally:
        for mesh in made:
            mesh.color_attributes.remove(mesh.color_attributes[ISLAND_ATTRIBUTE])


def id_shader(tree, mode, material_name, object_name):
    emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
    color = emission_input(tree)
    if mode == 'MATERIAL':
        color.default_value = id_color(material_name)
    elif mode == 'OBJECT':
        color.default_value = id_color(object_name)
    elif mode == 'VERTEX':
        tree.links.new(tree.nodes.new('ShaderNodeVertexColor').outputs['Color'], color)
    else:
        islands = tree.nodes.new('ShaderNodeVertexColor')
        islands.layer_name = ISLAND_ATTRIBUTE
        tree.links.new(islands.outputs['Color'], color)


def position_shader(tree, origin, span):
    emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
    geometry = tree.nodes.new('ShaderNodeNewGeometry')
    shifted = tree.nodes.new('ShaderNodeVectorMath')
    shifted.operation = 'SUBTRACT'
    shifted.inputs[1].default_value = origin
    tree.links.new(geometry.outputs['Position'], shifted.inputs[0])
    scaled = tree.nodes.new('ShaderNodeVectorMath')
    scaled.operation = 'SCALE'
    scaled.inputs['Scale'].default_value = 1.0 / span
    tree.links.new(shifted.outputs[0], scaled.inputs[0])
    tree.links.new(scaled.outputs[0], emission_input(tree))


def world_normal_shader(tree):
    emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
    tree.links.new(map_signal(tree.nodes, tree.links, 'world_normal', 1.0), emission_input(tree))


def rounded_shader(tree, radius):
    tree.nodes.clear()
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    diffuse = tree.nodes.new('ShaderNodeBsdfDiffuse')
    bevel = tree.nodes.new('ShaderNodeBevel')
    bevel.inputs['Radius'].default_value = radius
    tree.links.new(bevel.outputs['Normal'], diffuse.inputs['Normal'])
    tree.links.new(diffuse.outputs[0], output.inputs['Surface'])


@contextmanager
def source_shading(sources, shade):
    made, restore, padded = {}, [], []
    try:
        for item in sources:
            if not item.material_slots:
                item.data.materials.append(None)
                padded.append(item.data)
            for slot in item.material_slots:
                key = shade(item, slot.material, None)
                if key not in made:
                    material = bpy.data.materials.new('DP Bake source')
                    shade(item, slot.material, material.node_tree)
                    made[key] = material
                restore.append((slot, slot.material))
                slot.material = made[key]
        yield
    finally:
        for slot, material in reversed(restore):
            slot.material = material
        for mesh in padded:
            mesh.materials.pop()
        for material in made.values():
            bpy.data.materials.remove(material)


def id_source_shade(mode):
    def shade(item, material, tree):
        material_name = material.name if material is not None else ''
        key = {'MATERIAL': material_name, 'OBJECT': item.name}.get(mode, mode)
        if tree is not None:
            id_shader(tree, mode, material_name, item.name)
        return key
    return shade


def bounds(objects):
    corners = numpy.array([tuple(item.matrix_world @ Vector(corner)) for item in objects for corner in item.bound_box])
    origin = corners.min(axis=0)
    return tuple(origin), max(float((corners.max(axis=0) - origin).max()), 1e-6)


def map_key_image(obj, data, key, size):
    item = data.maps.get(key)
    if item is None:
        item = data.maps.add()
        item.name = key
    if item.image is None or tuple(item.image.size) != (size, size):
        if item.image is not None:
            release(data, item.image)
        item.image = create(data, f'DP {obj.name} {data.name} {key} map', (0.0, 0.0, 0.0, 0.0), True, size=size)
    return item.image


def store(data, key_image, number, pixels):
    image = variant(data, key_image, number)
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    image.pack()
    touch()


def height_pixels(high, low, normal, span, distance):
    delta = (high[..., :3] - low[..., :3]) * span
    direction = normal[..., :3] * 2.0 - 1.0
    direction /= numpy.maximum(numpy.linalg.norm(direction, axis=-1, keepdims=True), 1e-6)
    value = numpy.clip(.5 + (delta * direction).sum(axis=-1) / (2.0 * distance), 0.0, 1.0)
    value[high[..., 3] < .5] = .5
    result = numpy.ones(high.shape, dtype=numpy.float32)
    result[..., :3] = value[..., None]
    result[..., 3] = low[..., 3]
    return result


def emitting(build):
    def shade(item, material, tree):
        if tree is not None:
            build(tree)
        return 'shade'
    return shade


def positions(context, obj, project, wanted, sources, samples, distance, scale, resolution):
    origin, span = bounds((obj, *sources.high))
    black = lambda data: emission_tree(data.material.node_tree, (0.0, 0.0, 0.0, 1.0))
    with source_shading(sources.high, emitting(lambda tree: position_shader(tree, origin, span))):
        high = bake_pass(context, obj, project, wanted, black, 'EMIT', samples, sources.high, scale=scale, resolution=resolution, **sources.reach(distance))
    low = bake_pass(context, obj, project, wanted, lambda data: position_shader(data.material.node_tree, origin, span), 'EMIT', BAKE_SAMPLES,
                    scale=scale, resolution=resolution)
    return high, low, span


def world_normals(context, obj, project, wanted, scale, resolution):
    return bake_pass(context, obj, project, wanted, lambda data: world_normal_shader(data.material.node_tree), 'EMIT', BAKE_SAMPLES,
                     scale=scale, resolution=resolution)


def painted_values(project, key, attribute, shape):
    data = project.sets[key[0]]
    image = getattr(data, attribute)
    if image is None:
        return None
    pixels = read_pixels(variant(data, image, key[1]))
    return resized(pixels[..., 0], shape)


def uses_map(project, wanted, attribute):
    return any(getattr(project.sets[index], attribute) is not None for index in wanted)


def reach_masks(project, high, low, span, distance):
    masks = {}
    for key, pixels in high.items():
        cage = painted_values(project, key, 'cage_map', pixels.shape[:2])
        hit = pixels[..., 3] >= .5
        if cage is None:
            masks[key] = hit
            continue
        gap = numpy.linalg.norm((pixels[..., :3] - low[key][..., :3]) * span, axis=-1)
        masks[key] = hit & ((cage >= FULL_REACH) | (gap <= cage * distance))
    return masks


def bake_height(context, obj, project, wanted, sources, samples, distance, scale, resolution):
    high, low, span = positions(context, obj, project, wanted, sources, samples, distance, scale, resolution)
    normal = world_normals(context, obj, project, wanted, scale, resolution)
    masks = reach_masks(project, high, low, span, distance)
    results = {}
    for key in low:
        pixels = height_pixels(high[key], low[key], normal[key], span, distance)
        pixels[~masks[key], :3] = .5
        results[key] = pixels
    return results


@contextmanager
def flat_shading(obj):
    mesh = obj.data
    saved = None
    if 'sharp_face' in mesh.attributes:
        saved = numpy.zeros(len(mesh.polygons), dtype=bool)
        mesh.attributes['sharp_face'].data.foreach_get('value', saved)
    mesh.shade_flat()
    try:
        yield
    finally:
        if saved is None:
            mesh.attributes.remove(mesh.attributes['sharp_face'])
        else:
            mesh.attributes['sharp_face'].data.foreach_set('value', saved)
        mesh.update()


def tangent_shader(tree, uv):
    emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
    tangent = tree.nodes.new('ShaderNodeTangent')
    tangent.direction_type, tangent.uv_map = 'UV_MAP', uv
    encoded = tree.nodes.new('ShaderNodeVectorMath')
    encoded.operation = 'MULTIPLY_ADD'
    tree.links.new(tangent.outputs['Tangent'], encoded.inputs[0])
    encoded.inputs[1].default_value = encoded.inputs[2].default_value = (.5, .5, .5)
    tree.links.new(encoded.outputs['Vector'], emission_input(tree))


def decoded(pixels):
    vectors = pixels[..., :3] * 2.0 - 1.0
    return vectors / numpy.maximum(numpy.linalg.norm(vectors, axis=-1, keepdims=True), 1e-6)


def skewed_normals(context, obj, project, wanted, sources, samples, distance, scale, resolution):
    black = lambda data: emission_tree(data.material.node_tree, (0.0, 0.0, 0.0, 1.0))

    def high_normals():
        with source_shading(sources.high, emitting(world_normal_shader)):
            return bake_pass(context, obj, project, wanted, black, 'EMIT', samples, sources.high, scale=scale, resolution=resolution, **sources.reach(distance))
    smooth = high_normals()
    with flat_shading(obj):
        flat = high_normals()
    uv = project.uv_map if project.uv_map in obj.data.uv_layers else obj.data.uv_layers.active.name
    origin, span = bounds((obj, *sources.high))
    tangent = bake_pass(context, obj, project, wanted, lambda data: tangent_shader(data.material.node_tree, uv), 'EMIT', BAKE_SAMPLES,
                        scale=scale, resolution=resolution)
    normal = world_normals(context, obj, project, wanted, scale, resolution)
    place = bake_pass(context, obj, project, wanted, lambda data: position_shader(data.material.node_tree, origin, span), 'EMIT', BAKE_SAMPLES,
                      scale=scale, resolution=resolution)
    results = {}
    for key, pixels in smooth.items():
        skew = painted_values(project, key, 'skew_map', pixels.shape[:2])
        share = (skew if skew is not None else numpy.zeros(pixels.shape[:2], dtype=numpy.float32))[..., None]
        seen = decoded(pixels) * (1 - share) + decoded(flat[key]) * share
        seen /= numpy.maximum(numpy.linalg.norm(seen, axis=-1, keepdims=True), 1e-6)
        base = decoded(normal[key])
        side = decoded(tangent[key])
        side = side - base * (side * base).sum(axis=-1, keepdims=True)
        side /= numpy.maximum(numpy.linalg.norm(side, axis=-1, keepdims=True), 1e-6)
        up = numpy.cross(base, side)
        along = numpy.gradient(place[key][..., :3], axis=0)
        up *= numpy.where((up * along).sum(axis=-1, keepdims=True) < 0, -1.0, 1.0)
        result = numpy.ones(pixels.shape, dtype=numpy.float32)
        result[..., 0] = (seen * side).sum(axis=-1) * .5 + .5
        result[..., 1] = (seen * up).sum(axis=-1) * .5 + .5
        result[..., 2] = (seen * base).sum(axis=-1) * .5 + .5
        result[pixels[..., 3] < .5, :3] = FLAT_NORMAL[:3]
        result[..., 3] = normal[key][..., 3]
        results[key] = result
    return results


def bake_normal(context, obj, project, wanted, sources, samples, distance, scale, resolution):
    if uses_map(project, wanted, 'skew_map'):
        results = skewed_normals(context, obj, project, wanted, sources, samples, distance, scale, resolution)
    else:
        results = bake_pass(context, obj, project, wanted, lambda item: emission_tree(item.material.node_tree, FLAT_NORMAL), 'NORMAL', samples,
                            sources.high, scale=scale, resolution=resolution, normal_space='TANGENT', **sources.reach(distance))
    return trimmed(context, obj, project, wanted, sources, samples, distance, scale, resolution, results, FLAT_NORMAL)


def trimmed(context, obj, project, wanted, sources, samples, distance, scale, resolution, results, fallback):
    if not uses_map(project, wanted, 'cage_map'):
        return results
    high, low, span = positions(context, obj, project, wanted, sources, samples, distance, scale, resolution)
    masks = reach_masks(project, high, low, span, distance)
    for key, pixels in results.items():
        pixels[~masks[key], :3] = fallback[:3]
    return results


def shifted(mask, dy, dx):
    result = numpy.zeros_like(mask)
    height, width = mask.shape
    result[max(dy, 0):height + min(dy, 0), max(dx, 0):width + min(dx, 0)] = mask[max(-dy, 0):height + min(-dy, 0), max(-dx, 0):width + min(-dx, 0)]
    return result


def border_pixels(coverage):
    inside = coverage[..., 3] > .5
    reach = max(4, round(inside.shape[0] * BORDER_SHARE))
    distance = numpy.zeros(inside.shape, dtype=numpy.float32)
    current = inside
    for _ in range(reach):
        current = current & shifted(current, 1, 0) & shifted(current, -1, 0) & shifted(current, 0, 1) & shifted(current, 0, -1)
        distance += current
    result = numpy.zeros(coverage.shape, dtype=numpy.float32)
    result[..., :3] = (distance / reach)[..., None]
    result[..., 3] = inside
    return result


def uses_samples(data, key):
    return key in PER_MAP_BAKE and not (key == 'curvature' and data.bake_curvature == 'PER_VERTEX')


def uses_extrusion(data, key):
    return key in EXTRUSION_MAPS or (key == 'curvature' and data.bake_curvature == 'NORMAL')


def normal_results(context, obj, project, wanted, sources, samples, distance, scale, resolution, size):
    if sources.high:
        return bake_normal(context, obj, project, wanted, sources, samples, distance, scale, resolution)
    return bake_pass(context, obj, project, wanted, lambda item: rounded_shader(item.material.node_tree, EDGE_ROUNDING * size), 'NORMAL',
                     samples, scale=scale, resolution=resolution, normal_space='TANGENT')


def curvature_from_normal(pixels):
    nx = pixels[..., 0] * 2.0 - 1.0
    ny = pixels[..., 1] * 2.0 - 1.0
    curvature = numpy.clip(.5 + 2.0 * (numpy.gradient(nx, axis=1) + numpy.gradient(ny, axis=0)), 0.0, 1.0)
    covered = pixels[..., 3] >= .5
    curvature = numpy.where(covered, curvature, .5)
    result = numpy.ones(pixels.shape, dtype=numpy.float32)
    result[..., :3] = curvature[..., None]
    result[..., 3] = pixels[..., 3]
    return result


def bake_key(context, obj, project, wanted, key, data, sources, size):
    samples, distance, scale, resolution = map_samples(data, key), map_extrusion(data, key) * size, int(data.bake_antialias), data.bake_resolution
    black = lambda item: emission_tree(item.material.node_tree, (0.0, 0.0, 0.0, 1.0))
    if key == 'uv_border':
        coverage = bake_pass(context, obj, project, wanted, lambda item: emission_tree(item.material.node_tree, (1.0, 1.0, 1.0, 1.0)), 'EMIT', 1,
                             margin=0, scale=scale, resolution=resolution)
        return {item: border_pixels(pixels) for item, pixels in coverage.items()}
    if key == 'height':
        return bake_height(context, obj, project, wanted, sources, samples, distance, scale, resolution)
    if key == 'normal':
        return normal_results(context, obj, project, wanted, sources, samples, distance, scale, resolution, size)
    if key == 'curvature' and data.bake_curvature == 'NORMAL':
        return {item: curvature_from_normal(pixels) for item, pixels in normal_results(context, obj, project, wanted, sources, samples, distance, scale, resolution, size).items()}
    if key == 'id':
        if sources.high:
            with island_colors(sources.high if data.bake_id == 'ISLAND' else ()), source_shading(sources.high, id_source_shade(data.bake_id)):
                results = bake_pass(context, obj, project, wanted, black, 'EMIT', samples, sources.high, scale=scale, resolution=resolution, **sources.reach(distance))
            return trimmed(context, obj, project, wanted, sources, samples, distance, scale, resolution, results, (0.0, 0.0, 0.0))
        with island_colors((obj,) if data.bake_id == 'ISLAND' else ()):
            return bake_pass(context, obj, project, wanted, lambda item: id_shader(item.material.node_tree, data.bake_id, item.name, obj.name),
                             'EMIT', BAKE_SAMPLES, scale=scale, resolution=resolution)

    def prepare(item):
        tree = item.material.node_tree
        emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
        tree.links.new(map_signal(tree.nodes, tree.links, key, size, data.bake_ao_distance, data.bake_ao_spread, data.bake_curvature, data.bake_thickness_range),
                       emission_input(tree))
    return bake_pass(context, obj, project, wanted, prepare, 'EMIT', samples if key in RAY_TRACED and uses_samples(data, key) else BAKE_SAMPLES,
                     scale=scale, resolution=resolution)


def bakeable(context, obj, data, keys):
    sources = bake_sources(context, obj, data)
    return [key for key in keys if sources.high or not MESH_MAP[key].needs_source]


def baked_results(context, obj, project, wanted, keys, data):
    size = object_size(obj)
    sources = bake_sources(context, obj, data)
    for key in bakeable(context, obj, data, keys):
        yield key, bake_key(context, obj, project, wanted, key, data, sources, size)


def store_maps(obj, project, key, results):
    for (index, number), pixels in results.items():
        item = project.sets[index]
        store(item, map_key_image(obj, item, key, pixels.shape[0]), number, pixels)


def bake_maps(context, obj, project, wanted, keys, data):
    baked = []
    for key, results in baked_results(context, obj, project, wanted, keys, data):
        store_maps(obj, project, key, results)
        baked.append(key)
    return baked


def geometry_key(item):
    count = len(item.data.vertices)
    coords = numpy.empty(count * 3, dtype=numpy.float32)
    item.data.vertices.foreach_get('co', coords)
    matrix = ','.join(f'{value:.5f}' for row in item.matrix_world for value in row)
    return f'{item.name}:{count}:{float(coords.sum()):.5f}:{float(numpy.abs(coords).sum()):.5f}:{matrix}'


def map_customized(data, key):
    entry = data.bake_maps.get(key)
    if entry is not None and ((uses_samples(data, key) and entry.samples > 0) or (uses_extrusion(data, key) and entry.extrusion > 0.0)):
        return True
    if key == 'ao':
        return abs(data.bake_ao_distance - BAKE_AO_DISTANCE) > 1e-5 or abs(data.bake_ao_spread - BAKE_AO_SPREAD) > 1e-3
    if key == 'curvature':
        return data.bake_curvature != BAKE_CURVATURES[0][0]
    if key == 'thickness':
        return abs(data.bake_thickness_range - BAKE_THICKNESS_RANGE) > 1e-5
    return False


def map_signature(data):
    parts = []
    if abs(data.bake_ao_distance - BAKE_AO_DISTANCE) > 1e-5:
        parts.append(f'ao_d:{data.bake_ao_distance:.4f}')
    if abs(data.bake_ao_spread - BAKE_AO_SPREAD) > 1e-3:
        parts.append(f'ao_s:{data.bake_ao_spread:.2f}')
    if data.bake_curvature != BAKE_CURVATURES[0][0]:
        parts.append(f'curv:{data.bake_curvature}')
    if abs(data.bake_thickness_range - BAKE_THICKNESS_RANGE) > 1e-5:
        parts.append(f'thick:{data.bake_thickness_range:.4f}')
    for item in MESH_MAPS:
        entry = data.bake_maps.get(item.key)
        if entry is None:
            continue
        if uses_samples(data, item.key) and entry.samples > 0:
            parts.append(f'{item.key}:s={entry.samples}')
        if uses_extrusion(data, item.key) and entry.extrusion > 0.0:
            parts.append(f'{item.key}:e={entry.extrusion:.4f}')
    return tuple(parts)


def signature(context, obj, data):
    sources = bake_sources(context, obj, data)
    objects = (obj, *sources.high, *((sources.cage,) if sources.cage is not None else ()))
    quality = ((data.bake_antialias,) if data.bake_antialias != BAKE_ANTIALIAS[0][0] else ()) + ((f'res:{data.bake_resolution}',) if data.bake_resolution else ())
    parts = (str(data.bake_samples), data.bake_id, f'{data.bake_extrusion:.4f}', *quality, *map_signature(data), *(geometry_key(item) for item in objects))
    return str(zlib.crc32('|'.join(parts).encode()))


def baked_keys(data):
    return [item.key for item in MESH_MAPS if item.key in data.maps and data.maps[item.key].image is not None]
