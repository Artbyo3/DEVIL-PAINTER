from contextlib import contextmanager
import bpy
import numpy
from . import compositing, tiles
from .compositing import rgba
from .document import set_channels

BAKE_MARGIN = 16
BAKE_SAMPLES = 1
DUMMY_SIZE = 8


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


def bake_pass(context, obj, project, wanted, prepare, bake_type='EMIT', samples=BAKE_SAMPLES, extra=(), margin=BAKE_MARGIN, **options):
    mesh = obj.data
    name = uv_name(obj, project)
    face_tiles = tiles.face_tiles(mesh, name)
    numbers = sorted({number for index in wanted for number in tiles.numbers(project.sets[index])})
    results = {}
    with bake_scene(context, obj, samples, extra):
        try:
            for number in numbers:
                created = []
                targets = {}
                try:
                    for index, data in enumerate(project.sets):
                        tree = data.material.node_tree
                        if index in wanted and number in tiles.numbers(data):
                            prepare(data)
                            image = target_image(f'DP Bake {data.name} {number}', data.resolution)
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
                        bpy.ops.object.bake(type=bake_type, margin=margin, use_clear=True, target='IMAGE_TEXTURES', uv_layer=layer, **options)
                    finally:
                        mesh.uv_layers.remove(mesh.uv_layers[layer])
                        mesh.uv_layers.active = mesh.uv_layers[name]
                    for index, image in targets.items():
                        results[(index, number)] = read_pixels(image)
                finally:
                    for image in created:
                        bpy.data.images.remove(image)
        finally:
            for data in project.sets:
                data.material[compositing.SIGNATURE_KEY] = ''
                compositing.sync(data)
    return results


def bake_channel(context, obj, project, wanted, channel, margin=BAKE_MARGIN):
    def prepare(data):
        if channel in set_channels(data):
            compositing.rebuild(data, solo=channel, raw=True)
            compositing.update_values(data)
        else:
            emission_tree(data.material.node_tree, rgba(channel.default))

    results = {}
    for key, pixels in bake_pass(context, obj, project, wanted, prepare, margin=margin).items():
        values = pixels[..., :3].copy()
        values[pixels[..., 3] < .5] = channel.default
        results[key] = values
    return results
