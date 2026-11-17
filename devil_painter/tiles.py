import bpy
import numpy

FIRST_TILE = 1001
PARKED_UV = -5.0


def numbers(data):
    return [tile.number for tile in data.tiles] or [FIRST_TILE]


def blank(name, size, fill, data_values=False):
    image = bpy.data.images.new(name, size, size, alpha=True)
    image.alpha_mode = 'STRAIGHT'
    if data_values:
        image.colorspace_settings.name = 'Non-Color'
    pixels = numpy.empty((size * size, 4), dtype=numpy.float32)
    pixels[:] = fill
    image.pixels.foreach_set(pixels.ravel())
    image.pack()
    return image


def variant(data, key, number):
    if key is None or number == numbers(data)[0]:
        return key
    return next((item.image for item in data.tile_images if item.key == key and item.number == number), key)


def register(data, key, number, image):
    item = data.tile_images.add()
    item.key, item.number, item.image = key, number, image


def adopt(data, key, fill):
    data_values = key.colorspace_settings.is_data
    for number in numbers(data)[1:]:
        if variant(data, key, number) is key:
            register(data, key, number, blank(f'{key.name} {number}', key.size[0], fill, data_values))
    return key


def create(data, name, fill, data_values=False):
    return adopt(data, blank(name, data.resolution, fill, data_values), fill)


def copy(data, key, name):
    duplicate = key.copy()
    duplicate.name = name
    duplicate.pack()
    for number in numbers(data)[1:]:
        source = variant(data, key, number)
        if source is not key:
            tile = source.copy()
            tile.name = f'{name} {number}'
            tile.pack()
            register(data, duplicate, number, tile)
    return duplicate


def remove(data, key):
    for index in range(len(data.tile_images) - 1, -1, -1):
        item = data.tile_images[index]
        if item.key == key:
            if item.image is not None:
                bpy.data.images.remove(item.image)
            data.tile_images.remove(index)
    bpy.data.images.remove(key)


def every_image(data, keys):
    found = [key for key in keys if key is not None]
    found += [item.image for item in data.tile_images if item.image is not None and item.key in found]
    return found


def face_tiles(mesh, uv_name):
    layer = mesh.uv_layers.get(uv_name) or mesh.uv_layers.active
    count = len(mesh.polygons)
    if layer is None or not count:
        return numpy.full(count, FIRST_TILE, dtype=numpy.int32)
    coords = numpy.empty(len(layer.data) * 2, dtype=numpy.float32)
    layer.data.foreach_get('uv', coords)
    coords = coords.reshape(-1, 2)
    starts = numpy.empty(count, dtype=numpy.int32)
    totals = numpy.empty(count, dtype=numpy.int32)
    mesh.polygons.foreach_get('loop_start', starts)
    mesh.polygons.foreach_get('loop_total', totals)
    centers = numpy.add.reduceat(coords, starts, axis=0) / totals[:, None]
    floors = numpy.floor(centers).astype(numpy.int32)
    return FIRST_TILE + numpy.clip(floors[:, 0], 0, 9) + 10 * numpy.maximum(floors[:, 1], 0)


def face_slots(mesh):
    slots = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    mesh.polygons.foreach_get('material_index', slots)
    return slots


def slot_tiles(mesh, uv_name, slot, use_udim):
    if not use_udim:
        return [FIRST_TILE]
    found = sorted(set(face_tiles(mesh, uv_name)[face_slots(mesh) == slot].tolist()))
    return found or [FIRST_TILE]


def shifted_uv(mesh, uv_name, faces, number):
    source = mesh.uv_layers[uv_name]
    coords = numpy.empty(len(source.data) * 2, dtype=numpy.float32)
    source.data.foreach_get('uv', coords)
    coords = coords.reshape(-1, 2)
    starts = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    totals = numpy.empty(len(mesh.polygons), dtype=numpy.int32)
    mesh.polygons.foreach_get('loop_start', starts)
    mesh.polygons.foreach_get('loop_total', totals)
    inside = numpy.repeat(faces, totals)
    offset = numpy.array(((number - FIRST_TILE) % 10, (number - FIRST_TILE) // 10), dtype=numpy.float32)
    coords = numpy.where(inside[:, None], coords - offset, PARKED_UV)
    layer = mesh.uv_layers.new(name='DP Bake UV', do_init=False)
    mesh.uv_layers.active = source
    layer.data.foreach_set('uv', coords.ravel())
    return layer.name
