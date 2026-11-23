import numpy
from . import compositing, history, strokes
from .document import active_layer, editing_mask, paint_target, set_channels, slot_value
from .sets import island_of, triangle_at, uv_island_labels
from .tiles import FIRST_TILE, variant

POLY_MODES = (('TRIANGLE', 'Triangle'), ('FACE', 'Face'), ('ISLAND', 'Mesh part'), ('UV', 'UV chunk'), ('LOOP', 'Loop'))
POLY_NOUN = {mode: label if label.startswith('UV') else label.lower() for mode, label in POLY_MODES}
SEAM_PIXELS = 2


def uv_coords(mesh, uv_name):
    layer = mesh.uv_layers.get(uv_name) or mesh.uv_layers.active
    coords = numpy.empty(len(layer.data) * 2, dtype=numpy.float64)
    layer.data.foreach_get('uv', coords)
    return coords.reshape(-1, 2)


def edge_distance(mesh, key, location):
    start, end = (mesh.vertices[index].co for index in key)
    direction = end - start
    share = max(0.0, min(1.0, (location - start).dot(direction) / max(direction.length_squared, 1e-12)))
    return (start + direction * share - location).length


def edge_faces(mesh):
    owners = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            owners.setdefault(key, []).append(polygon.index)
    return owners


def opposite(polygon, key):
    keys = polygon.edge_keys
    return keys[(keys.index(key) + 2) % 4] if len(keys) == 4 and key in keys else None


def face_loop(mesh, face, location):
    owners = edge_faces(mesh)
    polygon = mesh.polygons[face]
    if len(polygon.edge_keys) != 4:
        return [face]
    nearest = min(polygon.edge_keys, key=lambda key: edge_distance(mesh, key, location))
    reached = [face]
    for key in (nearest, opposite(polygon, nearest)):
        current = face
        while key is not None:
            following = next((item for item in owners.get(key, ()) if item != current), None)
            if following is None or following in reached:
                break
            reached.append(following)
            current = following
            key = opposite(mesh.polygons[following], key)
    return reached


def picked_triangles(mesh, uv_name, mode, face, location):
    mesh.calc_loop_triangles()
    if mode == 'TRIANGLE':
        return [triangle_at(mesh, face, location)]
    if mode == 'FACE':
        faces = {face}
    elif mode == 'ISLAND':
        faces = set(island_of(mesh, face))
    elif mode == 'UV':
        labels = uv_island_labels(mesh, uv_name)
        faces = set(numpy.flatnonzero(labels == labels[face]).tolist())
    else:
        faces = set(face_loop(mesh, face, location))
    return [triangle for triangle in mesh.loop_triangles if triangle.polygon_index in faces]


def grown(mask, steps):
    for _ in range(steps):
        spread = mask.copy()
        spread[1:] |= mask[:-1]
        spread[:-1] |= mask[1:]
        spread[:, 1:] |= mask[:, :-1]
        spread[:, :-1] |= mask[:, 1:]
        mask = spread
    return mask


def rasterize(triangles, coords, resolution):
    covered = {}
    for triangle in triangles:
        uv = coords[list(triangle.loops)]
        corner = numpy.floor(uv.mean(axis=0))
        number = FIRST_TILE + int(corner[0]) + 10 * int(corner[1])
        points = (uv - corner) * resolution - .5
        low = numpy.clip(numpy.floor(points.min(axis=0)).astype(int), 0, resolution - 1)
        high = numpy.clip(numpy.ceil(points.max(axis=0)).astype(int), 0, resolution - 1)
        xs, ys = numpy.meshgrid(numpy.arange(low[0], high[0] + 1), numpy.arange(low[1], high[1] + 1))
        (ax, ay), (bx, by), (cx, cy) = points
        area = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        if abs(area) < 1e-12:
            continue
        first = ((bx - xs) * (cy - ys) - (cx - xs) * (by - ys)) / area
        second = ((cx - xs) * (ay - ys) - (ax - xs) * (cy - ys)) / area
        inside = (first >= 0) & (second >= 0) & (first + second <= 1)
        mask = covered.setdefault(number, numpy.zeros((resolution, resolution), dtype=bool))
        mask[ys[inside], xs[inside]] = True
    return {number: grown(mask, SEAM_PIXELS) for number, mask in covered.items()}


def paint_region(image, coverage, color, alpha, before, after):
    pixels = strokes.read(image)
    rows, columns = numpy.flatnonzero(coverage.any(1)), numpy.flatnonzero(coverage.any(0))
    region = (slice(rows[0], rows[-1] + 1), slice(columns[0], columns[-1] + 1))
    before.append((image.name, region, pixels[region].copy()))
    crop = pixels[region]
    inside = coverage[region]
    if color is not None:
        crop[..., :3][inside] = color
    crop[..., 3][inside] = alpha
    strokes.write(image, pixels)
    after.append((image.name, region, pixels[region].copy()))


def fill_targets(data, color, erase):
    layer = active_layer(data)
    target = paint_target(data)
    if target is None:
        return []
    alpha = 0.0 if erase else 1.0
    if target != layer.image or editing_mask(data):
        return [(target, None if erase else color, alpha)]
    targets = [(target, None if erase else color, alpha)]
    if not erase:
        for channel in set_channels(data):
            brush_slot, slot = data.brush_slots[channel.key], layer.slots[channel.key]
            if channel.key != 'base_color' and brush_slot.enabled and slot.enabled and slot.source == 'IMAGE' and slot.image is not None:
                targets.append((slot.image, strokes.rgb(slot_value(brush_slot)), 1.0))
    return targets


def polygon_fill(obj, data, mode, face, location, color, erase):
    mesh = obj.data
    if mesh.polygons[face].material_index != data.slot:
        return 'That face belongs to another texture set.'
    uv_name = obj.devil_painter.uv_map
    triangles = [triangle for triangle in picked_triangles(mesh, uv_name, mode, face, location) if mesh.polygons[triangle.polygon_index].material_index == data.slot]
    covered = rasterize(triangles, uv_coords(mesh, uv_name), data.resolution)
    targets = fill_targets(data, color, erase)
    if not targets or not covered:
        return 'Pick a paint layer, mask, or paint effect to fill.'
    before, after = [], []
    for number, coverage in covered.items():
        for image, value, alpha in targets:
            paint_region(variant(data, image, number), coverage, value, alpha, before, after)
    compositing.sync(data)
    faces = len({triangle.polygon_index for triangle in triangles})
    message = f'{"Erased" if erase else "Filled"} {POLY_NOUN[mode]}: {faces} face{"s" if faces != 1 else ""}.'
    history.push(message, strokes.Fill(before, after))
    return message
