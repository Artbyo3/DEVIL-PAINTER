import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Vector

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor
from devil_painter.actions import LAST_LAYER
from devil_painter.document import active_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import settle

TIMEOUT = 600
STARTED = time.time()


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


def click(window, region, key, kind='LEFTMOUSE', fx=.6, **modifiers):
    rect = control(key).rect
    press(window, kind, region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h / 2, **modifiers)


def build_mesh(area):
    cube = bpy.data.objects['Cube']
    mesh = cube.data
    direction = area.spaces.active.region_3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    facing = sorted(range(len(mesh.polygons)), key=lambda index: mesh.polygons[index].normal.dot(direction))
    mesh.materials.clear()
    mesh.materials.append(bpy.data.materials.new('Body'))
    mesh.materials.append(bpy.data.materials.new('Trim'))
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = 1 if index == facing[-1] else 0
    mesh.update()
    return cube, facing[0]


def screen_point(region, area, cube, face):
    center = cube.matrix_world @ cube.data.polygons[face].center
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, center)
    return region.x + point.x, region.y + point.y


def stroke(window, x, y):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 9):
        move(window, x + step * 4, y + step * 2)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 32), y=int(y + 16))


def alpha(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(-1, 4)[:, 3]


def uids(data):
    return [layer.uid for layer in data.layers]


def healthy(data):
    message = editor._active.message
    return (editor._active is not None and not message.startswith(('Render error', 'Editor error'))
            and all(has('ROW_' + uid) for uid in uids(data)) and has('ADD_PAINT'))


def layer_menu(window, region, uid, item):
    click(window, region, 'ROW_' + uid, kind='RIGHTMOUSE')
    yield from settle()
    check(has(item), f'the layer menu offers {item}')
    click(window, region, item)
    yield from settle()


def stays_responsive(window, region, data):
    middle = (region.x + region.width / 2, region.y + region.height / 2)
    started = time.perf_counter()
    for step in range(20):
        move(window, middle[0] + step * 3, middle[1])
        yield from settle()
    elapsed = time.perf_counter() - started
    check(healthy(data) and elapsed < 5.0, f'the workspace keeps drawing and answering input ({elapsed:.2f}s for 20 moves)')


def journey():
    prepare_scratch()
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube, front = build_mesh(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    front_point = screen_point(region, area, cube, front)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    project = cube.devil_painter
    body = project.sets[0]
    first = body.layers[0].uid
    check(len(body.layers) == 1 and body.active_uid == first, 'a new texture set starts with one default layer')

    yield from layer_menu(window, region, first, 'DELETE')
    check(uids(body) == [first] and body.active_uid == first and editor._active.message == LAST_LAYER,
          f'deleting the default layer first is refused with a plain message: {editor._active.message!r}')
    yield from stays_responsive(window, region, body)
    check(active_layer(body) is not None, 'the texture set still has an active layer')

    yield from layer_menu(window, region, first, 'MOVE_TO_SET.1')
    check(uids(body) == [first] and editor._active.message == LAST_LAYER, 'moving the only layer to another set is refused the same way')
    yield from stays_responsive(window, region, body)

    click(window, region, 'ADD_PAINT')
    yield from settle()
    check(len(body.layers) == 2, 'adding a layer after the refused delete works')
    second = next(uid for uid in uids(body) if uid != first)
    check(uids(body).index(first) == 0, 'the default layer is still at index 0')
    yield from layer_menu(window, region, first, 'DELETE')
    check(uids(body) == [second] and body.active_uid == second, 'with another layer present, the default layer at index 0 deletes')
    yield from stays_responsive(window, region, body)

    stroke(window, *front_point)
    yield from settle()
    check(alpha(active_layer(body).image).max() > .5, 'a brush stroke after deleting the first layer paints the remaining layer')

    click(window, region, 'ADD_PAINT')
    yield from settle()
    click(window, region, 'ADD_FILL')
    yield from settle()
    check(len(body.layers) == 3, 'two more layers are added')
    order = uids(body)
    yield from layer_menu(window, region, order[1], 'DELETE')
    check(uids(body) == [order[0], order[2]] and active_layer(body) is not None, 'deleting the middle layer leaves the other two and an active layer')
    yield from stays_responsive(window, region, body)
    yield from layer_menu(window, region, uids(body)[-1], 'DELETE')
    check(len(body.layers) == 1 and active_layer(body) is not None, 'deleting the last layer of the list leaves one active layer')
    yield from stays_responsive(window, region, body)
    remaining = uids(body)
    yield from layer_menu(window, region, remaining[0], 'DELETE')
    check(uids(body) == remaining and editor._active.message == LAST_LAYER, 'deleting the last remaining layer is refused')
    yield from stays_responsive(window, region, body)

    click(window, region, 'ADD_PAINT')
    yield from settle()
    click(window, region, 'ROW_' + remaining[0], ctrl=True)
    yield from settle()
    check(len(editor._active.chosen(body)) == 2, 'both layers are selected')
    yield from layer_menu(window, region, remaining[0], 'DELETE_SELECTED')
    check(len(body.layers) == 2 and editor._active.message == LAST_LAYER, 'deleting every selected layer at once is refused without removing any')
    yield from stays_responsive(window, region, body)
    other = next(uid for uid in uids(body) if uid != body.active_uid)
    click(window, region, 'ROW_' + other, ctrl=True)
    yield from settle()
    check(len(editor._active.chosen(body)) == 2, 'both layers are selected again')
    yield from layer_menu(window, region, other, 'MOVE_SELECTED.1')
    check(len(body.layers) == 1 and len(project.sets[1].layers) == 2 and editor._active.message == LAST_LAYER,
          'moving every selected layer to another set keeps one layer behind')
    yield from stays_responsive(window, region, body)

    kept = uids(body)
    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(editor._active is not None and uids(body) == kept and healthy(body), 'Devil Painter reopens on the same stack with a working workspace')
    before = alpha(active_layer(body).image).max()
    stroke(window, *front_point)
    yield from settle()
    check(alpha(active_layer(body).image).max() > max(before, .5), 'painting works after reopening')
    click(window, region, 'CLOSE')
    yield from settle()
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI LAYER DELETE CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI layer delete test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
