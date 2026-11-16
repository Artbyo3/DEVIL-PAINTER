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

TIMEOUT = 120
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
    return next(item for item in editor._active.workspace.controls if item.key == key)


def click(window, region, key):
    rect = control(key).rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w / 2, region.y + rect.y + rect.h / 2)


def stroke(window, region):
    x, y = region.x + region.width * .47, region.y + region.height * .45
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
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None, 'Ctrl+Alt+P opens Devil Painter over the 3D viewport')
    check(control('START') is not None and control('TARGET').label == 'Cube', 'the start card offers to paint the selected mesh')

    click(window, region, 'RES_1024')
    yield 0.3
    click(window, region, 'START')
    yield 1.5
    data = cube.devil_painter
    paint_layer = data.layers[0]
    check(data.enabled and data.resolution == 1024 and len(data.layers) == 1 and paint_layer.kind == 'PAINT', 'Start painting creates a 1K stack with a paint layer')
    check(cube.mode == 'TEXTURE_PAINT' and area.spaces.active.shading.type == 'MATERIAL', 'the viewport switches to texture paint with material preview')
    check(bpy.context.scene.tool_settings.image_paint.canvas == paint_layer.image, 'the brush paints on the selected layer')
    check(control('PAINT').active, 'the paint tool is active in the dock')

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
    check(abs(socket(nodes[fill.uid + '.metallic'].inputs, 'B', 'VALUE').default_value - fill.metallic) < 1e-5,
          'the material preview follows the metallic value')

    click(window, region, 'EYE_1')
    yield 0.5
    check(not fill.visible and fill.uid not in data.material[SIGNATURE_KEY], 'the eye hides the fill layer from the material')
    click(window, region, 'EYE_1')
    yield 0.5
    check(fill.visible and fill.uid in data.material[SIGNATURE_KEY], 'the eye shows the fill layer again')

    click(window, region, 'ADD_MASK_BLACK')
    yield 0.5
    check(fill.mask is not None and alpha(fill.mask).max() == 0.0, 'a black mask hides the fill layer')
    check(bpy.context.scene.tool_settings.image_paint.canvas == fill.mask, 'painting now edits the mask')
    stroke(window, region)
    yield 1.0
    check(alpha(fill.mask).max() > .5, 'a brush stroke reveals the fill through its mask')

    card = next(rect for rect, title in editor._active.workspace.cards if title == 'Layers')
    pixel = rendered_pixel(window, area, region, (card.x + card.w / 2, card.y + 6))
    check(all(abs(a - b) < .03 for a, b in zip(pixel[:3], SURFACE_FLOATING)), 'the layer card renders in the Devil palette')

    scale = editor._active.workspace.scale
    red = numpy.zeros((data.resolution * data.resolution, 4), dtype=numpy.float32)
    red[:] = (1.0, 0.0, 0.0, 1.0)
    paint_layer.image.pixels.foreach_set(red.ravel())
    paint_layer.image.update()
    fill.color = (0.0, 0.0, 1.0)
    rows = {index: control(f'ROW_{index}').rect for index in (0, 1)}
    thumb = lambda rect, slot: (rect.x + (30 + 16 + slot * 36) * scale, rect.y + rect.h / 2)
    paint_thumb = rendered_pixel(window, area, region, thumb(rows[0], 0))
    fill_thumb = rendered_pixel(window, area, region, thumb(rows[1], 0))
    mask_thumb = rendered_pixel(window, area, region, thumb(rows[1], 1))
    check(paint_thumb[0] > .9 and paint_thumb[1] < .1 and paint_thumb[2] < .1, 'the paint layer thumbnail shows the painted image')
    check(fill_thumb[2] > .9 and fill_thumb[0] < .1, 'the fill layer thumbnail shows the fill color')
    check(mask_thumb[0] < .2, 'the mask thumbnail shows the mostly black mask')

    export_dir = scratch / 'export'
    with bpy.context.temp_override(window=window, area=area, region=region):
        result = bpy.ops.devil_painter.export_textures(directory=str(export_dir))
    files = {suffix: export_dir / f'Cube_{suffix}.png' for suffix in ('BaseColor', 'Roughness', 'Metallic')}
    check(result == {'FINISHED'} and all(path.is_file() for path in files.values()), 'export writes base color, roughness and metallic PNGs')
    metallic = bpy.data.images.load(str(files['Metallic']))
    values = numpy.empty(len(metallic.pixels), dtype=numpy.float32)
    metallic.pixels.foreach_get(values)
    check(values.max() > .9 and values.min() < .1, 'exported metallic is high only where the mask was painted')
    bpy.data.images.remove(metallic)

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(scratch / 'painted.blend'), copy=True)
    check(paint_layer.image.packed_file is not None and fill.mask.packed_file is not None, 'saving packs the painted layers into the .blend')

    click(window, region, 'ROW_0')
    yield 0.3
    check(data.active == 0 and bpy.context.scene.tool_settings.image_paint.canvas == paint_layer.image, 'clicking a row selects that layer')
    paint_uid = paint_layer.uid
    click(window, region, 'MOVE_UP')
    yield 0.5
    check(data.layers[1].uid == paint_uid and data.active == 1, 'Move up raises the selected layer')

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
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None and any(item.key == 'ADD_PAINT' for item in editor._active.workspace.controls), 'reopening shows the layer stack')
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
