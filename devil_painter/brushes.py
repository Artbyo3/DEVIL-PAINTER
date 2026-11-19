import hashlib
from pathlib import Path
import json
import math
import bpy
import numpy
from .blending import CHANNEL
from .document import set_channels, set_slot_value
from .library import library_root, load_image, save_settings, settings
from .painting import STROKE_TOOLS, active_tool, brush_source

ALPHA_SIZE = 256
PREVIEW_SIZE = 96
ALPHA_TEXTURE = 'DP Brush Alpha'
ALPHAS = ('Square', 'Star', 'Ring', 'Grain', 'Splat', 'Scratches')
PRESETS = (
    dict(name='Soft Round', hardness=0.0, flow=1.0, spacing=10.0, smoothing=0.0, jitter=0.0, alpha='', random_angle=False),
    dict(name='Hard Round', hardness=.9, flow=1.0, spacing=8.0, smoothing=0.0, jitter=0.0, alpha='', random_angle=False),
    dict(name='Airbrush', hardness=0.0, flow=.12, spacing=4.0, smoothing=.2, jitter=0.0, alpha='', random_angle=False),
    dict(name='Ink', hardness=.95, flow=1.0, spacing=4.0, smoothing=.7, jitter=0.0, alpha='', random_angle=False),
    dict(name='Chalk', hardness=.5, flow=.6, spacing=18.0, smoothing=.1, jitter=.2, alpha='Grain', random_angle=True),
    dict(name='Splatter', hardness=.6, flow=1.0, spacing=70.0, smoothing=0.0, jitter=.8, alpha='Splat', random_angle=True),
    dict(name='Square', hardness=.8, flow=1.0, spacing=25.0, smoothing=.3, jitter=0.0, alpha='Square', random_angle=False),
    dict(name='Scratches', hardness=.7, flow=.8, spacing=40.0, smoothing=0.0, jitter=.5, alpha='Scratches', random_angle=True),
)
PRESSURE_FIELDS = ('pressure_flow', 'pressure_hardness', 'pressure_angle')
PRESET_FIELDS = ('hardness', 'flow', 'spacing', 'smoothing', 'jitter', 'random_angle', 'stroke', 'angle', *PRESSURE_FIELDS)
PRESET_DEFAULTS = dict(stroke='SPACE', angle=0.0, **{field: False for field in PRESSURE_FIELDS})
STENCIL_TEXTURE = 'DP Stencil'


def alpha_folder():
    folder = library_root() / 'alphas'
    folder.mkdir(exist_ok=True)
    return folder


def grid(size):
    axis = (numpy.arange(size) + .5) / size * 2 - 1
    return numpy.meshgrid(axis, axis)


def alpha_shape(name, size):
    x, y = grid(size)
    radius, angle = numpy.hypot(x, y), numpy.arctan2(y, x)
    random = numpy.random.default_rng(len(name) * 7919)
    if name == 'Square':
        shape = numpy.clip((.75 - numpy.maximum(abs(x), abs(y))) * 12, 0, 1)
    elif name == 'Star':
        edge = .45 + .4 * (.5 + .5 * numpy.cos(angle * 5)) ** 3
        shape = numpy.clip((edge - radius) * 14, 0, 1)
    elif name == 'Ring':
        shape = numpy.clip((.12 - abs(radius - .7)) * 14, 0, 1)
    elif name == 'Grain':
        noise = random.random((size // 4, size // 4)).repeat(4, 0).repeat(4, 1)
        shape = (noise > .45) * numpy.clip((.95 - radius) * 8, 0, 1)
    elif name == 'Splat':
        shape = numpy.zeros((size, size))
        for _ in range(26):
            cx, cy = random.normal(0, .35, 2)
            blob = random.uniform(.04, .22)
            shape = numpy.maximum(shape, numpy.clip((blob - numpy.hypot(x - cx, y - cy)) * 30, 0, 1))
    else:
        shape = numpy.zeros((size, size))
        for _ in range(9):
            tilt, offset, width = random.uniform(-.5, .5), random.uniform(-.7, .7), random.uniform(.008, .025)
            distance = abs(y - offset - tilt * x)
            shape = numpy.maximum(shape, numpy.clip((width - distance) / width, 0, 1) * (abs(x) < random.uniform(.4, .95)))
    return shape.astype(numpy.float32)


def write_gray(path, shape):
    size = shape.shape[0]
    pixels = numpy.ones((size, size, 4), dtype=numpy.float32)
    pixels[..., :3] = shape[..., None]
    image = bpy.data.images.new(path.stem, size, size, alpha=False)
    try:
        image.pixels.foreach_set(pixels.ravel())
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


def alpha_path(name):
    path = alpha_folder() / f'{name}.png'
    if not path.is_file():
        write_gray(path, alpha_shape(name, ALPHA_SIZE))
    return path


def falloff(distance, hardness):
    return numpy.clip((1 - distance) / max(1e-3, 1 - hardness), 0, 1) ** 2 * (distance < 1)


def preview_path(preset):
    digest = hashlib.sha1(json.dumps(preset, sort_keys=True).encode('utf-8')).hexdigest()[:20]
    path = library_root() / 'brush_previews' / f'{digest}.png'
    if path.is_file():
        return path
    path.parent.mkdir(exist_ok=True)
    size, dab = PREVIEW_SIZE, 22
    canvas = numpy.zeros((size, size), dtype=numpy.float32)
    stamp_x, stamp_y = grid(dab)
    stamp = falloff(numpy.hypot(stamp_x, stamp_y), preset['hardness'])
    if preset['alpha'] in ALPHAS:
        shape = alpha_shape(preset['alpha'], ALPHA_SIZE)
        stamp = stamp * shape[::ALPHA_SIZE // dab, ::ALPHA_SIZE // dab][:dab, :dab]
    random = numpy.random.default_rng(5)
    steps = max(4, int(70 / max(1.0, preset['spacing'] * dab / 100)))
    for step in range(steps):
        t = step / (steps - 1)
        cx = 12 + t * (size - 24 - dab) + random.normal(0, preset['jitter'] * 6)
        cy = size / 2 - dab / 2 + math.sin(t * math.pi * 2) * 22 + random.normal(0, preset['jitter'] * 6)
        x0, y0 = int(max(0, min(size - dab, cx))), int(max(0, min(size - dab, cy)))
        region = canvas[y0:y0 + dab, x0:x0 + dab]
        region += preset['flow'] * stamp * (1 - region)
    write_gray(path, numpy.clip(canvas, 0, 1))
    return path


def alpha_texture(image):
    texture = bpy.data.textures.get(ALPHA_TEXTURE) or bpy.data.textures.new(ALPHA_TEXTURE, 'IMAGE')
    texture.image = image
    return texture


def set_hardness(brush, hardness):
    brush.curve_distance_falloff_preset = 'CUSTOM'
    points = brush.curve_distance_falloff.curves[0].points
    while len(points) > 2:
        points.remove(points[1])
    points[0].location, points[-1].location = (0.0, 1.0), (1.0, 0.0)
    if hardness > 0:
        points.new(min(.98, hardness), 1.0)
    brush.curve_distance_falloff.update()


def pressure_mapped(data):
    return any(getattr(data, 'brush_' + field) for field in PRESSURE_FIELDS)


def pressure_response(curve, pressure, mapped):
    return curve.evaluate(curve.curves[0], pressure) if mapped else 1.0


def sync_pressure(context, data, pressure):
    brush = context.tool_settings.image_paint.brush
    flow = data.brush_flow * pressure_response(brush.curve_strength, pressure, data.brush_pressure_flow)
    setattr(brush_source(context, 'strength'), 'strength', flow if active_tool(context) in STROKE_TOOLS else data.brush_opacity)
    hardness = data.brush_hardness * pressure_response(brush.curve_hardness, pressure, data.brush_pressure_hardness)
    if abs(brush.get('dp_hardness', -1.0) - hardness) > 1e-4:
        set_hardness(brush, hardness)
        brush['dp_hardness'] = hardness
    if brush.mask_texture is not None:
        brush.mask_texture_slot.angle = math.radians(data.brush_angle * pressure_response(brush.curve_strength, pressure, data.brush_pressure_angle))


def sync(context, data):
    paint = context.tool_settings.image_paint
    brush = paint.brush
    if brush is None or brush.library is not None:
        return
    brush.use_accumulate = active_tool(context) in STROKE_TOOLS and data.brush_flow < 1
    brush.spacing = max(1, round(data.brush_spacing))
    brush.use_smooth_stroke = data.brush_smoothing > 0
    brush.smooth_stroke_radius = round(10 + 90 * data.brush_smoothing)
    brush.smooth_stroke_factor = .5 + .49 * data.brush_smoothing
    brush.jitter = data.brush_jitter
    brush.use_pressure_size = data.brush_pressure_size
    brush.use_pressure_strength = data.brush_pressure_opacity
    brush.stroke_method = data.brush_stroke
    if data.brush_alpha is None:
        brush.mask_texture = None
    else:
        brush.mask_texture = alpha_texture(data.brush_alpha)
        slot = brush.mask_texture_slot
        slot.mask_map_mode = 'VIEW_PLANE'
        slot.use_random = data.brush_random_angle
        slot.random_angle = math.tau
    sync_pressure(context, data, 1.0)
    sync_stencil(context, brush, data)
    sync_symmetry(context, data)


def view_region(context):
    areas = [area for area in context.screen.areas if area.type == 'VIEW_3D'] if context.screen is not None else []
    if not areas:
        return None
    area = max(areas, key=lambda item: item.width * item.height)
    return next((region for region in area.regions if region.type == 'WINDOW'), None)


def stencil_frame(data, width, height):
    image = data.brush_stencil
    aspect = image.size[0] / max(image.size[1], 1) if image is not None and image.size[1] else 1.0
    half = data.stencil_scale * min(width, height) / 2
    dimension = (half * aspect, half) if aspect >= 1 else (half, half / aspect)
    return (data.stencil_x * width, data.stencil_y * height), dimension, math.radians(data.stencil_angle)


def sync_stencil(context, brush, data):
    if data.brush_stencil is None:
        brush.texture = None
        return
    texture = bpy.data.textures.get(STENCIL_TEXTURE) or bpy.data.textures.new(STENCIL_TEXTURE, 'IMAGE')
    texture.image = data.brush_stencil
    brush.texture = texture
    brush.texture_slot.map_mode = 'STENCIL'
    region = view_region(context)
    if region is not None:
        position, dimension, angle = stencil_frame(data, region.width, region.height)
        brush.stencil_pos, brush.stencil_dimension = position, dimension
        brush.texture_slot.angle = angle


def sync_symmetry(context, data):
    obj = context.view_layer.objects.active if context.view_layer is not None else None
    if obj is not None and obj.type == 'MESH':
        obj.data.use_mirror_x, obj.data.use_mirror_y, obj.data.use_mirror_z = data.brush_mirror


def normal_color(data):
    tilt, angle = math.radians(data.brush_normal_tilt), math.radians(data.brush_normal_angle)
    vector = (math.sin(tilt) * math.cos(angle), math.sin(tilt) * math.sin(angle), math.cos(tilt))
    set_slot_value(data.brush_slots['normal'], tuple(value * .5 + .5 for value in vector))


def user_presets():
    return settings().setdefault('brush_presets', [])


def save_preset(data):
    names = {preset['name'] for preset in (*PRESETS, *user_presets())}
    number = 1
    while f'Custom {number}' in names:
        number += 1
    preset = dict(name=f'Custom {number}', alpha=bpy.path.abspath(data.brush_alpha.filepath) if data.brush_alpha is not None else '',
                  **{field: getattr(data, 'brush_' + field) for field in PRESET_FIELDS})
    user_presets().append(preset)
    save_settings()
    return preset['name']


def remove_preset(index):
    name = user_presets().pop(index)['name']
    save_settings()
    return name


def use_material(context, data, definition):
    for channel in set_channels(data):
        slot, values = data.brush_slots[channel.key], definition['slots'].get(channel.key)
        slot.enabled = values is not None or channel.key == 'base_color'
        slot.source, slot.image = 'VALUE', None
        if values is None:
            continue
        if values.get('source') == 'IMAGE':
            slot.source, slot.image = 'IMAGE', load_image(values['image'], CHANNEL[channel.key])
        value = values.get('value', channel.default)
        set_slot_value(slot, tuple(value) if isinstance(value, (list, tuple)) else (value,))
        if channel.key == 'base_color' and slot.source == 'VALUE':
            brush_source(context, 'color').color = tuple(float(part) for part in value[:3])
    data.brush_material = definition['name']


def clear_material(data):
    for slot in data.brush_slots:
        slot.source, slot.image = 'VALUE', None
    data.brush_material = ''


def load_alpha(name):
    path = Path(name) if Path(name).suffix else alpha_path(name)
    return bpy.data.images.load(str(path), check_existing=True)


def apply_preset(context, data, preset):
    for field in PRESET_FIELDS:
        setattr(data, 'brush_' + field, preset.get(field, PRESET_DEFAULTS.get(field)))
    alpha = preset['alpha']
    data.brush_alpha = (bpy.data.images.load(alpha, check_existing=True) if alpha.endswith('.png') else load_alpha(alpha)) if alpha else None
    data.brush_preset = preset['name']
    sync(context, data)
