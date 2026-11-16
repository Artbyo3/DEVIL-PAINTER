import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import gpu
from mathutils import Matrix

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor
from devil_painter.ui_system import BG_BASE

TIMEOUT = 60
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


def on_screen(region, rect):
    return region.x + rect.x + rect.w / 2, region.y + rect.y + rect.h / 2


def rendered_pixels(window, area, region, probes):
    offscreen = gpu.types.GPUOffScreen(region.width, region.height)
    pixels = {}
    with offscreen.bind():
        framebuffer = gpu.state.active_framebuffer_get()
        framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix(((2 / region.width, 0, 0, -1), (0, 2 / region.height, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1))))
            with bpy.context.temp_override(window=window, area=area, region=region):
                editor._active.renderer.draw(editor._active)
        for name, (x, y) in probes.items():
            pixels[name] = tuple(framebuffer.read_color(int(x), int(y), 1, 1, 4, 0, 'FLOAT').to_list()[0][0])
    offscreen.free()
    return pixels


def journey():
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    scene = bpy.context.scene
    cube = bpy.data.objects['Cube']
    cube.select_set(True)
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    active = editor._active
    check(active is not None and active.full, 'Ctrl+Alt+P opens the full-canvas editor over the 3D viewport')
    layout = active.canvas_layout
    check({'CLOSE', 'SHOW_3D'} <= set(layout.buttons), 'editor shows the close and 3D view buttons')

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=2)
    canvas = layout.canvas
    pixels = rendered_pixels(window, area, region, {
        'canvas': (canvas.x + canvas.w * .23, canvas.y + canvas.h * .27),
        'outside': (1, 1),
    })
    check(all(abs(a - b) < .06 for a, b in zip(pixels['canvas'], BG_BASE)), 'canvas renders the shared dark base color')
    check(pixels['outside'][3] == 0.0, 'editor leaves the viewport margin uncovered')

    empty_spot = (region.x + canvas.x + canvas.w * .2, region.y + canvas.y + canvas.h * .3)
    press(window, 'LEFTMOUSE', *empty_spot)
    yield 0.5
    check(cube.select_get(), 'clicks inside the editor stay in the editor')

    zoom = active.view.zoom
    move(window, *empty_spot)
    window.event_simulate(type='WHEELUPMOUSE', value='PRESS', x=int(empty_spot[0]), y=int(empty_spot[1]))
    yield 0.3
    check(active.view.zoom > zoom, 'scrolling over the canvas zooms it')

    press(window, 'LEFTMOUSE', *on_screen(region, layout.buttons['SHOW_3D'][0]))
    yield 0.5
    check(not active.full and 'RESTORE_CANVAS' in active.canvas_layout.buttons, '3D view shrinks the editor into a window')
    panel = active.canvas_layout.panel
    check(panel.x > region.width * .2, 'the editor window sits on the right and reveals the 3D viewport')

    grab = (region.x + panel.x + panel.w * .4, region.y + panel.y + panel.h - 15 * active.canvas_layout.scale)
    move(window, *grab)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(grab[0]), y=int(grab[1]))
    move(window, grab[0] - 60, grab[1] - 40)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(grab[0] - 60), y=int(grab[1] - 40))
    yield 0.5
    moved = active.canvas_layout.panel
    check(abs(moved.x - (panel.x - 60)) < 2 and abs(moved.y - (panel.y - 40)) < 2, 'dragging the top bar moves the editor window')
    check(abs(scene.dp_ui_rect[0] * active.canvas_layout.scale - moved.x) < 2, 'the window position is saved with the scene')

    viewport_spot = (region.x + moved.x * .5, region.y + region.height * .3)
    press(window, 'LEFTMOUSE', *viewport_spot)
    yield 0.5
    check(not cube.select_get(), 'clicks beside the editor window reach the 3D viewport')

    press(window, 'LEFTMOUSE', *on_screen(region, active.canvas_layout.buttons['RESTORE_CANVAS'][0]))
    yield 0.5
    check(active.full and 'SHOW_3D' in active.canvas_layout.buttons, 'Full canvas restores the full editor')

    press(window, 'LEFTMOUSE', *on_screen(region, active.canvas_layout.buttons['CLOSE'][0]))
    yield 0.5
    check(editor._active is None, 'the close button closes the editor')

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None, 'Ctrl+Alt+P reopens the editor')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is None, 'Ctrl+Alt+P closes the editor again')

    devil_painter.unregister()
    check(not hasattr(bpy.types, 'DEVIL_PAINTER_OT_editor'), 'editor unregisters cleanly')
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
