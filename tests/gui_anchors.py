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
from devil_painter import editor, library, shelf, smart
from devil_painter.document import active_effect, active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import settle

TIMEOUT = 600
STARTED = time.time()
CHANNELS = ('BaseColor', 'Roughness')
LOCAL = .02


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


def stroke(window, region, fx, fy):
    x, y = region.x + region.width * fx, region.y + region.height * fy
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 13):
        move(window, x + step * 6, y + step * 3)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 72), y=int(y + 36))


def strength(before, unfed, fed, where):
    span = unfed['Roughness'][..., 0] - before['Roughness'][..., 0]
    kept = where & (numpy.abs(span) > .2)
    return round(float(numpy.median((fed['Roughness'][..., 0] - before['Roughness'][..., 0])[kept] / span[kept])), 3)


def grown(region, reach=3):
    result = region.copy()
    for axis in (0, 1):
        for shift in range(-reach, reach + 1):
            result |= numpy.roll(region, shift, axis)
    return result


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'anchor_export'
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

    def change(first, second, where=None):
        return {name: round(float(numpy.abs(first[name] - second[name])[where if where is not None else ...].mean()), 4) for name in CHANNELS}

    click(window, region, 'ADD_PAINT')
    yield from settle()
    anchor_uid = active_layer(data).uid
    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def layer():
        return find_layer(data, layer_uid)

    def canvas():
        return pixels(find_layer(data, anchor_uid).image)[:, 3].reshape(data.resolution, data.resolution)

    def select_row(uid, **modifiers):
        yield from reveal(window, region, 'ROW_' + uid, 'LAYERS')
        press(window, 'LEFTMOUSE', *spot(region, 'ROW_' + uid, .6), **modifiers)
        yield from settle()

    def select_effect(effect_uid):
        yield from reveal(window, region, f'FX_{layer_uid}.{effect_uid}', 'LAYERS')
        click(window, region, f'FX_{layer_uid}.{effect_uid}', fx=.6)
        yield from settle()

    def paint_anchor(color, fx, fy):
        yield from select_row(anchor_uid)
        yield from set_hex(window, region, 'BRUSH_COLOR', color)
        before = canvas()
        stroke(window, region, fx, fy)
        yield from settle()
        changed = numpy.abs(canvas() - before)
        return changed > .5, grown(changed > 0.0)

    def anchor_to(uid, channel):
        yield from menu(window, region, 'FX_ANCHOR', f'SET_FXANCHOR.{uid}')
        yield from menu(window, region, 'FX_ANCHOR_CHANNEL', f'SET_FXANCHORCHANNEL.{channel}')

    def routing():
        return [(effect.kind, effect.target, effect.anchor == anchor_uid, effect.anchor_channel, round(effect.anchor_weight, 2)) for effect in layer().effects]

    yield from add_effect(window, region, 'CONTENT', 'GENERATOR')
    generator_uid = active_effect(data).uid
    yield from menu(window, region, 'GENERATOR', 'SET_GENERATOR.NOISE')
    yield from slide(window, region, 'GEN_LEVEL', .9)
    yield from reveal(window, region, 'FX_ANCHOR')
    check(control('FX_ANCHOR').text == 'None' and has('FX_ANCHOR_CHANNEL') and not has('FX_anchor_weight'),
          'a Generator effect shows an Anchor input that starts empty, with its channel, in the Anchor effect style')
    unfed = yield from exported()
    yield from anchor_to(anchor_uid, 'base_color')
    generator = layer().effects[0]
    check((generator.anchor, generator.anchor_channel) == (anchor_uid, 'base_color') and control('FX_ANCHOR').text == find_layer(data, anchor_uid).name,
          'picking a layer in the Anchor dropdown feeds its base color into the Generator')
    yield from reveal(window, region, 'FX_anchor_weight')
    fed = yield from exported()
    generator_anchored = change(unfed, fed)
    check(generator_anchored['Roughness'] > .05, f'an anchored Generator differs from the same Generator unanchored ({generator_anchored})')

    dark, dark_reach = yield from paint_anchor('#000000', .42, .45)
    check(int(dark.sum()) > 500, f'a brush stroke lands on the anchor layer ({int(dark.sum())} pixels)')
    yield from select_effect(generator_uid)
    darkened = yield from exported()
    generator_inside, generator_outside = change(fed, darkened, dark), change(fed, darkened, ~dark_reach)
    check(generator_inside['Roughness'] > .3 and generator_outside['Roughness'] < generator_inside['Roughness'] * LOCAL,
          f'painting the anchor reshapes the Generator only where the anchor was painted (inside {generator_inside}, outside {generator_outside})')
    yield from slide(window, region, 'FX_anchor_weight', 0.0)
    released = yield from exported()
    check(all(numpy.array_equal(released[name], unfed[name]) for name in CHANNELS), 'at zero anchor strength the Generator exports exactly as unanchored')

    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    filter_uid = active_effect(data).uid
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.INVERT')
    yield from reveal(window, region, 'FX_ANCHOR')
    check(control('FX_ANCHOR').text == 'None' and has('FX_ANCHOR_CHANNEL') and not has('FX_anchor_weight'),
          'a Filter effect shows the same Anchor input under its filter dropdown')
    plain_filter = yield from exported()
    yield from anchor_to(anchor_uid, 'base_color')
    fed_filter = yield from exported()
    filter_anchored = change(plain_filter, fed_filter)
    check(filter_anchored['Roughness'] > .05, f'a Filter fed by an anchor differs from the same Filter unfed ({filter_anchored})')
    held = {'black stroke': strength(unfed, plain_filter, fed_filter, dark), 'unpainted': strength(unfed, plain_filter, fed_filter, ~dark_reach)}
    check(held['black stroke'] < held['unpainted'] - .3, f'the anchor sets how strongly the Filter applies: weaker under the black stroke ({held})')
    light, light_reach = yield from paint_anchor('#FFFFFF', .5, .58)
    fresh = light & ~dark_reach
    yield from select_effect(filter_uid)
    lit = yield from exported()
    filter_inside, filter_outside = change(fed_filter, lit, fresh), change(fed_filter, lit, ~light_reach)
    check(int(fresh.sum()) > 500 and filter_inside['Roughness'] > .02 and filter_outside['Roughness'] < filter_inside['Roughness'] * LOCAL,
          f'painting the anchor white reshapes the Filter only under the new stroke (inside {filter_inside}, outside {filter_outside})')
    full = {'white stroke': strength(unfed, plain_filter, lit, fresh), 'unpainted': strength(unfed, plain_filter, lit, ~(dark_reach | light_reach))}
    check(full['white stroke'] > full['unpainted'] + .1, f'the Filter applies more strongly under the white stroke ({full})')

    yield from add_effect(window, region, 'MASK', 'GENERATOR')
    yield from menu(window, region, 'GENERATOR', 'SET_GENERATOR.NOISE')
    masked = yield from exported()
    yield from anchor_to(anchor_uid, 'base_color')
    yield from slide(window, region, 'FX_anchor_weight', .5)
    check(abs(layer().effects[2].anchor_weight - .5) < .01, 'the anchor strength slider sets how strongly the anchor feeds the mask Generator')
    mask_fed = yield from exported()
    mask_generator = change(masked, mask_fed)
    check(mask_generator['Roughness'] > .01, f'an anchored mask Generator changes the mask ({mask_generator})')
    yield from add_effect(window, region, 'MASK', 'FILTER')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.INVERT')
    inverted = yield from exported()
    yield from anchor_to(anchor_uid, 'roughness')
    mask_filter_fed = yield from exported()
    mask_filter = change(inverted, mask_filter_fed)
    check(mask_filter['Roughness'] > .01, f'a mask Filter fed by the anchor roughness differs from the same Filter unfed ({mask_filter})')
    yield from menu(window, region, 'FX_ANCHOR', 'SET_FXANCHOR.')
    check(not layer().effects[3].anchor and control('FX_ANCHOR').text == 'None' and not has('FX_anchor_weight'), 'choosing None in the Anchor dropdown unfeeds the Filter')
    unhooked = yield from exported()
    check(all(numpy.array_equal(unhooked[name], inverted[name]) for name in CHANNELS), 'an unfed Filter exports exactly as before it was fed')
    yield from anchor_to(anchor_uid, 'roughness')
    routes = routing()
    final = yield from exported()

    yield from select_row(anchor_uid)
    yield from select_row(layer_uid, ctrl=True)
    click(window, region, 'ROW_' + layer_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'GROUP')
    yield from settle()
    folder_uid = layer().parent
    check(folder_uid and find_layer(data, anchor_uid).parent == folder_uid, 'the anchor and the fed layer group into one folder')
    yield from select_row(folder_uid)
    click(window, region, 'ROW_' + folder_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'SAVE_SMART')
    yield from settle()
    saved = smart.smart_materials()[-1]
    names = [entry['name'] for entry in saved['layers']]
    stored = next(entry for entry in saved['layers'] if entry['kind'] == 'FILL')['effects']
    check(all(item['anchor'] == f'#{names.index(find_layer(data, anchor_uid).name)}' for item in stored),
          'saving the folder as a smart material stores each anchor as a link inside the material')
    click(window, region, 'SHELF_TAB.SMART')
    yield from settle()
    user_tile = next(index for index, item in enumerate(shelf.items('SMART')) if item.user_index >= 0)
    click(window, region, f'ITEM.{user_tile}')
    yield from settle()
    copy_folder_uid = active_layer(data).uid
    copies = {item.kind: item for item in data.layers if item.parent == copy_folder_uid}
    copied = [(effect.kind, effect.target, effect.anchor == copies['PAINT'].uid, effect.anchor_channel, round(effect.anchor_weight, 2))
              for effect in copies['FILL'].effects]
    check(copy_folder_uid != folder_uid and copied == routes, f'applying the smart material relinks every anchor to the new copy of the anchor layer ({copied})')
    copy_uid, copy_filter_uid = copies['FILL'].uid, copies['FILL'].effects[3].uid
    for uid in (anchor_uid, layer_uid):
        find_layer(data, uid).visible = False
    applied = yield from exported()
    smart_match = max(float(numpy.abs(applied[name] - final[name]).max()) for name in CHANNELS)
    check(smart_match < .02, f'the applied smart material exports the same channels as the original ({smart_match:.4f})')
    yield from reveal(window, region, f'FX_{copy_uid}.{copy_filter_uid}', 'LAYERS')
    click(window, region, f'FX_{copy_uid}.{copy_filter_uid}', fx=.6)
    yield from settle()
    yield from menu(window, region, 'FX_ANCHOR', 'SET_FXANCHOR.')
    unlinked = yield from exported()
    smart_gap = change(applied, unlinked)
    check(not find_layer(data, copy_uid).effects[3].anchor and smart_gap['Roughness'] > .01,
          f'the relinked anchor drives the applied smart material: unhooking its mask Filter changes the output ({smart_gap})')
    find_layer(data, copy_folder_uid).visible = False
    for uid in (anchor_uid, layer_uid):
        find_layer(data, uid).visible = True
    data.active_uid = layer_uid

    saved_file = scratch / 'anchor_inputs.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(routing() == routes, 'the saved file reopens with every anchor routing')
    reopened = yield from exported()
    gap = max(float(numpy.abs(reopened[name] - final[name]).max()) for name in CHANNELS)
    check(gap == 0.0, f'the reopened file exports the same channels ({gap})')
    yield from select_effect(generator_uid)
    yield from reveal(window, region, 'FX_ANCHOR')
    check(control('FX_ANCHOR').text == find_layer(data, anchor_uid).name, 'the reopened Generator shows its anchor')
    print('ANCHOR EVIDENCE', dict(generator_anchored=generator_anchored, generator_painted_inside=generator_inside, generator_painted_outside=generator_outside,
                                  filter_anchored=filter_anchored, filter_strength_black=held, filter_painted_inside=filter_inside,
                                  filter_painted_outside=filter_outside, filter_strength_white=full, mask_generator=mask_generator, mask_filter=mask_filter,
                                  dark_pixels=int(dark.sum()), light_pixels=int(fresh.sum()), smart_match=round(smart_match, 4), smart_unhook=smart_gap))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI ANCHOR CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI anchor test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)


