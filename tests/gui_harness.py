import contextlib
import os
import time
from pathlib import Path
import bpy
from devil_painter import bakejob, editor
from tools.workspace import FAILURE_RECORD_VARIABLE

SENTINEL = 'F19'
POLL = 0.02
SETTLE_TIMEOUT = 20.0
WAIT_TIMEOUT = 60.0
SENTINEL_OPERATOR = 'WM_OT_devil_painter_test_sentinel'
_seen = dict(count=0, draws=0, x=0, y=0)
_failures = dict(expected=0, recorded=set())
FAILURE_RECORD = Path(os.environ[FAILURE_RECORD_VARIABLE]) if FAILURE_RECORD_VARIABLE in os.environ else None


def observe(event):
    if event.type == SENTINEL:
        if event.value == 'PRESS':
            _seen['count'] += 1
    elif event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} or event.type.endswith('MOUSE'):
        _seen['x'], _seen['y'] = event.mouse_x, event.mouse_y


class WM_OT_devil_painter_test_sentinel(bpy.types.Operator):
    bl_idname = 'wm.devil_painter_test_sentinel'
    bl_label = 'Devil Painter test sentinel'

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        observe(event)
        return {'RUNNING_MODAL'} if event.type == SENTINEL else {'PASS_THROUGH'}


def record_failure(failure):
    if id(failure) in _failures['recorded']:
        return
    _failures['recorded'].add(id(failure))
    if _failures['expected'] or FAILURE_RECORD is None:
        return
    with FAILURE_RECORD.open('a', encoding='utf-8') as record:
        record.write(f'{type(failure).__name__}: {failure}\n')


@contextlib.contextmanager
def expected_failures():
    _failures['expected'] += 1
    try:
        yield
    finally:
        _failures['expected'] -= 1


def instrument():
    cls = editor.DEVIL_PAINTER_OT_editor
    handle_event, draw_overlay, fail = cls.handle_event, cls.draw_overlay, cls.fail

    def observed_event(self, context, event):
        observe(event)
        return handle_event(self, context, event)

    def counted_draw(self):
        draw_overlay(self)
        if self.failure is not None:
            record_failure(self.failure)
        if not self._closed and bpy.context.area == self._area:
            _seen['draws'] += 1

    def recorded_fail(self, failure):
        record_failure(failure)
        return fail(self, failure)

    cls.handle_event, cls.draw_overlay, cls.fail = observed_event, counted_draw, recorded_fail
    if FAILURE_RECORD is not None:
        FAILURE_RECORD.write_text('', encoding='utf-8')


instrument()


def open_editor():
    active = editor._active
    return active if active is not None and not active._closed else None


def regions_hidden(active):
    try:
        space = active._area.spaces.active
    except ReferenceError:
        return True
    return space is None or not any(getattr(space, name) for name in active.saved_regions if not space.is_property_readonly(name))


def window_of(window):
    return window if window is not None else bpy.context.window_manager.windows[0]


def listening(window):
    if not hasattr(bpy.types, WM_OT_devil_painter_test_sentinel.__name__):
        bpy.utils.register_class(WM_OT_devil_painter_test_sentinel)
    if [operator.bl_idname for operator in window.modal_operators][:1] != [SENTINEL_OPERATOR]:
        with bpy.context.temp_override(window=window):
            bpy.ops.wm.devil_painter_test_sentinel('INVOKE_DEFAULT')


def wait_for(condition, message, timeout):
    started = time.monotonic()
    while not condition():
        if time.monotonic() - started > timeout:
            raise AssertionError(f'timed out after {timeout:.0f}s waiting for {message}')
        if open_editor() is not None:
            open_editor()._area.tag_redraw()
        yield POLL


def settle(window=None):
    window = window_of(window)
    listening(window)
    before = _seen['count']
    window.event_simulate(type=SENTINEL, value='PRESS', x=int(_seen['x']), y=int(_seen['y']))
    window.event_simulate(type=SENTINEL, value='RELEASE', x=int(_seen['x']), y=int(_seen['y']))
    yield from wait_for(lambda: _seen['count'] > before, 'Blender to handle the simulated input', SETTLE_TIMEOUT)
    if open_editor() is None:
        return
    yield from wait_for(lambda: open_editor() is None or not open_editor().stroke_pending, 'the brush stroke to finish', SETTLE_TIMEOUT)
    if open_editor() is None:
        return
    yield from wait_for(lambda: open_editor() is None or regions_hidden(open_editor()), 'Blender to finish hiding its regions', SETTLE_TIMEOUT)
    if open_editor() is None:
        return
    drawn = _seen['draws']
    open_editor()._area.tag_redraw()
    yield from wait_for(lambda: open_editor() is None or _seen['draws'] > drawn, 'the workspace to redraw', SETTLE_TIMEOUT)


def until(condition, message, timeout=WAIT_TIMEOUT):
    yield from wait_for(condition, message, timeout)
    yield from settle()


def bake_landed():
    yield from until(lambda: not bakejob.running(), 'the background bake to land')
