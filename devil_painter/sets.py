import numpy
from bpy_extras import view3d_utils
from .document import active_tile
from .tiles import FIRST_TILE, face_slots, face_tiles, numbers, slot_tiles


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


def face_under(region, view, obj, coord):
    origin = view3d_utils.region_2d_to_origin_3d(region, view, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, view, coord)
    inverse = obj.matrix_world.inverted()
    hit, _, _, face = obj.ray_cast(inverse @ origin, (inverse.to_3x3() @ direction).normalized())
    return face if hit and face < len(obj.data.polygons) else -1


def locate(obj, project, face):
    mesh = obj.data
    slot = mesh.polygons[face].material_index
    index = next((position for position, data in enumerate(project.sets) if data.slot == slot), project.active_set)
    tile = int(face_tiles(mesh, project.uv_map)[face])
    return index, tile
