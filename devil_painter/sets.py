import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import geometry
from .document import active_tile
from .tiles import FIRST_TILE, face_slots, face_tiles, numbers, slot_tiles

UV_SCALE = 100000
FACE_INDEX = '.devil_painter_face'


def uv_name(obj):
    layer = obj.data.uv_layers.active
    return layer.name if layer is not None else ''


def slot_names(obj):
    names = []
    for index, slot in enumerate(obj.material_slots):
        names.append(slot.material.name if slot.material is not None else f'Slot {index + 1}')
    return names or ['Main']


def detect(obj, use_udim):
    mesh = obj.data
    name = uv_name(obj)
    return [(label, slot_tiles(mesh, name, index, use_udim) if name else [FIRST_TILE]) for index, label in enumerate(slot_names(obj))]


def has_udim(obj):
    return any(len(found) > 1 or found[0] != FIRST_TILE for _, found in detect(obj, True))


def tile_label(found):
    if len(found) == 1 and found[0] == FIRST_TILE:
        return 'Single tile'
    return 'UDIM ' + ', '.join(str(number) for number in found)


def remember_mask(mesh):
    selected = numpy.empty(len(mesh.polygons), dtype=bool)
    mesh.polygons.foreach_get('select', selected)
    return mesh.use_paint_mask, selected


def restore_mask(mesh, saved):
    flag, selected = saved
    if len(selected) == len(mesh.polygons):
        mesh.polygons.foreach_set('select', selected)
    mesh.use_paint_mask = flag
    mesh.update()


def mask_faces(obj, project):
    data = project.sets[project.active_set]
    mesh = obj.data
    selected = numpy.ones(len(mesh.polygons), dtype=bool)
    if len(project.sets) > 1:
        selected &= face_slots(mesh) == data.slot
    if len(numbers(data)) > 1:
        selected &= face_tiles(mesh, project.uv_map) == active_tile(data)
    mesh.polygons.foreach_set('select', selected)
    mesh.use_paint_mask = True
    mesh.update()


def island_of(mesh, face):
    starts = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    totals = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    mesh.polygons.foreach_get('loop_start', starts)
    mesh.polygons.foreach_get('loop_total', totals)
    corners = numpy.empty(len(mesh.loops), dtype=numpy.int32)
    mesh.loops.foreach_get('vertex_index', corners)
    owners = numpy.repeat(numpy.arange(len(mesh.polygons)), totals)
    reached = {face}
    frontier = {face}
    while frontier:
        vertices = numpy.unique(numpy.concatenate([corners[starts[item]:starts[item] + totals[item]] for item in frontier]))
        touching = set(numpy.unique(owners[numpy.isin(corners, vertices)]).tolist())
        frontier = touching - reached
        reached |= frontier
    return sorted(reached)


def face_under(region, view, obj, coord):
    origin = view3d_utils.region_2d_to_origin_3d(region, view, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, view, coord)
    inverse = obj.matrix_world.inverted()
    hit, _, _, face = obj.ray_cast(inverse @ origin, (inverse.to_3x3() @ direction).normalized())
    return face if hit else -1


def hit_under(region, view, obj, coord):
    origin = view3d_utils.region_2d_to_origin_3d(region, view, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, view, coord)
    inverse = obj.matrix_world.inverted()
    hit, location, _, face = obj.ray_cast(inverse @ origin, (inverse.to_3x3() @ direction).normalized())
    return (face, location) if hit else (-1, None)


def surface_mesh(obj):
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data


def original_face(obj, face):
    mesh = obj.data
    stored = mesh.attributes.get(FACE_INDEX) or mesh.attributes.new(FACE_INDEX, 'INT', 'FACE')
    indices = numpy.arange(len(mesh.polygons), dtype=numpy.int32)
    values = numpy.empty_like(indices)
    stored.data.foreach_get('value', values)
    if not numpy.array_equal(values, indices):
        stored.data.foreach_set('value', indices)
        mesh.update()
    carried = surface_mesh(obj).attributes.get(FACE_INDEX)
    return carried.data[face].value if carried is not None else -1


def triangle_at(mesh, face, location):
    mesh.calc_loop_triangles()
    candidates = [triangle for triangle in mesh.loop_triangles if triangle.polygon_index == face]
    points = lambda triangle: [mesh.vertices[index].co for index in triangle.vertices]
    return next((triangle for triangle in candidates if geometry.intersect_point_tri(location, *points(triangle)) is not None),
                min(candidates, key=lambda triangle: (sum(points(triangle), location * 0) / 3 - location).length))


def uv_at(mesh, uv_name, triangle, location):
    layer = mesh.uv_layers.get(uv_name) or mesh.uv_layers.active
    corners = [mesh.vertices[index].co for index in triangle.vertices]
    coords = [layer.data[loop].uv.to_3d() for loop in triangle.loops]
    return geometry.barycentric_transform(location, *corners, *coords).to_2d()


def uv_island_labels(mesh, uv_name):
    layer = mesh.uv_layers.get(uv_name) or mesh.uv_layers.active
    coords = numpy.empty(len(layer.data) * 2, dtype=numpy.float64)
    layer.data.foreach_get('uv', coords)
    vertices = numpy.empty(len(mesh.loops), dtype=numpy.int64)
    mesh.loops.foreach_get('vertex_index', vertices)
    keys = numpy.column_stack((vertices, numpy.round(coords.reshape(-1, 2) * UV_SCALE).astype(numpy.int64)))
    _, corner_ids = numpy.unique(keys, axis=0, return_inverse=True)
    totals = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    mesh.polygons.foreach_get('loop_total', totals)
    owners = numpy.repeat(numpy.arange(len(mesh.polygons)), totals)
    parent = list(range(len(mesh.polygons)))

    def root(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item
    first = {}
    for corner, owner in zip(corner_ids.ravel().tolist(), owners.tolist()):
        other = first.setdefault(corner, owner)
        if other != owner:
            parent[root(owner)] = root(other)
    return numpy.array([root(item) for item in range(len(parent))], dtype=numpy.int64)


def locate(obj, project, face):
    mesh = surface_mesh(obj)
    slot = mesh.polygons[face].material_index
    index = next((position for position, data in enumerate(project.sets) if data.slot == slot), project.active_set)
    tile = int(face_tiles(mesh, project.uv_map)[face])
    return index, tile
