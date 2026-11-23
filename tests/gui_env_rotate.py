import math
import sys
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library
from tools.workspace import prepare_scratch
from tests.gui_harness import POLL, check, click, control, finish, keys, press, run_journey, settle, spot, type_text, until, viewport

STEPS = 8


def pointer_move(window, x, y, **modifiers):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(round(x)), y=int(round(y)), **modifiers)


def free_spot(point):
    return not editor._active.workspace.covers(*point) and editor._active.workspace.hit(*point) is None


def write_decal(folder):
    folder.mkdir(exist_ok=True)
    decal = bpy.data.images.new('decal', 32, 32, alpha=True)
    decal.pixels.foreach_set(numpy.tile(numpy.array((1.0, 0.0, 0.0, 1.0), dtype=numpy.float32), 32 * 32))
    decal.filepath_raw = str(folder / 'decal.png')
    decal.file_format = 'PNG'
    decal.save()
    bpy.data.images.remove(decal)


def env_drag(window, region, start, end, shading, cancel=False, drop_shift=False):
    pointer_move(window, region.x + start[0], region.y + start[1], shift=True)
    window.event_simulate(type='RIGHTMOUSE', value='PRESS', x=int(round(region.x + start[0])), y=int(round(region.y + start[1])), shift=True)
    yield POLL
    mid_drag = None
    mid_angle = None
    for step in range(1, STEPS + 1):
        holding = not (drop_shift and step > STEPS // 2)
        px = start[0] + (end[0] - start[0]) * step / STEPS
        py = start[1] + (end[1] - start[1]) * step / STEPS
        pointer_move(window, region.x + px, region.y + py, shift=holding)
        yield POLL
        if step == STEPS // 2:
            mid_drag = editor._active.state.drag
            mid_angle = shading.studiolight_rotate_z
    if cancel:
        window.event_simulate(type='ESC', value='PRESS', x=int(round(region.x + end[0])), y=int(round(region.y + end[1])))
        window.event_simulate(type='ESC', value='RELEASE', x=int(round(region.x + end[0])), y=int(round(region.y + end[1])))
        yield POLL
    window.event_simulate(type='RIGHTMOUSE', value='RELEASE', x=int(round(region.x + end[0])), y=int(round(region.y + end[1])), shift=not drop_shift)
    yield from settle()
    return mid_drag, mid_angle


def stencil_shift_drag(window, region, start, end):
    pointer_move(window, region.x + start[0], region.y + start[1], shift=True)
    window.event_simulate(type='RIGHTMOUSE', value='PRESS', x=int(round(region.x + start[0])), y=int(round(region.y + start[1])), shift=True)
    yield POLL
    running = [operator.bl_idname for operator in window.modal_operators]
    for step in range(1, STEPS + 1):
        px = start[0] + (end[0] - start[0]) * step / STEPS
        py = start[1] + (end[1] - start[1]) * step / STEPS
        pointer_move(window, region.x + px, region.y + py, shift=True)
        yield POLL
    window.event_simulate(type='RIGHTMOUSE', value='RELEASE', x=int(round(region.x + end[0])), y=int(round(region.y + end[1])), shift=True)
    yield from settle()
    yield from until(lambda: not editor._active.stencil_pending, 'the stencil gesture to finish')
    return running


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    textures = scratch / 'env_rotate_textures'
    write_decal(textures)

    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()

    shading = area.spaces.active.shading
    shading.studiolight_rotate_z = 0.0
    yield from settle()
    stage = editor._active.workspace.zones.stage
    scale = editor._active.workspace.scale
    left_start = (round(stage.x + stage.w * .3), round(stage.y + stage.h * .5))
    right_start = (round(stage.x + stage.w * .7), round(stage.y + stage.h * .5))
    check(free_spot(left_start) and free_spot(right_start), 'drag origins lie on the bare 3D viewport')

    dx = round(180 * scale)
    mid_drag, mid_angle = yield from env_drag(window, region, left_start, (left_start[0] + dx, left_start[1]), shading, drop_shift=True)
    expected = editor.wrap_angle(dx / (editor.ENV_ROTATE_PIXELS * scale) * math.tau)
    check(mid_drag is not None and mid_drag[0] == 'ENV_ROTATE_DRAG', 'Shift+right-drag enters environment rotation drag')
    check(abs(mid_angle - expected / 2) < .05, f'environment rotates live mid-drag ({math.degrees(mid_angle):.1f}°)')
    check(editor._active.state.drag is None, 'releasing right mouse ends the drag even after releasing Shift early')
    check(abs(shading.studiolight_rotate_z - expected) < .02, f'environment rotated to {math.degrees(shading.studiolight_rotate_z):.1f}° (expected {math.degrees(expected):.1f}°)')
    check(f'{round(math.degrees(expected))}°' in editor._active.message, f'status toast reports the rotation ({editor._active.message})')

    click(window, region, 'VIEWPORT')
    yield from settle()
    slider = control('ENV_ROTATION')
    check(abs(slider.value - (shading.studiolight_rotate_z + math.pi) / math.tau) < 1e-4, 'Viewport Rotation slider reflects the dragged angle')
    check(slider.shortcut == 'Shift Right-drag', f'Rotation slider tooltip advertises the drag shortcut ({slider.shortcut})')

    before = shading.studiolight_rotate_z
    dx_wrap = round(200 * scale)
    yield from env_drag(window, region, left_start, (left_start[0] + dx_wrap, left_start[1]), shading)
    expected_wrap = editor.wrap_angle(before + dx_wrap / (editor.ENV_ROTATE_PIXELS * scale) * math.tau)
    check(editor._active.state.popover is None, 'Shift+right-drag on the bare viewport closes an open popover')
    check(expected_wrap < 0 and abs(shading.studiolight_rotate_z - expected_wrap) < .02,
          f'dragging past +180° wraps cleanly to {math.degrees(shading.studiolight_rotate_z):.1f}°')

    before = shading.studiolight_rotate_z
    dx_back = -round(60 * scale)
    yield from env_drag(window, region, right_start, (right_start[0] + dx_back, right_start[1]), shading)
    expected_back = editor.wrap_angle(before + dx_back / (editor.ENV_ROTATE_PIXELS * scale) * math.tau)
    check(expected_back > 0 and abs(shading.studiolight_rotate_z - expected_back) < .02,
          f'dragging past -180° wraps cleanly to {math.degrees(shading.studiolight_rotate_z):.1f}°')

    before = shading.studiolight_rotate_z
    _, mid_cancel = yield from env_drag(window, region, left_start, (left_start[0] + round(120 * scale), left_start[1]), shading, cancel=True)
    check(abs(mid_cancel - before) > .2, 'environment rotates live before Esc cancel')
    check(editor._active.state.drag is None and abs(shading.studiolight_rotate_z - before) < 1e-4,
          'pressing Esc during Shift+right-drag cancels and restores the starting angle')

    click(window, region, 'VIEWPORT')
    yield from settle()
    click(window, region, 'ENV_ROTATION', fx=.5)
    yield from settle()
    check(abs(shading.studiolight_rotate_z) < .05, 'dragging the Rotation slider still works after viewport drag')
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield from until(lambda: 'decal' in {control(key).label for key in keys('ITEM.')}, 'the decal is listed')
    item = next(key for key in keys('ITEM.') if control(key).label == 'decal')
    click(window, region, item, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'USE_STENCIL.' + item.removeprefix('ITEM.'))
    yield from settle()
    click(window, region, 'STENCIL_CARD')
    yield from settle()
    click(window, region, 'STENCIL_SCALE', fx=.05)
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    center = tuple(bpy.context.tool_settings.image_paint.brush.stencil_pos)
    before_stencil = shading.studiolight_rotate_z
    running = yield from stencil_shift_drag(window, region, (center[0] + 60, center[1]), (center[0] + 90, center[1]))
    check(running[:1] == ['BRUSH_OT_stencil_control'], 'with an active stencil, Shift+right-drag still scales the stencil')
    check(abs(shading.studiolight_rotate_z - before_stencil) < 1e-4, 'active stencil Shift+right-drag leaves environment rotation untouched')

    click(window, region, 'STENCIL_CARD')
    yield from settle()
    click(window, region, 'STENCIL_CLEAR')
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    dx_after = round(90 * scale)
    yield from env_drag(window, region, left_start, (left_start[0] + dx_after, left_start[1]), shading)
    expected_after = editor.wrap_angle(before_stencil + dx_after / (editor.ENV_ROTATE_PIXELS * scale) * math.tau)
    check(abs(shading.studiolight_rotate_z - expected_after) < .02, 'after removing the stencil, Shift+right-drag rotates the environment again')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    print('ALL GUI ENV ROTATE CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI environment rotation drag test')
