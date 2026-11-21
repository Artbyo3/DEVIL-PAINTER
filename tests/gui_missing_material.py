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
from devil_painter.document import active_layer, find_layer
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


def click(window, region, key):
    rect = control(key).rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .6, region.y + rect.y + rect.h / 2)


def build_mesh(area):
    cube = bpy.data.objects['Cube']
    mesh = cube.data
    direction = area.spaces.active.region_3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    front = min(range(len(mesh.polygons)), key=lambda index: mesh.polygons[index].normal.dot(direction))
    mesh.materials.clear()
    mesh.materials.append(bpy.data.materials.new('Body'))
    mesh.update()
    return cube, front


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


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values


def alpha(image):
    return pixels(image).reshape(-1, 4)[:, 3].max()


def body():
    return bpy.data.objects['Cube'].devil_painter.sets[0]


def stack(data):
    return [(layer.uid, layer.name, layer.kind, layer.visible, layer.opacity) for layer in data.layers]


def journey():
    prepare_scratch()
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube, front = build_mesh(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    point = screen_point(region, area, cube, front)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    painted = active_layer(body()).uid
    stroke(window, *point)
    yield from settle()
    check(alpha(find_layer(body(), painted).image) > .5, 'the first stroke lands on the default paint layer')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    fresh = active_layer(body()).uid
    check(fresh != painted and alpha(find_layer(body(), fresh).image) < .01, 'a second, empty paint layer is active')
    before_stack = stack(body())
    before_pixels = pixels(find_layer(body(), painted).image).copy()
    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')

    name = body().material.name
    bpy.data.materials.remove(body().material)
    yield from settle()
    check(body().material is None and name not in bpy.data.materials and cube.material_slots[body().slot].material is None,
          f'the add-on material {name!r} is deleted and its slot is empty')

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    data = body()
    check(editor._active is not None and data.material is not None, 'reopening Devil Painter recreates the texture set material')
    check(cube.material_slots[data.slot].material == data.material, f'the recreated material {data.material.name!r} sits in the texture set slot')
    check(stack(data) == before_stack, f'the layer stack is unchanged after the repair: {stack(data)}')
    check(numpy.array_equal(pixels(find_layer(data, painted).image), before_pixels), 'the painted layer keeps its pixels after the repair')
    check(active_layer(data).uid == fresh, 'the empty paint layer is still active')

    stroke(window, *point)
    yield from settle()
    data = body()
    check(editor._active is not None, 'Devil Painter stays open after painting on the recreated material')
    check(alpha(find_layer(data, fresh).image) > .5, 'the stroke after the repair lands on the active layer')
    check(numpy.array_equal(pixels(find_layer(data, painted).image), before_pixels), 'the earlier painted layer is untouched by the new stroke')
    check(stack(data) == before_stack, 'the stroke adds no layers and changes none of the existing ones')

    click(window, region, 'UNDO')
    yield from settle()
    data = body()
    check(editor._active is not None and alpha(find_layer(data, fresh).image) < .01, 'undo removes the stroke, so the stroke recorded an undo step')
    check(numpy.array_equal(pixels(find_layer(data, painted).image), before_pixels), 'undo keeps the earlier painting')
    click(window, region, 'REDO')
    yield from settle()
    check(editor._active is not None and alpha(find_layer(body(), fresh).image) > .5, 'redo brings the stroke back')

    click(window, region, 'CLOSE')
    yield from settle()
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI MISSING MATERIAL CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI missing material test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
