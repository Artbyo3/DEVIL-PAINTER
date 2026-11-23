from dataclasses import dataclass
import bpy
from . import caches, strokes
from .document import texture_set

PREFIX = 'Devil Painter: '


@dataclass(frozen=True)
class Entry:
    label: str
    pixels: object = None
    buffered: bool = False


_entries = []
_state = dict(cursor=0, stepping=False, version=0)


def limit():
    return max(0, int(bpy.context.preferences.edit.undo_steps))


def entries():
    return tuple(_entries)


def cursor():
    return _state['cursor']


def version():
    return _state['version']


def clean_label(message):
    text = message.strip()
    if text.startswith(PREFIX):
        text = text.removeprefix(PREFIX).strip()
    text = text.rstrip('.')
    return text or 'Edit'


def record(label, pixels=None, buffered=False):
    del _entries[_state['cursor']:]
    _entries.append(Entry(clean_label(label), pixels, buffered))
    cap = limit()
    if cap > 0 and len(_entries) > cap:
        del _entries[:-cap]
    _state['cursor'] = len(_entries)
    _state['version'] += 1


def push(label, pixels=None):
    bpy.ops.ed.undo_push(message=PREFIX + label)
    record(label, pixels, buffered=False)


def attach(label, pixels=None, buffered=False):
    record(label, pixels, buffered=buffered)


def current_data():
    window = getattr(bpy.context, 'window', None)
    view_layer = window.view_layer if window is not None else bpy.context.view_layer
    return texture_set(view_layer.objects.active)


def apply_step(entry, redo):
    caches.touch()
    if entry.buffered:
        strokes.clear_buffer(current_data())
    if entry.pixels is not None:
        strokes.restore(entry.pixels.after if redo else entry.pixels.before)


def run_blender(redo):
    operator = bpy.ops.ed.redo if redo else bpy.ops.ed.undo
    if not operator.poll():
        return False
    _state['stepping'] = True
    try:
        result = operator()
    finally:
        _state['stepping'] = False
    return result == {'FINISHED'}


def step(redo):
    if not redo:
        if _state['cursor'] <= 0:
            if _entries:
                return False
            if run_blender(False):
                caches.touch()
                return True
            return False
        if not run_blender(False):
            return False
        _state['cursor'] -= 1
        apply_step(_entries[_state['cursor']], False)
        return True
    if _state['cursor'] >= len(_entries):
        if _entries:
            return False
        if run_blender(True):
            caches.touch()
            return True
        return False
    if not run_blender(True):
        return False
    entry = _entries[_state['cursor']]
    _state['cursor'] += 1
    apply_step(entry, True)
    return True


def jump(target):
    target = max(0, min(len(_entries), int(target)))
    moved = 0
    while _state['cursor'] > target:
        if not step(False):
            break
        moved += 1
    while _state['cursor'] < target:
        if not step(True):
            break
        moved += 1
    return moved


def sync_external(redo):
    if _state['stepping']:
        return False
    if not redo and _state['cursor'] > 0:
        _state['cursor'] -= 1
        apply_step(_entries[_state['cursor']], False)
        return True
    if redo and _state['cursor'] < len(_entries):
        entry = _entries[_state['cursor']]
        _state['cursor'] += 1
        apply_step(entry, True)
        return True
    return False


def forget():
    _entries.clear()
    _state['cursor'] = 0
    _state['stepping'] = False
    _state['version'] += 1
