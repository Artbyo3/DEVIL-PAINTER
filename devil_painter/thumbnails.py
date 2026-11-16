import hashlib
import json
from pathlib import Path
import bmesh
import bpy
import bpy.utils.previews
import gpu
import numpy
from .blending import CHANNELS, srgb_to_linear
from .compositing import build_tree, write_values
from .document import add_slots
from .library import apply_definition, library_root

SIZE = 96
SAMPLES = 12
LOAD_BUDGET = 4
WORLD_FILE = 'city.exr'
WORLD_STRENGTH = .7
_state = dict(collection=None, budget=LOAD_BUDGET, starved=False)
_textures = {}
_queue = {}


def begin_frame():
    _state['budget'] = LOAD_BUDGET
    _state['starved'] = False


def waiting():
    return bool(_queue) or _state['starved']


def collection():
    if _state['collection'] is None:
        _state['collection'] = bpy.utils.previews.new()
    return _state['collection']


def upload(preview):
    width, height = preview.image_size
    if not width or not height:
        return None
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    preview.image_pixels_float.foreach_get(pixels)
    pixels = pixels.reshape(-1, 4)
    pixels[:, :3] = srgb_to_linear(pixels[:, :3])
    return gpu.types.GPUTexture((width, height), format='RGBA16F', data=gpu.types.Buffer('FLOAT', pixels.size, pixels.ravel()))


def file_texture(path):
    key = str(path)
    if key in _textures:
        return _textures[key]
    if _state['budget'] <= 0:
        _state['starved'] = True
        return None
    _state['budget'] -= 1
    previews = collection()
    preview = previews[key] if key in previews else previews.load(key, key, 'IMAGE')
    _textures[key] = upload(preview)
    return _textures[key]


def cache_path(definition):
    digest = hashlib.sha1(json.dumps(definition, sort_keys=True).encode('utf-8')).hexdigest()[:24]
    return library_root() / 'thumbnails' / f'{digest}.png'


def material_texture(definition):
    path = cache_path(definition)
    if path.is_file():
        return file_texture(path)
    _queue.setdefault(path, definition)
    return None


def preview_sphere():
    mesh = bpy.data.meshes.new('DP Thumbnail')
    shape = bmesh.new()
    shape.loops.layers.uv.new('UVMap')
    bmesh.ops.create_uvsphere(shape, u_segments=48, v_segments=24, radius=1.0, calc_uvs=True)
    for face in shape.faces:
        face.smooth = True
    shape.to_mesh(mesh)
    shape.free()
    return mesh


def render(path, definition):
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.data.scenes.new('DP Thumbnail')
    mesh = preview_sphere()
    sphere = bpy.data.objects.new('DP Thumbnail', mesh)
    camera_data = bpy.data.cameras.new('DP Thumbnail')
    camera = bpy.data.objects.new('DP Thumbnail Camera', camera_data)
    material = bpy.data.materials.new('DP Thumbnail')
    world = bpy.data.worlds.new('DP Thumbnail')
    created = [scene, sphere, mesh, camera, camera_data, material, world]
    try:
        scene.collection.objects.link(sphere)
        scene.collection.objects.link(camera)
        mesh.materials.append(material)
        layer = sphere.devil_painter.layers.add()
        layer.uid, layer.kind = 'T', 'FILL'
        add_slots(layer)
        apply_definition(layer, definition)
        build_tree(material.node_tree, CHANNELS, [layer])
        write_values(material.node_tree.nodes, CHANNELS, [layer])
        camera_data.type, camera_data.ortho_scale = 'ORTHO', 2.1
        camera.location, camera.rotation_euler = (0.0, -5.0, 0.0), (1.5708, 0.0, 0.0)
        scene.camera = camera
        environment = world.node_tree.nodes.new('ShaderNodeTexEnvironment')
        environment.image = bpy.data.images.load(str(Path(bpy.utils.system_resource('DATAFILES', path='studiolights/world')) / WORLD_FILE))
        created.append(environment.image)
        background = next(node for node in world.node_tree.nodes if node.type == 'BACKGROUND')
        background.inputs['Strength'].default_value = WORLD_STRENGTH
        world.node_tree.links.new(environment.outputs['Color'], background.inputs['Color'])
        scene.view_settings.view_transform = 'Standard'
        scene.world = world
        render_settings = scene.render
        render_settings.engine = 'CYCLES'
        scene.cycles.samples = SAMPLES
        scene.cycles.use_denoising = False
        render_settings.resolution_x = render_settings.resolution_y = SIZE
        render_settings.film_transparent = True
        render_settings.image_settings.file_format = 'PNG'
        render_settings.image_settings.color_mode = 'RGBA'
        render_settings.filepath = str(path)
        bpy.ops.render.render(write_still=True, scene=scene.name)
    finally:
        bpy.data.batch_remove(created)


def render_next():
    if not _queue:
        return False
    path = next(iter(_queue))
    definition = _queue.pop(path)
    render(Path(path), definition)
    return True


def release():
    if _state['collection'] is not None:
        bpy.utils.previews.remove(_state['collection'])
        _state['collection'] = None
    _textures.clear()
    _queue.clear()
