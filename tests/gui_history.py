import sys
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
from devil_painter import editor, history, strokes
from devil_painter.document import active_effect, active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, has, move, press, reveal, run_journey, settle, viewport


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


def stroke(window, x, y, dx=32, dy=16):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 9):
        move(window, x + dx * step / 8, y + dy * step / 8)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def alpha(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(-1, 4)[:, 3]


def body():
    return bpy.data.objects['Cube'].devil_painter.sets[0]


def journey():
    prepare_scratch()
    devil_painter.register()
    yield from settle()
    check(not hasattr(strokes, 'HISTORY_LIMIT') and not hasattr(strokes, 'undo') and not hasattr(strokes, 'redo'),
          'strokes no longer carries a separate pixel history stack')
    window, area, region = viewport()
    cube, front = build_mesh(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    point = screen_point(region, area, cube, front)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    paint_uid = active_layer(body()).uid
    check(has('PANEL_HISTORY') and has('HISTORY.0') and has('HISTORY.1') and control('HISTORY.1').active and history.cursor() == 1,
          'the History panel shows the initial state and the first step as active')

    stroke(window, *point)
    yield from settle()
    check(alpha(find_layer(body(), paint_uid).image).max() > .5 and history.cursor() == 2 and history.entries()[1].label == 'Paint stroke',
          'a paint stroke lands in the unified history')
    yield from reveal(window, region, 'HISTORY.2', 'HISTORY')
    check(control('HISTORY.2').active, 'the History panel highlights the paint stroke')

    click(window, region, 'ADD_FILL')
    yield from settle()
    fill_uid = active_layer(body()).uid
    check(history.cursor() == 3, 'adding a fill layer appends to the same history')

    click(window, region, 'ROW_' + fill_uid, kind='RIGHTMOUSE', fx=.6)
    yield from settle()
    click(window, region, 'ADD_MASK_BLACK')
    yield from settle()
    check(history.cursor() == 4, 'adding a mask appends to the same history')

    stroke(window, *point)
    yield from settle()
    check(alpha(find_layer(body(), fill_uid).mask).max() > .5 and history.cursor() == 5 and history.entries()[4].label == 'Mask stroke',
          'a mask stroke lands in the unified history instead of Blender-only undo')

    yield from reveal(window, region, 'ADD_FX_MASK')
    click(window, region, 'ADD_FX_MASK')
    yield from settle()
    click(window, region, 'NEW_FX.MASK.PAINT')
    yield from settle()
    fx_uid = active_effect(body()).uid
    check(history.cursor() == 6, 'adding a paint effect appends to the same history')

    stroke(window, *point)
    yield from settle()
    effect_image = lambda: next(item for item in find_layer(body(), fill_uid).effects if item.uid == fx_uid).image
    check(alpha(effect_image()).max() > .5 and history.cursor() == 7 and history.entries()[6].label == 'Paint effect stroke',
          'a paint effect stroke lands in the unified history')

    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    check(alpha(effect_image()).max() < .01 and history.cursor() == 6, 'Ctrl+Z undoes the paint effect stroke')
    yield from reveal(window, region, 'HISTORY.7', 'HISTORY')
    check(control('HISTORY.6').active and control('HISTORY.7').value == 0.0, 'the undone step stays listed as redoable in the History panel')

    press(window, 'Z', *middle, ctrl=True, shift=True)
    yield from settle()
    check(alpha(effect_image()).max() > .5 and history.cursor() == 7, 'Ctrl+Shift+Z redoes the paint effect stroke')

    yield from reveal(window, region, 'HISTORY.2', 'HISTORY')
    click(window, region, 'HISTORY.2')
    yield from settle()
    check(history.cursor() == 2 and len(body().layers) == 1 and alpha(find_layer(body(), paint_uid).image).max() > .5,
          'clicking an earlier step in the History panel jumps back across layers, masks, and effects in one click')

    yield from reveal(window, region, 'HISTORY.5', 'HISTORY')
    click(window, region, 'HISTORY.5')
    yield from settle()
    restored_fill = find_layer(body(), fill_uid)
    check(history.cursor() == 5 and restored_fill is not None and alpha(restored_fill.mask).max() > .5 and len(restored_fill.effects) == 0,
          'clicking a later step in the History panel jumps forward and restores the mask stroke')

    stroke(window, point[0] - 20, point[1] - 10, dx=24, dy=-12)
    yield from settle()
    check(len(history.entries()) == 6 and history.cursor() == 6 and history.entries()[5].label == 'Mask stroke',
          'painting from an earlier history state trims redoable steps and starts a new branch')

    before_line = alpha(find_layer(body(), fill_uid).mask).copy()
    press(window, 'LEFTMOUSE', point[0] + 24, point[1] - 16, shift=True)
    yield from settle()
    after_line = alpha(find_layer(body(), fill_uid).mask).copy()
    check(not numpy.array_equal(before_line, after_line) and history.cursor() == 7, 'a Shift-click stroke on a mask records a unified history step')
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    check(numpy.array_equal(alpha(find_layer(body(), fill_uid).mask), before_line) and history.cursor() == 6,
          'Ctrl+Z undoes the Shift-click mask stroke')
    press(window, 'Z', *middle, ctrl=True, shift=True)
    yield from settle()
    check(numpy.array_equal(alpha(find_layer(body(), fill_uid).mask), after_line) and history.cursor() == 7,
          'Ctrl+Shift+Z redoes the Shift-click mask stroke')

    saved_limit = bpy.context.preferences.edit.undo_steps
    try:
        bpy.context.preferences.edit.undo_steps = 4
        click(window, region, 'ADD_PAINT')
        yield from settle()
        check(len(history.entries()) == 4 and history.cursor() == 4, 'history depth follows Blender undo_steps instead of a separate cap')
    finally:
        bpy.context.preferences.edit.undo_steps = saved_limit

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI HISTORY CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI history test')
