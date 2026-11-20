import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
import bpy
import numpy
from . import baking, meshmaps, tiles
from .thumbnails import leave_with_parent

BAKE_SCRIPT = '; '.join(('import sys', 'sys.dont_write_bytecode = True', 'import importlib', 'from pathlib import Path',
                         "root, name, folder = sys.argv[sys.argv.index('--') + 1:]", 'sys.path.insert(0, root)',
                         "importlib.import_module(name + '.document').register()",
                         "importlib.import_module(name + '.bakejob').serve(Path(folder))"))
SNAPSHOT = 'snapshot.blend'
_state = dict(job=None)


@dataclass
class Job:
    process: object
    folder: Path
    object_name: str
    set_index: int
    keys: list
    signature: str
    layout: list
    rebake: bool
    progress: dict = field(default_factory=dict)


def set_layout(project):
    return [[data.resolution, tiles.numbers(data)] for data in project.sets]


def painted_images(project):
    return [image for data in project.sets for image in tiles.every_image(data, [data.cage_map, data.skew_map])]


def device_settings(scene):
    preferences = bpy.context.preferences.addons['cycles'].preferences
    with baking.gpu_device(scene):
        return dict(type=preferences.compute_device_type, used=[device.id for device in preferences.devices if device.use])


def write_atomic(path, value):
    partial = path.with_suffix('.partial')
    partial.write_text(json.dumps(value), encoding='utf-8')
    os.replace(partial, path)


def running():
    return _state['job'] is not None


def start(context, obj, data, keys, rebake):
    project = obj.devil_painter
    folder = Path(tempfile.mkdtemp(prefix='devil_painter_bake_', dir=bpy.app.tempdir or None))
    painted = {}
    for number, image in enumerate(painted_images(project)):
        numpy.save(folder / f'painted.{number}.npy', baking.read_pixels(image))
        painted[image.name] = number
    set_index = next(index for index, item in enumerate(project.sets) if item == data)
    write_atomic(folder / 'job.json', dict(object=obj.name, set=set_index, keys=keys, devices=device_settings(context.scene), painted=painted))
    package = Path(__file__).resolve().parent
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / SNAPSHOT), copy=True, check_existing=False)
        process = subprocess.Popen([bpy.app.binary_path, '--background', '--factory-startup', str(folder / SNAPSHOT), '--python-expr', BAKE_SCRIPT,
                                    '--', str(package.parent), package.name, str(folder)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    except (OSError, RuntimeError):
        shutil.rmtree(folder, ignore_errors=True)
        raise
    _state['job'] = Job(process, folder, obj.name, set_index, keys, meshmaps.signature(context, obj, data), set_layout(project), rebake)


def status():
    job = _state['job']
    if job is None:
        return None
    done, total = job.progress.get('done', 0), len(job.keys)
    if not job.progress:
        return 0.0, 'Starting the bake'
    label = meshmaps.MESH_MAP[job.keys[min(done, total - 1)]].label
    tile = f' · tile {job.progress["tile"]}' if job.progress.get('tile') and len({number for _, numbers in job.layout for number in numbers}) > 1 else ''
    return done / total, f'{label} {min(done + 1, total)} of {total}{tile}'


def remove(job):
    job.process.stdin.close()
    job.process.wait()
    shutil.rmtree(job.folder, ignore_errors=True)


def poll():
    job = _state['job']
    if job is None:
        return None
    try:
        job.progress = json.loads((job.folder / 'progress.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    if job.process.poll() is None:
        return None
    _state['job'] = None
    try:
        outcome = json.loads((job.folder / 'result.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        outcome = dict(baked=[], error='The bake process stopped unexpectedly.')
    return job, outcome


def results(job, key, entries):
    return {(index, number): numpy.load(job.folder / f'{key}.{index}.{number}.npy') for index, number in entries}


def cancel():
    job = _state['job']
    if job is None:
        return False
    _state['job'] = None
    job.process.kill()
    remove(job)
    return True


def apply_devices(settings):
    preferences = bpy.context.preferences.addons['cycles'].preferences
    try:
        preferences.compute_device_type = settings['type']
    except TypeError:
        return
    preferences.refresh_devices()
    for device in preferences.devices:
        device.use = device.id in settings['used']


def bake_all(folder, job):
    apply_devices(job['devices'])
    for name, number in job['painted'].items():
        bpy.data.images[name].pixels.foreach_set(numpy.load(folder / f'painted.{number}.npy').ravel())
    context = bpy.context
    obj = bpy.data.objects[job['object']]
    project = obj.devil_painter
    progress = dict(done=0, tile=0)
    baking.TILE_BAKED.append(lambda number: write_atomic(folder / 'progress.json', dict(progress, tile=number)))
    write_atomic(folder / 'progress.json', progress)
    baked = []
    for key, pixels in meshmaps.baked_results(context, obj, project, list(range(len(project.sets))), job['keys'], project.sets[job['set']]):
        for (index, number), values in pixels.items():
            numpy.save(folder / f'{key}.{index}.{number}.npy', values)
        baked.append([key, [[index, number] for index, number in pixels]])
        progress.update(done=len(baked), tile=0)
        write_atomic(folder / 'progress.json', progress)
    return baked


def serve(folder):
    threading.Thread(target=leave_with_parent, daemon=True).start()
    try:
        outcome = dict(baked=bake_all(folder, json.loads((folder / 'job.json').read_text(encoding='utf-8'))), error='')
    except RuntimeError as error:
        outcome = dict(baked=[], error=str(error).strip())
    except Exception as error:
        outcome = dict(baked=[], error=f'{type(error).__name__}: {error}')
    write_atomic(folder / 'result.json', outcome)
    os._exit(0)
