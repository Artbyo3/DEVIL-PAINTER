from dataclasses import dataclass
import math
import bpy
import numpy
from mathutils.bvhtree import BVHTree
from . import caches, compositing
from .document import active_tile, channel_depth, find_layer, set_channels, slot_value
from .tiles import FIRST_TILE, blank, conform, create, face_slots, variant

HISTORY_LIMIT = 80
SMEAR_STRENGTH = .85
TRACE_STEP = .5
BLEED_TEXELS = 2.0
MERGE_TOOLS = {'PAINT', 'FILL', 'ERASE', 'BLUR', 'SMEAR', 'CLONE'}
_history = []
_future = []
_state = dict(redoing=False)


@dataclass
class Fill:
    before: list
    after: list


def ensure_buffer(obj, data):
    image = data.stroke
    if image is None or tuple(image.size) != (data.resolution, data.resolution):
        data.stroke = blank(f'DP {obj.name} {data.name} stroke', data.resolution, (0.0, 0.0, 0.0, 0.0))
    return data.stroke


def read(image):
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)


def write(image, pixels):
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    caches.touch()


def rgb(value):
    return numpy.array(value if len(value) == 3 else value * 3, dtype=numpy.float32)


def ensure_canvases(obj, data):
    for layer in data.layers:
        if layer.kind != 'PAINT':
            continue
        for channel in set_channels(data):
            slot = layer.slots[channel.key]
            if channel.key == 'base_color' or not slot.enabled:
                continue
            float_buffer = channel_depth(data, channel.key) != '8'
            if slot.source == 'IMAGE' and slot.image is not None:
                conform(data, slot.image, float_buffer)
                continue
            slot.source, slot.image = 'IMAGE', create(data, f'DP {obj.name} {data.name} {layer.uid} {slot.name}', (*rgb(slot_value(slot)), 1.0), True, float_buffer)


@dataclass
class Gesture:
    path: list
    radius: float
    source: tuple = None
    copies: tuple = ()


def box_blur(pixels, radius):
    radius = max(1, int(round(radius)))
    result = pixels
    for axis in (0, 1):
        padding = [(0, 0)] * result.ndim
        padding[axis] = (radius + 1, radius)
        summed = numpy.cumsum(numpy.pad(result, padding, mode='edge'), axis=axis)
        upper = numpy.take(summed, numpy.arange(2 * radius + 1, summed.shape[axis]), axis=axis)
        lower = numpy.take(summed, numpy.arange(0, summed.shape[axis] - 2 * radius - 1), axis=axis)
        result = (upper - lower) / (2 * radius + 1)
    return result


def shifted(pixels, dx, dy):
    result = pixels.copy()
    height, width = pixels.shape[:2]
    target = (slice(max(dy, 0), height + min(dy, 0)), slice(max(dx, 0), width + min(dx, 0)))
    source = (slice(max(-dy, 0), height + min(-dy, 0)), slice(max(-dx, 0), width + min(-dx, 0)))
    result[target] = pixels[source]
    return result


def disc(shape, center, radius):
    ys, xs = numpy.ogrid[:shape[0], :shape[1]]
    distance = numpy.hypot(xs - center[0], ys - center[1]) / max(radius, 1.0)
    return numpy.clip(1 - distance, 0, 1) ** .5


def steps(path):
    return [(start, end) for start, end in zip(path, path[1:]) if round(end[0] - start[0]) or round(end[1] - start[1])]


def smear(pixels, gesture, coverage):
    for start, end in steps(gesture.path):
        dx, dy = int(round(end[0] - start[0])), int(round(end[1] - start[1]))
        weight = (disc(coverage.shape, end, gesture.radius) * (coverage > 0) * SMEAR_STRENGTH)[..., None]
        pixels += weight * (shifted(pixels, dx, dy) - pixels)
    return pixels


def flow_colors(shape, gesture, base):
    colors = base.copy()
    for start, end in steps(gesture.path):
        direction = numpy.array(end, dtype=numpy.float32) - numpy.array(start, dtype=numpy.float32)
        direction /= max(float(numpy.hypot(*direction)), 1e-6)
        weight = (disc(shape, end, gesture.radius) > 0)[..., None]
        colors = numpy.where(weight, (direction[0] * .5 + .5, direction[1] * .5 + .5, 0.0), colors)
    return colors


def trace(path, radius):
    spots = numpy.asarray(path, dtype=numpy.float64).reshape(-1, 2)
    step = max(radius * TRACE_STEP, 2.0)
    kept = [spots[0]]
    for spot in spots[1:]:
        if numpy.hypot(*(spot - kept[-1])) >= step:
            kept.append(spot)
    tail = numpy.hypot(*(spots[-1] - kept[-1]))
    if len(kept) > 1 and tail < step / 2:
        kept[-1] = spots[-1]
    elif tail > 1e-6:
        kept.append(spots[-1])
    return numpy.array(kept)


def ribbon(points, paths, radius):
    best = numpy.full(len(points), numpy.inf)
    along, across = numpy.zeros(len(points)), numpy.zeros(len(points))
    for path in paths:
        spots = trace(path, radius)
        if len(spots) == 1:
            offset = points - spots[0]
            distance = numpy.hypot(offset[:, 0], offset[:, 1])
            closer = distance < best
            best, along, across = numpy.where(closer, distance, best), numpy.where(closer, offset[:, 0], along), numpy.where(closer, offset[:, 1], across)
            continue
        vectors = numpy.diff(spots, axis=0)
        lengths = numpy.hypot(vectors[:, 0], vectors[:, 1])
        offsets = numpy.concatenate(([0.0], numpy.cumsum(lengths)[:-1]))
        last = len(vectors) - 1
        for index, (start, vector, length, offset) in enumerate(zip(spots, vectors, lengths, offsets)):
            unit = vector / length
            relative = points - start
            reach = numpy.clip(relative @ unit, -numpy.inf if index == 0 else 0.0, numpy.inf if index == last else length)
            gap = relative - reach[:, None] * unit
            distance = numpy.hypot(gap[:, 0], gap[:, 1])
            side = unit[0] * relative[:, 1] - unit[1] * relative[:, 0]
            closer = distance < best
            best = numpy.where(closer, distance, best)
            along = numpy.where(closer, offset + reach, along)
            across = numpy.where(closer, numpy.copysign(distance, side), across)
    return along, across


def along_stroke(source, covered, gesture):
    span = max(2 * gesture.radius, 1.0)
    height, width = source.shape[:2]
    factor = max(1, int(min(height, width) // span))
    if factor > 1:
        height, width = height // factor, width // factor
        source = source[:height * factor, :width * factor].reshape(height, factor, width, factor, 3).mean(axis=(1, 3))
    rows, columns = numpy.nonzero(covered)
    points = numpy.stack((columns, rows), axis=-1) + .5
    along, across = ribbon(points, [path for path in (gesture.path, *gesture.copies) if path], gesture.radius)
    picked = (numpy.floor(across / span * height + height / 2).astype(numpy.int64) % height,
              numpy.floor(along / span * height).astype(numpy.int64) % width)
    values = numpy.zeros(covered.shape + (3,), dtype=numpy.float32)
    values[rows, columns] = source[picked]
    return values


def brush_values(slot, added, gesture):
    if slot.source == 'IMAGE' and slot.image is not None and slot.image.size[0]:
        source = read(slot.image)[..., :3]
        if gesture is not None and (gesture.path or any(gesture.copies)):
            return along_stroke(source, added > 0, gesture)
        rows = numpy.arange(added.shape[0]) * source.shape[0] // added.shape[0]
        columns = numpy.arange(added.shape[1]) * source.shape[1] // added.shape[1]
        return source[rows][:, columns]
    return numpy.broadcast_to(rgb(slot_value(slot)), added.shape + (3,))


def barycentric(points, first, second, third):
    edge, other, relative = second - first, third - first, points - first
    d00, d01, d11 = (edge * edge).sum(-1), (edge * other).sum(-1), (other * other).sum(-1)
    d20, d21 = (relative * edge).sum(-1), (relative * other).sum(-1)
    denominator = d00 * d11 - d01 * d01
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return numpy.stack((1 - v - w, v, w), axis=-1)


def surface_triangles(obj, data):
    mesh, project = obj.data, obj.devil_painter
    mesh.calc_loop_triangles()
    count = len(mesh.loop_triangles)
    corners, loops, faces = numpy.empty(count * 3, dtype=numpy.int64), numpy.empty(count * 3, dtype=numpy.int64), numpy.empty(count, dtype=numpy.int64)
    mesh.loop_triangles.foreach_get('vertices', corners)
    mesh.loop_triangles.foreach_get('loops', loops)
    mesh.loop_triangles.foreach_get('polygon_index', faces)
    corners, loops = corners.reshape(-1, 3), loops.reshape(-1, 3)
    if len(project.sets) > 1:
        kept = face_slots(mesh)[faces] == data.slot
        corners, loops = corners[kept], loops[kept]
    coordinates = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float64)
    mesh.vertices.foreach_get('co', coordinates)
    layer = mesh.uv_layers.get(project.uv_map) or mesh.uv_layers.active
    uvs = numpy.empty(len(layer.data) * 2, dtype=numpy.float64)
    layer.data.foreach_get('uv', uvs)
    tile = active_tile(data) - FIRST_TILE
    texels = (uvs.reshape(-1, 2)[loops] - (tile % 10, tile // 10)) * data.resolution
    return coordinates.reshape(-1, 3), corners, texels


def nearest(tree, queries, triangles, reach):
    found = [tree.find_nearest(query, reach) for query in queries.tolist()]
    indices = numpy.array([-1 if index is None else index for _, _, index, _ in found], dtype=numpy.int64)
    spots = numpy.array([(0.0, 0.0, 0.0) if index is None else tuple(spot) for spot, _, index, _ in found], dtype=numpy.float64).reshape(-1, 3)
    weights = barycentric(spots, *triangles[indices].transpose(1, 0, 2))
    return (indices >= 0) & numpy.isfinite(weights).all(1), indices, weights


def clone_sources(obj, data, covered, offset):
    vertices, corners, texels = surface_triangles(obj, data)
    flat = numpy.pad(texels, ((0, 0), (0, 0), (0, 1)))
    shapes, solids = flat.reshape(-1, 3).tolist(), numpy.arange(len(flat) * 3).reshape(-1, 3).tolist()
    rows, columns = numpy.nonzero(covered)
    centers = numpy.stack((columns + .5, rows + .5, numpy.zeros(len(rows))), axis=-1)
    found, indices, weights = nearest(BVHTree.FromPolygons(shapes, solids), centers, flat, BLEED_TEXELS)
    located = numpy.einsum('ij,ijk->ik', weights[found], vertices[corners[indices[found]]]) + offset
    rows, columns = rows[found], columns[found]
    found, indices, weights = nearest(BVHTree.FromPolygons(vertices.tolist(), corners.tolist()), located, vertices[corners], math.inf)
    picked = numpy.floor(numpy.einsum('ij,ijk->ik', weights[found], texels[indices[found]])).astype(numpy.int64)
    inside = ((picked >= 0) & (picked < data.resolution)).all(1)
    return rows[found][inside], columns[found][inside], picked[inside, 1], picked[inside, 0]


def merge_targets(data, layer, tile, tool):
    targets = []
    if tool != 'ERASE' or data.brush_slots['base_color'].enabled:
        targets.append(('base_color', variant(data, layer.image, tile)))
    for channel in set_channels(data):
        brush_slot, slot = data.brush_slots[channel.key], layer.slots[channel.key]
        if channel.key != 'base_color' and brush_slot.enabled and slot.enabled and slot.source == 'IMAGE' and slot.image is not None:
            targets.append((channel.key, variant(data, slot.image, tile)))
    return targets


def apply_tool(data, tool, key, pixels, stroke, added, gesture, sources=None):
    if tool in {'BLUR', 'SMEAR'} and gesture is None:
        return False
    if tool == 'ERASE':
        pixels[..., 3] *= 1 - added
    elif tool == 'BLUR':
        pixels += added[..., None] * (box_blur(pixels, max(1.0, gesture.radius / 2)) - pixels)
    elif tool == 'SMEAR':
        smear(pixels, gesture, added)
    elif tool == 'CLONE':
        if sources is None:
            return False
        rows, columns, source_rows, source_columns = sources
        copied = pixels[source_rows, source_columns]
        pixels[rows, columns] += added[rows, columns, None] * (copied - pixels[rows, columns])
    else:
        alpha = pixels[..., 3:]
        total = alpha + added[..., None] * (1 - alpha) if key == 'base_color' else numpy.maximum(alpha, added[..., None])
        weight = added[..., None] / numpy.maximum(total, 1e-4) if key == 'base_color' else added[..., None]
        slot = data.brush_slots[key]
        if key == 'flow' and gesture is not None:
            values = flow_colors(added.shape, gesture, pixels[..., :3])
        elif key == 'base_color' and not (slot.source == 'IMAGE' and slot.image is not None):
            values = stroke[..., :3]
        else:
            values = brush_values(slot, added, gesture)
        pixels[..., :3] += weight * (values - pixels[..., :3])
        pixels[..., 3:] = total
    return True


def merge(obj, data, gesture=None, tool=None):
    layer = find_layer(data, data.stroke_owner)
    if layer is None or data.stroke is None or layer.image is None:
        return None
    stroke = read(data.stroke)
    coverage = numpy.minimum(stroke[..., 3], data.brush_opacity)
    rows, columns = numpy.flatnonzero(coverage.max(1) > 0), numpy.flatnonzero(coverage.max(0) > 0)
    if not rows.size:
        return None
    tool = tool or (data.stroke_tool if data.stroke_tool in MERGE_TOOLS else 'PAINT')
    if tool in {'PAINT', 'FILL'}:
        for channel in set_channels(data):
            if data.brush_slots[channel.key].enabled and not layer.slots[channel.key].enabled:
                layer.slots[channel.key].enabled = True
        ensure_canvases(obj, data)
    reach = 0 if tool in {'PAINT', 'FILL', 'ERASE'} else int(gesture.radius * 2 + 2) if gesture is not None else 0
    height, width = coverage.shape
    region = (slice(max(rows[0] - reach, 0), min(rows[-1] + 1 + reach, height)), slice(max(columns[0] - reach, 0), min(columns[-1] + 1 + reach, width)))
    cloning = tool == 'CLONE' and gesture is not None and gesture.source is not None and gesture.path
    sources = clone_sources(obj, data, coverage > 0, gesture.source) if cloning else None
    before, after = [], []
    for key, image in merge_targets(data, layer, active_tile(data), tool):
        pixels = read(image)
        if pixels.shape != stroke.shape:
            continue
        crop = pixels[region].copy()
        if not apply_tool(data, tool, key, pixels, stroke, coverage, gesture, sources):
            continue
        before.append((image.name, region, crop))
        after.append((image.name, region, pixels[region].copy()))
        write(image, numpy.clip(pixels, 0.0, 1.0))
    stroke[...] = 0.0
    write(data.stroke, stroke)
    compositing.sync(data)
    return Fill(before, after)


def record(entry):
    _history.append(entry)
    del _history[:-HISTORY_LIMIT]
    if not _state['redoing']:
        _future.clear()
    _state['redoing'] = False


def restore(entry):
    for name, region, crop in entry:
        image = bpy.data.images.get(name)
        if image is not None:
            pixels = read(image)
            pixels[region] = crop
            write(image, pixels)


def undo():
    if _history:
        entry = _history.pop()
        _future.append(entry)
        if isinstance(entry, Fill):
            restore(entry.before)
        elif entry is not None:
            restore(entry)


def redo():
    if not _future:
        return
    entry = _future.pop()
    if isinstance(entry, Fill):
        restore(entry.after)
        _history.append(entry)
    elif entry is None:
        _history.append(None)
    else:
        _state['redoing'] = True


def forget():
    _history.clear()
    _future.clear()
    _state['redoing'] = False
