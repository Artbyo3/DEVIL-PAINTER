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
from devil_painter.blending import BLEND_MODES, CHANNEL, FOLDER_BLENDS, srgb_to_linear
from devil_painter.document import active_layer, find_layer, geometry_attribute
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


def write_png(path, color):
    image = bpy.data.images.new(path.stem, 16, 16, alpha=False)
    image.pixels.foreach_set(numpy.tile(numpy.array(color, dtype=numpy.float32), 16 * 16))
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def nodes(data):
    return data.material.node_tree.nodes


def links(data):
    return data.material.node_tree.links


def screen_point(region, area, cube, face):
    center = cube.matrix_world @ cube.data.polygons[face].center
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, center)
    return region.x + point.x, region.y + point.y


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
    return cube, facing[0], facing[1]


def stroke_face(window, x, y):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 9):
        move(window, x + step * 4, y + step * 2)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 32), y=int(y + 16))


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


def add_effect(window, region, target, kind):
    opener = 'ADD_FX_' + target
    yield from reveal(window, region, opener)
    yield from menu(window, region, opener, f'NEW_FX.{target}.{kind}')


def slide(window, region, key, fx):
    yield from reveal(window, region, key)
    click(window, region, key, fx=fx)
    yield from settle()


def drag_row(window, region, source, target, fy, checks=()):
    x, y = spot(region, source, .6)
    tx, ty = spot(region, target, .6, fy)
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    yield from settle()
    for step in range(1, 7):
        move(window, x + (tx - x) * step / 6, y + (ty - y) * step / 6)
    yield from settle()
    for key, message in checks:
        check(has(key), message)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(tx), y=int(ty))
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


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    export_dir = scratch / 'layer_export'
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube, front, side = build_mesh(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    front_point = screen_point(region, area, cube, front)
    side_point = screen_point(region, area, cube, side)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'RES.1.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    project = cube.devil_painter
    body, trim = project.sets[0], project.sets[1]
    check(len(project.sets) == 2 and project.active_set == 0, 'the project has a Body and a Trim texture set')
    paint_uid = body.layers[0].uid
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    check(Path(project.export_directory) == export_dir, 'the export folder is typed into the export card')

    click(window, region, 'ADD_FILL')
    yield from settle()
    fill_uid = body.active_uid
    yield from reveal(window, region, 'BLEND.base_color')
    click(window, region, 'BLEND.base_color')
    yield from settle()
    offered = keys('SET_BLEND.base_color.')
    check(len(offered) == len(BLEND_MODES) and len(BLEND_MODES) >= 20 and {'SET_BLEND.base_color.DIVIDE', 'SET_BLEND.base_color.LINEAR_LIGHT',
          'SET_BLEND.base_color.HUE', 'SET_BLEND.base_color.EXCLUSION', 'SET_BLEND.base_color.NORMAL_DETAIL'} <= set(offered),
          'the blend dropdown offers every shader mix mode plus normal map detail')
    click(window, region, 'SET_BLEND.base_color.DIVIDE')
    yield from settle()
    check(nodes(body)[f'{fill_uid}.base_color'].blend_type == 'DIVIDE', 'picking Divide drives the base color mix node')
    if body.channels['normal'].enabled:
        if not find_layer(body, fill_uid).slots['normal'].enabled:
            yield from reveal(window, region, 'USE.normal')
            click(window, region, 'USE.normal')
            yield from settle()
        yield from reveal(window, region, 'BLEND.normal')
        yield from menu(window, region, 'BLEND.normal', 'SET_BLEND.normal.NORMAL_DETAIL')
        check(find_layer(body, fill_uid).slots['normal'].blend == 'NORMAL_DETAIL' and nodes(body)[f'{fill_uid}.normal'].blend_type == 'MIX',
              'normal map detail blends normals instead of mixing them')
    yield from reveal(window, region, 'BLEND.base_color')
    yield from menu(window, region, 'BLEND.base_color', 'SET_BLEND.base_color.MIX')

    click(window, region, 'ADD_FOLDER')
    yield from settle()
    folder_uid = body.active_uid
    yield from reveal(window, region, 'ROW_' + fill_uid, 'LAYERS')
    yield from drag_row(window, region, 'ROW_' + fill_uid, 'ROW_' + folder_uid, .5,
                        (('DROP_INTO', 'dragging a layer over the middle of a folder shows the drop-into marker'),))
    check(find_layer(body, fill_uid).parent == folder_uid, 'dropping a layer on a folder moves it into the folder')
    yield from select_row(window, region, folder_uid)
    yield from reveal(window, region, 'FOLDER_BLEND')
    click(window, region, 'FOLDER_BLEND')
    yield from settle()
    check(len(keys('SET_FOLDERBLEND.')) == len(FOLDER_BLENDS) and control('SET_FOLDERBLEND.PASSTHROUGH').active,
          'folders default to passthrough and offer every blend mode')
    click(window, region, 'SET_FOLDERBLEND.MULTIPLY')
    yield from settle()
    check(find_layer(body, folder_uid).folder_blend == 'MULTIPLY' and nodes(body)[f'{folder_uid}.base_color'].blend_type == 'MULTIPLY',
          'an isolated folder merges its children first, then multiplies onto the stack')
    yield from drag_row(window, region, 'ROW_' + paint_uid, 'ROW_' + folder_uid, .9,
                        (('DROP_LINE', 'dragging a layer near the top edge of a row shows the insertion line'),))
    order = [layer.uid for layer in body.layers]
    check(order.index(paint_uid) > order.index(folder_uid) and find_layer(body, paint_uid).parent == '',
          'dropping above a row reorders the stack')

    yield from select_row(window, region, fill_uid)
    yield from add_effect(window, region, 'MASK', 'FILL')
    layer = find_layer(body, fill_uid)
    fill_effect = layer.effects[-1].uid
    check(layer.effects[-1].kind == 'FILL' and body.target == 'EFFECT' and has(f'FX_{fill_uid}.{fill_effect}'),
          'a fill effect lands in the mask stack and shows as a row under the layer')
    check(control(f'FX_{fill_uid}.{fill_effect}').preview is not None, 'the fill effect row shows a pattern thumbnail')
    check(f'{fill_effect}.texture' in nodes(body), 'the fill effect drives a procedural pattern node in the mask')
    yield from reveal(window, region, 'FX_SOURCE')
    yield from menu(window, region, 'FX_SOURCE', 'SET_FXPATTERN.CELLS')
    check(layer.effects[0].pattern == 'CELLS' and nodes(body)[f'{fill_effect}.texture'].bl_idname == 'ShaderNodeTexVoronoi',
          'the fill effect pattern can be swapped from its source menu')
    yield from slide(window, region, 'FX_scale', .3)
    check(abs(layer.effects[0].scale - 15.0) < 1.5, 'the fill effect scale slider edits the pattern scale')
    yield from reveal(window, region, 'FX_BLEND')
    yield from menu(window, region, 'FX_BLEND', 'SET_FXBLEND.SUBTRACT')
    check(layer.effects[0].blend == 'SUBTRACT', 'mask effects pick how they combine with the mask below')

    textures = scratch / 'textures'
    textures.mkdir(exist_ok=True)
    write_png(textures / 'lone.png', (.3, .3, .3, 1.0))
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield from until(lambda: has('ITEM.0'), 'has("ITEM.0")')
    yield from reveal(window, region, 'FX_SOURCE')
    yield from menu(window, region, 'FX_SOURCE', 'FX_PICK_TEXTURE')
    check(editor._active.state.shelf_tab == 'TEXTURES' and has('ARM_INFO') and has('ITEM.0'), 'picking a texture for the fill effect arms the texture shelf')
    click(window, region, 'ITEM.0')
    yield from settle()
    effect = layer.effects[0]
    check(effect.source == 'IMAGE' and effect.texture is not None and effect.texture.name.startswith('lone')
          and any(node.bl_idname == 'ShaderNodeTexImage' and node.image == effect.texture for node in nodes(body)),
          'a shelf texture fills the mask effect through an image node')
    check(control(f'FX_{fill_uid}.{fill_effect}').preview == effect.texture, 'the texture fill effect row shows the texture as its thumbnail')
    yield from reveal(window, region, 'FX_SOURCE')
    yield from menu(window, region, 'FX_SOURCE', 'SET_FXPATTERN.CELLS')
    yield from add_effect(window, region, 'MASK', 'LEVELS')
    yield from slide(window, region, 'FX_gamma', .5)
    levels = layer.effects[-1]
    check(levels.kind == 'LEVELS' and abs(levels.gamma - 2.0) < .1 and any(node.bl_idname == 'ShaderNodeMath' and node.operation == 'POWER'
          and abs(node.inputs[1].default_value - 1 / levels.gamma) < 1e-4 for node in nodes(body)), 'levels remaps the mask with a gamma curve')
    yield from slide(window, region, 'FX_in_high', .8)
    check(abs(levels.in_high - .8) < .05 and any(node.bl_idname == 'ShaderNodeMapRange' and abs(node.inputs['From Max'].default_value - levels.in_high) < 1e-4
                                               for node in nodes(body)), 'levels input range feeds a map range node')

    yield from add_effect(window, region, 'MASK', 'FILTER')
    yield from reveal(window, region, 'FX_FILTER')
    click(window, region, 'FX_FILTER')
    yield from settle()
    check(has('SET_FXFILTER.BLUR') and has('SET_FXFILTER.THRESHOLD') and not has('SET_FXFILTER.HSV'),
          'mask filters offer value filters and leave out color-only ones')
    click(window, region, 'SET_FXFILTER.THRESHOLD')
    yield from settle()
    threshold = layer.effects[-1].uid
    check(any(node.bl_idname == 'ShaderNodeMath' and node.operation == 'GREATER_THAN' for node in nodes(body)), 'the threshold filter cuts the mask')
    yield from reveal(window, region, f'FXEYE_{fill_uid}.{threshold}', 'LAYERS')
    click(window, region, f'FXEYE_{fill_uid}.{threshold}')
    yield from settle()
    check(not layer.effects[-1].enabled and not any(node.bl_idname == 'ShaderNodeMath' and node.operation == 'GREATER_THAN' for node in nodes(body)),
          'the effect eye turns an effect off without deleting it')

    yield from select_row(window, region, fill_uid)
    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    check(layer.effects[-1].target == 'CONTENT' and layer.effects[-1].filter == 'HSV'
          and any(node.bl_idname == 'ShaderNodeHueSaturation' for node in nodes(body)), 'a content filter adjusts hue, saturation and value of the layer')
    yield from reveal(window, region, 'FX_FILTER')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.GRADIENT_MAP')
    check(has('FXCOLOR.color') and has('FXCOLOR.color_b'), 'a gradient map shows its dark and light color swatches')
    yield from set_hex(window, region, 'FXCOLOR.color', '#FF0000')
    check(layer.effects[-1].color[0] > .9 and layer.effects[-1].color[1] < .05, 'the color picker edits the gradient map colors')
    yield from reveal(window, region, 'FX_FILTER')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.BLUR')
    images = sum(1 for node in nodes(body) if node.bl_idname == 'ShaderNodeTexImage')
    yield from select_row(window, region, paint_uid)
    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    yield from reveal(window, region, 'FX_FILTER')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.BLUR')
    blurred = sum(1 for node in nodes(body) if node.bl_idname == 'ShaderNodeTexImage')
    check(blurred >= images + 8, 'a blur filter samples the painted layer with a ring of offset taps')
    yield from slide(window, region, 'FX_radius', .5)
    check(abs(find_layer(body, paint_uid).effects[-1].radius - 16.0) < 1.0, 'the blur radius slider edits the filter')
    yield from reveal(window, region, 'FX_DELETE')
    click(window, region, 'FX_DELETE')
    yield from settle()
    check(len(find_layer(body, paint_uid).effects) == 0 and body.target == 'CONTENT', 'deleting an effect removes it from the stack')

    first, second = layer.effects[0].uid, layer.effects[1].uid
    yield from reveal(window, region, f'FX_{fill_uid}.{first}', 'LAYERS')
    yield from reveal(window, region, f'FX_{fill_uid}.{second}', 'LAYERS')
    yield from drag_row(window, region, f'FX_{fill_uid}.{first}', f'FX_{fill_uid}.{second}', .5)
    check([effect.uid for effect in layer.effects][:2] == [second, first], 'dragging an effect row reorders the effect stack')
    yield from reveal(window, region, 'FX_UP')
    click(window, region, 'FX_UP')
    yield from settle()
    check([effect.uid for effect in layer.effects].index(first) == 2, 'the effect arrows move the selected effect')

    yield from select_row(window, region, paint_uid)
    yield from add_effect(window, region, 'MASK', 'FILL')
    yield from reveal(window, region, 'FX_SOURCE')
    yield from menu(window, region, 'FX_SOURCE', 'SET_FXSOURCE.VALUE')
    yield from slide(window, region, 'FX_value', .001)
    paint_layer = find_layer(body, paint_uid)
    check(paint_layer.effects[-1].source == 'VALUE' and paint_layer.effects[-1].value < .02 and paint_layer.effects[-1].blend == 'MULTIPLY',
          'a black value fill hides the layer through its mask')
    yield from add_effect(window, region, 'MASK', 'PAINT')
    painted = paint_layer.effects[-1]
    check(painted.kind == 'PAINT' and painted.image is not None and bpy.context.scene.tool_settings.image_paint.canvas == painted.image,
          'selecting a paint effect sends the brush into the effect image')
    check(control(f'FX_{paint_uid}.{painted.uid}').preview == painted.image, 'the paint effect row shows its painted image as the thumbnail')
    click(window, region, 'BRUSH_COLOR')
    yield from settle()
    click(window, region, 'COLOR_HEX')
    yield from settle()
    type_text(window, '#FFFFFF', *spot(region, 'COLOR_HEX'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    stroke_face(window, *front_point)
    yield from settle()
    check(pixels(painted.image)[:, 3].max() > .5, 'a brush stroke paints into the paint effect')
    yield from context_menu(window, region, paint_uid, 'EXPORT_MASK')
    mask_file = export_dir / f'{bpy.path.clean_name(paint_layer.name)}_Mask.png'
    check(mask_file.exists(), 'Export mask writes the flattened mask to the export folder')
    mask = png(mask_file)
    check(mask[:, 0].max() > .9 and numpy.mean(mask[:, 0] > .5) < .2, 'the exported mask is black except where the paint effect revealed it')

    click(window, region, 'ADD_PAINT')
    yield from settle()
    compare_uid = body.active_uid
    yield from add_effect(window, region, 'MASK', 'COMPARE')
    yield from reveal(window, region, 'FX_OTHER')
    yield from menu(window, region, 'FX_OTHER', f'SET_FXOTHER.{paint_uid}')
    compare_layer = find_layer(body, compare_uid)
    check(compare_layer.effects[-1].other == paint_uid, 'compare mask points at another layer')
    yield from context_menu(window, region, compare_uid, 'EXPORT_MASK')
    compared = png(export_dir / f'{bpy.path.clean_name(compare_layer.name)}_Mask.png')
    check(numpy.abs(compared[:, 0] - mask[:, 0]).mean() < .02, 'a compare mask reuses the mask of the other layer pixel for pixel')
    yield from select_row(window, region, compare_uid)
    yield from add_effect(window, region, 'MASK', 'ANCHOR')
    yield from reveal(window, region, 'FX_OTHER')
    yield from menu(window, region, 'FX_OTHER', f'SET_FXOTHER.{fill_uid}')
    yield from reveal(window, region, 'FX_CHANNEL')
    yield from menu(window, region, 'FX_CHANNEL', 'SET_FXCHANNEL.base_color')
    anchored = nodes(body)[f'{fill_uid}.base_color']
    check(any(link.from_node == anchored and link.to_node.bl_idname == 'ShaderNodeRGBToBW' for link in links(body)),
          'an anchor feeds the base color result of another layer into this mask')

    yield from select_row(window, region, compare_uid)
    yield from select_row(window, region, paint_uid, ctrl=True)
    check(editor._active.state.multi == {compare_uid, paint_uid} and control('ROW_' + compare_uid).active and control('ROW_' + paint_uid).active,
          'Ctrl-click adds layers to the selection and highlights every selected row')
    yield from context_menu(window, region, paint_uid, 'HIDE_SELECTED')
    check(not find_layer(body, paint_uid).visible and not find_layer(body, compare_uid).visible, 'hiding the selection hides every selected layer')
    yield from context_menu(window, region, paint_uid, 'SHOW_SELECTED')
    check(find_layer(body, paint_uid).visible and find_layer(body, compare_uid).visible, 'showing the selection shows them again')
    count = len(body.layers)
    yield from context_menu(window, region, paint_uid, 'DUPLICATE_SELECTED')
    check(len(body.layers) == count + 2, 'duplicating the selection copies every selected layer')
    copies = [layer.uid for layer in body.layers if layer.name.endswith(' copy')]
    check(len(copies) == 2 and all(len(find_layer(body, uid).effects) for uid in copies), 'duplicates keep their effect stacks')
    yield from select_row(window, region, copies[0])
    yield from select_row(window, region, copies[1], ctrl=True)
    yield from context_menu(window, region, copies[0], 'DELETE_SELECTED')
    check(len(body.layers) == count and not any(find_layer(body, uid) for uid in copies), 'deleting the selection removes every selected layer')
    yield from select_row(window, region, folder_uid)
    yield from select_row(window, region, compare_uid, shift=True)
    check({folder_uid, compare_uid} <= editor._active.state.multi and len(editor._active.state.multi) >= 3, 'Shift-click selects a range of rows')
    yield from select_row(window, region, compare_uid)
    yield from select_row(window, region, paint_uid, ctrl=True)
    yield from context_menu(window, region, paint_uid, 'GROUP')
    group_uid = find_layer(body, paint_uid).parent
    check(group_uid and find_layer(body, group_uid).kind == 'FOLDER' and find_layer(body, compare_uid).parent == group_uid,
          'grouping puts the selected layers into a new folder')

    yield from select_row(window, region, paint_uid)
    x, y = spot(region, 'ROW_' + paint_uid, .6)
    press(window, 'C', x, y, ctrl=True)
    yield from settle()
    count = len(body.layers)
    press(window, 'V', x, y, ctrl=True)
    yield from settle()
    pasted = find_layer(body, body.active_uid)
    check(len(body.layers) == count + 1 and pasted.uid != paint_uid and len(pasted.effects) == len(find_layer(body, paint_uid).effects),
          'Ctrl+C and Ctrl+V over the layers paste a copy with its effects')
    source_paint = next(effect for effect in find_layer(body, paint_uid).effects if effect.kind == 'PAINT')
    copied_paint = next(effect for effect in pasted.effects if effect.kind == 'PAINT')
    check(copied_paint.image is not None and copied_paint.image != source_paint.image
          and numpy.allclose(pixels(copied_paint.image), pixels(source_paint.image)), 'pasted paint effects get their own copy of the painted image')
    before = len(find_layer(body, compare_uid).effects)
    yield from context_menu(window, region, compare_uid, 'PASTE_EFFECTS')
    check(len(find_layer(body, compare_uid).effects) == before + len(find_layer(body, paint_uid).effects), 'Paste effects appends the copied effect stack')
    before = len([effect for effect in find_layer(body, compare_uid).effects if effect.target == 'MASK'])
    yield from context_menu(window, region, compare_uid, 'PASTE_MASK')
    check(len([effect for effect in find_layer(body, compare_uid).effects if effect.target == 'MASK']) > before, 'Paste mask brings over the mask effects')

    yield from context_menu(window, region, fill_uid, 'INSTANCE_INTO.1')
    link = next((item for item in trim.layers if item.kind == 'INSTANCE'), None)
    check(link is not None and link.link_set == body.name and link.link_uid == fill_uid, 'Instance into Trim adds a linked layer to the other set')
    check(f'{link.uid}.base_color' in nodes(trim) and f'{fill_effect}.texture' in nodes(trim),
          'the instance composes the source layer and its effects into the Trim material')
    yield from select_row(window, region, fill_uid)
    yield from set_hex(window, region, 'SWATCH.base_color', '#00FF00')
    constant = nodes(trim).get(f'{link.uid}.base_color.const')
    mix = nodes(trim)[f'{link.uid}.base_color']
    value = constant.outputs[0].default_value if constant else next(item for item in mix.inputs if item.name == 'B' and item.type == 'RGBA').default_value
    check(value[1] > .9 and value[0] < .1, 'editing the source layer updates its instance in the other set')
    click(window, region, 'SET.1')
    yield from settle()
    check(project.active_set == 1 and has('ROW_' + link.uid) and has('LINKED_' + link.uid), 'the instance row shows a link badge')
    yield from select_row(window, region, link.uid)
    check(has('INSTANCE_INFO') and body.name in control('INSTANCE_INFO').label, 'the instance properties name the source set')
    click(window, region, 'SET.0')
    yield from settle()

    click(window, region, 'ADD_PAINT')
    yield from settle()
    geo_uid = body.active_uid
    yield from reveal(window, region, 'GEO_MASK')
    click(window, region, 'GEO_MASK')
    yield from settle()
    geo_layer = find_layer(body, geo_uid)
    name = geometry_attribute(body, geo_layer)
    check(geo_layer.geo_mask and name in cube.data.attributes and editor._active.state.geo_pick == 'FACE'
          and any(node.bl_idname == 'ShaderNodeAttribute' and node.attribute_name == name for node in nodes(body)),
          'turning on the geometry mask reads a face attribute in the material')
    press(window, 'LEFTMOUSE', *front_point)
    yield from settle()
    values = numpy.zeros(len(cube.data.polygons), dtype=numpy.float32)
    cube.data.attributes[name].data.foreach_get('value', values)
    check(values[front] == 1.0 and values.sum() == 1.0, 'clicking a face adds it to the geometry mask')
    yield from context_menu(window, region, geo_uid, 'EXPORT_MASK')
    geo_mask = png(export_dir / f'{bpy.path.clean_name(geo_layer.name)}_Mask.png')
    check(geo_mask[:, 0].max() > .9 and .02 < numpy.mean(geo_mask[:, 0] > .5) < .4, 'the exported geometry mask covers only the picked face')
    yield from select_row(window, region, geo_uid)
    yield from reveal(window, region, 'GEO_ISLANDS')
    click(window, region, 'GEO_ISLANDS')
    yield from settle()
    press(window, 'LEFTMOUSE', *side_point)
    yield from settle()
    cube.data.attributes[name].data.foreach_get('value', values)
    check(values.sum() == len(values), 'clicking a mesh part adds every connected face')
    yield from reveal(window, region, 'GEO_INVERT')
    click(window, region, 'GEO_INVERT')
    yield from settle()
    cube.data.attributes[name].data.foreach_get('value', values)
    check(values.sum() == 0.0, 'Invert swaps picked and unpicked faces')
    click(window, region, 'GEO_ISLANDS')
    yield from settle()
    check(editor._active.state.geo_pick == '', 'clicking the active pick mode again stops picking')

    click(window, region, 'ADD_FOLDER')
    yield from settle()
    flat_folder = body.active_uid
    click(window, region, 'ADD_FILL')
    yield from settle()
    red_uid = body.active_uid
    check(find_layer(body, red_uid).parent == flat_folder, 'a new fill layer lands inside the selected folder')
    yield from set_hex(window, region, 'SWATCH.base_color', '#FF0000')
    yield from slide(window, region, 'VALUE.roughness', .25)
    roughness = find_layer(body, red_uid).slots['roughness'].value
    folder_name = find_layer(body, flat_folder).name
    yield from context_menu(window, region, flat_folder, 'FLATTEN')
    flattened = active_layer(body)
    check(find_layer(body, flat_folder) is None and find_layer(body, red_uid) is None and flattened.kind == 'PAINT'
          and flattened.name == 'Flattened ' + folder_name, 'Flatten replaces the folder with one paint layer')
    color = pixels(flattened.image)
    covered = color[color[:, 3] > .5]
    check(len(covered) > 1000 and numpy.median(covered[:, 0]) > .95 and numpy.median(covered[:, 1]) < .05,
          'the flattened layer holds the composited red paint')
    rough = pixels(flattened.slots['roughness'].image)[color[:, 3] > .5, 0]
    check(abs(numpy.median(rough) - roughness) < .03, 'the flattened layer keeps the composited roughness')
    check(nodes(body).get(f'{flattened.uid}.base_color') is not None, 'the flattened layer composes into the material')
    stem = bpy.path.clean_name(flattened.name)
    yield from context_menu(window, region, flattened.uid, 'EXPORT_LAYER')
    base = export_dir / f'{stem}_{CHANNEL["base_color"].suffix}.png'
    check(base.exists() and (export_dir / f'{stem}_{CHANNEL["roughness"].suffix}.png').exists(), 'Export flattened writes one file per channel')
    exported = png(base)
    solid = exported[exported[:, 3] > .5]
    check(numpy.median(solid[:, 0]) > .95 and numpy.median(solid[:, 1]) < .05, 'the exported flattened color is the layer red')

    yield from select_row(window, region, paint_uid)
    yield from select_row(window, region, compare_uid, ctrl=True)
    yield from context_menu(window, region, paint_uid, 'FLATTEN')
    check(find_layer(body, paint_uid) is None and find_layer(body, compare_uid) is None and active_layer(body).kind == 'PAINT',
          'Flatten merges a multi-selection into one paint layer')

    click(window, region, 'ADD_FILL')
    yield from settle()
    leveled = active_layer(body)
    yield from set_hex(window, region, 'SWATCH.base_color', '#DADADA')
    gray_value = leveled.slots['base_color'].color[0]
    yield from add_effect(window, region, 'CONTENT', 'LEVELS')
    levels = leveled.effects[-1]
    check(has('FX_COMPONENT') and control('FX_COMPONENT').text == 'All' and has('FX_CLAMP') and control('FX_CLAMP').active,
          'content levels offer a channel picker starting on All and a clamp toggle that starts on')
    yield from reveal(window, region, 'FX_COMPONENT')
    yield from menu(window, region, 'FX_COMPONENT', 'SET_FXCOMPONENT.R')
    yield from slide(window, region, 'FX_out_high', .5)
    check(abs(levels.comp_out_high[0] - .5) < .03 and levels.out_high == 1.0 and tuple(levels.comp_out_high)[1:] == (1.0, 1.0)
          and control('FX_out_high').text == f'{levels.comp_out_high[0]:.2f}', 'with Red picked, the levels sliders edit the red channel only')
    yield from context_menu(window, region, leveled.uid, 'EXPORT_LAYER')
    exported = png(export_dir / f'{bpy.path.clean_name(leveled.name)}_{CHANNEL["base_color"].suffix}.png')
    rgb = srgb_to_linear(numpy.median(exported[exported[:, 3] > .5, :3], axis=0))
    wanted = (gray_value * levels.comp_out_high[0], gray_value, gray_value)
    check(numpy.abs(rgb - wanted).max() < .012, f'red levels scale only the red channel of the export {tuple(round(float(value), 3) for value in rgb)} '
          f'(expected {tuple(round(float(value), 3) for value in wanted)})')
    yield from reveal(window, region, f'FX_{leveled.uid}.{levels.uid}', 'LAYERS')
    click(window, region, f'FX_{leveled.uid}.{levels.uid}')
    yield from settle()
    yield from reveal(window, region, 'FX_COMPONENT')
    yield from menu(window, region, 'FX_COMPONENT', 'SET_FXCOMPONENT.ALL')
    check(control('FX_out_high').text == '1.00', 'back on All, the sliders show the levels of every channel again')
    yield from reveal(window, region, 'FX_CLAMP')
    click(window, region, 'FX_CLAMP')
    yield from settle()
    check(not levels.clamp and not control('FX_CLAMP').active and any(node.bl_idname == 'ShaderNodeMapRange' and not node.clamp for node in nodes(body)),
          'turning clamp off lets the levels ranges extend past their limits')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI LAYER CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI layer test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
