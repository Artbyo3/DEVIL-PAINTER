import math
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
from devil_painter import editor, library, painting
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import settle, until

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


def spot_of(region, key, fx=.5, fy=.5):
    return spot(region, key, fx, fy)


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
            yield from settle()
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


def nodes(data):
    return data.material.node_tree.nodes


def pick(window, region, opener, item):
    yield from reveal(window, region, opener)
    yield from menu(window, region, opener, item)


def menu(window, region, opener, item):
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


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


def slide(window, region, key, fx):
    yield from reveal(window, region, key)
    click(window, region, key, fx=fx)
    yield from settle()


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


def face_center_pixel(cube, face, resolution):
    mesh = cube.data
    layer = mesh.uv_layers.active
    uv = numpy.array([tuple(layer.data[loop].uv) for loop in mesh.polygons[face].loop_indices]).mean(axis=0) % 1.0
    return int(uv[1] * resolution), int(uv[0] * resolution)


def face_of(cube, normal):
    return max(cube.data.polygons, key=lambda polygon: polygon.normal.dot(Vector(normal))).index


def face_point(region, area, cube, face, share=0.0, corner=0):
    polygon = cube.data.polygons[face]
    target = cube.matrix_world @ (polygon.center * (1 - share) + cube.data.vertices[polygon.vertices[corner]].co * share)
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, target)
    return region.x + point.x, region.y + point.y


def image_at(image, spot):
    return image_pixels(image)[spot]


def image_pixels(image):
    values = pixels(image)
    side = image.size[0]
    return values.reshape(side, side, 4)


def drag(window, x, y, dx, dy, count=8, **modifiers):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y), **modifiers)
    for step in range(1, count + 1):
        move(window, x + dx * step / count, y + dy * step / count)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def card_click(window, region, opener, key, popover):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == popover):
        click(window, region, opener)
        yield from settle()
    check(has(key), f'{opener} shows {key}')
    click(window, region, key)
    yield from settle()


def close_cards(window, middle):
    if editor._active.state.popover is not None:
        press(window, 'ESC', *middle)
    yield from settle()


def card_slide(window, region, opener, key, popover, fx):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == popover):
        click(window, region, opener)
        yield from settle()
    click(window, region, key, fx=fx)
    yield from settle()


def build_plates():
    import bmesh
    mesh = bpy.data.meshes.new('Plates')
    shape = bmesh.new()
    uv = shape.loops.layers.uv.new('UVMap')
    for index in range(2):
        corners = [shape.verts.new((index * 2.2 + x, y, -4.0)) for x, y in ((0, 0), (2, 0), (2, 2), (0, 2))]
        face = shape.faces.new(corners)
        for loop, (u, v) in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uv].uv = (u + index, v)
    shape.to_mesh(mesh)
    shape.free()
    mesh.materials.append(bpy.data.materials.new('Plates'))
    plates = bpy.data.objects.new('Plates', mesh)
    bpy.context.scene.collection.objects.link(plates)
    return plates


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'paint_export'
    textures = scratch / 'textures'
    textures.mkdir(exist_ok=True)
    decal = bpy.data.images.new('decal', 32, 32, alpha=True)
    decal.pixels.foreach_set(numpy.tile(numpy.array((1.0, 0.0, 0.0, 1.0), dtype=numpy.float32), 32 * 32))
    decal.filepath_raw = str(textures / 'decal.png')
    decal.file_format = 'PNG'
    decal.save()
    bpy.data.images.remove(decal)
    for name, value in (('brick_basecolor', (.2, .6, .2, 1.0)), ('brick_roughness', (.7, .7, .7, 1.0))):
        swatch = bpy.data.images.new(name, 16, 16, alpha=True)
        swatch.pixels.foreach_set(numpy.tile(numpy.array(value, dtype=numpy.float32), 16 * 16))
        swatch.filepath_raw = str(textures / f'{name}.png')
        swatch.file_format = 'PNG'
        swatch.save()
        bpy.data.images.remove(swatch)
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = cube.devil_painter.sets[0]
    resolution = data.resolution
    right, front, top, left, back = (face_of(cube, normal) for normal in ((1, 0, 0), (0, -1, 0), (0, 0, 1), (-1, 0, 0), (0, 1, 0)))
    spot = {face: face_center_pixel(cube, face, resolution) for face in (right, front, top, left, back)}

    click(window, region, 'BRUSH_CARD')
    yield from settle()
    check(all(has(key) for key in ('BRUSH_ANGLE', 'BRUSH_STROKE', 'SAVE_BRUSH', 'BRUSH_SMOOTHING', 'BRUSHUSE.base_color', 'BRUSHUSE.height')),
          'the brush card offers angle, stroke, lazy mouse, presets, and every channel')
    check(control('BRUSH_SMOOTHING').label == 'Lazy mouse', 'smoothing is the lazy mouse')
    click(window, region, 'BRUSH_ANGLE', fx=.25)
    yield from settle()
    check(abs(data.brush_angle - 90) < 4, 'the angle slider rotates the brush')
    click(window, region, 'BRUSH_SMOOTHING', fx=.5)
    yield from settle()
    brush = bpy.context.tool_settings.image_paint.brush
    check(brush.use_smooth_stroke and brush.smooth_stroke_radius > 40, 'lazy mouse stabilizes the Blender stroke')
    click(window, region, 'BRUSH_STROKE')
    yield from settle()
    check(all(has('SET_STROKE.' + method) for method in ('SPACE', 'LINE', 'DOTS', 'AIRBRUSH', 'ANCHORED')), 'the stroke menu offers line, dots, airbrush, and anchored strokes')
    click(window, region, 'SET_STROKE.LINE')
    yield from settle()
    check(data.brush_stroke == 'LINE' and bpy.context.tool_settings.image_paint.brush.stroke_method == 'LINE', 'Line strokes draw straight lines')
    yield from card_click(window, region, 'BRUSH_CARD', 'SAVE_BRUSH', 'BRUSH')
    check(data.brush_preset == 'Custom 1' and library.settings().get('brush_presets'), 'Save as preset stores the brush')
    yield from close_cards(window, middle)
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    check('Custom 1' in labels and control(labels['Custom 1']).preview is not None, 'the brush shelf shows the saved preset with a preview')
    click(window, region, labels['Soft Round'])
    yield from settle()
    check(data.brush_stroke == 'SPACE' and data.brush_angle == 0.0, 'a built-in preset resets the stroke and angle')
    click(window, region, labels['Custom 1'])
    yield from settle()
    check(data.brush_stroke == 'LINE' and abs(data.brush_angle - 90) < 4, 'the saved preset brings its stroke and angle back')
    click(window, region, labels['Custom 1'], kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'DELETE_BRUSH.0')
    yield from settle()
    check(not library.settings().get('brush_presets'), 'a saved preset can be deleted')
    click(window, region, labels['Soft Round'])
    yield from settle()

    click(window, region, 'BRUSH_SIZE', fx=.06)
    yield from settle()
    check(painting.brush_value(bpy.context.scene, 'size') < 40, 'the size slider makes a small brush')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    painted_uid = active_layer(data).uid
    layer = lambda: find_layer(data, painted_uid)
    yield from set_hex(window, region, 'BRUSH_COLOR', 'FF0000')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSHUSE.height', 'BRUSH')
    yield from card_slide(window, region, 'BRUSH_CARD', 'BRUSHVAL.height', 'BRUSH', .9)
    yield from card_slide(window, region, 'BRUSH_CARD', 'BRUSHVAL.roughness', 'BRUSH', .2)
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSHUSE.normal', 'BRUSH')
    check(has('BRUSH_NORMAL_TILT') and has('BRUSH_NORMAL_ANGLE'), 'painting normals offers tilt and direction')
    yield from card_slide(window, region, 'BRUSH_CARD', 'BRUSH_NORMAL_TILT', 'BRUSH', .5)
    normal_color = tuple(data.brush_slots['normal'].color)
    check(normal_color[2] < .95 and abs(normal_color[0] - .5) > .1, 'the normal tilt sets the painted normal direction')
    yield from close_cards(window, middle)
    yield from card_click(window, region, 'SYMMETRY', 'MIRROR.X', 'SYMMETRY')
    check(data.brush_mirror[0] and cube.data.use_mirror_x and control('SYMMETRY').text.startswith('Mirror X'), 'Mirror X turns on mesh symmetry')
    yield from close_cards(window, middle)
    x, y = face_point(region, area, cube, right)
    drag(window, x, y, 6, 4)
    yield from settle()
    canvas = lambda key: layer().slots[key].image
    check(image_at(layer().image, spot[right])[3] > .5 and image_at(layer().image, spot[right])[0] > .9, 'one stroke paints the base color')
    check(abs(image_at(canvas('roughness'), spot[right])[0] - .2) < .05 and image_at(canvas('height'), spot[right])[0] > .8,
          'the same stroke paints roughness and height')
    check(abs(image_at(canvas('normal'), spot[right])[0] - normal_color[0]) < .05, 'the same stroke paints the tilted normal')
    check(image_at(layer().image, spot[left])[3] > .5, 'Mirror X repeats the stroke on the opposite side')
    check(layer().slots['normal'].blend == 'NORMAL_DETAIL', 'painted normals add detail over the layers below')
    check(any(node.type == 'BUMP' or node.name == 'shader.bump' for node in nodes(data)), 'painted height drives the bump')
    yield from card_click(window, region, 'SYMMETRY', 'MIRROR.X', 'SYMMETRY')
    yield from card_slide(window, region, 'SYMMETRY', 'RADIAL', 'SYMMETRY', .2)
    yield from card_click(window, region, 'SYMMETRY', 'RADIAL_AXIS.Z', 'SYMMETRY')
    check(data.brush_radial == 4 and data.brush_radial_axis == 'Z' and control('SYMMETRY').text == 'Radial 4', 'radial symmetry makes four copies around Z')
    yield from close_cards(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    radial_uid = active_layer(data).uid
    x, y = face_point(region, area, cube, front)
    drag(window, x, y, 6, 4)
    yield from settle()
    radial = find_layer(data, radial_uid).image
    check(all(image_at(radial, spot[face])[3] > .5 for face in (right, front, left, back)) and image_at(radial, spot[top])[3] < .5,
          f'a radial stroke lands on all four sides and not on top {[round(float(image_at(radial, spot[face])[3]), 2) for face in (right, front, left, back, top)]} {int((image_pixels(radial)[..., 3] > .5).sum())} {editor._active.message}')
    yield from card_slide(window, region, 'SYMMETRY', 'RADIAL', 'SYMMETRY', 0.0)
    yield from close_cards(window, middle)
    yield from select_row(window, region, painted_uid)

    click(window, region, 'ERASE')
    yield from settle()
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSHUSE.base_color', 'BRUSH')
    check(not data.brush_slots['base_color'].enabled, 'base color can be left out of the eraser')
    yield from close_cards(window, middle)
    x, y = face_point(region, area, cube, right)
    drag(window, x, y, 4, 2)
    yield from settle()
    check(image_at(canvas('roughness'), spot[right])[3] < .5 and image_at(layer().image, spot[right])[3] > .5,
          'Erase without base color clears roughness and keeps the color')
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    check(image_at(canvas('roughness'), spot[right])[3] > .5, 'Ctrl+Z restores the erased channel')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSHUSE.base_color', 'BRUSH')
    yield from close_cards(window, middle)
    drag(window, x, y, 4, 2)
    yield from settle()
    check(image_at(layer().image, spot[right])[3] < .5, 'Erase with base color clears the layer there')

    click(window, region, 'PAINT')
    yield from settle()
    fx, fy = face_point(region, area, cube, front)
    drag(window, fx, fy, 6, 3)
    yield from settle()
    before = image_pixels(layer().image).copy()
    click(window, region, 'BLUR')
    yield from settle()
    drag(window, fx - 40, fy, 80, 0)
    yield from settle()
    after = image_pixels(layer().image)
    partial = lambda values: int(((values[..., 3] > .05) & (values[..., 3] < .95)).sum())
    check(numpy.abs(after - before).max() > .05 and partial(after) > partial(before), 'Blur softens the painted edge')
    before = after.copy()
    click(window, region, 'SMEAR')
    yield from settle()
    drag(window, fx, fy, 70, 0, count=12)
    yield from settle()
    after = image_pixels(layer().image)
    check(after[..., 3].sum() > before[..., 3].sum() and numpy.abs(after - before).max() > .05, 'Smudge drags paint along the stroke')
    click(window, region, 'CLONE')
    yield from settle()
    drag(window, fx, fy, 0, 0, count=1)
    yield from settle()
    check('Ctrl+click' in editor._active.message, 'Clone asks for a source first')
    sx, sy = face_point(region, area, cube, front)
    press(window, 'LEFTMOUSE', sx, sy, ctrl=True)
    yield from settle()
    check(editor._active.state.clone_source is not None, 'Ctrl+click sets the clone source on the model')
    tx, ty = face_point(region, area, cube, top)
    drag(window, tx, ty, 4, 2)
    yield from settle()
    copied, source = image_at(layer().image, spot[top]), image_at(layer().image, spot[front])
    check(source[3] > .2 and numpy.abs(copied - source).max() < .06, 'Clone copies the painted area to the top')
    check(abs(image_at(canvas('roughness'), spot[top])[0] - image_at(canvas('roughness'), spot[front])[0]) < .06, 'Clone copies the roughness channel too')
    click(window, region, 'PAINT')
    yield from settle()

    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot_of(region, 'TEXTURE_DIR'))
    wanted = {'decal', 'brick_basecolor', 'brick_roughness'}
    yield from until(lambda: wanted <= {control(key).label for key in keys('ITEM.')}, 'wanted <= {control(key).label for key in keys("ITEM.")}')
    check(wanted <= {control(key).label for key in keys('ITEM.')}, 'the texture folder lists the decal and the brick textures')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    click(window, region, labels['Gold'], kind='RIGHTMOUSE')
    yield from settle()
    check(has(f'PAINT_MATERIAL.{labels["Gold"].removeprefix("ITEM.")}'), 'materials offer Paint with this material')
    click(window, region, f'PAINT_MATERIAL.{labels["Gold"].removeprefix("ITEM.")}')
    yield from settle()
    check(data.brush_material == 'Gold' and data.brush_slots['metallic'].enabled and abs(data.brush_slots['metallic'].value - 1.0) < 1e-3,
          'the brush takes every channel of the Gold material')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    gold = active_layer(data)
    gold_uid = gold.uid
    x, y = face_point(region, area, cube, front)
    drag(window, x, y, 6, 3)
    yield from settle()
    gold = find_layer(data, gold_uid)
    color = image_at(gold.image, spot[front])
    check(color[3] > .5 and color[0] > color[2] + .3, f'material painting lays down the gold color {color} {tuple(painting.brush_value(bpy.context.scene, "color"))} {int((image_pixels(gold.image)[..., 3] > .5).sum())} {editor._active.message}')
    check(image_at(gold.slots['metallic'].image, spot[front])[0] > .95 and abs(image_at(gold.slots['roughness'].image, spot[front])[0] - .2) < .05,
          'material painting lays down gold metallic and roughness in the same stroke')
    labels = {control(key).label: key for key in keys('ITEM.')}
    brick = labels.get('Brick')
    check(brick is not None, 'the texture set appears as a material')
    click(window, region, brick, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, f'PAINT_MATERIAL.{brick.removeprefix("ITEM.")}')
    yield from settle()
    check(data.brush_slots['roughness'].source == 'IMAGE' and has('BRUSH_CARD'), 'a textured material puts its textures on the brush')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    textured_uid = active_layer(data).uid
    drag(window, x, y, 6, 3)
    yield from settle()
    textured = find_layer(data, textured_uid)
    check(abs(image_at(textured.slots['roughness'].image, spot[front])[0] - .7) < .05, 'material painting samples the material textures per channel')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_MATERIAL_CLEAR', 'BRUSH')
    check(data.brush_material == '', 'the brush material can be cleared')
    yield from close_cards(window, middle)

    click(window, region, 'CHANNELS')
    yield from settle()
    click(window, region, 'CHANSET.flow')
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    click(window, region, 'ADD_PAINT')
    yield from settle()
    flow_uid = active_layer(data).uid
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSHUSE.flow', 'BRUSH')
    yield from close_cards(window, middle)
    x, y = face_point(region, area, cube, front, .3, 0)
    drag(window, x, y, 60, 0, count=10)
    yield from settle()
    flow_map = image_pixels(find_layer(data, flow_uid).slots['flow'].image)
    painted = flow_map[image_pixels(find_layer(data, flow_uid).image)[..., 3] > .5]
    check(len(painted) and numpy.abs(painted[:, :2] - .5).max(axis=1).mean() > .3, 'a flow map stroke records its direction')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSHUSE.flow', 'BRUSH')
    yield from close_cards(window, middle)

    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    click(window, region, labels['decal'], kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'USE_STENCIL.' + labels['decal'].removeprefix('ITEM.'))
    yield from settle()
    brush = bpy.context.tool_settings.image_paint.brush
    check(data.brush_stencil is not None and brush.texture is not None and brush.texture.image == data.brush_stencil
          and brush.texture_slot.map_mode == 'STENCIL', 'Use as stencil puts the texture on screen as a brush stencil')
    check(control('STENCIL_CARD').preview == data.brush_stencil, 'the tool strip shows the stencil thumbnail')
    yield from card_slide(window, region, 'STENCIL_CARD', 'STENCIL_SCALE', 'STENCIL', .2)
    check(abs(data.stencil_scale - .8) < .05 and brush.stencil_dimension[0] > 10, 'the stencil scale slider sizes the stencil')
    yield from card_slide(window, region, 'STENCIL_CARD', 'STENCIL_ANGLE', 'STENCIL', .125)
    check(abs(math.degrees(brush.texture_slot.angle) - 45) < 4, 'the stencil rotation slider turns the stencil')
    yield from card_slide(window, region, 'STENCIL_CARD', 'STENCIL_ANGLE', 'STENCIL', 0.0)
    yield from close_cards(window, middle)
    yield from set_hex(window, region, 'BRUSH_COLOR', 'FFFFFF')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    decal_uid = active_layer(data).uid
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_PROJECT', 'STENCIL')
    yield from settle()
    projected = image_pixels(find_layer(data, decal_uid).image)
    reds = (projected[..., 3] > .5) & (projected[..., 0] > .8) & (projected[..., 1] < .2)
    check(int(reds.sum()) > 500 and 'Projected' in editor._active.message, 'Project through the view stamps the stencil image onto the model')
    check(abs(image_at(find_layer(data, decal_uid).slots['roughness'].image, tuple(numpy.argwhere(reds)[len(numpy.argwhere(reds)) // 2]))[0] - data.brush_slots['roughness'].value) < .05,
          'the projection also writes the brush channels')
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    check(int((image_pixels(find_layer(data, decal_uid).image)[..., 3] > .5).sum()) == 0, 'Ctrl+Z undoes the projection')
    drag(window, middle[0], middle[1], 6, 3)
    yield from settle()
    through = image_pixels(find_layer(data, decal_uid).image)
    stamped = through[through[..., 3] > .5]
    check(len(stamped) and numpy.median(stamped[:, 0]) > .8 and numpy.median(stamped[:, 1]) < .2, 'a white stroke through the red stencil paints red')
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_CLEAR', 'STENCIL')
    check(data.brush_stencil is None and bpy.context.tool_settings.image_paint.brush.texture is None, 'the stencil can be removed')
    yield from close_cards(window, middle)

    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    click(window, region, labels['Wood'])
    yield from settle()
    wood_uid = active_layer(data).uid
    yield from pick(window, region, 'PROJECTION', 'SET_PROJECTION.PLANAR')
    wood = find_layer(data, wood_uid)
    check(wood.projection == 'PLANAR' and f'{wood_uid}:projector' in nodes(data) and has('GIZMO_MOVE') and has('GIZMO_SIZE'),
          'a planar projection adds a projector and its gizmo on the model')
    check(len(control('GIZMO_MOVE').points) >= 8, 'the gizmo draws the projector frame')
    gx, gy = spot_of(region, 'GIZMO_MOVE')
    drag(window, gx, gy, 60, 0)
    yield from settle()
    wood = find_layer(data, wood_uid)
    check(Vector(wood.proj_offset).length > .1 and tuple(nodes(data)[f'{wood_uid}:projector'].inputs['Location'].default_value) == tuple(wood.proj_offset),
          'dragging the gizmo moves the projection')
    size = wood.proj_size
    sx, sy = spot_of(region, 'GIZMO_SIZE')
    drag(window, sx, sy, 50, 50)
    yield from settle()
    check(find_layer(data, wood_uid).proj_size > size * 1.1, 'dragging the corner handle grows the projection')
    yield from reveal(window, region, 'PROJ_ALIGN')
    click(window, region, 'PROJ_ALIGN')
    yield from settle()
    check(Vector(find_layer(data, wood_uid).proj_rotation).length > .1, 'Align to view points the projector along the view')
    yield from slide(window, region, 'PROJ_SPIN', .25)
    check(abs(math.degrees(find_layer(data, wood_uid).proj_rotation[2]) - 90) < 5, 'the spin slider turns the projection')
    for mode in ('SPHERICAL', 'CYLINDRICAL'):
        yield from pick(window, region, 'PROJECTION', 'SET_PROJECTION.' + mode)
        check(find_layer(data, wood_uid).projection == mode and any(node.type == 'MATH' and node.operation == 'ARCTAN2' for node in nodes(data))
              and has('GIZMO_MOVE'), f'a {mode.lower()} projection wraps around the projector')

    plates = build_plates()
    bpy.context.view_layer.objects.active = plates
    plates.select_set(True)
    yield from settle()
    check(has('START') and has('SETUP_UDIM') and control('SETUP_UDIM').active, 'the second mesh offers UDIM tiles')
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    plate_set = plates.devil_painter.sets[0]
    check([tile.number for tile in plate_set.tiles] == [1001, 1002], 'the plates use two UDIM tiles')
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot_of(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    click(window, region, labels['Wood'])
    yield from settle()
    tiled_uid = active_layer(plate_set).uid
    yield from pick(window, region, 'PROJECTION', 'SET_PROJECTION.UV')

    def tiles_export():
        yield from context_menu(window, region, tiled_uid, 'EXPORT_LAYER')
        stem = bpy.path.clean_name(find_layer(plate_set, tiled_uid).name)
        first, second = (png(export_dir / f'{stem}_BaseColor.{number}.png') for number in (1001, 1002))
        return float(numpy.abs(first[:, :3] - second[:, :3]).mean())

    apart = yield from tiles_export()
    yield from reveal(window, region, 'TILE_MATCH')
    click(window, region, 'TILE_MATCH')
    yield from settle()
    check(find_layer(plate_set, tiled_uid).tile_match and any(node.type == 'VECT_MATH' and node.operation == 'FRACTION' for node in nodes(plate_set)),
          'Same on every UV tile repeats the fill per UDIM tile')
    matched = yield from tiles_export()
    check(apart > .02 and matched < .005, f'the exported tiles differ without matching and match with it ({apart:.3f}, {matched:.4f})')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI PAINTING CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI painting test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
