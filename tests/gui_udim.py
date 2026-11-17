import math
import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Euler, Vector

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, tiles
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch

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


def keys(prefix):
    return [item.key for item in editor._active.workspace.controls if item.key.startswith(prefix)]


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5, **modifiers):
    press(window, kind, *spot(region, key, fx, fy), **modifiers)


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
            yield 0.1
            if direction == 'WHEELUPMOUSE' and editor._active.state.scroll.get(panel, 0.0) <= 0.0:
                break
        if shown(key):
            break
    check(shown(key), key + ' is in view')


def type_text(window, text, x, y):
    for _ in range(160):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


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


def set_hex(window, region, opener, text):
    yield from reveal(window, region, opener)
    click(window, region, opener)
    yield 0.3
    click(window, region, 'COLOR_HEX')
    yield 0.2
    type_text(window, text, *spot(region, 'COLOR_HEX'))
    yield 0.4
    press(window, 'ESC', *spot(region, 'COLOR_HEX'))
    yield 0.3


def build_plates():
    import bmesh
    mesh = bpy.data.meshes.new('Plates')
    shape = bmesh.new()
    uv = shape.loops.layers.uv.new('UVMap')
    verts = [shape.verts.new((x, y, 0.0)) for y in (-1.0, 1.0) for x in (-2.0, 0.0, 2.0)]
    for index in range(2):
        face = shape.faces.new([verts[index], verts[index + 1], verts[index + 4], verts[index + 3]])
        for loop, (u, v) in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uv].uv = (u + index, v)
    shape.to_mesh(mesh)
    shape.free()
    mesh.materials.append(bpy.data.materials.new('Plates'))
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item)
    plates = bpy.data.objects.new('Plates', mesh)
    bpy.context.scene.collection.objects.link(plates)
    bpy.context.view_layer.objects.active = plates
    plates.select_set(True)
    return plates


def screen(region, area, obj, point):
    spot = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, obj.matrix_world @ Vector(point))
    return region.x + spot.x, region.y + spot.y


def drag(window, start, end, count=16):
    move(window, *start)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(start[0]), y=int(start[1]))
    for step in range(1, count + 1):
        move(window, start[0] + (end[0] - start[0]) * step / count, start[1] + (end[1] - start[1]) * step / count)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(end[0]), y=int(end[1]))


def painted(image):
    return int((pixels(image)[:, 3] > .5).sum())


def tile_image(data, image, number):
    return tiles.variant(data, image, number)


def journey():
    scratch = prepare_scratch()
    export_dir = scratch / 'udim_export'
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    plates = build_plates()
    area.spaces.active.region_3d.view_rotation = Euler((math.radians(35), 0.0, 0.0)).to_quaternion()
    area.spaces.active.region_3d.view_location = (0.0, 0.0, 0.0)
    area.spaces.active.region_3d.view_distance = 7.0
    yield 0.4
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.6
    check(has('SETUP_UDIM') and control('SETUP_UDIM').active and 'UDIM 1001, 1002' in control('SETUP_TILES.0').label,
          'the setup card detects the two UDIM tiles')
    click(window, region, 'RES.0.1024')
    yield 0.2
    click(window, region, 'START')
    yield 2.0
    project = plates.devil_painter
    data = project.sets[0]
    check([tile.number for tile in data.tiles] == [1001, 1002], 'the texture set paints two UV tiles')
    click(window, region, 'ADD_PAINT')
    yield 0.8
    uid = active_layer(data).uid
    layer = lambda: find_layer(data, uid)
    first, second = tile_image(data, layer().image, 1001), tile_image(data, layer().image, 1002)
    check(first is not None and second is not None and first != second and tuple(second.size) == (1024, 1024), 'each tile gets its own canvas')
    click(window, region, 'PROJECT')
    yield 0.4
    check(has('CROSS_TILES') and control('CROSS_TILES').active and project.cross_tiles, 'strokes cross UV tiles by default')
    press(window, 'ESC', *middle)
    yield 0.3
    click(window, region, 'BRUSH_SIZE', fx=.04)
    yield 0.3
    yield from set_hex(window, region, 'BRUSH_COLOR', 'FF0000')
    roughness = lambda number: tile_image(data, layer().slots['roughness'].image, number)

    drag(window, screen(region, area, plates, (-1.0, 0.0, 0.0)), screen(region, area, plates, (1.0, 0.0, 0.0)))
    yield 2.0
    check(painted(tile_image(data, layer().image, 1001)) > 500 and painted(tile_image(data, layer().image, 1002)) > 500,
          f'one stroke paints across the boundary into both tiles ({editor._active.message})')
    near_edge = pixels(tile_image(data, layer().image, 1001)).reshape(1024, 1024, 4)[:, 1000:, 3].max() > .5
    from_edge = pixels(tile_image(data, layer().image, 1002)).reshape(1024, 1024, 4)[:, :24, 3].max() > .5
    check(near_edge and from_edge, 'the stroke runs to the right edge of tile 1001 and on from the left edge of tile 1002')
    check(pixels(roughness(1001))[:, 3].max() > .5 and pixels(roughness(1002))[:, 3].max() > .5, 'the stroke paints every channel in both tiles')
    check('crossed UV tiles 1001, 1002' in editor._active.message, 'the editor reports the tiles the stroke crossed')
    press(window, 'Z', *middle, ctrl=True)
    yield 1.0
    plates = bpy.data.objects['Plates']
    project = plates.devil_painter
    data = project.sets[0]
    check(painted(tile_image(data, layer().image, 1001)) == 0 and painted(tile_image(data, layer().image, 1002)) == 0, 'one Ctrl+Z undoes the stroke in both tiles')

    drag(window, screen(region, area, plates, (1.0, -.3, 0.0)), screen(region, area, plates, (1.5, .3, 0.0)))
    yield 1.5
    check(painted(tile_image(data, layer().image, 1001)) == 0 and painted(tile_image(data, layer().image, 1002)) > 300, 'a stroke inside tile 1002 stays in that tile')
    click(window, region, 'PROJECT')
    yield 0.4
    click(window, region, 'CROSS_TILES')
    yield 0.3
    press(window, 'ESC', *middle)
    yield 0.3
    check(not project.cross_tiles, 'crossing can be turned off')
    before = painted(tile_image(data, layer().image, 1002))
    drag(window, screen(region, area, plates, (-1.0, .5, 0.0)), screen(region, area, plates, (1.0, .5, 0.0)))
    yield 2.0
    check(painted(tile_image(data, layer().image, 1001)) > 300 and painted(tile_image(data, layer().image, 1002)) == before,
          'with crossing off, a live stroke stays in the tile it starts in')
    click(window, region, 'PROJECT')
    yield 0.4
    click(window, region, 'CROSS_TILES')
    yield 0.3
    press(window, 'ESC', *middle)
    yield 0.3

    click(window, region, 'EXPORT')
    yield 0.4
    click(window, region, 'EXPORT_DIR')
    yield 0.2
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield 0.3
    click(window, region, 'EXPORT_RUN')
    yield 4.0
    files = sorted(path.name for path in export_dir.glob('*.png'))
    color = {number: next((export_dir / name for name in files if 'BaseColor' in name and f'{number}' in name), None) for number in (1001, 1002)}
    check(color[1001] is not None and color[1002] is not None, f'export writes one base color file per tile ({len(files)} files)')
    reds = {number: int(((png(path)[:, 0] > .8) & (png(path)[:, 1] < .2)).sum()) for number, path in color.items()}
    check(reds[1001] > 300 and reds[1002] > 300, f'each exported tile carries its painted red ({reds[1001]}, {reds[1002]})')

    click(window, region, 'CLOSE')
    yield 0.6
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI UDIM CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI UDIM test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
