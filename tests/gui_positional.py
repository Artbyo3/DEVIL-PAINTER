import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import caches, compositing, editor, library
from devil_painter.document import active_effect, active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import settle, wait_for

TIMEOUT = 900
STARTED = time.time()
CHANNELS = ('BaseColor', 'Roughness')
REFRESH_TIMEOUT = 120.0


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
    side = image.size[0]
    bpy.data.images.remove(image)
    return values.reshape(side, side, 4)


def menu(window, region, opener, item):
    yield from reveal(window, region, opener)
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


def add_effect(window, region, target, kind):
    yield from menu(window, region, 'ADD_FX_' + target, f'NEW_FX.{target}.{kind}')


def slide(window, region, key, fx):
    yield from reveal(window, region, key)
    click(window, region, key, fx=fx)
    yield from settle()


def stroke(window, region):
    x, y = region.x + region.width * .45, region.y + region.height * .5
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 13):
        move(window, x + step * 6, y + step * 3)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 72), y=int(y + 36))


def detail(values):
    return float(numpy.abs(numpy.diff(values[..., :3], axis=0)).mean() + numpy.abs(numpy.diff(values[..., :3], axis=1)).mean())


def grown(region, reach):
    result = region.copy()
    for axis in (0, 1):
        for shift in range(-reach, reach + 1):
            result |= numpy.roll(region, shift, axis)
    return result


def shrunk(region, reach):
    return ~grown(~region, reach)


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'positional_export'
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

    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    def exported():
        click(window, region, 'EXPORT')
        yield from settle()
        click(window, region, 'EXPORT_RUN')
        yield from settle()
        press(window, 'ESC', *middle)
        yield from settle()
        return {name: png(export_dir / f'Cube_Material_{name}.png')[..., :3] for name in CHANNELS}

    def refreshed():
        yield from wait_for(lambda: caches.fresh(data, compositing.below_stamp(data)), 'the viewport to refresh the textures below its filters', REFRESH_TIMEOUT)
        return True

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def layer():
        return find_layer(data, layer_uid)

    yield from add_effect(window, region, 'CONTENT', 'FILL')
    fill_uid = active_effect(data).uid
    sharp = yield from exported()
    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.BLUR')
    yield from slide(window, region, 'FX_radius', .4)
    filter_uid = active_effect(data).uid
    check([effect.uid for effect in layer().effects] == [fill_uid, filter_uid] and active_effect(data).filter == 'BLUR',
          'a Blur filter sits on top of a pattern Fill in the content stack')
    yield from refreshed()
    shader_caches = {node.image.get(caches.KEY) for node in data.material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image is not None} - {None}
    check(f'{layer_uid}.{filter_uid}.base_color' in shader_caches, f'the viewport material reads the cached texture below the filter ({len(shader_caches)} cached channels)')
    blurred = yield from exported()
    softened = round(detail(blurred['BaseColor']) / detail(sharp['BaseColor']), 3)
    check(softened < .7, f'the Blur now blurs the Fill below it, which it never touched before ({softened} of the original detail)')

    yield from add_effect(window, region, 'CONTENT', 'PAINT')
    paint = active_effect(data)
    paint_uid = paint.uid
    click(window, region, 'BRUSH_COLOR')
    yield from settle()
    click(window, region, 'COLOR_HEX')
    yield from settle()
    type_text(window, '#00FF00', *spot(region, 'COLOR_HEX'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    stroke(window, region)
    yield from settle()
    alpha = pixels(paint.image)[:, 3].reshape(data.resolution, data.resolution)
    check(alpha.max() > .5, 'a brush stroke lands on the Paint effect above the Blur')
    yield from refreshed()
    core = shrunk(alpha > alpha.max() * .9, 2)
    ring = grown(alpha > 0.0, 2) & ~grown(alpha > 0.0, 1)
    above = yield from exported()

    def sharpness(result):
        green = result['BaseColor'][core]
        leak = float(numpy.median(numpy.abs(result['BaseColor'][ring] - blurred['BaseColor'][ring]).max(-1)))
        return dict(core_green=round(float(green[:, 1].mean() - green[:, [0, 2]].mean()), 3), leak=round(leak, 4))

    kept = sharpness(above)
    check(int(core.sum()) > 50 and kept['core_green'] > .9 and kept['leak'] < .005,
          f'the stroke above the Blur stays sharp: pure green inside, no green leaking past its edge ({kept}, {int(core.sum())} core pixels)')
    off_stroke = ~grown(alpha > 0.0, 12)
    base_kept = float(numpy.abs(above['BaseColor'][off_stroke] - blurred['BaseColor'][off_stroke]).mean())
    check(base_kept < .002, f'away from the stroke the base stays exactly as blurred ({base_kept:.4f})')

    yield from reveal(window, region, f'FX_{layer_uid}.{filter_uid}', 'LAYERS')
    click(window, region, f'FX_{layer_uid}.{filter_uid}', fx=.6)
    yield from settle()
    yield from reveal(window, region, 'FX_UP')
    click(window, region, 'FX_UP')
    yield from settle()
    check([effect.uid for effect in layer().effects] == [fill_uid, paint_uid, filter_uid], 'moving the Blur up puts it over the stroke')
    yield from refreshed()
    on_top = yield from exported()
    smeared = sharpness(on_top)
    check(smeared['leak'] > kept['leak'] + .01 and smeared['core_green'] < kept['core_green'] - .02,
          f'with the Blur on top the stroke blurs too ({smeared} against {kept})')
    click(window, region, 'FX_DOWN')
    yield from settle()
    check([effect.uid for effect in layer().effects] == [fill_uid, filter_uid, paint_uid], 'moving the Blur back down restores the order')
    restored = yield from exported()
    check(all(numpy.array_equal(restored[name], above[name]) for name in CHANNELS), 'moving the Blur back under the stroke exports exactly as before')

    yield from reveal(window, region, f'FXEYE_{layer_uid}.{filter_uid}', 'LAYERS')
    click(window, region, f'FXEYE_{layer_uid}.{filter_uid}')
    yield from settle()
    unfiltered = yield from exported()
    gain = round(detail(unfiltered['BaseColor']) / detail(above['BaseColor']), 3)
    check(gain > 1.2, f'hiding the Blur brings the sharp Fill back under the stroke ({gain})')
    click(window, region, f'FXEYE_{layer_uid}.{filter_uid}')
    yield from settle()

    yield from reveal(window, region, 'ROW_' + layer_uid, 'LAYERS')
    click(window, region, 'ROW_' + layer_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'ADD_MASK_WHITE')
    yield from settle()
    yield from add_effect(window, region, 'MASK', 'GENERATOR')
    yield from menu(window, region, 'GENERATOR', 'SET_GENERATOR.NOISE')
    yield from slide(window, region, 'GEN_LEVEL', .5)
    masked = yield from exported()
    yield from add_effect(window, region, 'MASK', 'FILTER')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.BLUR')
    yield from slide(window, region, 'FX_radius', .6)
    check(layer().effects[-1].target == 'MASK' and layer().effects[-1].filter == 'BLUR', 'a Blur filter sits on top of a Generator in the mask stack')
    yield from refreshed()
    mask_blurred = yield from exported()
    mask_softened = round(detail(mask_blurred['BaseColor']) / detail(masked['BaseColor']), 3)
    check(mask_softened < .8, f'the mask Blur blurs the Generator below it ({mask_softened} of the original mask detail)')

    saved_file = scratch / 'positional_filters.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    packed = [image for image in caches.cached_images() if image.packed_file is not None]
    check(len(packed) >= 3, f'the cached textures below the filters reopen packed with the file ({len(packed)})')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    reopened = yield from exported()
    gap = max(float(numpy.abs(reopened[name] - mask_blurred[name]).max()) for name in CHANNELS)
    check(gap == 0.0, f'the reopened file exports the same channels ({gap})')
    print('POSITIONAL EVIDENCE', dict(fill_softened=softened, stroke_above=kept, stroke_under=smeared, base_kept=round(base_kept, 4), unhidden_gain=gain,
                                      mask_softened=mask_softened, reopen_gap=gap))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI POSITIONAL CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI positional test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
