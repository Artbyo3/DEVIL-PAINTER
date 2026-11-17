import colorsys
import re
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
import bpy
import numpy
from mathutils import Vector
from .baking import bake_pass, emission_tree
from .signals import map_signal
from .tiles import create, variant

FLAT_NORMAL = (0.5, 0.5, 1.0, 1.0)
EDGE_ROUNDING = .02
LOW_SUFFIX = re.compile(r'[ _.\-]*(low|lp|lo)$', re.IGNORECASE)
COPY_SUFFIX = re.compile(r'\.\d+$')
HIGH_WORDS = ('high', 'hp', 'hi')
BORDER_SHARE = 1 / 32
GOLDEN_RATIO = .618033988749895


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


def emission_input(tree):
    return next(node for node in tree.nodes if node.type == 'EMISSION').inputs['Color']


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
        tree.links.new(map_signal(tree.nodes, tree.links, 'id', 1.0), color)


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


def map_key_image(obj, data, key):
    item = data.maps.get(key)
    if item is None:
        item = data.maps.add()
        item.name = key
    if item.image is None or tuple(item.image.size) != (data.resolution, data.resolution):
        item.image = create(data, f'DP {obj.name} {data.name} {key} map', (0.0, 0.0, 0.0, 0.0), True)
    return item.image


def store(data, key_image, number, pixels):
    image = variant(data, key_image, number)
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    image.pack()


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


def bake_height(context, obj, project, wanted, sources, samples, distance):
    origin, span = bounds((obj, *sources.high))
    def shade(item, material, tree):
        if tree is not None:
            position_shader(tree, origin, span)
        return 'position'

    with source_shading(sources.high, shade):
        high = bake_pass(context, obj, project, wanted, lambda data: emission_tree(data.material.node_tree, (0.0, 0.0, 0.0, 1.0)),
                         'EMIT', samples, sources.high, **sources.reach(distance))
    low = bake_pass(context, obj, project, wanted, lambda data: position_shader(data.material.node_tree, origin, span), 'EMIT', samples)
    normal = bake_pass(context, obj, project, wanted, lambda data: world_normal_shader(data.material.node_tree), 'EMIT', samples)
    return {key: height_pixels(high[key], low[key], normal[key], span, distance) for key in low}


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


def bake_key(context, obj, project, wanted, key, data, sources, size):
    samples, distance = data.bake_samples, data.bake_extrusion * size
    black = lambda item: emission_tree(item.material.node_tree, (0.0, 0.0, 0.0, 1.0))
    if key == 'uv_border':
        coverage = bake_pass(context, obj, project, wanted, lambda item: emission_tree(item.material.node_tree, (1.0, 1.0, 1.0, 1.0)), 'EMIT', 1, margin=0)
        return {item: border_pixels(pixels) for item, pixels in coverage.items()}
    if key == 'height':
        return bake_height(context, obj, project, wanted, sources, samples, distance)
    if key == 'normal':
        if sources.high:
            return bake_pass(context, obj, project, wanted, lambda item: emission_tree(item.material.node_tree, FLAT_NORMAL), 'NORMAL', samples,
                             sources.high, normal_space='TANGENT', **sources.reach(distance))
        return bake_pass(context, obj, project, wanted, lambda item: rounded_shader(item.material.node_tree, EDGE_ROUNDING * size), 'NORMAL',
                         samples, normal_space='TANGENT')
    if key == 'id':
        if sources.high:
            with source_shading(sources.high, id_source_shade(data.bake_id)):
                return bake_pass(context, obj, project, wanted, black, 'EMIT', samples, sources.high, **sources.reach(distance))
        return bake_pass(context, obj, project, wanted, lambda item: id_shader(item.material.node_tree, data.bake_id, item.name, obj.name),
                         'EMIT', samples)

    def prepare(item):
        tree = item.material.node_tree
        emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
        tree.links.new(map_signal(tree.nodes, tree.links, key, size), emission_input(tree))
    return bake_pass(context, obj, project, wanted, prepare, 'EMIT', samples)


def bake_maps(context, obj, project, wanted, keys, data):
    size = object_size(obj)
    sources = bake_sources(context, obj, data)
    baked = []
    for key in keys:
        if MESH_MAP[key].needs_source and not sources.high:
            continue
        for (index, number), pixels in bake_key(context, obj, project, wanted, key, data, sources, size).items():
            item = project.sets[index]
            store(item, map_key_image(obj, item, key), number, pixels)
        baked.append(key)
    return baked


def geometry_key(item):
    count = len(item.data.vertices)
    coords = numpy.empty(count * 3, dtype=numpy.float32)
    item.data.vertices.foreach_get('co', coords)
    matrix = ','.join(f'{value:.5f}' for row in item.matrix_world for value in row)
    return f'{item.name}:{count}:{float(coords.sum()):.5f}:{float(numpy.abs(coords).sum()):.5f}:{matrix}'


def signature(context, obj, data):
    sources = bake_sources(context, obj, data)
    objects = (obj, *sources.high, *((sources.cage,) if sources.cage is not None else ()))
    parts = (str(data.bake_samples), data.bake_id, f'{data.bake_extrusion:.4f}', *(geometry_key(item) for item in objects))
    return str(zlib.crc32('|'.join(parts).encode()))


def baked_keys(data):
    return [item.key for item in MESH_MAPS if item.key in data.maps and data.maps[item.key].image is not None]
