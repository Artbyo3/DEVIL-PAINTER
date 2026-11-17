import hashlib
import json
import itertools
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import bmesh
import bpy
import gpu
import imbuf
import numpy
from .blending import CHANNELS, srgb_to_linear
from .compositing import Build, Sampler, build_tree, write_values
from .document import add_slots
from .library import apply_definition, library_root

SIZE = 96
PREVIEW_SIZE = 128
UPLOAD_SECONDS = .006
SAMPLES = 12
WORLD_FILE = 'city.exr'
WORLD_STRENGTH = .7
JOB_POLL = .1
RENDER_SCRIPT = '; '.join(('import sys', 'sys.dont_write_bytecode = True', 'import importlib', 'from pathlib import Path',
                           "root, name, folder = sys.argv[sys.argv.index('--') + 1:]", 'sys.path.insert(0, root)',
                           "importlib.import_module(name + '.document').register()",
                           "importlib.import_module(name + '.thumbnails').serve(Path(folder))"))
_state = dict(worker=None, depth=0, process=None)
_lock = threading.Lock()
_idle = threading.Event()
_idle.set()
_order = itertools.count()
_textures = {}
_wanted = {}
_busy = set()
_ready = []
_queue = {}
_jobs = {}
_failed = set()
_owned = {}


@contextmanager
def foreground():
    _state['depth'] += 1
    _idle.clear()
    try:
        yield
    finally:
        _state['depth'] -= 1
        if not _state['depth']:
            _idle.set()


def begin_frame():
    with _lock:
        ready = list(_ready)
        _ready.clear()
    deadline = time.perf_counter() + UPLOAD_SECONDS
    for index, (key, pixels) in enumerate(ready):
        if time.perf_counter() > deadline:
            with _lock:
                _ready.extend(ready[index:])
            break
        _textures[key] = None if pixels is None else upload(pixels)


def waiting():
    with _lock:
        return bool(_queue) or bool(_jobs) or bool(_wanted) or bool(_ready) or bool(_busy)


def upload(pixels):
    height, width = pixels.shape[:2]
    pixels = pixels.reshape(-1, 4)
    pixels[:, :3] = srgb_to_linear(pixels[:, :3])
    return gpu.types.GPUTexture((width, height), format='RGBA16F', data=gpu.types.Buffer('FLOAT', pixels.size, pixels.ravel()))


def preview_cache(path):
    stamp = path.stat()
    digest = hashlib.sha1(f'{path.resolve()}|{stamp.st_mtime_ns}|{stamp.st_size}'.encode('utf-8')).hexdigest()[:24]
    return library_root() / 'preview_cache' / f'{digest}.png'


def decode(source, cached):
    if cached.is_file():
        buffer = imbuf.load(str(cached))
    else:
        buffer = imbuf.load(str(source))
        width, height = buffer.size
        scale = PREVIEW_SIZE / max(width, height, 1)
        if scale < 1:
            buffer.resize((max(1, round(width * scale)), max(1, round(height * scale))), method='BILINEAR')
        buffer.convert_buffer_type('BYTE')
        cached.parent.mkdir(parents=True, exist_ok=True)
        buffer.file_type = 'PNG'
        imbuf.write(buffer, filepath=str(cached))
    buffer.convert_buffer_type('BYTE')
    width, height = buffer.size
    with buffer.with_buffer() as view:
        values = numpy.asarray(view, dtype=numpy.uint8).reshape(height, width, -1)
    buffer.free()
    pixels = numpy.ones((height, width, 4), dtype=numpy.float32)
    channels = values.shape[2]
    pixels[..., :3] = (values[..., :3] if channels >= 3 else values[..., :1]) / 255.0
    if channels in (2, 4):
        pixels[..., 3] = values[..., -1] / 255.0
    return pixels


def work():
    while True:
        with _lock:
            if not _wanted:
                _state['worker'] = None
                return
            key = max(_wanted, key=lambda name: _wanted[name][0])
            _, source, cached = _wanted.pop(key)
            _busy.add(key)
        _idle.wait()
        try:
            pixels = decode(source, cached)
        except Exception:
            pixels = None
        with _lock:
            _busy.discard(key)
            _ready.append((key, pixels))


def file_texture(path):
    key = str(path)
    if key in _textures:
        return _textures[key]
    with _lock:
        if key in _wanted:
            _wanted[key] = (next(_order), *_wanted[key][1:])
            return None
        if key in _busy or any(name == key for name, _ in _ready):
            return None
    try:
        source = Path(path)
        cached = preview_cache(source)
    except OSError:
        _textures[key] = None
        return None
    with _lock:
        _wanted[key] = (next(_order), source, cached)
        if _state['worker'] is None:
            _state['worker'] = threading.Thread(target=work, name='Devil Painter previews', daemon=True)
            _state['worker'].start()
    return None


def cache_path(definition):
    digest = hashlib.sha1(json.dumps(definition, sort_keys=True).encode('utf-8')).hexdigest()[:24]
    return library_root() / 'thumbnails' / f'{digest}.png'


def material_texture(definition, owner=''):
    path = cache_path(definition)
    if path.is_file():
        texture = file_texture(path)
        if owner and texture is not None:
            _owned[owner] = texture
        return texture if texture is not None else _owned.get(owner)
    if path not in _failed:
        _queue[owner or str(path)] = (path, definition)
    return _owned.get(owner)


def preview_mesh(rounded_cube):
    mesh = bpy.data.meshes.new('DP Thumbnail')
    shape = bmesh.new()
    shape.loops.layers.uv.new('UVMap')
    if rounded_cube:
        bmesh.ops.create_cube(shape, size=1.25, calc_uvs=True)
        bmesh.ops.bevel(shape, geom=list(shape.verts) + list(shape.edges), offset=.12, segments=3, affect='EDGES')
    else:
        bmesh.ops.create_uvsphere(shape, u_segments=48, v_segments=24, radius=1.0, calc_uvs=True)
        for face in shape.faces:
            face.smooth = True
    shape.to_mesh(mesh)
    shape.free()
    return mesh


def render(path, definition):
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.data.scenes.new('DP Thumbnail')
    definitions = [item for item in definition.get('layers', [definition]) if item.get('kind', 'FILL') == 'FILL']
    mesh = preview_mesh(any('generator' in item for item in definitions))
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
        layers = sphere.devil_painter.sets.add().layers
        for index, item in enumerate(definitions):
            layer = layers.add()
            layer.uid, layer.kind = f'T{index}', 'FILL'
            add_slots(layer)
            apply_definition(layer, item)
            for number, entry in enumerate(item.get('effects', ())):
                effect = layer.effects.add()
                effect.uid = f'T{index}E{number}'
                for field, value in entry.items():
                    setattr(effect, field, value)
        tree = material.node_tree
        build_tree(Build(tree.nodes, tree.links, Sampler(tree.nodes, tree.links, [1001], lambda image, number: image, ''), live=True, size=2.0),
                   CHANNELS, list(layers))
        write_values(material.node_tree.nodes, CHANNELS, list(layers))
        if any('generator' in item for item in definitions):
            sphere.rotation_euler = (.5, 0.0, .7)
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


def job_folder():
    folder = library_root() / 'thumbnail_jobs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def renderer():
    process = _state['process']
    if process is not None and process.poll() is None:
        return
    package = Path(__file__).resolve().parent
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == 'win32' else 0
    _state['process'] = subprocess.Popen([bpy.app.binary_path, '--background', '--factory-startup', '--python-expr', RENDER_SCRIPT, '--',
                                          str(package.parent), package.name, str(job_folder())],
                                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def dispatch():
    for key, (path, definition) in _queue.items():
        if key in _jobs and _jobs[key][1] == path:
            continue
        if key in _jobs:
            _jobs[key][0].unlink(missing_ok=True)
        job = job_folder() / f'{path.stem}.json'
        partial = job.with_suffix('.partial')
        partial.write_text(json.dumps(dict(path=str(path), definition=definition)), encoding='utf-8')
        os.replace(partial, job)
        _jobs[key] = (job, path)
    _queue.clear()
    for key, (job, path) in list(_jobs.items()):
        if path.is_file():
            del _jobs[key]
        elif not job.exists():
            _failed.add(path)
            del _jobs[key]
    if _jobs:
        renderer()


def newest_job(folder):
    stamped = []
    for job in folder.glob('*.json'):
        try:
            stamped.append((job.stat().st_mtime_ns, job))
        except OSError:
            continue
    return max(stamped)[1] if stamped else None


def leave_with_parent():
    sys.stdin.read()
    os._exit(0)


def serve(folder):
    if hasattr(os, 'nice'):
        os.nice(10)
    threading.Thread(target=leave_with_parent, daemon=True).start()
    while True:
        job = newest_job(folder)
        if job is None:
            time.sleep(JOB_POLL)
            continue
        try:
            entry = json.loads(job.read_text(encoding='utf-8'))
            job.unlink()
        except (OSError, ValueError):
            continue
        target = Path(entry['path'])
        partial = target.with_name(target.stem + '.partial.png')
        try:
            render(partial, entry['definition'])
            os.replace(partial, target)
        except Exception:
            partial.unlink(missing_ok=True)


def release():
    with _lock:
        _wanted.clear()
        _ready.clear()
        _busy.clear()
    _textures.clear()
    _queue.clear()
    _jobs.clear()
    _failed.clear()
    _owned.clear()
    process = _state['process']
    _state['process'] = None
    if process is not None and process.poll() is None:
        process.stdin.close()
