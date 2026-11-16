import hashlib
import json
import math
import bpy
import numpy
from .library import library_root
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
PRESET_FIELDS = ('hardness', 'flow', 'spacing', 'smoothing', 'jitter', 'random_angle')


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
    if preset['alpha']:
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


def sync(context, data):
    paint = context.tool_settings.image_paint
    brush = paint.brush
    if brush is None or brush.library is not None:
        return
    stroke = active_tool(context) in STROKE_TOOLS
    flow = data.brush_flow
    setattr(brush_source(context, 'strength'), 'strength', flow if stroke else data.brush_opacity)
    brush.use_accumulate = stroke and flow < 1
    brush.spacing = max(1, round(data.brush_spacing))
    if abs(brush.get('dp_hardness', -1.0) - data.brush_hardness) > 1e-4:
        set_hardness(brush, data.brush_hardness)
        brush['dp_hardness'] = data.brush_hardness
    brush.use_smooth_stroke = data.brush_smoothing > 0
    brush.smooth_stroke_radius = round(10 + 90 * data.brush_smoothing)
    brush.smooth_stroke_factor = .5 + .49 * data.brush_smoothing
    brush.jitter = data.brush_jitter
    brush.use_pressure_size = data.brush_pressure_size
    brush.use_pressure_strength = data.brush_pressure_opacity
    if data.brush_alpha is None:
        brush.mask_texture = None
    else:
        brush.mask_texture = alpha_texture(data.brush_alpha)
        slot = brush.mask_texture_slot
        slot.mask_map_mode = 'VIEW_PLANE'
        slot.use_random = data.brush_random_angle
        slot.random_angle = math.tau


def load_alpha(name):
    return bpy.data.images.load(str(alpha_path(name)), check_existing=True)


def apply_preset(context, data, preset):
    for field in PRESET_FIELDS:
        setattr(data, 'brush_' + field, preset[field])
    data.brush_alpha = load_alpha(preset['alpha']) if preset['alpha'] else None
    data.brush_preset = preset['name']
    sync(context, data)
