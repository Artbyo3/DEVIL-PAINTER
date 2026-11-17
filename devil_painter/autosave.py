import time
from pathlib import Path
import bpy
from .document import project_of
from .library import save_settings, settings

CHECK_SECONDS = 5.0
SUFFIX = '_autosave.blend'
MINUTE_RANGE = (1, 30)
_state = dict(last=time.monotonic(), path='', saved=0.0)


def minutes():
    return settings().get('autosave_minutes', 0)


def set_minutes(value):
    settings()['autosave_minutes'] = int(value)
    save_settings()
    _state['last'] = time.monotonic()


def target():
    if bpy.data.filepath:
        path = Path(bpy.data.filepath)
        return path.with_name(path.stem + SUFFIX)
    return Path(bpy.app.tempdir) / ('devil_painter' + SUFFIX)


def changed():
    return bpy.data.is_dirty or any(image.is_dirty for image in bpy.data.images)


def busy(manager):
    return any(operator.bl_idname.startswith('PAINT_OT') for window in manager.windows for operator in window.modal_operators)


def save_now():
    manager = bpy.context.window_manager
    path = target()
    with bpy.context.temp_override(window=manager.windows[0]):
        bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, check_existing=False)
    _state.update(last=time.monotonic(), path=str(path), saved=time.time())
    return path


def tick():
    manager = bpy.context.window_manager
    due = minutes() and time.monotonic() - _state['last'] >= minutes() * 60
    if due and manager is not None and manager.windows and not busy(manager) and changed() \
            and any(project_of(obj) is not None for obj in bpy.data.objects):
        save_now()
    return CHECK_SECONDS


def status():
    if not minutes():
        return 'Autosave is off'
    if not _state['saved']:
        return f'Next autosave within {minutes()} min'
    return f'Saved {time.strftime("%H:%M", time.localtime(_state["saved"]))} to {Path(_state["path"]).name}'


def register():
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=CHECK_SECONDS, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
