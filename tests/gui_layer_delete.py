import sys
import time
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
from tests.gui_harness import check, control, finish, has, move, press, run_journey, settle, viewport


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
    return editor._active is not None and all(has('ROW_' + uid) for uid in uids(data)) and has('ADD_PAINT')


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


def current_set():
    return bpy.data.objects['Cube'].devil_painter.sets[0]


def undo_restores_pixels(window, region, point):
    click(window, region, 'ADD_PAINT')
    yield from settle()
    painted = active_layer(current_set()).uid
    stroke(window, *point)
    yield from settle()
    yield from layer_menu(window, region, painted, 'ADD_MASK_BLACK')
    stroke(window, *point)
    yield from settle()
    layer = find_layer(current_set(), painted)
    content, mask = alpha(layer.image).max(), alpha(layer.mask).max()
    check(content > .5 and mask > .5, f'the new layer holds a stroke and a painted mask ({content:.2f}, {mask:.2f})')
    before = uids(current_set())
    yield from layer_menu(window, region, painted, 'DELETE')
    check(painted not in uids(current_set()), 'the painted layer is deleted')
    click(window, region, 'UNDO')
    yield from settle()
    restored = find_layer(current_set(), painted)
    check(uids(current_set()) == before and restored is not None, f'undo brings the deleted layer back: {uids(current_set())}')
    check(restored.image is not None and abs(alpha(restored.image).max() - content) < 1e-3,
          f'undo restores the deleted layer with its painting (alpha {alpha(restored.image).max():.2f})')
    check(restored.mask is not None and abs(alpha(restored.mask).max() - mask) < 1e-3,
          f'undo restores the deleted layer with its painted mask (mask {alpha(restored.mask).max():.2f})')
    click(window, region, 'REDO')
    yield from settle()
    check(painted not in uids(current_set()), 'redo deletes the layer again')
    click(window, region, 'UNDO')
    yield from settle()
    restored = find_layer(current_set(), painted)
    check(restored is not None and alpha(restored.image).max() > .5 and alpha(restored.mask).max() > .5,
          'a second undo restores the painting and the mask again')
    yield from layer_menu(window, region, painted, 'DELETE')
    check(uids(current_set()) == [uid for uid in before if uid != painted], 'deleting it again leaves the stack as it was')
    yield from stays_responsive(window, region, current_set())

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

    folder_btn, delete_btn = control('ADD_FOLDER'), control('DELETE_LAYER')
    check(folder_btn.kind == 'CHIP' and folder_btn.icon == 'FOLDER' and folder_btn.rect.w == folder_btn.rect.h
          and folder_btn.tip == 'New folder above the selected layer',
          'the Layers header folder button is a square icon chip with its existing tooltip')
    check(delete_btn.kind == 'CHIP' and delete_btn.icon == 'DELETE' and delete_btn.rect.w == delete_btn.rect.h
          and delete_btn.tip == 'Delete Layer'
          and control('ADD_PAINT').rect.x < control('ADD_FILL').rect.x < folder_btn.rect.x < delete_btn.rect.x,
          'the Layers header delete button sits immediately to the right of the folder icon button')
    click(window, region, 'DELETE_LAYER')
    yield from settle()
    check(uids(body) == [] and active_layer(body) is None, 'clicking the header delete button on the only layer leaves an empty stack')
    check(has('LAYERS_EMPTY') and has('ADD_PAINT') and has('ADD_FILL') and 'PROPERTIES' not in editor._active.workspace.zones.rects,
          'the empty stack draws a Layers note and the add buttons, and hides Properties')
    yield from stays_responsive(window, region, body)
    click(window, region, 'DELETE_LAYER')
    yield from settle()
    check(uids(body) == [] and editor._active.message == 'There is no layer to delete.', 'deleting on an empty stack says there is nothing to delete')
    stroke(window, *front_point)
    yield from settle()
    check(uids(body) == [] and healthy(body), 'a brush stroke on an empty stack keeps the workspace running')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    first = body.active_uid
    check(uids(body) == [first] and active_layer(body).kind == 'PAINT' and not has('LAYERS_EMPTY'), 'adding a paint layer to the empty stack starts it again')
    click(window, region, 'ADD_FOLDER')
    yield from settle()
    header_folder = body.active_uid
    check(len(body.layers) == 2 and active_layer(body).kind == 'FOLDER', 'clicking the header folder icon button adds a folder')
    click(window, region, 'DELETE_LAYER')
    yield from settle()
    check(uids(body) == [first] and body.active_uid == first and header_folder not in uids(body),
          'clicking the header delete icon button deletes the active layer')

    trim = len(project.sets[1].layers)
    yield from layer_menu(window, region, first, 'MOVE_TO_SET.1')
    check(uids(body) == [] and len(project.sets[1].layers) == trim + 1, 'moving the only layer to another set leaves this set empty')
    click(window, region, 'UNDO')
    yield from settle()
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    body = project.sets[0]
    check(uids(body) == [first] and len(project.sets[1].layers) == trim, f'undo moves the layer back: {uids(body)}')
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
    yield from undo_restores_pixels(window, region, front_point)
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    body = project.sets[0]

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
    check(uids(body) == [] and has('LAYERS_EMPTY'), 'deleting the last remaining layer leaves an empty stack')
    yield from stays_responsive(window, region, body)
    click(window, region, 'ADD_FILL')
    yield from settle()
    check(len(body.layers) == 1 and active_layer(body).kind == 'FILL' and not has('LAYERS_EMPTY') and has('ROW_' + body.active_uid),
          'adding a layer to the empty stack starts a new stack')

    click(window, region, 'ADD_PAINT')
    yield from settle()
    other = next(uid for uid in uids(body) if uid != body.active_uid)
    click(window, region, 'ROW_' + other, ctrl=True)
    yield from settle()
    check(len(editor._active.chosen(body)) == 2, 'both layers are selected')
    yield from layer_menu(window, region, other, 'DELETE_SELECTED')
    check(uids(body) == [] and has('LAYERS_EMPTY'), 'deleting every selected layer at once empties the stack')
    yield from stays_responsive(window, region, body)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    click(window, region, 'ADD_PAINT')
    yield from settle()
    other = next(uid for uid in uids(body) if uid != body.active_uid)
    click(window, region, 'ROW_' + other, ctrl=True)
    yield from settle()
    trim = len(project.sets[1].layers)
    yield from layer_menu(window, region, other, 'MOVE_SELECTED.1')
    check(uids(body) == [] and len(project.sets[1].layers) == trim + 2, 'moving every selected layer to another set empties this set')
    yield from stays_responsive(window, region, body)

    kept = uids(body)
    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(editor._active is not None and uids(body) == kept and healthy(body), 'Devil Painter reopens on the same stack with a working workspace')
    check(has('LAYERS_EMPTY'), 'the reopened empty stack still shows its empty note')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    stroke(window, *front_point)
    yield from settle()
    check(alpha(active_layer(body).image).max() > .5, 'painting works after reopening on an empty stack and adding a layer')
    click(window, region, 'CLOSE')
    yield from settle()
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI LAYER DELETE CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI layer delete test')
