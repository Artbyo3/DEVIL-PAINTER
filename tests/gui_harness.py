import contextlib
import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy
from mathutils import Quaternion
from devil_painter import bakejob, editor, shelf
from devil_painter.document import active_layer
from tools.workspace import FAILURE_RECORD_VARIABLE

TIMEOUT = 900
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


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def finish(code):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def viewport():
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return window, area, region


def move(window, x, y):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))


def press(window, kind, x, y, **modifiers):
    move(window, x, y)
    window.event_simulate(type=kind, value='PRESS', x=int(x), y=int(y), **modifiers)
    window.event_simulate(type=kind, value='RELEASE', x=int(x), y=int(y), **modifiers)


def control(key):
    return next(item for item in reversed(editor._active.workspace.controls) if item.key == key)


def has(key):
    return any(item.key == key for item in editor._active.workspace.controls)


def keys(prefix):
    return [item.key for item in editor._active.workspace.controls if item.key.startswith(prefix)]


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5, **modifiers):
    press(window, kind, *spot(region, key, fx, fy), **modifiers)


def type_text(window, text, x, y):
    for _ in range(editor._active.state.text.cursor):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


def shown(key):
    if not has(key):
        return False
    item = control(key)
    return item.clip is None or (item.clip.contains(item.rect.x, item.rect.y) and item.clip.contains(item.rect.x + item.rect.w, item.rect.top))


def reveal(window, region, key, panel='PROPERTIES'):
    for direction in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE'):
        for _ in range(30):
            if shown(key) or panel not in editor._active.workspace.scroll_areas:
                break
            viewport_rect = editor._active.workspace.scroll_areas[panel][0]
            x, y = region.x + viewport_rect.x + viewport_rect.w / 2, region.y + viewport_rect.y + viewport_rect.h / 2
            move(window, x, y)
            window.event_simulate(type=direction, value='PRESS', x=int(x), y=int(y))
            yield from settle()
            if direction == 'WHEELUPMOUSE' and editor._active.state.scroll.get(panel, 0.0) <= 0.0:
                break
        if shown(key):
            break
    check(shown(key), key + ' is in view')


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(-1, 4)


def png(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = pixels(image)
    bpy.data.images.remove(image)
    return values


def shelf_index(label):
    return next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == label)


def set_hex(window, region, opener, text):
    yield from reveal(window, region, opener)
    click(window, region, opener)
    yield from settle()
    click(window, region, 'COLOR_HEX')
    yield from settle()
    type_text(window, text, *spot(region, 'COLOR_HEX'))
    yield from settle()
    press(window, 'ESC', *spot(region, 'COLOR_HEX'))
    yield from settle()


def slide(window, region, key, fx):
    yield from reveal(window, region, key)
    click(window, region, key, fx=fx)
    yield from settle()


def close_cards(window, middle):
    if editor._active.state.popover is not None:
        press(window, 'ESC', *middle)
    yield from settle()


def new_layer(window, region, data):
    click(window, region, 'ADD_PAINT')
    yield from settle()
    return active_layer(data).uid


def nodes(data):
    return data.material.node_tree.nodes


def top_view(area):
    view = area.spaces.active.region_3d
    view.view_perspective = 'ORTHO'
    view.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    view.view_location = (0.0, 0.0, 0.0)
    view.view_distance = 3.0


def context_menu(window, region, uid, item):
    yield from reveal(window, region, 'ROW_' + uid, 'LAYERS')
    click(window, region, 'ROW_' + uid, kind='RIGHTMOUSE')
    yield from settle()
    check(has(item), f'the layer menu offers {item}')
    click(window, region, item)
    yield from settle()


def select_row(window, region, uid, **modifiers):
    yield from reveal(window, region, 'ROW_' + uid, 'LAYERS')
    click(window, region, 'ROW_' + uid, fx=.6, **modifiers)
    yield from settle()


def native_dab(window, region, point):
    x, y = round(region.x + point[0]), round(region.y + point[1])
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    return x - region.x, y - region.y


def run_journey(steps, label, timeout=TIMEOUT):
    started = time.time()

    def advance():
        try:
            if time.time() - started > timeout:
                raise AssertionError(f'{label} timed out')
            return next(steps)
        except Exception:
            traceback.print_exc()
            print('GUI TEST FAILED')
            finish(1)

    bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
