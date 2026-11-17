from dataclasses import dataclass
import bpy
import numpy
from . import compositing
from .document import active_tile, find_layer, set_channels, slot_value
from .tiles import blank, create, variant

HISTORY_LIMIT = 80
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


def merge(obj, data):
    layer = find_layer(data, data.stroke_owner)
    if layer is None or data.stroke is None or layer.image is None:
        return False
    stroke = read(data.stroke)
    coverage = numpy.minimum(stroke[..., 3], data.brush_opacity)
    rows, columns = numpy.flatnonzero(coverage.max(1) > 0), numpy.flatnonzero(coverage.max(0) > 0)
    if not rows.size:
        return False
    region = (slice(rows[0], rows[-1] + 1), slice(columns[0], columns[-1] + 1))
    added = coverage[region][..., None]
    snapshot = []
    tile = active_tile(data)
    painted = variant(data, layer.image, tile)
    base = read(painted)
    if base.shape != stroke.shape:
        return False
    crop = base[region]
    snapshot.append((painted.name, region, crop.copy()))
    alpha = crop[..., 3:]
    total = alpha + added * (1 - alpha)
    weight = added / numpy.maximum(total, 1e-4)
    crop[..., :3] += weight * (stroke[region][..., :3] - crop[..., :3])
    crop[..., 3:] = total
    write(painted, base)
    for channel in set_channels(data):
        brush_slot, slot = data.brush_slots[channel.key], layer.slots[channel.key]
        canvas = variant(data, slot.image, tile) if slot.source == 'IMAGE' else None
        if channel.key == 'base_color' or not (brush_slot.enabled and slot.enabled) or canvas is None:
            continue
        values = read(canvas)
        crop = values[region]
        snapshot.append((canvas.name, region, crop.copy()))
        crop[..., :3] += weight * (rgb(slot_value(brush_slot)) - crop[..., :3])
        write(canvas, values)
    stroke[region] = 0.0
    write(data.stroke, stroke)
    record(snapshot)
    compositing.sync(data)
    return True


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
