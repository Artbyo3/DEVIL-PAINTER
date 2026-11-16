from contextlib import contextmanager
from pathlib import Path
import bpy
import numpy
from . import compositing
from .blending import linear_to_srgb
from .document import set_channels

BAKE_MARGIN = 16
BAKE_SAMPLES = 1


@contextmanager
def bake_scene(context, obj, samples=BAKE_SAMPLES):
    scene = context.scene
    engine, saved_samples, mode = scene.render.engine, scene.cycles.samples, obj.mode
    selected = [item for item in context.view_layer.objects if item.select_get()]
    active = context.view_layer.objects.active
    try:
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for item in selected:
            item.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = samples
        yield
    finally:
        scene.render.engine, scene.cycles.samples = engine, saved_samples
        obj.select_set(False)
        for item in selected:
            item.select_set(True)
        context.view_layer.objects.active = active
        if obj.mode != mode:
            bpy.ops.object.mode_set(mode=mode)


def bake_emission(tree, size):
    image = bpy.data.images.new('DP Bake', size, size, alpha=True, float_buffer=True)
    image.generated_color = (0.0, 0.0, 0.0, 0.0)
    image.colorspace_settings.name = 'Non-Color'
    target = tree.nodes.new('ShaderNodeTexImage')
    target.image = image
    tree.nodes.active = target
    try:
        bpy.ops.object.bake(type='EMIT', margin=BAKE_MARGIN, use_clear=True, target='IMAGE_TEXTURES')
        pixels = numpy.empty(size * size * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape(size, size, 4)
    finally:
        tree.nodes.remove(target)
        bpy.data.images.remove(image)


def bake_channels(context, obj, data, channels):
    results = {}
    with bake_scene(context, obj):
        try:
            for channel in channels:
                compositing.rebuild(data, solo=channel, raw=True)
                compositing.update_values(data)
                pixels = bake_emission(data.material.node_tree, data.resolution)
                values = pixels[..., :3]
                values[pixels[..., 3] < .5] = channel.default
                results[channel.key] = values
        finally:
            compositing.sync(data)
    return results


def save_png(values, path, srgb):
    size = values.shape[0]
    rgba = numpy.ones((size, size, 4), dtype=numpy.float32)
    rgba[..., :3] = linear_to_srgb(values) if srgb else numpy.clip(values, 0, 1)
    image = bpy.data.images.new(path.stem, size, size, alpha=False)
    try:
        image.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'
        image.pixels.foreach_set(rgba.ravel())
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


def export(context, obj, data, directory, stem):
    channels = set_channels(data)
    results = bake_channels(context, obj, data, channels)
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for channel in channels:
        path = folder / f'{stem}_{channel.suffix}.png'
        save_png(results[channel.key], path, channel.srgb)
        written.append(path)
    return written
