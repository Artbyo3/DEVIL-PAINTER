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
from devil_painter import editor, library
from devil_painter.document import active_effect, active_layer, find_layer
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


def add_effect(window, region, target, kind):
    opener = 'ADD_FX_' + target
    yield from reveal(window, region, opener)
    yield from menu(window, region, opener, f'NEW_FX.{target}.{kind}')


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


def build_mesh():
    import bmesh
    cube = bpy.data.objects['Cube']
    shape = bmesh.new()
    bmesh.ops.create_cube(shape, size=2.0)
    bmesh.ops.subdivide_edges(shape, edges=shape.edges[:], cuts=3, use_grid_fill=True)
    loose = bmesh.ops.create_cube(shape, size=.5)
    bmesh.ops.translate(shape, verts=loose['verts'], vec=(0.0, 0.0, -3.0))
    mesh = cube.data
    shape.to_mesh(mesh)
    shape.free()
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    mesh.materials.clear()
    mesh.update()
    return cube


def facing(area, cube):
    direction = area.spaces.active.region_3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    sides = [polygon for polygon in cube.data.polygons if polygon.center.z > -2.0]
    front = min(sides, key=lambda polygon: polygon.normal.dot(direction) * 10 + (polygon.center - polygon.normal).length)
    return front.index


def face_pixels(cube, face, resolution):
    mesh = cube.data
    layer = mesh.uv_layers.active
    polygon = mesh.polygons[face]
    uv = numpy.array([tuple(layer.data[loop].uv) for loop in polygon.loop_indices])
    area = abs(numpy.dot(uv[:, 0], numpy.roll(uv[:, 1], 1)) - numpy.dot(uv[:, 1], numpy.roll(uv[:, 0], 1))) / 2
    center = uv.mean(axis=0) % 1.0
    return area * resolution * resolution, (int(center[1] * resolution), int(center[0] * resolution))


def point_toward_corner(region, area, cube, face, share):
    polygon = cube.data.polygons[face]
    corner = cube.data.vertices[polygon.vertices[0]].co
    target = cube.matrix_world @ (polygon.center * (1 - share) + corner * share)
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, target)
    return region.x + point.x, region.y + point.y


def image_pixels(image):
    values = pixels(image)
    side = image.size[0]
    return values.reshape(side, side, 4)


def mask_png(export_dir, layer):
    values = png(export_dir / f'{bpy.path.clean_name(layer.name)}_Mask.png')
    side = int(round(len(values) ** .5))
    return values.reshape(side, side, 4)[..., 0]


def toggle_maps(window, region, wanted):
    for key in keys('BAKEMAP.'):
        if control(key).active != (key.removeprefix('BAKEMAP.') in wanted):
            click(window, region, key)
            yield from settle()


def pick_menu(window, region, opener, item):
    yield from reveal(window, region, opener)
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


def choose_effect(window, region, uid, effect_uid):
    key = f'FX_{uid}.{effect_uid}'
    yield from reveal(window, region, key, 'LAYERS')
    click(window, region, key, fx=.6)
    yield from settle()
    check(active_effect(editor._active.painted()[1]).uid == effect_uid, 'the effect row selects the effect')


def fill_at(window, x, y):
    press(window, 'LEFTMOUSE', x, y)
    yield from settle()
    return editor._active.message


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'mask_export'
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube = build_mesh()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    project = cube.devil_painter
    data = project.sets[0]
    resolution = data.resolution
    front = facing(area, cube)
    front_point = point_toward_corner(region, area, cube, front, 0.0)
    front_area, front_pixel = face_pixels(cube, front, resolution)
    back = max((polygon for polygon in cube.data.polygons if polygon.center.z > -2.0), key=lambda polygon: polygon.normal.dot(cube.data.polygons[front].normal) * -1).index
    _, back_pixel = face_pixels(cube, back, resolution)
    top = max(cube.data.polygons, key=lambda polygon: polygon.center.z + polygon.normal.z * 4).index
    bottom = min((polygon for polygon in cube.data.polygons if polygon.center.z > -2.0), key=lambda polygon: polygon.center.z + polygon.normal.z * 4).index
    _, top_pixel = face_pixels(cube, top, resolution)
    _, bottom_pixel = face_pixels(cube, bottom, resolution)
    check(len(cube.data.uv_layers) == 1, 'Start painting unwraps the mesh into UV chunks')

    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'BAKE')
    yield from settle()
    yield from toggle_maps(window, region, {'ao', 'curvature', 'thickness', 'position', 'world_normal', 'id', 'uv_border'})
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    check(all(key in data.maps and data.maps[key].image is not None for key in ('ao', 'curvature', 'position', 'world_normal', 'id', 'uv_border')),
          'the bake card bakes the maps generators read, including UV border distance')
    border = image_pixels(data.maps['uv_border'].image)
    inside = border[border[..., 3] > .5][:, 0]
    check(inside.min() < .05 and inside.max() > .95 and border[front_pixel][0] > .5, 'UV border distance is dark at UV chunk edges and bright inside')

    click(window, region, 'ADD_FILL')
    yield from settle()
    worn = active_layer(data)
    worn_uid = worn.uid
    yield from reveal(window, region, 'GENERATOR')
    click(window, region, 'GENERATOR')
    yield from settle()
    offered = [key.removeprefix('SET_GENERATOR.') for key in keys('SET_GENERATOR.') if key != 'SET_GENERATOR.NONE']
    check(len(offered) >= 21 and {'METAL_EDGE_WEAR', 'FIBERGLASS_EDGE_WEAR', 'BUILDER', 'UV_BORDER', 'SPHERICAL', 'GRADIENT_X', 'SIDES', 'NOISE'} <= set(offered),
          f'the generator menu offers {len(offered)} generators')
    press(window, 'ESC', *middle)
    yield from settle()
    for key in offered:
        yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.' + key)
        layer = find_layer(data, worn_uid)
        built = f'{worn_uid}.gen.range' in nodes(data)
        check(layer.generator == key and (built or (key == 'HEIGHT' and has('GEN_MISSING'))), f'the {key} generator builds its mask')
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.BUILDER')
    check(has('GEN_EDGES') and has('GEN_DIRT') and has('GEN_TOP'), 'the mask builder shows its edges, dirt, and top weights')
    yield from slide(window, region, 'GEN_TOP', .9)
    check(abs(find_layer(data, worn_uid).gen_top - .9) < .05 and abs(nodes(data)[f'{worn_uid}.gen.gen_top'].inputs[1].default_value - .9) < .05,
          'the top weight slider feeds the mask builder')
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.TOP')
    yield from slide(window, region, 'GEN_NOISE', 0.0)
    yield from context_menu(window, region, worn_uid, 'EXPORT_MASK')
    mask = mask_png(export_dir, find_layer(data, worn_uid))
    check(mask[top_pixel] > .7 and mask[bottom_pixel] < .3, 'the top surfaces generator reveals the top and hides the bottom')
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.EDGE_WEAR')
    yield from context_menu(window, region, worn_uid, 'EXPORT_MASK')
    generated = mask_png(export_dir, find_layer(data, worn_uid))

    yield from add_effect(window, region, 'MASK', 'FILTER')
    yield from reveal(window, region, 'FX_FILTER')
    click(window, region, 'FX_FILTER')
    yield from settle()
    mask_filters = [key.removeprefix('SET_FXFILTER.') for key in keys('SET_FXFILTER.')]
    check(len(keys('HEADING.')) >= 6 and {'DILATE', 'ERODE', 'PIXELATE', 'SCRATCHES', 'AO_SHADE', 'INVERT'} <= set(mask_filters)
          and 'HSV' not in mask_filters, f'the mask filter menu groups {len(mask_filters)} filters under headings')
    click(window, region, 'SET_FXFILTER.INVERT')
    yield from settle()
    yield from context_menu(window, region, worn_uid, 'EXPORT_MASK')
    inverted = mask_png(export_dir, find_layer(data, worn_uid))
    island = border[..., 3] > .5
    check(numpy.abs((1 - generated) - inverted)[island].mean() < .05, 'the Invert filter flips the generated mask inside the effect stack')
    filter_uid = find_layer(data, worn_uid).effects[-1].uid
    yield from choose_effect(window, region, worn_uid, filter_uid)

    for key in mask_filters:
        yield from reveal(window, region, 'FX_FILTER')
        click(window, region, 'FX_FILTER')
        yield from settle()
        click(window, region, 'SET_FXFILTER.' + key)
        yield from settle()
        check(active_effect(data).filter == key and 'error' not in editor._active.message.lower(), f'the {key} mask filter builds')
    yield from pick_menu(window, region, 'FX_FILTER', 'SET_FXFILTER.DILATE')
    check(sum(1 for node in nodes(data) if node.type == 'MATH' and node.operation == 'MAXIMUM') >= 8, 'Dilate takes the maximum of a ring of taps')
    yield from pick_menu(window, region, 'FX_FILTER', 'SET_FXFILTER.PIXELATE')
    check(any(node.type == 'MATH' and node.operation == 'FLOOR' for node in nodes(data)), 'Pixelate snaps the mask lookup to a grid')
    yield from pick_menu(window, region, 'FX_FILTER', 'SET_FXFILTER.INVERT')

    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    yield from reveal(window, region, 'FX_FILTER')
    click(window, region, 'FX_FILTER')
    yield from settle()
    content_filters = [key.removeprefix('SET_FXFILTER.') for key in keys('SET_FXFILTER.')]
    check(len(content_filters) >= 60 and {'HSV', 'COLOR_FRINGE', 'SEPIA', 'REPLACE_COLOR'} <= set(content_filters),
          f'the content filter menu offers {len(content_filters)} filters')
    press(window, 'ESC', *middle)
    yield from settle()
    for key in content_filters:
        yield from reveal(window, region, 'FX_FILTER')
        click(window, region, 'FX_FILTER')
        yield from settle()
        click(window, region, 'SET_FXFILTER.' + key)
        yield from settle()
        check(active_effect(data).filter == key and 'error' not in editor._active.message.lower(), f'the {key} content filter builds')
    yield from pick_menu(window, region, 'FX_FILTER', 'SET_FXFILTER.SCRATCHES')
    check(any(node.type == 'TEX_VORONOI' and node.feature == 'DISTANCE_TO_EDGE' for node in nodes(data)), 'Scratches draws thin voronoi lines')
    yield from pick_menu(window, region, 'FX_FILTER', 'SET_FXFILTER.AO_SHADE')
    check(any(node.type == 'TEX_IMAGE' and node.image == data.maps['ao'].image for node in nodes(data)), 'Occlusion shading reads the baked ambient occlusion')
    click(window, region, 'FX_DELETE')
    yield from settle()

    yield from add_effect(window, region, 'MASK', 'PAINT')
    click(window, region, 'POLYFILL')
    yield from settle()
    check(editor._active.state.poly_mode == 'FACE' and all(has('POLY.' + mode) for mode in ('TRIANGLE', 'FACE', 'ISLAND', 'UV', 'LOOP')),
          'the polygon fill tool offers triangle, face, mesh part, UV chunk, and loop')
    yield from set_hex(window, region, 'BRUSH_COLOR', '000000')
    message = yield from fill_at(window, *front_point)
    yield from settle()
    check(message.startswith('Filled face: 1 face'), 'polygon fill paints one face into the mask paint effect')
    yield from context_menu(window, region, worn_uid, 'EXPORT_MASK')
    refined = mask_png(export_dir, find_layer(data, worn_uid))
    check(refined[front_pixel] < .05 and abs(refined[back_pixel] - inverted[back_pixel]) < .05,
          'the painted effect hides the generated mask on that face and leaves the rest')

    yield from context_menu(window, region, worn_uid, 'SAVE_SMART_MASK')
    yield from settle()
    saved = library.settings().get('smart_masks', [])
    check(len(saved) == 1 and len(saved[0]['effects']) == 2 and saved[0]['generator']['generator'] == 'EDGE_WEAR' and Path(saved[0]['preview']).is_file(),
          'Save mask as smart mask stores the generator, the effect stack, and a preview')
    import json
    check('smart_masks' in json.loads((library.library_root() / library.SETTINGS_FILE).read_text(encoding='utf-8')), 'smart masks are written to the library')
    library._cache.clear()
    check(len(library.settings().get('smart_masks', [])) == 1, 'smart masks survive reloading the library')
    click(window, region, 'SHELF_TAB.MASKS')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    item_key = labels.get(saved[0]['name'])
    check(item_key is not None and control(item_key).preview is not None, 'the Masks shelf shows the saved smart mask with its preview')
    click(window, region, 'ADD_FILL')
    yield from settle()
    reused_uid = active_layer(data).uid
    click(window, region, item_key)
    yield from settle()
    reused = find_layer(data, reused_uid)
    check(reused.generator == 'EDGE_WEAR' and [effect.kind for effect in reused.effects if effect.target == 'MASK'] == ['FILTER', 'PAINT'],
          'clicking the smart mask gives another layer the same generator and effect stack')
    yield from context_menu(window, region, reused_uid, 'EXPORT_MASK')
    check(numpy.abs(mask_png(export_dir, reused) - refined)[island].mean() < .02, 'the reused smart mask matches the original mask')
    labels = {control(key).label: key for key in keys('ITEM.')}
    click(window, region, labels[saved[0]['name']], kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'DELETE_SMART_MASK.0')
    yield from settle()
    check(not library.settings().get('smart_masks') and saved[0]['name'] not in {control(key).label for key in keys('ITEM.')}, 'a smart mask can be deleted')

    click(window, region, 'ADD_FILL')
    yield from settle()
    picked_uid = active_layer(data).uid
    yield from add_effect(window, region, 'MASK', 'ID_COLOR')
    check(has('FX_PICK_ID') and has('FX_amount') and not has('FX_ID_MISSING'), 'the ID color effect offers a picker and a tolerance')
    yield from reveal(window, region, 'FX_PICK_ID')
    click(window, region, 'FX_PICK_ID')
    yield from settle()
    press(window, 'LEFTMOUSE', *front_point)
    yield from settle()
    id_map = image_pixels(data.maps['id'].image)
    check(numpy.abs(numpy.array(active_effect(data).color) - id_map[front_pixel][:3]).max() < .02, 'clicking the model picks the baked ID color')
    yield from context_menu(window, region, picked_uid, 'EXPORT_MASK')
    selected = mask_png(export_dir, find_layer(data, picked_uid))
    colors = len(numpy.unique(numpy.round(id_map[id_map[..., 3] > .5][:, :3], 2), axis=0))
    check(selected[front_pixel] > .9 and selected[back_pixel] < .1 and selected[top_pixel] < .1,
          f'the ID color mask keeps only the picked UV chunk ({selected[front_pixel]:.2f}, {selected[back_pixel]:.2f}, {selected[top_pixel]:.2f}, {colors} ID colors, {id_map[front_pixel]}, {id_map[back_pixel]})')

    click(window, region, 'ADD_PAINT')
    yield from settle()
    painted = active_layer(data)
    painted_uid = painted.uid
    yield from set_hex(window, region, 'BRUSH_COLOR', 'FF0000')

    def covered():
        return int((image_pixels(find_layer(data, painted_uid).image)[..., 3] > .5).sum())

    message = yield from fill_at(window, *front_point)
    face_count = covered()
    check(message.startswith('Filled face: 1 face') and .8 * front_area < face_count < 2.5 * front_area + 400, 'Face fills exactly the clicked face')
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    data = project.sets[0]
    check(covered() == 0, 'Ctrl+Z undoes a polygon fill')
    click(window, region, 'POLY.TRIANGLE')
    yield from settle()
    message = yield from fill_at(window, *point_toward_corner(region, area, cube, front, .3))
    check(message.startswith('Filled triangle') and covered() < .8 * face_count, 'Triangle fills half of the face')
    for mode, faces in (('UV', 16), ('LOOP', 16), ('ISLAND', 96)):
        click(window, region, 'POLY.' + mode)
        yield from settle()
        message = yield from fill_at(window, *front_point)
        check(f': {faces} faces' in message, f'{mode} fill picks {faces} faces: {message}')
    click(window, region, 'POLY_ERASE')
    click(window, region, 'POLY.FACE')
    yield from settle()
    message = yield from fill_at(window, *front_point)
    check(message.startswith('Erased face') and image_pixels(find_layer(data, painted_uid).image)[front_pixel][3] < .5, 'Erase clears the clicked face')
    click(window, region, 'POLY_ERASE')
    yield from settle()

    click(window, region, 'ADD_FILL')
    yield from settle()
    part_uid = active_layer(data).uid
    yield from context_menu(window, region, part_uid, 'ADD_MASK_BLACK')
    click(window, region, 'POLY.UV')
    yield from settle()
    message = yield from fill_at(window, *front_point)
    yield from context_menu(window, region, part_uid, 'EXPORT_MASK')
    part = mask_png(export_dir, find_layer(data, part_uid))
    check(part[front_pixel] > .9 and part[back_pixel] < .1 and part[top_pixel] < .1, 'polygon fill on a black mask restricts the layer to one UV chunk')

    click(window, region, 'QUICK_MASK')
    yield from settle()
    check(data.quick_mask is not None and has('QUICK_APPLY'), 'Quick mask turns on a temporary stencil')
    tint = [node for node in nodes(data) if node.type == 'MIX' and node.data_type == 'RGBA'
            and tuple(round(value, 2) for value in node.inputs[7].default_value) == (1.0, .08, .15, 1.0)]
    check(tint, 'the quick mask shows as a red overlay on the model')
    click(window, region, 'POLY.FACE')
    yield from settle()
    stencil_name = data.quick_mask.name
    yield from fill_at(window, *front_point)
    check(image_pixels(data.quick_mask)[front_pixel][3] > .5, 'polygon fill paints into the quick mask')
    click(window, region, 'ADD_FILL')
    yield from settle()
    quick_layer = active_layer(data)
    quick_uid = quick_layer.uid
    check(data.quick_mask is None and quick_layer.mask is not None and quick_layer.mask.name != stencil_name,
          'the next new layer takes the quick mask and the stencil ends')
    yield from context_menu(window, region, quick_uid, 'EXPORT_MASK')
    quick = mask_png(export_dir, find_layer(data, quick_uid))
    check(quick[front_pixel] > .9 and quick[back_pixel] < .1, 'the new layer shows only where the quick mask was painted')
    click(window, region, 'QUICK_MASK')
    yield from settle()
    click(window, region, 'POLY.UV')
    yield from settle()
    yield from fill_at(window, *front_point)
    click(window, region, 'QUICK_APPLY')
    yield from settle()
    applied = find_layer(data, quick_uid)
    check(data.quick_mask is None and any(effect.kind == 'PAINT' and effect.blend == 'MULTIPLY' for effect in applied.effects),
          'Mask selected layer adds the quick mask to a layer that already has a mask')
    click(window, region, 'POLYFILL')
    yield from settle()
    check(editor._active.state.poly_mode == '', 'the polygon fill tool turns off')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI MASK CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI mask test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
