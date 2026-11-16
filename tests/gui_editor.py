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


def press(window, kind, x, y, **modifiers):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    window.event_simulate(type=kind, value='PRESS', x=x, y=y, **modifiers)
    window.event_simulate(type=kind, value='RELEASE', x=x, y=y, **modifiers)


def rendered_pixels(window, area, region):
    offscreen = gpu.types.GPUOffScreen(region.width, region.height)
    surface, bar, _ = editor.editor_frame(region)
    probes = {
        'bar': (int(bar[0] + bar[2] / 2), int(bar[1] + bar[3] / 2)),
        'surface': (int(surface[0] + surface[2] / 2), int(surface[1] + surface[3] / 3)),
        'margin': (int(surface[0] / 2), int(surface[1] / 2)),
    }
    pixels = {}
    with offscreen.bind():
        framebuffer = gpu.state.active_framebuffer_get()
        framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix(((2 / region.width, 0, 0, -1), (0, 2 / region.height, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1))))
            with bpy.context.temp_override(window=window, area=area, region=region):
                editor._active.draw_overlay()
        for name, (x, y) in probes.items():
            pixels[name] = tuple(framebuffer.read_color(x, y, 1, 1, 4, 0, 'FLOAT').to_list()[0][0])
    offscreen.free()
    return pixels


def close_to(color, expected):
    return all(abs(a - b) < 0.02 for a, b in zip(color, expected))


def journey():
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    cube.select_set(True)
    shortcut = (area.x + area.width // 2, area.y + area.height // 2)
    empty_spot = (region.x + int(region.width * 0.12), region.y + int(region.height * 0.2))

    press(window, 'P', *shortcut, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None, 'Ctrl+Alt+P opens the editor over the 3D viewport')
    check(editor._active._handle is not None, 'editor draw handler is installed')

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=2)
    pixels = rendered_pixels(window, area, region)
    check(close_to(pixels['bar'], editor.BAR_COLOR), 'editor title bar renders its color')
    check(pixels['surface'][3] > 0.9, 'editor surface covers the viewport')
    check(pixels['margin'][3] == 0.0, 'editor leaves its margin uncovered')

    press(window, 'LEFTMOUSE', *empty_spot)
    yield 0.5
    check(cube.select_get(), 'clicks inside the editor do not reach the scene behind it')

    press(window, 'ESC', *shortcut)
    yield 0.5
    check(editor._active is None, 'Esc closes the editor')

    press(window, 'LEFTMOUSE', *empty_spot)
    yield 0.5
    check(not cube.select_get(), 'the same click reaches the scene once the editor is closed')

    press(window, 'P', *shortcut, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None, 'Ctrl+Alt+P reopens the editor')
    press(window, 'P', *shortcut, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is None, 'Ctrl+Alt+P toggles the editor closed')

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
