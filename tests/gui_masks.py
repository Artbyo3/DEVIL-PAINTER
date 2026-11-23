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
from devil_painter import editor, library
from devil_painter.document import active_effect, active_layer, find_layer
from devil_painter.effects import copy_effect
from devil_painter.procedural import PATTERN
from devil_painter.masks import BREAKUPS, GENERATOR_VALUES, LAYER_GENERATOR_FIELDS
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, check, click, context_menu, control, drag_slider, finish, has, keys, move, nodes, pixels, png, press, reveal, run_journey, set_hex, settle, slide, spot, type_text, until, viewport


def menu(window, region, opener, item):
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


def add_effect(window, region, target, kind):
    opener = 'ADD_FX_' + target
    yield from reveal(window, region, opener)
    yield from menu(window, region, opener, f'NEW_FX.{target}.{kind}')


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


def search(window, region, text):
    click(window, region, 'SHELF_SEARCH')
    yield from settle()
    type_text(window, text, *spot(region, 'SHELF_SEARCH'))
    yield from settle()
    move(window, region.x + region.width / 2, region.y + region.height / 2)
    yield from settle()


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
    drag_slider(window, region, 'BAKE_SAMPLES', .03)
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    check(all(key in data.maps and data.maps[key].image is not None for key in ('ao', 'curvature', 'position', 'world_normal', 'id', 'uv_border')),
          'the bake card bakes the maps generators read, including UV border distance')
    border = image_pixels(data.maps['uv_border'].image)
    inside = border[border[..., 3] > .5][:, 0]
    check(inside.min() < .05 and inside.max() > .95 and border[front_pixel][0] > .5, 'UV border distance is dark at UV chunk edges and bright inside')

    click(window, region, 'ADD_FILL')
    yield from settle()
    worn = active_layer(data)
    worn_uid = worn.uid
    yield from add_effect(window, region, 'MASK', 'GENERATOR')
    first_uid = active_effect(data).uid

    def generator_node(effect_uid, suffix):
        return nodes(data)[f'{worn_uid}.{effect_uid}.gen.{suffix}']

    yield from reveal(window, region, 'GENERATOR')
    click(window, region, 'GENERATOR')
    yield from settle()
    offered = [key.removeprefix('SET_GENERATOR.') for key in keys('SET_GENERATOR.')]
    check(len(offered) >= 21 and {'METAL_EDGE_WEAR', 'FIBERGLASS_EDGE_WEAR', 'BUILDER', 'UV_BORDER', 'SPHERICAL', 'GRADIENT_X', 'SIDES', 'NOISE'} <= set(offered),
          f'the generator menu offers {len(offered)} generators')
    press(window, 'ESC', *middle)
    yield from settle()
    for key in offered:
        yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.' + key)
        built = f'{worn_uid}.{first_uid}.gen.range' in nodes(data)
        check(active_effect(data).generator == key and (built or (key == 'HEIGHT' and has('GEN_MISSING'))), f'the {key} generator builds its mask')
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.BUILDER')
    check(has('GEN_EDGES') and has('GEN_DIRT') and has('GEN_TOP'), 'the mask builder shows its edges, dirt, and top weights')
    yield from slide(window, region, 'GEN_TOP', .9)
    check(abs(active_effect(data).gen_top - .9) < .05 and abs(generator_node(first_uid, 'gen_top').inputs[1].default_value - .9) < .05,
          'the top weight slider feeds the mask builder')
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.TOP')
    yield from slide(window, region, 'GEN_NOISE', 0.0)
    yield from context_menu(window, region, worn_uid, 'EXPORT_MASK')
    mask = mask_png(export_dir, find_layer(data, worn_uid))
    check(mask[top_pixel] > .7 and mask[bottom_pixel] < .3, 'the top surfaces generator reveals the top and hides the bottom')

    def exported():
        chosen = active_effect(data).uid
        yield from context_menu(window, region, worn_uid, 'EXPORT_MASK')
        values = mask_png(export_dir, find_layer(data, worn_uid))
        yield from choose_effect(window, region, worn_uid, chosen)
        return values[top_pixel], values[bottom_pixel]

    def stack():
        return [(effect.uid, effect.generator) for effect in find_layer(data, worn_uid).effects if effect.kind == 'GENERATOR']

    click(window, region, 'SHELF_TAB.GENERATORS')
    yield from settle()
    yield from search(window, region, 'Bottom')
    labels = {control(key).label: key for key in keys('ITEM.')}
    check('Bottom surfaces' in labels, 'the generators shelf finds Bottom surfaces')
    click(window, region, labels['Bottom surfaces'])
    yield from settle()
    yield from search(window, region, '')
    second_uid = active_effect(data).uid
    check(stack() == [(first_uid, 'TOP'), (second_uid, 'BOTTOM')] and f'{worn_uid}.{first_uid}.gen.range' in nodes(data)
          and f'{worn_uid}.{second_uid}.gen.range' in nodes(data),
          'clicking a generator in the shelf adds a second Generator effect above the first instead of replacing it')
    yield from slide(window, region, 'GEN_NOISE', 0.0)
    multiplied = yield from exported()
    check(multiplied[0] < .3 and multiplied[1] < .3, f'Bottom multiplied over Top hides both faces (top {multiplied[0]:.3f}, bottom {multiplied[1]:.3f})')
    yield from pick_menu(window, region, 'FX_BLEND', 'SET_FXBLEND.MAXIMUM')
    lightened = yield from exported()
    check(active_effect(data).blend == 'MAXIMUM' and lightened[0] > .7 and lightened[1] > .7,
          f'switching the second generator to Lighten reveals both faces (top {lightened[0]:.3f}, bottom {lightened[1]:.3f})')
    yield from slide(window, region, 'FX_opacity', .5)
    halved = yield from exported()
    opacity = active_effect(data).opacity
    check(abs(opacity - .5) < .05 and halved[0] > .7 and abs(halved[1] - opacity) < .1,
          f'the second generator opacity scales its contribution (opacity {opacity:.2f}, bottom {halved[1]:.3f})')
    yield from slide(window, region, 'FX_opacity', .995)
    restored = yield from exported()
    check(restored[1] > .9, f'full opacity brings the bottom back (bottom {restored[1]:.3f})')
    yield from reveal(window, region, 'FX_DOWN')
    click(window, region, 'FX_DOWN')
    yield from settle()
    reordered = yield from exported()
    check(stack() == [(second_uid, 'BOTTOM'), (first_uid, 'TOP')] and reordered[0] > .7 and reordered[1] < .3,
          f'moving the Lighten generator below the Top multiply changes the export (bottom {restored[1]:.3f} -> {reordered[1]:.3f})')
    print('STACK ORDER EVIDENCE', dict(multiply=[round(float(value), 3) for value in multiplied], lighten=[round(float(value), 3) for value in lightened],
                                       half=[round(float(value), 3) for value in halved], top_then_bottom=[round(float(value), 3) for value in restored],
                                       bottom_then_top=[round(float(value), 3) for value in reordered]))
    yield from reveal(window, region, 'FX_DELETE')
    click(window, region, 'FX_DELETE')
    yield from settle()
    check(stack() == [(first_uid, 'TOP')] and f'{worn_uid}.{second_uid}.gen.range' not in nodes(data), 'deleting one generator leaves the other')
    yield from choose_effect(window, region, worn_uid, first_uid)
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
    check(len(saved) == 1 and [(entry['kind'], entry['generator']) for entry in saved[0]['effects']][0] == ('GENERATOR', 'EDGE_WEAR')
          and len(saved[0]['effects']) == 3 and 'generator' not in saved[0] and Path(saved[0]['preview']).is_file(),
          'Save mask as smart mask stores the generator, the effect stack, and a preview')
    import json
    check('smart_masks' in json.loads((library.library_root() / library.SETTINGS_FILE).read_text(encoding='utf-8')), 'smart masks are written to the library')
    library._cache.clear()
    check(len(library.settings().get('smart_masks', [])) == 1, 'smart masks survive reloading the library')
    click(window, region, 'SHELF_TAB.MASKS')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    item_key = labels.get(saved[0]['name'])
    yield from until(lambda: item_key is not None and control(item_key).preview is not None, 'the saved smart mask preview on the Masks shelf')
    check(item_key is not None and control(item_key).preview is not None, 'the Masks shelf shows the saved smart mask with its preview')
    click(window, region, 'ADD_FILL')
    yield from settle()
    reused_uid = active_layer(data).uid
    click(window, region, item_key)
    yield from settle()
    reused = find_layer(data, reused_uid)
    check([(effect.kind, effect.generator if effect.kind == 'GENERATOR' else '') for effect in reused.effects if effect.target == 'MASK']
          == [('GENERATOR', 'EDGE_WEAR'), ('FILTER', ''), ('PAINT', '')],
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
    id_row = f'FX_{picked_uid}.{find_layer(data, picked_uid).effects[-1].uid}'
    yield from reveal(window, region, id_row, 'LAYERS')
    click(window, region, id_row)
    yield from settle()
    yield from reveal(window, region, 'FX_ADD_ID')
    click(window, region, 'FX_ADD_ID')
    yield from settle()
    press(window, 'LEFTMOUSE', *point_toward_corner(region, area, cube, top, 0.0))
    yield from settle()
    extra = active_effect(data).id_colors
    check(len(extra) == 1 and numpy.abs(numpy.array(extra[0].color) - id_map[top_pixel][:3]).max() < .02 and has('FX_ID_COLOR.0') and has('FX_REMOVE_ID.0'),
          'Add color picks a second ID color from the model and lists it under the first')
    yield from context_menu(window, region, picked_uid, 'EXPORT_MASK')
    both = mask_png(export_dir, find_layer(data, picked_uid))
    check(both[front_pixel] > .9 and both[top_pixel] > .9 and both[back_pixel] < .1,
          f'the ID color mask keeps both picked UV chunks and nothing else ({both[front_pixel]:.2f}, {both[top_pixel]:.2f}, {both[back_pixel]:.2f})')
    yield from reveal(window, region, id_row, 'LAYERS')
    click(window, region, id_row)
    yield from settle()
    yield from reveal(window, region, 'FX_REMOVE_ID.0')
    click(window, region, 'FX_REMOVE_ID.0')
    yield from settle()
    check(len(active_effect(data).id_colors) == 0 and not has('FX_ID_COLOR.0'), 'Remove drops the extra ID color')
    yield from context_menu(window, region, picked_uid, 'EXPORT_MASK')
    single = mask_png(export_dir, find_layer(data, picked_uid))
    check(single[front_pixel] > .9 and single[top_pixel] < .1, 'after Remove the mask keeps only the first ID color again')

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

    click(window, region, 'ADD_FILL')
    yield from settle()
    legacy = active_layer(data)
    legacy_uid = legacy.uid
    source = find_layer(data, worn_uid)
    wear = next(effect for effect in source.effects if effect.uid == first_uid)
    flip = next(effect for effect in source.effects if effect.uid == filter_uid)
    for field in LAYER_GENERATOR_FIELDS:
        setattr(legacy, field, getattr(wear, field))
    data.serial += 1
    old_filter = legacy.effects.add()
    copy_effect(flip, old_filter)
    old_filter.uid = f'E{data.serial}'
    legacy_filter_uid = old_filter.uid
    legacy_values = {field: getattr(wear, field) for field in LAYER_GENERATOR_FIELDS[1:]}

    click(window, region, 'ADD_FILL')
    yield from settle()
    fresh_uid = active_layer(data).uid
    yield from add_effect(window, region, 'MASK', 'GENERATOR')
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.METAL_EDGE_WEAR')
    check(active_effect(data).gen_breakup == 'SCRATCH', 'picking Metal edge wear sets its scratch breakup as the explicit default')
    yield from context_menu(window, region, fresh_uid, 'EXPORT_MASK')
    reference = mask_png(export_dir, find_layer(data, fresh_uid))
    click(window, region, 'ADD_FILL')
    yield from settle()
    stored_uid = active_layer(data).uid
    data.serial += 1
    old_generator = active_layer(data).effects.add()
    copy_effect(find_layer(data, fresh_uid).effects[0], old_generator)
    old_generator.uid = f'E{data.serial}'
    old_generator.property_unset('gen_breakup')
    check(not old_generator.is_property_set('gen_breakup') and old_generator.gen_breakup == 'NOISE',
          'a Generator effect saved in the previous format carries no breakup choice')
    saved_file = scratch / 'legacy_generator.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    data = project.sets[0]
    stored = find_layer(data, legacy_uid)
    check(editor._active is None and stored.generator == 'EDGE_WEAR' and [effect.kind for effect in stored.effects] == ['FILTER'],
          'the reopened file holds a layer in the old format: its generator in layer fields and an Invert filter in the mask stack')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    migrated = find_layer(data, legacy_uid)
    effects = [(effect.kind, effect.target, effect.blend, round(effect.opacity, 3), effect.generator if effect.kind == 'GENERATOR' else effect.filter)
               for effect in migrated.effects]
    moved = migrated.effects[0]
    check(editor._active is not None and migrated.generator == 'NONE'
          and effects == [('GENERATOR', 'MASK', 'MULTIPLY', 1.0, 'EDGE_WEAR'), ('FILTER', 'MASK', 'MIX', 1.0, 'INVERT')]
          and migrated.effects[1].uid == legacy_filter_uid and all(getattr(moved, field) == value for field, value in legacy_values.items())
          and f'{legacy_uid}.{moved.uid}.gen.range' in nodes(data),
          f'opening Devil Painter moves the old generator into the mask stack first, multiplied at full opacity, with its settings {effects}')
    yield from context_menu(window, region, legacy_uid, 'EXPORT_MASK')
    upgraded = mask_png(export_dir, find_layer(data, legacy_uid))
    difference = float(numpy.abs(upgraded - inverted)[island].mean())
    check(difference < .02, f'the migrated old document renders the same mask as the same generator and Invert built in the new stack ({difference:.4f})')
    previous = find_layer(data, stored_uid).effects[0]
    check(previous.is_property_set('gen_breakup') and previous.gen_breakup == 'SCRATCH' and previous.gen_weight == 1.0,
          'opening Devil Painter gives a previous-format Metal edge wear its old scratch breakup and a full edges weight')
    yield from context_menu(window, region, stored_uid, 'EXPORT_MASK')
    migrated_mask = mask_png(export_dir, find_layer(data, stored_uid))
    gap = float(numpy.abs(migrated_mask - reference).max())
    check(gap == 0.0, f'the previous-format generator renders the same mask after migration as one built with the new settings ({gap:.4f})')

    click(window, region, 'ADD_FILL')
    yield from settle()
    breakup_uid = active_layer(data).uid
    yield from add_effect(window, region, 'MASK', 'GENERATOR')
    first_breakup = active_effect(data).uid

    def generator_effect(effect_uid):
        return next(item for item in find_layer(data, breakup_uid).effects if item.uid == effect_uid)

    def breakup_node(effect_uid, suffix='noise'):
        return nodes(data)[f'{breakup_uid}.{effect_uid}.gen.{suffix}']

    def breakup_export():
        chosen = active_effect(data).uid
        yield from context_menu(window, region, breakup_uid, 'EXPORT_MASK')
        values = mask_png(export_dir, find_layer(data, breakup_uid))
        yield from choose_effect(window, region, breakup_uid, chosen)
        return values

    def settings(effect_uid):
        effect = generator_effect(effect_uid)
        return {field: round(getattr(effect, field), 4) if isinstance(getattr(effect, field), float) else getattr(effect, field)
                for field in ('generator', 'gen_breakup') + GENERATOR_VALUES}

    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.EDGE_WEAR')
    yield from slide(window, region, 'GEN_NOISE', .8)
    check(control('GEN_WEIGHT').label == 'Edges' and control('GEN_BREAKUP').text == 'Noise' and has('GEN_DETAIL'),
          'Edge wear shows its edges term weight, its Noise breakup texture, and the breakup detail')
    yield from reveal(window, region, 'GEN_BREAKUP')
    click(window, region, 'GEN_BREAKUP')
    yield from settle()
    offered_breakups = [key.removeprefix('SET_BREAKUP.') for key in keys('SET_BREAKUP.')]
    check(offered_breakups == [item.key for item in BREAKUPS] and {'SCRATCH', 'CELLS', 'GRUNGE', 'CRACKS'} <= set(offered_breakups),
          f'the breakup menu offers the {len(offered_breakups)} built-in breakup textures and procedural patterns')
    press(window, 'ESC', *middle)
    yield from settle()
    for item in BREAKUPS:
        yield from pick_menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.' + item.key)
        texture = breakup_node(first_breakup)
        check(generator_effect(first_breakup).gen_breakup == item.key and texture.bl_idname == PATTERN[item.pattern].node
              and has('GEN_DETAIL') == item.detail and abs(texture.inputs['Scale'].default_value - generator_effect(first_breakup).gen_scale) < 1e-4,
              f'the {item.label} breakup drives the generator, with Detail {"shown" if item.detail else "hidden"}')
    yield from pick_menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.NOISE')
    noise_mask = yield from breakup_export()
    yield from pick_menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.CELLS')
    cells_mask = yield from breakup_export()
    switched = float(numpy.abs(cells_mask - noise_mask)[island].mean())
    check(switched > .02, f'switching the breakup texture from Noise to Cells changes the exported mask (mean difference {switched:.4f})')
    yield from pick_menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.GRUNGE')
    grunge_mask = yield from breakup_export()
    yield from slide(window, region, 'GEN_DETAIL', .2)
    detail = generator_effect(first_breakup).gen_detail
    check(abs(detail - 3.0) < .2 and abs(breakup_node(first_breakup).inputs['Detail'].default_value - detail) < 1e-4,
          f'the Detail slider sets the grunge breakup detail ({detail:.2f})')
    detailed_mask = yield from breakup_export()
    detail_change = float(numpy.abs(detailed_mask - grunge_mask)[island].mean())
    check(detail_change > .005, f'tuning the breakup detail changes the exported mask (mean difference {detail_change:.4f})')

    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.BUILDER')
    check(generator_effect(first_breakup).gen_breakup == 'NOISE' and [control(key).label for key in ('GEN_EDGES', 'GEN_DIRT', 'GEN_TOP')] == ['Edges', 'Dirt', 'Top']
          and not has('GEN_WEIGHT'), 'picking the mask builder restores its own Noise breakup and shows one weight per term')
    yield from slide(window, region, 'GEN_NOISE', .2)
    untouched = settings(first_breakup)
    builder_mask = yield from breakup_export()
    yield from slide(window, region, 'GEN_TOP', .9)
    tuned = settings(first_breakup)
    changed = [field for field in untouched if untouched[field] != tuned[field]]
    check(changed == ['gen_top'] and abs(breakup_node(first_breakup, 'gen_top').inputs[1].default_value - tuned['gen_top']) < 1e-4
          and breakup_node(first_breakup, 'gen_edges').inputs[1].default_value == untouched['gen_edges']
          and breakup_node(first_breakup, 'gen_dirt').inputs[1].default_value == untouched['gen_dirt'],
          f'tuning the top term changes only the top weight; edges, dirt, and the breakup stay fixed (changed {changed})')
    top_mask = yield from breakup_export()
    term_change = float(numpy.abs(top_mask - builder_mask)[island].mean())
    check(term_change > .02, f'tuning one term changes the exported mask (mean difference {term_change:.4f})')

    yield from add_effect(window, region, 'MASK', 'GENERATOR')
    second_breakup = active_effect(data).uid
    yield from pick_menu(window, region, 'GENERATOR', 'SET_GENERATOR.DIRT')
    yield from pick_menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.STRIPES')
    yield from slide(window, region, 'GEN_WEIGHT', .3)
    second = settings(second_breakup)
    check(settings(first_breakup) == tuned and second['gen_breakup'] == 'STRIPES' and abs(second['gen_weight'] - .3) < .05
          and breakup_node(first_breakup).bl_idname == 'ShaderNodeTexNoise' and breakup_node(second_breakup).bl_idname == 'ShaderNodeTexWave'
          and abs(breakup_node(second_breakup, 'gen_weight').inputs[1].default_value - second['gen_weight']) < 1e-4,
          'a second Generator on the same layer keeps its own breakup and term weight while the first keeps its settings')
    yield from choose_effect(window, region, breakup_uid, first_breakup)
    yield from pick_menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.BRICKS')
    check(settings(second_breakup) == second and generator_effect(first_breakup).gen_breakup == 'BRICKS'
          and breakup_node(first_breakup).bl_idname == 'ShaderNodeTexBrick' and breakup_node(second_breakup).bl_idname == 'ShaderNodeTexWave',
          'changing the first Generator breakup leaves the second Generator untouched')
    print('BREAKUP EVIDENCE', dict(texture_switch=round(switched, 4), detail=round(detail_change, 4), top_term=round(term_change, 4), migration=gap))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI MASK CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI mask test')
