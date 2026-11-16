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
from devil_painter import editor, painting
from devil_painter.compositing import SIGNATURE_KEY, socket
from devil_painter.ui_system import SURFACE_FLOATING
from tools.workspace import prepare_scratch

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


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.top and b.y < a.top


def type_text(window, text, x, y):
    for _ in range(80):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


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
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    space = area.spaces.active
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None, 'Ctrl+Alt+P opens Devil Painter over the 3D viewport')
    check(not any(getattr(space, name) for name in HIDDEN), "Blender's header, tool header, toolbar and navigation gizmo are hidden")
    check(control('TARGET').label == 'Cube', 'the start card offers to paint the selected mesh')

    click(window, region, 'RES_1024')
    yield 0.3
    click(window, region, 'START')
    yield 1.5
    data = cube.devil_painter
    paint_layer = data.layers[0]
    check(data.enabled and data.resolution == 1024 and len(data.layers) == 1 and paint_layer.kind == 'PAINT', 'Start painting creates a 1K stack with a paint layer')
    check(cube.mode == 'TEXTURE_PAINT' and space.shading.type == 'MATERIAL', 'the viewport switches to texture paint with material preview')
    check(bpy.context.scene.tool_settings.image_paint.canvas == paint_layer.image, 'the brush paints on the selected layer')
    check(has('PANEL_LAYERS') and has('PANEL_PROPERTIES'), 'the right column shows the layers and properties panels')
    check(control('SET_NAME').label.startswith('Cube'), 'the workspace bar names the texture set')
    zones = editor._active.workspace.zones
    check(not any(overlaps(a, b) for a, b in ((zones.bar, zones.strip), (zones.bar, zones.column), (zones.strip, zones.column),
                                               (zones.dock, zones.column), (zones.dock, zones.stage), (zones.stage, zones.column))),
          'the workspace bar, tool strip, dock, stage and column never overlap')
    size_rect = control('BRUSH_SIZE').rect
    check(zones.strip.contains(size_rect.x + 1, size_rect.y + 1) and zones.strip.y < zones.bar.y, 'brush settings sit in the tool strip under the workspace bar')
    check(not space.show_region_tool_header, 'the tool header stays hidden after a brush is activated')

    stroke(window, region)
    yield 1.0
    check(alpha(paint_layer.image).max() > .5, 'a brush stroke in the viewport paints the layer')

    click(window, region, 'ADD_FILL')
    yield 0.5
    fill = data.layers[data.active]
    check(len(data.layers) == 2 and fill.kind == 'FILL' and data.active == 1, '+ Fill adds a fill layer above the paint layer')
    rect = control('METALLIC').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w - 1, region.y + rect.y + rect.h / 2)
    yield 0.5
    check(fill.metallic > .95, 'dragging the metallic slider sets the fill metallic')
    nodes = data.material.node_tree.nodes
    check(abs(socket(nodes[fill.uid + '.metallic'].inputs, 'B', 'VALUE').default_value - fill.metallic) < 1e-5, 'the material preview follows the metallic value')

    click(window, region, 'LAYER_COLOR')
    yield 0.4
    check(editor._active.state.popover is not None and has('COLOR_SV') and has('COLOR_HUE'), 'the fill swatch opens the custom color picker')
    click(window, region, 'COLOR_HUE', fx=.001)
    yield 0.2
    click(window, region, 'COLOR_SV', fx=.999, fy=.999)
    yield 0.4
    check(fill.color[0] > .9 and fill.color[1] < .05 and fill.color[2] < .05, 'picking hue and saturation sets the fill color')
    click(window, region, 'COLOR_HEX')
    yield 0.2
    x, y = spot(region, 'COLOR_HEX')
    type_text(window, '#0000FF', x, y)
    yield 0.4
    check(fill.color[2] > .9 and fill.color[0] < .05, 'typing a hex color sets the fill color')
    press(window, 'LEFTMOUSE', region.x + region.width * .3, region.y + region.height * .1)
    yield 0.4
    check(editor._active.state.popover is None, 'clicking outside closes the color picker')

    click(window, region, 'BLEND')
    yield 0.4
    click(window, region, 'SET_BLEND_MULTIPLY')
    yield 0.4
    check(fill.blend == 'MULTIPLY' and nodes[fill.uid + '.color'].blend_type == 'MULTIPLY', 'the blend dropdown sets Multiply in the material')

    click(window, region, 'EYE_1')
    yield 0.5
    check(not fill.visible and fill.uid not in data.material[SIGNATURE_KEY], 'the eye hides the fill layer from the material')
    click(window, region, 'EYE_1')
    yield 0.5
    check(fill.visible and fill.uid in data.material[SIGNATURE_KEY], 'the eye shows the fill layer again')

    click(window, region, 'ROW_1', kind='RIGHTMOUSE')
    yield 0.4
    check(has('DUPLICATE') and has('ADD_MASK_BLACK'), 'right-clicking a layer opens its context menu')
    click(window, region, 'ADD_MASK_BLACK')
    yield 0.5
    check(fill.mask is not None and alpha(fill.mask).max() == 0.0, 'the menu adds a black mask')
    check(bpy.context.scene.tool_settings.image_paint.canvas == fill.mask, 'painting now edits the mask')
    stroke(window, region)
    yield 1.0
    check(alpha(fill.mask).max() > .5, 'a brush stroke reveals the fill through its mask')
    check(control('MASKTHUMB_1').active and has('MASK_INFO') and not has('OPACITY'), 'with the mask selected, Properties shows the mask')
    click(window, region, 'SELECT_LAYER')
    yield 0.4
    check(not data.paint_mask and has('OPACITY') and not control('MASKTHUMB_1').active, 'Back to layer shows the layer properties again')
    click(window, region, 'MASKTHUMB_1')
    yield 0.4
    check(data.paint_mask and has('MASK_INFO') and bpy.context.scene.tool_settings.image_paint.canvas == fill.mask,
          'clicking the mask thumbnail selects the mask for painting and editing')

    row = control('ROW_0').rect
    card = next(rect for rect, _ in editor._active.workspace.cards if rect.contains(row.x + row.w / 2, row.y + row.h / 2))
    pixel = rendered_pixel(window, area, region, (card.x + card.w - 3, card.y + 3))
    check(all(abs(a - b) < .03 for a, b in zip(pixel[:3], SURFACE_FLOATING)), 'the layers panel renders in the Devil palette')

    click(window, region, 'ROW_1')
    click(window, region, 'ROW_1')
    yield 0.4
    check(editor._active.state.text is not None, 'double-clicking a layer starts renaming it in place')
    type_text(window, 'Rust', *spot(region, 'ROW_1'))
    yield 0.4
    check(fill.name == 'Rust', 'typing a name and pressing Enter renames the layer')

    click(window, region, 'ROW_1', kind='RIGHTMOUSE')
    yield 0.4
    click(window, region, 'DUPLICATE')
    yield 0.6
    copy = data.layers[2]
    check(len(data.layers) == 3 and copy.name == 'Rust copy' and copy.mask is not None and copy.mask != data.layers[1].mask,
          'Duplicate copies the layer with its own mask')

    scale = editor._active.workspace.scale
    red = numpy.zeros((data.resolution * data.resolution, 4), dtype=numpy.float32)
    red[:] = (1.0, 0.0, 0.0, 1.0)
    paint_layer = data.layers[0]
    paint_layer.image.pixels.foreach_set(red.ravel())
    paint_layer.image.update()
    row = control('ROW_0').rect
    paint_thumb = rendered_pixel(window, area, region, (row.x + 46 * scale, row.y + row.h / 2))
    check(paint_thumb[0] > .9 and paint_thumb[1] < .1 and paint_thumb[2] < .1, 'the paint layer thumbnail shows the painted image')

    export_dir = scratch / 'export'
    click(window, region, 'EXPORT')
    yield 0.4
    check(has('EXPORT_DIR') and has('EXPORT_RUN') and has('BROWSE'), 'Export textures opens the custom export card')
    click(window, region, 'EXPORT_DIR')
    yield 0.2
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield 0.3
    check(Path(data.export_directory) == export_dir, 'typing the folder sets the export directory')
    click(window, region, 'EXPORT_RUN')
    yield 1.0
    files = {suffix: export_dir / f'Cube_{suffix}.png' for suffix in ('BaseColor', 'Roughness', 'Metallic')}
    check(all(path.is_file() for path in files.values()), 'Export writes base color, roughness and metallic PNGs')
    metallic = bpy.data.images.load(str(files['Metallic']))
    values = numpy.empty(len(metallic.pixels), dtype=numpy.float32)
    metallic.pixels.foreach_get(values)
    check(values.max() > .9 and values.min() < .1, 'exported metallic is high only where the masks were painted')
    bpy.data.images.remove(metallic)

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(scratch / 'painted.blend'), copy=True)
    check(all(layer.image is None or layer.image.packed_file is not None for layer in data.layers), 'saving packs the painted layers into the .blend')

    for _ in range(30):
        if 'LAYERS' in editor._active.workspace.scroll_areas and 'PROPERTIES' in editor._active.workspace.scroll_areas:
            break
        click(window, region, 'ADD_PAINT')
        yield 0.2
    check('LAYERS' in editor._active.workspace.scroll_areas, 'a long layer stack becomes scrollable')
    width = control('PANEL_LAYERS').rect.w
    drag(window, region, 'COLUMN_EDGE', -80, 0)
    yield 0.4
    check(control('PANEL_LAYERS').rect.w > width + 40, 'dragging the column edge widens the right column')
    check(has('SPLITTER'), 'a divider appears between layers and properties when they do not fit')
    layers_view = editor._active.workspace.scroll_areas['LAYERS'][0].h
    drag(window, region, 'SPLITTER', 0, -60)
    yield 0.4
    check(editor._active.workspace.scroll_areas['LAYERS'][0].h > layers_view + 30, 'dragging the divider gives the layers more room')
    before = editor._active.state.scroll.get('LAYERS', 0.0)
    x, y = spot(region, 'PANEL_LAYERS', fy=-1.0)
    move(window, x, y)
    window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
    yield 0.3
    check(editor._active.state.scroll['LAYERS'] > before, 'the mouse wheel scrolls the layer stack')

    rows = sum(item.key.startswith('ROW_') for item in editor._active.workspace.controls)
    check(rows < len(data.layers), 'layer rows scrolled out of view are not built or drawn')
    layers_view = editor._active.workspace.scroll_areas['LAYERS'][0].h
    click(window, region, 'PANEL_PROPERTIES')
    yield 0.3
    check('PROPERTIES' in editor._active.state.collapsed and not has('OPACITY'), 'clicking a panel header collapses it')
    check(editor._active.workspace.scroll_areas['LAYERS'][0].h > layers_view + 30, 'collapsing properties gives its room to the layers')
    click(window, region, 'PANEL_PROPERTIES')
    yield 0.3
    check(has('OPACITY'), 'clicking it again expands it')

    rect = control('BRUSH_STRENGTH').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .25, region.y + rect.y + rect.h / 2)
    yield 0.3
    check(abs(painting.brush_value(bpy.context.scene, 'strength') - .25) < .03, 'the strength slider sets the strength the brush uses')
    click(window, region, 'ERASE')
    yield 0.5
    check(control('ERASE').active, 'the dock switches to the eraser')

    click(window, region, 'CLOSE')
    yield 0.5
    check(editor._active is None, 'the close button closes Devil Painter')
    check(space.show_region_header and space.show_region_toolbar and space.show_gizmo_navigate, "closing restores Blender's header, toolbar and gizmo")
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None and has('ADD_PAINT'), 'reopening shows the layer stack')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
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
