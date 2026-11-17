from dataclasses import dataclass
import bpy
import numpy
from . import compositing
from .document import active_tile, find_layer, set_channels, slot_value
from .tiles import blank, create, variant

HISTORY_LIMIT = 80
SMEAR_STRENGTH = .85
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


def rgb(value):
    return numpy.array(value if len(value) == 3 else value * 3, dtype=numpy.float32)


def ensure_canvases(obj, data):
    for layer in data.layers:
        if layer.kind != 'PAINT':
            continue
        for channel in set_channels(data):
            slot = layer.slots[channel.key]
            if channel.key == 'base_color' or not slot.enabled or (slot.source == 'IMAGE' and slot.image is not None):
                continue
            slot.source, slot.image = 'IMAGE', create(data, f'DP {obj.name} {data.name} {layer.uid} {slot.name}', (*rgb(slot_value(slot)), 1.0), True)


@dataclass
class Gesture:
    path: list
    radius: float
    source: tuple = None


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


def brush_values(slot, shape):
    if slot.source == 'IMAGE' and slot.image is not None and slot.image.size[0]:
        source = read(slot.image)
        rows = numpy.arange(shape[0]) * source.shape[0] // shape[0]
        columns = numpy.arange(shape[1]) * source.shape[1] // shape[1]
        return source[rows][:, columns][..., :3]
    return numpy.broadcast_to(rgb(slot_value(slot)), shape + (3,))


def merge_targets(data, layer, tile, tool):
    targets = []
    if tool != 'ERASE' or data.brush_slots['base_color'].enabled:
        targets.append(('base_color', variant(data, layer.image, tile)))
    for channel in set_channels(data):
        brush_slot, slot = data.brush_slots[channel.key], layer.slots[channel.key]
        if channel.key != 'base_color' and brush_slot.enabled and slot.enabled and slot.source == 'IMAGE' and slot.image is not None:
            targets.append((channel.key, variant(data, slot.image, tile)))
    return targets


def apply_tool(data, tool, key, pixels, stroke, added, gesture):
    if tool in {'BLUR', 'SMEAR'} and gesture is None:
        return False
    if tool == 'ERASE':
        pixels[..., 3] *= 1 - added
    elif tool == 'BLUR':
        pixels += added[..., None] * (box_blur(pixels, max(1.0, gesture.radius / 2)) - pixels)
    elif tool == 'SMEAR':
        smear(pixels, gesture, added)
    elif tool == 'CLONE':
        if gesture is None or gesture.source is None or not gesture.path:
            return False
        dx = int(round(gesture.path[0][0] - gesture.source[0]))
        dy = int(round(gesture.path[0][1] - gesture.source[1]))
        pixels += added[..., None] * (shifted(pixels, dx, dy) - pixels)
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
            values = brush_values(slot, added.shape)
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
    before, after = [], []
    for key, image in merge_targets(data, layer, active_tile(data), tool):
        pixels = read(image)
        if pixels.shape != stroke.shape:
            continue
        crop = pixels[region].copy()
        if not apply_tool(data, tool, key, pixels, stroke, coverage, gesture):
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
