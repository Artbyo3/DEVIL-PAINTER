import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import gpu
import numpy
from mathutils import Matrix

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, painting, shelf, shortcuts, smart, thumbnails
from devil_painter.compositing import SIGNATURE_KEY, socket
from devil_painter.document import active_effect, texture_set
from devil_painter.ui_system import SURFACE_FLOATING
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, settle, until

TIMEOUT = 180
STARTED = time.time()
HIDDEN = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_gizmo_navigate')


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


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5):
    press(window, kind, *spot(region, key, fx, fy))


def drag(window, region, key, dx, dy):
    x, y = spot(region, key)
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 7):
        move(window, x + dx * step / 6, y + dy * step / 6)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def right_column(zones):
    return next(rect for side, index, rect in zones.strips if side == 'RIGHT' and index == 0)


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.top and b.y < a.top


def type_text(window, text, x, y):
    for _ in range(editor._active.state.text.cursor):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


def write_png(path, color):
    image = bpy.data.images.new(path.stem, 16, 16, alpha=False)
    image.pixels.foreach_set(numpy.tile(numpy.array(color, dtype=numpy.float32), 16 * 16))
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def shelf_index(label):
    return next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == label)


def tile_shown(key):
    if not has(key):
        return False
    item = control(key)
    return item.clip.contains(item.rect.x, item.rect.y) and item.clip.contains(item.rect.x + item.rect.w, item.rect.top)


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
            viewport = editor._active.workspace.scroll_areas[panel][0]
            x, y = region.x + viewport.x + viewport.w / 2, region.y + viewport.y + viewport.h / 2
            window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
            window.event_simulate(type=direction, value='PRESS', x=int(x), y=int(y))
            yield from settle()
            if direction == 'WHEELUPMOUSE' and editor._active.state.scroll.get(panel, 0.0) <= 0.0:
                break
        if shown(key):
            break
    check(shown(key), key + ' scrolls into view')


def png_pixels(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    bpy.data.images.remove(image)
    return values.reshape(-1, 4)


def stroke(window, region):
    x, y = region.x + region.width * .42, region.y + region.height * .45
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 13):
        move(window, x + step * 6, y + step * 3)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 72), y=int(y + 36))


def alpha(image):
    pixels = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(-1, 4)[:, 3]


def tree_nodes(data):
    return data.material.node_tree.nodes


def surface_source(data):
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    return output.inputs['Surface'].links[0].from_node


def upstream_image(node):
    pending, seen = [node], set()
    while pending:
        current = pending.pop()
        if current.type == 'TEX_IMAGE':
            return current.image
        seen.add(current.name)
        pending.extend(link.from_node for socket in current.inputs for link in socket.links if link.from_node.name not in seen)
    return None


def rendered_pixel(window, area, region, point):
    offscreen = gpu.types.GPUOffScreen(region.width, region.height)
    with offscreen.bind():
        framebuffer = gpu.state.active_framebuffer_get()
        framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix(((2 / region.width, 0, 0, -1), (0, 2 / region.height, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1))))
            with bpy.context.temp_override(window=window, area=area, region=region):
                editor._active.workspace = editor._active.make_layout()
                editor._active.renderer.draw(editor._active)
        pixel = tuple(framebuffer.read_color(int(point[0]), int(point[1]), 1, 1, 4, 0, 'FLOAT').to_list()[0][0])
    offscreen.free()
    return pixel


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test material library lives in scratch, not the user library')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    for managed in library.managed_folder().iterdir():
        managed.unlink()
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    space = area.spaces.active
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from until(lambda: editor._active is not None and not any(getattr(space, name) for name in HIDDEN), "Blender to finish hiding its regions")
    check(editor._active is not None, 'Ctrl+Alt+P opens Devil Painter over the 3D viewport')
    check(not any(getattr(space, name) for name in HIDDEN), "Blender's header, tool header, toolbar and navigation gizmo are hidden")
    check(control('TARGET').label == 'Cube', 'the start card offers to paint the selected mesh')

    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = texture_set(cube)
    paint_layer = data.layers[0]
    check(cube.devil_painter.enabled and len(cube.devil_painter.sets) == 1 and data.resolution == 1024 and len(data.layers) == 1 and paint_layer.kind == 'PAINT', 'Start painting creates a 1K stack with a paint layer')
    check(cube.mode == 'TEXTURE_PAINT' and space.shading.type == 'MATERIAL', 'the viewport switches to texture paint with material preview')
    check(bpy.context.scene.tool_settings.image_paint.canvas == data.stroke and data.stroke_owner == paint_layer.uid,
          'the brush paints into the stroke buffer of the selected layer')
    check(has('PANEL_LAYERS') and has('PANEL_PROPERTIES'), 'the right column shows the layers and properties panels')
    check(control('SET_NAME').label.startswith('Cube'), 'the workspace bar names the texture set')
    zones = editor._active.workspace.zones
    bar, strip, dock, column = zones.rects['BAR'], zones.rects['STRIP'], zones.rects['DOCK'], right_column(zones)
    check(not any(overlaps(a, b) for a, b in ((bar, strip), (bar, column), (strip, column), (dock, column), (dock, zones.stage), (zones.stage, column))),
          'the workspace bar, tool strip, dock, stage and column never overlap')
    size_rect = control('BRUSH_SIZE').rect
    check(strip.contains(size_rect.x + 1, size_rect.y + 1) and strip.y < bar.y, 'brush settings sit in the tool strip under the workspace bar')
    check(not space.show_region_tool_header, 'the tool header stays hidden after a brush is activated')

    stroke(window, region)
    yield from settle()
    check(alpha(paint_layer.image).max() > .5 and alpha(data.stroke).max() == 0.0, 'a brush stroke in the viewport paints the layer')
    roughness_canvas = paint_layer.slots['roughness'].image
    check(paint_layer.slots['roughness'].source == 'IMAGE' and roughness_canvas is not None and not paint_layer.slots['height'].image,
          'the same stroke paints the roughness canvas and leaves channels the brush skips alone')

    click(window, region, 'BRUSH_CARD')
    yield from settle()
    check(all(has(key) for key in ('BRUSH_FLOW', 'BRUSH_SPACING', 'BRUSH_HARDNESS', 'BRUSH_SMOOTHING', 'BRUSH_JITTER', 'BRUSHUSE.metallic')),
          'the brush card offers flow, spacing, hardness, smoothing, jitter and the painted channels')
    rect = control('BRUSH_HARDNESS').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .8, region.y + rect.y + rect.h / 2)
    yield from settle()
    brush = bpy.context.scene.tool_settings.image_paint.brush
    check(abs(data.brush_hardness - .8) < .05 and brush.curve_distance_falloff_preset == 'CUSTOM' and brush.library is None,
          'hardness shapes the falloff of the Devil Painter brush')
    rect = control('BRUSH_SMOOTHING').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .5, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(brush.use_smooth_stroke and data.brush_preset == 'Custom', 'smoothing turns on the stroke stabilizer')
    click(window, region, 'BRUSH_PRESSURE_SIZE')
    yield from settle()
    check(data.brush_pressure_size and bpy.context.scene.tool_settings.image_paint.brush.use_pressure_size, 'pen pressure can drive the brush size')
    press(window, 'ESC', *middle)
    yield from settle()
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    yield from until(lambda: control('ITEM.0').preview is not None, 'control("ITEM.0").preview is not None')
    check(control('ITEM.0').preview is not None, 'brush presets show stroke previews')
    click(window, region, f'ITEM.{shelf_index("Hard Round")}')
    yield from settle()
    brush = bpy.context.scene.tool_settings.image_paint.brush
    check(data.brush_preset == 'Hard Round' and brush.spacing == 8 and not brush.use_smooth_stroke, 'clicking a brush preset sets the brush')
    click(window, region, 'SHELF_TAB.ALPHAS')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Star")}')
    yield from settle()
    check(data.brush_alpha is not None and brush.mask_texture is not None and brush.mask_texture.image == data.brush_alpha,
          'clicking an alpha stamps the brush with it')
    move(window, region.x + 4, region.y + 4)
    yield from settle()
    check(control('BRUSH_ALPHA').preview == data.brush_alpha, 'the tool strip shows the brush alpha')
    click(window, region, f'ITEM.{shelf_index("No alpha")}')
    yield from settle()
    check(data.brush_alpha is None and brush.mask_texture is None, 'No alpha clears the stamp')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()

    rect = control('BRUSHVAL.metallic').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w - 1, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(data.brush_slots['metallic'].value > .95, 'the metallic chip in the tool strip sets what the brush paints')
    stroke(window, region)
    yield from settle()
    metallic_canvas = paint_layer.slots['metallic'].image

    def channel_max(image):
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
        return float(values.reshape(-1, 4)[:, 0].max())

    check(channel_max(metallic_canvas) > .9, 'one stroke paints color, roughness and metallic together')
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = texture_set(cube)
    paint_layer = data.layers[0]
    check(editor._active is not None and channel_max(bpy.data.images[metallic_canvas.name]) < .1, 'Ctrl+Z undoes the stroke on every channel')
    press(window, 'Z', *middle, ctrl=True, shift=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = texture_set(cube)
    paint_layer = data.layers[0]
    check(channel_max(bpy.data.images[metallic_canvas.name]) > .9 and alpha(data.stroke).max() == 0.0, 'Ctrl+Shift+Z repaints it')
    rect = control('BRUSHVAL.metallic').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + 1, region.y + rect.y + rect.h / 2)
    yield from settle()

    click(window, region, 'ADD_FILL')
    yield from settle()
    fill = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(len(data.layers) == 2 and fill.kind == 'FILL' and data.layers[1].uid == fill.uid, '+ Fill adds a fill layer above the paint layer')
    check(all(has(f'USE.{key}') for key in ('base_color', 'roughness', 'metallic', 'normal', 'height')) and not has('USE.emission'),
          'Properties lists one row per texture set channel')
    rect = control('VALUE.metallic').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w - 1, region.y + rect.y + rect.h / 2)
    yield from settle()
    metallic_slot = fill.slots['metallic']
    check(metallic_slot.value > .95, 'dragging the metallic slider sets the fill metallic')
    nodes = data.material.node_tree.nodes
    check(abs(socket(nodes[fill.uid + '.metallic'].inputs, 'B', 'RGBA').default_value[0] - metallic_slot.value) < 1e-5,
          'the material preview follows the metallic value')

    click(window, region, 'USE.height')
    yield from settle()
    rect = control('VALUE.height').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .9, region.y + rect.y + rect.h / 2)
    yield from settle()
    nodes = data.material.node_tree.nodes
    shader = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
    bump = next(node for node in nodes if node.type == 'BUMP')
    check(fill.slots['height'].enabled and fill.slots['height'].value > .85 and fill.uid + '.height' in nodes,
          'turning height on and dragging it adds the fill to the height channel')
    check(shader.inputs['Normal'].links[0].from_node == bump and bump.inputs['Height'].is_linked,
          'height drives a bump on the material normal')

    click(window, region, 'SWATCH.base_color')
    yield from settle()
    check(editor._active.state.popover is not None and has('COLOR_SV') and has('COLOR_HUE'), 'the fill swatch opens the custom color picker')
    click(window, region, 'COLOR_HUE', fx=.001)
    yield from settle()
    click(window, region, 'COLOR_SV', fx=.999, fy=.999)
    yield from settle()
    color = fill.slots['base_color'].color
    check(color[0] > .9 and color[1] < .05 and color[2] < .05, 'picking hue and saturation sets the fill color')
    click(window, region, 'COLOR_HEX')
    yield from settle()
    x, y = spot(region, 'COLOR_HEX')
    type_text(window, '#0000FF', x, y)
    yield from settle()
    color = fill.slots['base_color'].color
    check(color[2] > .9 and color[0] < .05, 'typing a hex color sets the fill color')
    press(window, 'LEFTMOUSE', region.x + region.width * .3, region.y + region.height * .1)
    yield from settle()
    check(editor._active.state.popover is None, 'clicking outside closes the color picker')

    color_target = fill.slots['base_color']
    click(window, region, 'SWATCH.base_color')
    yield from settle()
    check(has('RECENT.0') and has('COLOR_PICK'), 'the color card keeps recent swatches and offers an eyedropper')
    click(window, region, 'COLOR_PICK')
    yield from settle()
    check(editor._active.state.picking == 'base_color' and editor._active.state.popover is None, 'the eyedropper waits for a click on the model')
    before_pick = tuple(color_target.color)
    press(window, 'LEFTMOUSE', region.x + region.width * .45, region.y + region.height * .45)
    yield from settle()
    check(not editor._active.state.picking and tuple(color_target.color) != before_pick, 'clicking the model picks its color into the fill')
    click(window, region, 'SWATCH.base_color')
    yield from settle()
    click(window, region, 'RECENT.1')
    yield from settle()
    check(abs(color_target.color[2] - 1.0) < .02 and color_target.color[0] < .05, 'a recent swatch brings back the earlier blue')
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'BLEND.base_color')
    yield from settle()
    click(window, region, 'SET_BLEND.base_color.MULTIPLY')
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(fill.slots['base_color'].blend == 'MULTIPLY' and nodes[fill.uid + '.base_color'].blend_type == 'MULTIPLY'
          and fill.slots['height'].blend == 'MIX', 'the base color blend dropdown sets Multiply for that channel only')

    click(window, region, 'CHANNELS')
    yield from settle()
    check(has('CHANSET.emission') and not control('CHANSET.emission').active and has('CHANSET.user1') and has('CHANNELS_ALL'),
          'the Channels card lists every channel, export-only user channels, and an all-sets switch')
    click(window, region, 'CHANSET.emission')
    yield from settle()
    check(data.channels['emission'].enabled and has('SWATCH.emission') and has('CHANSET.opacity'),
          'adding emission to the texture set shows its row in Properties and keeps the card open')
    press(window, 'ESC', *middle)
    yield from settle()
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = texture_set(cube)
    check(editor._active is not None and has('ADD_PAINT'), 'Ctrl+Z keeps Devil Painter open')
    check(not data.channels['emission'].enabled and not has('SWATCH.emission'), 'Ctrl+Z undoes adding emission')
    press(window, 'Z', *middle, ctrl=True, shift=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = texture_set(cube)
    check(data.channels['emission'].enabled, 'Ctrl+Shift+Z redoes it')
    click(window, region, 'UNDO')
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = texture_set(cube)
    check(editor._active is not None and not data.channels['emission'].enabled, 'the dock Undo button undoes without closing Devil Painter')
    click(window, region, 'REDO')
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = texture_set(cube)
    paint_layer, fill = data.layers[0], data.layers[1]
    check(editor._active is not None and data.channels['emission'].enabled and has('SWATCH.emission'), 'the dock Redo button redoes it')

    click(window, region, 'VIEW')
    yield from settle()
    click(window, region, 'SOLO.roughness')
    yield from settle()
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    check(data.solo == 'roughness' and output.inputs['Surface'].links[0].from_node.type == 'EMISSION' and control('VIEW').text == 'Roughness',
          'View shows the roughness channel on its own')
    click(window, region, 'VIEW')
    yield from settle()
    click(window, region, 'SOLO.')
    yield from settle()
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    check(not data.solo and output.inputs['Surface'].links[0].from_node.type == 'BSDF_PRINCIPLED', 'View goes back to the full material')

    click(window, region, 'EYE_' + fill.uid)
    yield from settle()
    check(not fill.visible and fill.uid not in data.material[SIGNATURE_KEY], 'the eye hides the fill layer from the material')
    click(window, region, 'EYE_' + fill.uid)
    yield from settle()
    check(fill.visible and fill.uid in data.material[SIGNATURE_KEY], 'the eye shows the fill layer again')
    press(window, 'LEFTMOUSE', *spot(region, 'EYE_' + paint_layer.uid), alt=True)
    yield from settle()
    check(data.isolate == paint_layer.uid and f'{fill.uid}.base_color' not in tree_nodes(data) and f'{paint_layer.uid}.base_color' in tree_nodes(data)
          and control('EYE_' + fill.uid).icon == 'HIDE_ON' and fill.visible, 'Alt-clicking an eye shows only that layer without hiding the others for good')
    press(window, 'LEFTMOUSE', *spot(region, 'EYE_' + paint_layer.uid), alt=True)
    yield from settle()
    check(data.isolate == '' and f'{fill.uid}.base_color' in tree_nodes(data) and control('EYE_' + fill.uid).icon == 'HIDE_OFF',
          'Alt-clicking the eye again shows every layer')
    click(window, region, 'ROW_' + fill.uid, kind='RIGHTMOUSE')
    yield from settle()
    check(control('ISOLATE').label == 'Show only this layer', 'the layer menu offers Show only this layer')
    click(window, region, 'ISOLATE')
    yield from settle()
    check(data.isolate == fill.uid and f'{paint_layer.uid}.base_color' not in tree_nodes(data) and f'{fill.uid}.base_color' in tree_nodes(data),
          'Show only this layer isolates the layer in the material')
    click(window, region, 'ROW_' + fill.uid, kind='RIGHTMOUSE')
    yield from settle()
    check(control('ISOLATE').label == 'Show all layers', 'while isolated, the layer menu offers Show all layers')
    click(window, region, 'ISOLATE')
    yield from settle()
    check(data.isolate == '' and f'{paint_layer.uid}.base_color' in tree_nodes(data), 'Show all layers brings the whole stack back')

    click(window, region, 'ROW_' + fill.uid, kind='RIGHTMOUSE')
    yield from settle()
    check(has('DUPLICATE') and has('ADD_MASK_BLACK'), 'right-clicking a layer opens its context menu')
    click(window, region, 'ADD_MASK_BLACK')
    yield from settle()
    check(fill.mask is not None and alpha(fill.mask).max() == 0.0, 'the menu adds a black mask')
    check(bpy.context.scene.tool_settings.image_paint.canvas == fill.mask, 'painting now edits the mask')
    stroke(window, region)
    yield from settle()
    check(alpha(fill.mask).max() > .5, 'a brush stroke reveals the fill through its mask')
    check(control('MASKTHUMB_' + fill.uid).active and has('MASK_INFO') and not has('OPACITY'), 'with the mask selected, Properties shows the mask')
    click(window, region, 'SELECT_LAYER')
    yield from settle()
    check(data.target == 'CONTENT' and has('OPACITY') and not control('MASKTHUMB_' + fill.uid).active, 'Back to layer shows the layer properties again')
    click(window, region, 'MASKTHUMB_' + fill.uid)
    yield from settle()
    check(data.target == 'MASK' and has('MASK_INFO') and bpy.context.scene.tool_settings.image_paint.canvas == fill.mask,
          'clicking the mask thumbnail selects the mask for painting and editing')
    press(window, 'LEFTMOUSE', *spot(region, 'MASKTHUMB_' + fill.uid), alt=True)
    yield from settle()
    check(data.solo == 'mask:' + fill.uid and control('VIEW').text == 'Mask · ' + fill.name and data.target == 'MASK',
          'Alt-clicking the mask thumbnail shows that mask in the viewport and keeps it selected for painting')
    check(surface_source(data).type == 'EMISSION' and upstream_image(surface_source(data)) == fill.mask,
          'in mask view the material emits the layer mask instead of the shaded material')
    press(window, 'LEFTMOUSE', *spot(region, 'MASKTHUMB_' + fill.uid), alt=True)
    yield from settle()
    check(data.solo == '' and surface_source(data).type == 'BSDF_PRINCIPLED' and control('VIEW').text == 'Material',
          'Alt-clicking the mask thumbnail again goes back to the material')
    click(window, region, 'VIEW')
    yield from settle()
    check(has('SOLO.mask:' + fill.uid), 'the View menu offers the mask of the selected layer')
    click(window, region, 'SOLO.mask:' + fill.uid)
    yield from settle()
    check(data.solo == 'mask:' + fill.uid and surface_source(data).type == 'EMISSION', 'the View menu shows the mask in the viewport')
    click(window, region, 'VIEW')
    yield from settle()
    click(window, region, 'SOLO.')
    yield from settle()
    check(data.solo == '' and surface_source(data).type == 'BSDF_PRINCIPLED', 'the View menu goes back to the material')

    row = control('ROW_' + paint_layer.uid).rect
    card = next(rect for rect, _ in editor._active.workspace.cards if rect.contains(row.x + row.w / 2, row.y + row.h / 2))
    pixel = rendered_pixel(window, area, region, (card.x + card.w - 3, card.y + 3))
    check(all(abs(a - b) < .03 for a, b in zip(pixel[:3], SURFACE_FLOATING)), 'the layers panel renders in the Devil palette')

    click(window, region, 'ROW_' + fill.uid)
    click(window, region, 'ROW_' + fill.uid)
    yield from settle()
    check(editor._active.state.text is not None, 'double-clicking a layer starts renaming it in place')
    type_text(window, 'Rust', *spot(region, 'ROW_' + fill.uid))
    yield from settle()
    check(fill.name == 'Rust', 'typing a name and pressing Enter renames the layer')

    click(window, region, 'ROW_' + fill.uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'DUPLICATE')
    yield from settle()
    copy = data.layers[2]
    check(data.active_uid == copy.uid, 'the copy is selected above its source')
    check(len(data.layers) == 3 and copy.name == 'Rust copy' and copy.mask is not None and copy.mask != data.layers[1].mask,
          'Duplicate copies the layer with its own mask')

    scale = editor._active.workspace.scale
    red = numpy.zeros((data.resolution * data.resolution, 4), dtype=numpy.float32)
    red[:] = (1.0, 0.0, 0.0, 1.0)
    paint_layer = data.layers[0]
    paint_layer.image.pixels.foreach_set(red.ravel())
    paint_layer.image.update()
    row = control('ROW_' + paint_layer.uid).rect
    paint_thumb = rendered_pixel(window, area, region, (row.x + 46 * scale, row.y + row.h / 2))
    check(paint_thumb[0] > .9 and paint_thumb[1] < .1 and paint_thumb[2] < .1, 'the paint layer thumbnail shows the painted image')

    export_dir = scratch / 'export'
    click(window, region, 'EXPORT')
    yield from settle()
    check(has('EXPORT_DIR') and has('EXPORT_RUN') and has('BROWSE'), 'Export textures opens the custom export card')
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    check(Path(cube.devil_painter.export_directory) == export_dir, 'typing the folder sets the export directory')
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    files = {suffix: export_dir / f'Cube_Material_{suffix}.png' for suffix in ('BaseColor', 'Roughness', 'Metallic', 'Normal', 'Height', 'Emission')}
    check(all(path.is_file() for path in files.values()), 'Export writes one PNG per texture set channel')
    check(not (export_dir / 'Cube_Material_Opacity.png').exists(), 'channels outside the texture set are not exported')
    values = png_pixels(files['Height'])[:, 0]
    check(values.max() > .8 and abs(values.min() - .5) < .02, 'exported height rises only where the fill shows through its mask')
    metallic = bpy.data.images.load(str(files['Metallic']))
    values = numpy.empty(len(metallic.pixels), dtype=numpy.float32)
    metallic.pixels.foreach_get(values)
    check(values.max() > .9 and values.min() < .1, 'exported metallic is high only where the masks were painted')
    bpy.data.images.remove(metallic)

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(scratch / 'painted.blend'), copy=True)
    check(all(layer.image is None or layer.image.packed_file is not None for layer in data.layers), 'saving packs the painted layers into the .blend')

    check(has('SHELF_TAB.MATERIALS') and control('SHELF_TAB.MATERIALS').active and has('ITEM.0'), 'the material shelf shows material tiles')
    shelf_zone = editor._active.workspace.zones.rects['SHELF']
    check(not any(overlaps(shelf_zone, zone) for zone in (dock, column, editor._active.workspace.zones.stage)), 'the shelf sits in its own zone under the stage')
    first = library.BUILTIN_MATERIALS[0]
    yield from until(lambda: thumbnails.cache_path(first).is_file() and control('ITEM.0').preview is not None, 'thumbnails.cache_path(first).is_file() and control("ITEM.0").preview is not None')
    check(thumbnails.cache_path(first).is_file() and control('ITEM.0').preview is not None, 'material tiles get rendered sphere thumbnails')
    tile = control('ITEM.0').rect
    tile_pixel = rendered_pixel(window, area, region, (tile.x + tile.w / 2, tile.top - tile.w / 2))
    check(tile_pixel[0] > .2 and tile_pixel[0] > tile_pixel[2] * 2, 'the red plastic thumbnail renders red in the shelf')

    click(window, region, f'ITEM.{shelf_index("Gold")}')
    yield from settle()
    gold = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(gold.name == 'Gold' and gold.kind == 'FILL' and gold.slots['metallic'].value == 1.0 and not gold.slots['height'].enabled,
          'clicking Gold in the shelf adds a gold fill layer')
    click(window, region, f'ITEM.{shelf_index("Rust")}')
    yield from settle()
    rust = next(layer for layer in data.layers if layer.uid == data.active_uid)
    nodes = data.material.node_tree.nodes
    check(rust.slots['base_color'].source == 'PATTERN' and nodes[rust.uid + '.base_color.texture'].type == 'TEX_NOISE',
          'Rust lays down a procedural grunge pattern')
    check(has('SCALE.base_color') and has('SWATCHB.base_color') and has('PROJECTION') and control('PROJECTION').text == 'Tri-planar',
          'Properties shows the pattern parameters and the tri-planar projection')
    mapping = nodes[rust.uid + ':mapping']
    check(mapping.inputs['Vector'].links[0].from_socket.name == 'Object', 'tri-planar patterns use object coordinates')
    rect = control('SCALE.base_color').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .8, region.y + rect.y + rect.h / 2)
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(abs(nodes[rust.uid + '.base_color.texture'].inputs['Scale'].default_value - rust.slots['base_color'].scale) < 1e-4
          and rust.slots['base_color'].scale > 50, 'the scale slider sets the pattern scale in the material')
    click(window, region, 'PROJECTION')
    yield from settle()
    click(window, region, 'SET_PROJECTION.UV')
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(rust.projection == 'UV' and nodes[rust.uid + ':mapping'].inputs['Vector'].links[0].from_node == nodes[rust.uid + ':uv_transform']
          and nodes[rust.uid + ':uv_transform'].inputs['Vector'].links[0].from_socket.name == 'UV',
          'the projection dropdown switches the layer to UV mapping')

    click(window, region, 'SOURCE.roughness')
    yield from settle()
    click(window, region, 'PICK_PATTERN.roughness')
    yield from settle()
    check(editor._active.state.armed == 'roughness' and editor._active.state.shelf_tab == 'PATTERNS' and has('ARM_INFO'),
          'choosing Pattern from the shelf opens the pattern tab for roughness')
    click(window, region, f'ITEM.{shelf_index("Cells")}')
    yield from settle()
    check(rust.slots['roughness'].source == 'PATTERN' and rust.slots['roughness'].pattern == 'CELLS' and not editor._active.state.armed,
          'clicking a pattern drives the armed channel')

    textures = scratch / 'textures'
    textures.mkdir(exist_ok=True)
    write_png(textures / 'brick_basecolor.png', (.6, .2, .1, 1.0))
    write_png(textures / 'brick_roughness.png', (.7, .7, .7, 1.0))
    write_png(textures / 'brick_normal_gl.png', (.4, .6, 1.0, 1.0))
    write_png(textures / 'lone.png', (.1, .8, .2, 1.0))
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    check(has('SHELF_EMPTY') and has('TEXTURE_DIR'), 'the texture tab asks for a folder')
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield from until(lambda: sum(item.key.startswith('ITEM.') for item in editor._active.workspace.controls) == 4, 'sum(item.key.startswith("ITEM.") for item in editor._active.workspace.controls) == 4')
    check(library.texture_folder() == str(textures) and sum(item.key.startswith('ITEM.') for item in editor._active.workspace.controls) == 4,
          'typing a folder lists its textures in the shelf')
    yield from until(lambda: control('ITEM.0').preview is not None, 'control("ITEM.0").preview is not None')
    check(control('ITEM.0').preview is not None, 'texture tiles show the image thumbnails')
    click(window, region, 'SOURCE.base_color')
    yield from settle()
    click(window, region, 'PICK_TEXTURE.base_color')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("lone")}')
    yield from settle()
    slot = rust.slots['base_color']
    check(slot.source == 'IMAGE' and slot.image.name == 'lone.png' and has('IMAGE_NAME.base_color'), 'clicking a texture drives the armed channel')

    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    key = f'ITEM.{shelf_index("Brick")}'
    for _ in range(12):
        if tile_shown(key):
            break
        x, y = spot(region, 'ITEM.0')
        move(window, x, y)
        window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
        yield from settle()
    check(tile_shown(key), 'the material shelf scrolls to the texture set found in the folder')
    click(window, region, key)
    yield from settle()
    brick = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(brick.name == 'Brick' and brick.slots['roughness'].image.name == 'brick_roughness.png'
          and brick.slots['normal'].image.colorspace_settings.is_data and not brick.slots['metallic'].enabled,
          'a folder texture set becomes one fill layer with each map on its channel')

    rust_index = next(index for index, layer in enumerate(data.layers) if layer.uid == rust.uid)
    click(window, region, 'ROW_' + rust.uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'SAVE_MATERIAL')
    yield from settle()
    check(library.user_materials() and library.user_materials()[-1]['name'] == data.layers[rust_index].name
          and (library.library_root() / library.SETTINGS_FILE).is_file(), 'Save as material stores the layer in the user library')
    saved = next(index for index, item in enumerate(shelf.items('MATERIALS')) if item.user_index >= 0)
    check(shelf.items('MATERIALS')[saved].payload['slots']['base_color']['image'].endswith('lone.png'), 'the saved material keeps its texture file')

    export_dir = scratch / 'export_shelf'
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    normal = png_pixels(export_dir / 'Cube_Material_Normal.png')[:, :3]
    covered = numpy.abs(normal - (.5, .5, 1.0)).max(axis=1) > .02
    typical = numpy.median(normal[covered], axis=0)
    check(editor._active.message.startswith('Exported 6 textures') and covered.mean() > .3 and numpy.abs(typical[:2] - (.4, .6)).max() < .02,
          f'export bakes the texture set normal map into the normal channel, tilted by the Rust height below it (median {tuple(round(float(value), 3) for value in typical)})')

    def active():
        return next(layer for layer in data.layers if layer.uid == data.active_uid)

    def drag_to(key, fraction):
        rect = control(key).rect
        press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * fraction, region.y + rect.y + rect.h / 2)

    click(window, region, 'ADD_FOLDER')
    yield from settle()
    folder = active()
    folder_uid = folder.uid
    check(folder.kind == 'FOLDER' and has('FOLD_' + folder.uid) and has('OPACITY') and has('ADD_MASK_BLACK') and not has('USE.base_color'),
          '+ Folder adds a folder with its own opacity and mask')
    click(window, region, f'ITEM.{shelf_index("Copper")}')
    yield from settle()
    copper = active()
    check(copper.parent == folder.uid and control('MATERIAL_NAME').label == 'Material · Copper',
          'a material added while a folder is selected lands inside it as a material layer')
    yield from until(lambda: control('ROW_' + copper.uid).preview is not None, 'control("ROW_" + copper.uid).preview is not None')
    check(control('ROW_' + copper.uid).preview is not None, 'the material layer row shows its rendered material')
    drag_to('CHOPACITY.roughness', .5)
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(abs(copper.slots['roughness'].opacity - .5) < .05 and abs(nodes[copper.uid + '.roughness.opacity'].inputs[1].default_value - copper.slots['roughness'].opacity) < 1e-5,
          'the per-channel opacity slider sets that channel opacity in the material')
    drag_to('VALUE.metallic', .02)
    yield from settle()
    check(copper.slots['metallic'].value < .1, 'editing the material layer changes its channel')
    click(window, region, 'RESET_MATERIAL')
    yield from settle()
    check(copper.slots['metallic'].value == 1.0, 'Reset restores the material values')
    click(window, region, 'ADD_MASK_BLACK')
    yield from settle()
    mask = copper.mask
    click(window, region, 'SELECT_LAYER')
    yield from settle()
    click(window, region, 'REPLACE_MATERIAL')
    yield from settle()
    check(editor._active.state.armed and editor._active.state.shelf_tab == 'MATERIALS' and has('ARM_INFO'), 'Replace asks for a material from the shelf')
    click(window, region, f'ITEM.{shelf_index("Gold")}')
    yield from settle()
    check(copper.name == 'Gold' and abs(copper.slots['base_color'].color[2] - .336) < 1e-3 and copper.mask == mask,
          'replacing the material swaps every channel and keeps the mask')
    material_uid = copper.uid
    click(window, region, 'ROW_' + material_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'MOVE_OUT')
    yield from settle()
    moved = next(layer for layer in data.layers if layer.uid == material_uid)
    order = [layer.uid for layer in data.layers]
    check(moved.parent == '' and order.index(material_uid) > order.index(folder_uid), 'Move out of folder puts the layer above the folder')
    click(window, region, 'ROW_' + material_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'MOVE_INTO')
    yield from settle()
    moved = next(layer for layer in data.layers if layer.uid == material_uid)
    check(moved.parent == folder_uid, 'Move into folder below puts it back inside')
    click(window, region, 'FOLD_' + folder_uid)
    yield from settle()
    check(not has('ROW_' + material_uid), 'folding the folder hides its layers')
    click(window, region, 'FOLD_' + folder_uid)
    yield from settle()
    check(has('ROW_' + material_uid), 'unfolding shows them again')
    click(window, region, 'ROW_' + folder_uid)
    yield from settle()
    drag_to('OPACITY', .3)
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(abs(nodes[folder_uid + ':opacity'].inputs[1].default_value - next(layer for layer in data.layers if layer.uid == folder_uid).opacity) < 1e-5 and next(layer for layer in data.layers if layer.uid == folder_uid).opacity < .4
          and folder_uid + '.base_color' in nodes, 'folder opacity mixes the whole folder into the stack')

    library.import_textures([textures / 'lone.png'])
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.devil_painter.import_textures(directory=str(textures), files=[{'name': 'brick_roughness.png'}])
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    check(has('TEXTURE_IMPORT'), 'the texture tab offers Import')
    managed = [item for item in shelf.items('TEXTURES') if item.managed]
    check(len(managed) == 2 and all(library.is_managed(item.payload) for item in managed), 'Import copies textures into the library')
    click(window, region, 'ROW_' + material_uid)
    yield from settle()
    click(window, region, 'ITEM.0', kind='RIGHTMOUSE')
    yield from settle()
    check(has('ASSIGN_TEXTURE.roughness.0') and has('REMOVE_TEXTURE.0') and has('TEXTURE_FILL.0'), 'right-clicking a texture lists every channel to use it for')
    click(window, region, 'ASSIGN_TEXTURE.roughness.0')
    yield from settle()
    moved = next(layer for layer in data.layers if layer.uid == material_uid)
    check(moved.slots['roughness'].source == 'IMAGE' and moved.slots['roughness'].image.colorspace_settings.is_data,
          'Use for roughness assigns the texture as non-color data')
    removed = shelf.items('TEXTURES')[0].payload
    click(window, region, 'ITEM.0', kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'REMOVE_TEXTURE.0')
    yield from settle()
    check(not Path(removed).exists() and len([item for item in shelf.items('TEXTURES') if item.managed]) == 1, 'Remove from library deletes the imported copy')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()

    click(window, region, 'ROW_' + folder_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'DELETE')
    yield from settle()
    check(not any(layer.uid in {folder_uid, material_uid} for layer in data.layers), 'deleting a folder deletes the layers inside it')

    def map_pixels(key):
        image = data.maps[key].image
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
        return values.reshape(-1, 4)

    check(has('MAPS_EMPTY') and has('OPEN_BAKE'), 'the mesh maps panel invites a bake before any map exists')
    click(window, region, 'BAKE')
    yield from settle()
    check(all(has('BAKEMAP.' + key) for key in ('ao', 'curvature', 'thickness', 'position', 'world_normal', 'id', 'normal'))
          and has('BAKE_RUN') and not control('BAKEMAP.normal').active, 'the bake card lists every mesh map')
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(data.bake_samples <= 6, 'the samples slider sets the bake quality')
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    check(all(key in data.maps and data.maps[key].image is not None for key in ('ao', 'curvature', 'thickness', 'position', 'world_normal', 'id'))
          and 'normal' not in data.maps, 'Bake writes the selected mesh maps')
    check(cube.mode == 'TEXTURE_PAINT' and bpy.context.scene.render.engine != 'CYCLES', 'baking returns to texture paint mode and the render engine')
    position = map_pixels('position')
    covered = position[position[:, 3] > .5]
    check(covered[:, 0].min() < .15 and covered[:, 0].max() > .85, 'the position map spans the mesh bounds')
    curvature = map_pixels('curvature')[:, 0]
    check(curvature.max() > .6 and abs(numpy.median(curvature[curvature > .01]) - .5) < .08, 'curvature brightens the cube edges and stays neutral on flat faces')
    normal = map_pixels('world_normal')
    check(normal[:, 2].max() > .95 and normal[normal[:, 3] > .5][:, 2].min() < .05, 'the world normal map covers every face direction')
    check(has('MAP.ao') and has('MAP.curvature') and control('MAP.ao').preview == data.maps['ao'].image, 'the mesh maps panel shows map thumbnails')
    click(window, region, 'MAP.curvature')
    yield from settle()
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    viewed = output.inputs['Surface'].links[0].from_node
    check(data.solo == 'map:curvature' and viewed.type == 'EMISSION' and control('VIEW').text == 'Curvature', 'clicking a map thumbnail views it on the model')
    click(window, region, 'VIEW')
    yield from settle()
    check(has('SOLO.map:ao'), 'the View menu lists the baked maps')
    click(window, region, 'SOLO.')
    yield from settle()

    import bmesh
    detail = bpy.data.meshes.new('HighPoly')
    shape = bmesh.new()
    bmesh.ops.create_uvsphere(shape, u_segments=48, v_segments=24, radius=1.15)
    for face in shape.faces:
        face.smooth = True
    shape.to_mesh(detail)
    shape.free()
    high = bpy.data.objects.new('HighPoly', detail)
    bpy.context.scene.collection.objects.link(high)
    click(window, region, 'BAKE')
    yield from settle()
    click(window, region, 'BAKE_SOURCE')
    yield from settle()
    click(window, region, 'SET_SOURCE.HighPoly')
    yield from settle()
    click(window, region, 'BAKE')
    yield from settle()
    for key in ('ao', 'curvature', 'thickness', 'position', 'world_normal', 'id'):
        click(window, region, 'BAKEMAP.' + key)
        yield from settle()
    click(window, region, 'BAKEMAP.normal')
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    tangent = map_pixels('normal')
    covered = tangent[tangent[:, 3] > .5]
    check(data.bake_source == high and len(covered) and numpy.median(covered[:, 2]) > .8 and covered[:, 0].std() > .01,
          'the normal map bakes the high-poly surface in tangent space')
    check(cube.mode == 'TEXTURE_PAINT' and bpy.context.view_layer.objects.active == cube, 'baking keeps the painted mesh active')
    normal_map = next(node for node in data.material.node_tree.nodes if node.type == 'NORMAL_MAP')
    check(normal_map.inputs['Color'].links[0].from_node.type == 'VECT_MATH', 'the baked high-poly normal blends with the painted normal channel')
    bpy.data.objects.remove(high)

    click(window, region, f'ITEM.{shelf_index("Steel")}')
    yield from settle()
    steel = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(not has('GENERATOR'), 'a layer without generator effects shows no generator controls')
    yield from reveal(window, region, 'ADD_FX_MASK')
    click(window, region, 'ADD_FX_MASK')
    yield from settle()
    check(has('NEW_FX.MASK.GENERATOR'), 'the mask effect menu offers a Generator effect')
    click(window, region, 'NEW_FX.MASK.GENERATOR')
    yield from settle()
    wear = active_effect(data)
    wear_uid = wear.uid
    check(wear is not None and wear.kind == 'GENERATOR' and wear.target == 'MASK' and wear.blend == 'MULTIPLY' and has('GENERATOR'),
          'adding a Generator effect selects it and shows its generator controls')
    yield from reveal(window, region, 'GENERATOR')
    click(window, region, 'GENERATOR')
    yield from settle()
    check(not has('SET_GENERATOR.NONE'), 'a Generator effect is removed by deleting it, not by picking None')
    click(window, region, 'SET_GENERATOR.EDGE_WEAR')
    yield from settle()
    nodes = data.material.node_tree.nodes
    name = f'{steel.uid}.{wear_uid}'
    wear = active_effect(data)
    check(wear.generator == 'EDGE_WEAR' and name + '.gen.range' in nodes and has('GEN_LEVEL') and has('GEN_INVERT'),
          'Edge wear masks the layer from the baked curvature, with nodes named after the effect')
    sampled = [node for node in nodes if node.type == 'TEX_IMAGE' and node.image == data.maps['curvature'].image]
    check(len(sampled) == 1, 'the generator samples the curvature map in the material')
    yield from reveal(window, region, 'GEN_INVERT')
    rect = control('GEN_LEVEL').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .5, region.y + rect.y + rect.h / 2)
    yield from settle()
    wear = active_effect(data)
    ranged = data.material.node_tree.nodes[name + '.gen.range']
    check(abs(wear.gen_level - .5) < .05 and ranged.inputs['From Min'].default_value < wear.gen_level < ranged.inputs['From Max'].default_value,
          'the level slider moves the generator threshold')
    yield from reveal(window, region, 'GEN_INVERT')
    click(window, region, 'GEN_INVERT')
    yield from settle()
    check(active_effect(data).gen_invert and data.material.node_tree.nodes[name + '.gen.range'].inputs['To Min'].default_value == 1.0,
          'Invert flips the generated mask')
    click(window, region, 'SHELF_TAB.MASKS')
    yield from settle()
    yield from until(lambda: control('ITEM.0').preview is not None, 'control("ITEM.0").preview is not None')
    check(control('ITEM.0').preview is not None, 'smart masks show rendered previews')
    click(window, region, f'ITEM.{shelf_index("Dirt")}')
    yield from settle()
    stack = [effect for effect in steel.effects if effect.kind == 'GENERATOR']
    dirt = active_effect(data)
    check([effect.generator for effect in stack] == ['EDGE_WEAR', 'DIRT'] and dirt.generator == 'DIRT' and abs(dirt.gen_level - .3) < 1e-4
          and not dirt.gen_invert and stack[0].gen_invert
          and any(node.type == 'TEX_IMAGE' and node.image == data.maps['ao'].image for node in data.material.node_tree.nodes),
          'clicking the Dirt smart mask adds a second generator from the ambient occlusion map and keeps the first')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    for effect_uid in (dirt.uid, wear_uid):
        yield from reveal(window, region, f'FX_{steel.uid}.{effect_uid}', 'LAYERS')
        click(window, region, f'FX_{steel.uid}.{effect_uid}', fx=.6)
        yield from settle()
        yield from reveal(window, region, 'FX_DELETE')
        click(window, region, 'FX_DELETE')
        yield from settle()
    check(not any(effect.kind == 'GENERATOR' for effect in steel.effects) and not any('.gen.' in node.name for node in data.material.node_tree.nodes)
          and not has('GEN_LEVEL'), 'deleting the Generator effects removes their nodes')

    def layer_by(uid):
        return next(layer for layer in data.layers if layer.uid == uid)

    click(window, region, 'SHELF_TAB.SMART')
    yield from settle()
    yield from until(lambda: control('ITEM.0').preview is not None, 'control("ITEM.0").preview is not None')
    check(control('ITEM.0').preview is not None, 'smart materials show rendered stack previews')
    click(window, region, f'ITEM.{shelf_index("Rusty Iron")}')
    yield from settle()
    rusty = layer_by(data.active_uid)
    inside = [layer for layer in data.layers if layer.parent == rusty.uid]
    generated = [[effect.generator for effect in layer.effects if effect.kind == 'GENERATOR'] for layer in inside]
    check(rusty.kind == 'FOLDER' and rusty.name == 'Rusty Iron' and len(inside) == 3 and generated == [[], ['DIRT'], ['CAVITY']],
          'a smart material lands as a folder of layers with their generators')
    rusty_uid = rusty.uid
    click(window, region, 'ADD_PAINT')
    yield from settle()
    painted = layer_by(data.active_uid)
    painted_uid = painted.uid
    check(painted.parent == rusty_uid, 'a paint layer added while the folder is selected goes inside it')
    size = data.resolution
    red = numpy.zeros((size * size, 4), dtype=numpy.float32)
    red[:size * size // 2] = (1.0, 0.0, 0.0, 1.0)
    painted.image.pixels.foreach_set(red.ravel())
    painted.image.update()
    yield from reveal(window, region, 'ADD_MASK_WHITE')
    click(window, region, 'ADD_MASK_WHITE')
    yield from settle()
    check(layer_by(painted_uid).mask is not None, 'the painted layer has a mask to save')
    click(window, region, 'ROW_' + rusty_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'SAVE_SMART')
    yield from settle()
    saved = smart.smart_materials()[-1]
    paint_entry = next(item for item in saved['layers'] if item['kind'] == 'PAINT')
    check(saved['name'] == 'Rusty Iron' and len(saved['layers']) == 4 and Path(paint_entry['paint']).is_file() and Path(paint_entry['mask']).is_file(),
          'Save as smart material stores the folder, its layers, the painted image and the mask')
    user_tile = next(index for index, item in enumerate(shelf.items('SMART')) if item.user_index >= 0)
    click(window, region, f'ITEM.{user_tile}')
    yield from settle()
    copy = layer_by(data.active_uid)
    copied_paint = next(layer for layer in data.layers if layer.parent == copy.uid and layer.kind == 'PAINT')
    check(copy.uid != rusty_uid and copy.kind == 'FOLDER' and len([layer for layer in data.layers if layer.parent == copy.uid]) == 4
          and copied_paint.mask is not None and copied_paint.image != layer_by(painted_uid).image and alpha(copied_paint.image).max() == 1.0
          and copied_paint.image.packed_file is not None, 'applying the saved smart material rebuilds the stack with its painted pixels and mask')
    click(window, region, f'ITEM.{user_tile}', kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, f'DELETE_SMART.{shelf.items("SMART")[user_tile].user_index}')
    yield from settle()
    check(not smart.smart_materials(), 'a saved smart material can be deleted from the shelf')
    for uid in (copy.uid, rusty_uid):
        yield from reveal(window, region, 'ROW_' + uid, 'LAYERS')
        click(window, region, 'ROW_' + uid, kind='RIGHTMOUSE')
        yield from settle()
        click(window, region, 'DELETE')
        yield from settle()
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()

    click(window, region, 'SHELF_TOGGLE')
    yield from settle()
    check(not editor._active.state.shelf_open and not has('ITEM.0') and has('SHELF_TAB.MATERIALS'), 'the shelf collapses to its tabs')
    click(window, region, 'SHELF_TOGGLE')
    yield from settle()
    check(has('ITEM.0'), 'the shelf opens again')

    for _ in range(30):
        if 'LAYERS' in editor._active.workspace.scroll_areas and 'PROPERTIES' in editor._active.workspace.scroll_areas:
            break
        click(window, region, 'ADD_PAINT')
        yield from settle()
    check('LAYERS' in editor._active.workspace.scroll_areas, 'a long layer stack becomes scrollable')
    width = control('PANEL_LAYERS').rect.w
    drag(window, region, 'STRIP.RIGHT.0', -80, 0)
    yield from settle()
    check(control('PANEL_LAYERS').rect.w > width + 40, 'dragging the column edge widens the right column')
    check(has('SIZE.LAYERS'), 'the layers panel has a border to resize it')
    layers_height = editor._active.workspace.zones.rects['LAYERS'].h
    drag(window, region, 'SIZE.LAYERS', 0, -60)
    yield from settle()
    check(editor._active.workspace.zones.rects['LAYERS'].h > layers_height + 30, 'dragging the layers border gives the layers more room')
    for _ in range(4):
        click(window, region, 'ADD_PAINT')
        yield from settle()
    before = editor._active.state.scroll.get('LAYERS', 0.0)
    x, y = spot(region, 'PANEL_LAYERS', fy=-1.0)
    move(window, x, y)
    window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
    yield from settle()
    check(editor._active.state.scroll['LAYERS'] > before, 'the mouse wheel scrolls the layer stack')

    rows = sum(item.key.startswith('ROW_') for item in editor._active.workspace.controls)
    check(rows < len(data.layers), 'layer rows scrolled out of view are not built or drawn')
    layers_card = editor._active.workspace.zones.rects['LAYERS']
    layers_size = editor._active.state.section_heights['LAYERS']
    click(window, region, 'PANEL_PROPERTIES')
    yield from settle()
    check('PROPERTIES' in editor._active.state.collapsed and not has('OPACITY'), 'clicking a panel header collapses it')
    layers_now = editor._active.workspace.zones.rects['LAYERS']
    check(editor._active.state.section_heights['LAYERS'] == layers_size and layers_card.h - .5 <= layers_now.h <= (layers_size + 30) * editor._active.workspace.scale + .5,
          'collapsing properties keeps the layers panel at the size the user set, never growing past it')
    click(window, region, 'PANEL_PROPERTIES')
    yield from settle()
    check(has('OPACITY'), 'clicking it again expands it')

    rect = control('BRUSH_STRENGTH').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .25, region.y + rect.y + rect.h / 2)
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(abs(data.brush_opacity - .25) < .03 and abs(nodes['stroke.opacity'].inputs[1].default_value - data.brush_opacity) < 1e-5,
          'the opacity slider caps what one stroke can cover')
    click(window, region, 'ERASE')
    yield from settle()
    check(control('ERASE').active and bpy.context.scene.tool_settings.image_paint.canvas == data.stroke and data.stroke_tool == 'ERASE'
          and abs(painting.brush_value(bpy.context.scene, 'strength') - .25) < .03, 'the eraser collects its stroke in the buffer at the brush opacity')

    area_count = len(window.screen.areas)
    click(window, region, 'VIEW2D')
    yield from settle()
    flat = editor._active.flat_area
    data = texture_set(bpy.data.objects['Cube'])
    current = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(flat is not None and flat.type == 'IMAGE_EDITOR' and flat.spaces.active.ui_mode == 'PAINT' and len(window.screen.areas) == area_count + 1
          and control('VIEW2D').active, '2D view docks an image paint view beside the model')
    check(flat.spaces.active.image == (current.image if current.kind == 'PAINT' else current.mask) and not flat.spaces.active.show_region_header,
          'the 2D view shows the selected canvas without Blender headers')
    zones = editor._active.workspace.zones
    column = right_column(zones)
    check(not any(overlaps(zones.rects[key], column) for key in ('BAR', 'STRIP', 'SHELF')) and not overlaps(zones.stage, column),
          'the workspace still fits beside the 2D view')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    fresh = next(layer for layer in data.layers if layer.uid == data.active_uid)
    move(window, region.x + 10, region.y + 10)
    yield from settle()
    check(flat.spaces.active.image == fresh.image, 'the 2D view follows the selected layer')
    click(window, region, 'PAINT')
    yield from settle()
    flat_region = next(item for item in flat.regions if item.type == 'WINDOW')
    x, y = flat_region.x + flat_region.width * .5, flat_region.y + flat_region.height * .5
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 10):
        move(window, x + step * 4, y + step * 2)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 36), y=int(y + 18))
    yield from settle()
    check(alpha(fresh.image).max() > .1, 'painting in the 2D view paints the selected layer in UV space')
    click(window, region, 'VIEW2D')
    yield from settle()
    check(editor._active.flat_area is None and len(window.screen.areas) == area_count, 'clicking 2D view again closes it')
    click(window, region, 'VIEW2D')
    yield from settle()
    check(len(window.screen.areas) == area_count + 1, 'the 2D view opens again')

    press(window, 'E', *middle)
    yield from settle()
    check(control('ERASE').active, 'the E shortcut picks the eraser')
    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'OPEN_SHORTCUTS')
    yield from settle()
    click(window, region, 'BIND.FILL')
    yield from settle()
    press(window, 'K', *middle)
    yield from settle()
    check(shortcuts.bindings()['FILL'] == 'K' and control('BIND.FILL').label == 'K', 'a shortcut can be rebound by pressing the new key')
    press(window, 'ESC', *middle)
    yield from settle()
    press(window, 'K', *middle)
    yield from settle()
    check(control('FILL').active, 'the rebound key picks the fill tool')
    click(window, region, 'PAINT')
    yield from settle()

    click(window, region, 'VIEWPORT')
    yield from settle()
    shading = area.spaces.active.shading
    light = shading.studio_light
    click(window, region, 'ENV')
    yield from settle()
    names = [item.name for item in bpy.context.preferences.studio_lights if item.type == 'WORLD']
    click(window, region, f'SET_ENV.{next(index for index, name in enumerate(names) if name != light)}')
    yield from settle()
    check(shading.studio_light != light, 'the environment menu swaps the HDRI')
    click(window, region, 'VIEWPORT')
    yield from settle()
    for key, fraction in (('ENV_ROTATION', .75), ('ENV_STRENGTH', .25), ('CAMERA_FOV', .5)):
        rect = control(key).rect
        press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * fraction, region.y + rect.y + rect.h / 2)
        yield from settle()
    check(abs(shading.studiolight_rotate_z - 1.5708) < .1 and abs(shading.studiolight_intensity - .5) < .05 and abs(area.spaces.active.lens - 80) < 3,
          'the viewport card rotates and dims the environment and sets the lens')
    click(window, region, 'CAMERA_ORTHO')
    yield from settle()
    check(area.spaces.active.region_3d.view_perspective == 'ORTHO', 'the viewport card switches to orthographic')
    click(window, region, 'CAMERA_ORTHO')
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    data = texture_set(bpy.data.objects['Cube'])
    if not editor._active.state.shelf_open:
        click(window, region, 'SHELF_TOGGLE')
        yield from settle()
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    wood = f'ITEM.{shelf_index("Wood")}'
    shelf_height = editor._active.workspace.zones.rects['SHELF'].h
    drag(window, region, 'STRIP.BOTTOM.0', 0, 200)
    yield from settle()
    check(editor._active.workspace.zones.rects['SHELF'].h > shelf_height, 'dragging the shelf border makes the narrow shelf taller')
    yield from reveal(window, region, wood, 'SHELF')
    click(window, region, wood)
    yield from settle()
    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'SHADER.UNLIT')
    yield from settle()
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    check(data.shader == 'UNLIT' and output.inputs['Surface'].links[0].from_node.type == 'EMISSION', 'the project card switches the viewport shader')
    click(window, region, 'SHADER.PRINCIPLED')
    yield from settle()
    rect = control('NORMAL_STRENGTH').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .25, region.y + rect.y + rect.h / 2)
    yield from settle()
    nodes = data.material.node_tree.nodes
    check(abs(nodes['shader.normal_map'].inputs['Strength'].default_value - .5) < .05, 'shader settings drive the normal strength')
    click(window, region, 'PNF.DIRECTX')
    yield from settle()
    normal_map = data.material.node_tree.nodes['shader.normal_map']
    check(cube.devil_painter.normal_format == 'DIRECTX' and normal_map.inputs['Color'].links[0].from_node.type == 'COMBINE_COLOR',
          'a DirectX project flips the green channel into the shader')
    click(window, region, 'PNF.OPENGL')
    yield from settle()
    click(window, region, 'PHYS_USE')
    yield from settle()
    triplanar = next(layer for layer in data.layers if layer.name == 'Wood')
    scale = data.material.node_tree.nodes[triplanar.uid + ':mapping'].inputs['Scale'].default_value
    check(cube.devil_painter.use_physical and abs(scale[0] - triplanar.tiling * cube.scale[0] / cube.devil_painter.physical_size) < 1e-4,
          'real-world scale sizes tri-planar fills in meters')
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'CHANNELS')
    yield from settle()
    for key in ('ambient_occlusion', 'opacity', 'user1'):
        click(window, region, 'CHANSET.' + key)
        yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    nodes = data.material.node_tree.nodes
    shader = nodes['shader.bsdf']
    base_link = shader.inputs['Base Color'].links[0].from_node
    check(base_link.type == 'MIX' and base_link.blend_type == 'MULTIPLY', 'the ambient occlusion channel darkens the base color in the preview')
    check(data.material.surface_render_method == 'BLENDED' and shader.inputs['Alpha'].is_linked, 'the opacity channel makes the material transparent')
    check(data.channels['user1'].enabled and not any('user1' in link.from_node.name for link in shader.inputs['Base Color'].links),
          'user channels stay out of the shader')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'the close button closes Devil Painter')
    check(len(window.screen.areas) == area_count, 'closing Devil Painter also closes the 2D view')
    check(space.show_region_header and space.show_region_toolbar and space.show_gizmo_navigate, "closing restores Blender's header, toolbar and gizmo")
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(editor._active is not None and has('ADD_PAINT'), 'reopening shows the layer stack')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(editor._active is None, 'Ctrl+Alt+P closes Devil Painter again')

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
    devil_painter.unregister()
    check(not hasattr(bpy.types, 'DEVIL_PAINTER_OT_editor') and not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI EDITOR CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI editor test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0)
