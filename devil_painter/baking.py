from contextlib import contextmanager
import bpy
import numpy
from . import caches, compositing, tiles
from .compositing import rgba
from .document import set_channels

BAKE_MARGIN = 16
BELOW_MARGIN = 64
BAKE_SAMPLES = 1
DUMMY_SIZE = 8
GPU_BACKENDS = ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL')
NEIGHBORS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
TILE_BAKED = []


def usable_gpu(preferences):
    return any(device.use and device.type == preferences.compute_device_type for device in preferences.devices)


@contextmanager
def gpu_device(scene):
    preferences = bpy.context.preferences.addons['cycles'].preferences
    saved_type, saved_device = preferences.compute_device_type, scene.cycles.device
    try:
        for backend in GPU_BACKENDS if saved_type == 'NONE' else ():
            try:
                preferences.compute_device_type = backend
            except TypeError:
                continue
            preferences.refresh_devices()
            if usable_gpu(preferences):
                break
        else:
            preferences.compute_device_type = saved_type
        if preferences.compute_device_type != 'NONE' and usable_gpu(preferences):
            scene.cycles.device = 'GPU'
        yield
    finally:
        preferences.compute_device_type, scene.cycles.device = saved_type, saved_device


@contextmanager
def bake_scene(context, obj, samples=BAKE_SAMPLES, extra=()):
    scene = context.scene
    engine, saved_samples, mode = scene.render.engine, scene.cycles.samples, obj.mode
    selected = [item for item in context.view_layer.objects if item.select_get()]
    active = context.view_layer.objects.active
    hidden = [(item, item.hide_get(), item.hide_render) for item in extra]
    try:
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for item in selected:
            item.select_set(False)
        for item in extra:
            item.hide_set(False)
            item.hide_render = False
            item.select_set(True)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = samples
        with gpu_device(scene):
            yield
    finally:
        scene.render.engine, scene.cycles.samples = engine, saved_samples
        for item in (obj, *extra):
            item.select_set(False)
        for item, hide, hide_render in hidden:
            item.hide_set(hide)
            item.hide_render = hide_render
        for item in selected:
            item.select_set(True)
        context.view_layer.objects.active = active
        if obj.mode != mode:
            bpy.ops.object.mode_set(mode=mode)


def emission_tree(tree, color):
    tree.nodes.clear()
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    emission = tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = color
    tree.links.new(emission.outputs[0], output.inputs['Surface'])


def target_image(name, size):
    image = bpy.data.images.new(name, size, size, alpha=True, float_buffer=True)
    image.generated_color = (0.0, 0.0, 0.0, 0.0)
    image.colorspace_settings.name = 'Non-Color'
    return image


def read_pixels(image):
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)


def uv_name(obj, project):
    return project.uv_map if project.uv_map in obj.data.uv_layers else obj.data.uv_layers.active.name


def downsampled(pixels, scale):
    height, width, depth = pixels.shape
    return pixels.reshape(height // scale, scale, width // scale, scale, depth).mean(axis=(1, 3), dtype=numpy.float32)


def resized(values, shape):
    if values.shape[:2] == shape:
        return values
    source_h, source_w = values.shape[:2]
    target_h, target_w = shape
    if source_h % target_h == 0 and source_w % target_w == 0:
        return values.reshape(target_h, source_h // target_h, target_w, source_w // target_w, *values.shape[2:]).mean(axis=(1, 3), dtype=numpy.float32)
    ys = numpy.linspace(0, source_h - 1, target_h, dtype=numpy.float32)
    xs = numpy.linspace(0, source_w - 1, target_w, dtype=numpy.float32)
    y0, x0 = numpy.floor(ys).astype(numpy.int32), numpy.floor(xs).astype(numpy.int32)
    y1, x1 = numpy.minimum(y0 + 1, source_h - 1), numpy.minimum(x0 + 1, source_w - 1)
    wy, wx = (ys - y0)[:, None], (xs - x0)[None, :]
    if values.ndim == 3:
        wy, wx = wy[..., None], wx[..., None]
    top = values[y0[:, None], x0[None, :]] * (1 - wx) + values[y0[:, None], x1[None, :]] * wx
    bottom = values[y1[:, None], x0[None, :]] * (1 - wx) + values[y1[:, None], x1[None, :]] * wx
    return (top * (1 - wy) + bottom * wy).astype(numpy.float32)


def bake_tiles(obj, project, wanted, prepare, bake_type, margin, scale=1, resolution=0, **options):
    mesh = obj.data
    name = uv_name(obj, project)
    face_tiles = tiles.face_tiles(mesh, name)
    numbers = sorted({number for index in wanted for number in tiles.numbers(project.sets[index])})
    results = {}
    for number in numbers:
        created = []
        targets = {}
        try:
            for index, data in enumerate(project.sets):
                tree = data.material.node_tree
                if index in wanted and number in tiles.numbers(data):
                    prepare(data)
                    size = resolution or data.resolution
                    image = target_image(f'DP Bake {data.name} {number}', size * scale)
                    targets[index] = image
                else:
                    emission_tree(tree, (0.0, 0.0, 0.0, 1.0))
                    image = target_image('DP Bake unused', DUMMY_SIZE)
                created.append(image)
                node = tree.nodes.new('ShaderNodeTexImage')
                node.image = image
                node.select = True
                tree.nodes.active = node
            layer = tiles.shifted_uv(mesh, name, face_tiles == number, number)
            try:
                bpy.ops.object.bake(type=bake_type, margin=margin * scale, use_clear=True, target='IMAGE_TEXTURES', uv_layer=layer, **options)
            finally:
                mesh.uv_layers.remove(mesh.uv_layers[layer])
                mesh.uv_layers.active = mesh.uv_layers[name]
            for index, image in targets.items():
                results[(index, number)] = downsampled(read_pixels(image), scale)
            for listener in TILE_BAKED:
                listener(number)
        finally:
            for image in created:
                bpy.data.images.remove(image)
    return results


def resync(project):
    for data in project.sets:
        data.material[compositing.SIGNATURE_KEY] = ''
        compositing.sync(data)


def bake_pass(context, obj, project, wanted, prepare, bake_type='EMIT', samples=BAKE_SAMPLES, extra=(), margin=BAKE_MARGIN, scale=1, resolution=0, **options):
    refresh_below(context, obj, project)
    with bake_scene(context, obj, samples, extra):
        try:
            return bake_tiles(obj, project, wanted, prepare, bake_type, margin, scale, resolution, **options)
        finally:
            resync(project)


def stale_below(project):
    stale = []
    for index, data in enumerate(project.sets):
        if compositing.has_positional(data):
            stamp = compositing.below_stamp(data)
            if not caches.fresh(data, stamp):
                stale.append((index, stamp))
    return stale


def refresh_below(context, obj, project):
    stale = stale_below(project)
    if not stale:
        return False
    with bake_scene(context, obj):
        try:
            for index, stamp in stale:
                data = project.sets[index]
                build, emission = compositing.below_build(data)
                for name in list(build.below):
                    def prepare(item, name=name):
                        compositing.emit_below(build, emission, name)
                    for (_, number), pixels in bake_tiles(obj, project, [index], prepare, 'EMIT', BELOW_MARGIN).items():
                        caches.write(caches.tile(data, name, number), pixels)
                caches.mark(data, stamp)
        finally:
            resync(project)
    return True


def diffuse(values, outside, rings):
    height, width = outside.shape
    filled = numpy.pad(~outside, 1)
    fillable = numpy.pad(outside, 1)
    colors = numpy.pad(values, ((1, 1), (1, 1), (0, 0)))
    flat_filled, flat_fillable, flat_colors = filled.ravel(), fillable.ravel(), colors.reshape(-1, values.shape[-1])
    offsets = numpy.array([row * (width + 2) + column for row, column in NEIGHBORS])
    touching = numpy.zeros_like(filled)
    for row, column in NEIGHBORS:
        touching[1:-1, 1:-1] |= filled[1 + row:height + 1 + row, 1 + column:width + 1 + column]
    ring = numpy.flatnonzero(touching & fillable)
    for _ in range(rings):
        if not ring.size:
            break
        around = ring[:, None] + offsets
        weights = flat_filled[around]
        flat_colors[ring] = (flat_colors[around] * weights[..., None]).sum(axis=1) / weights.sum(axis=1, keepdims=True)
        flat_filled[ring] = True
        flat_fillable[ring] = False
        ring = numpy.unique(around)
        ring = ring[flat_fillable[ring]]
    return colors[1:-1, 1:-1], ~filled[1:-1, 1:-1]


def bake_channel(context, obj, project, wanted, channel, margin=BAKE_MARGIN, style='DILATION'):
    def prepare(data):
        if channel in set_channels(data):
            compositing.rebuild(data, solo=channel, raw=True)
            compositing.update_values(data, raw=True)
        else:
            emission_tree(data.material.node_tree, rgba(channel.default))

    results = {}
    for key, pixels in bake_pass(context, obj, project, wanted, prepare, margin=margin if style == 'DILATION' else 0).items():
        values = pixels[..., :3].copy()
        outside = pixels[..., 3] < .5
        if style == 'DIFFUSION':
            values, outside = diffuse(values, outside, margin)
        values[outside] = channel.default
        results[key] = values
    return results
