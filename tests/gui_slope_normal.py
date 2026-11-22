import sys
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import caches, compositing, editor, library, shelf
from devil_painter.document import active_effect, active_layer, find_layer, set_channels
from devil_painter.filters import NORMAL_DEPTH, SLOPE_REFERENCE
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, has, move, pixels, press, reveal, run_journey, set_hex, settle, shelf_index, slide, spot, type_text, viewport, wait_for

CHANNELS = ('BaseColor', 'Height', 'Normal')
REFRESH_TIMEOUT = 120.0
TEXTURE_SIZE = 1024
CHECK_SIZE = 4
FACE_MARGIN = 20


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


def height_strength(window, region, middle, edge):
    click(window, region, 'PROJECT')
    yield from settle()
    x, y = spot(region, 'BUMP_STRENGTH')
    rect = control('BUMP_STRENGTH').rect
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    target = x + (rect.w if edge else -rect.w)
    move(window, target, y)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(target), y=int(y))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()


def stroke(window, region, fx, fy):
    x, y = region.x + region.width * fx, region.y + region.height * fy
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 13):
        move(window, x + step * 6, y + step * 3)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 72), y=int(y + 36))


def write_png(path, values):
    side = values.shape[0]
    image = bpy.data.images.new(path.stem, side, side, alpha=False)
    image.pixels.foreach_set(values.astype(numpy.float32).ravel())
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def ramp_profile(side):
    cycle = numpy.concatenate((numpy.zeros(40), numpy.linspace(0.0, 1.0, 80, endpoint=False), numpy.ones(40), numpy.linspace(1.0, 0.0, 8, endpoint=False)))
    return numpy.resize(cycle, side)


def textures(folder, side=TEXTURE_SIZE):
    folder.mkdir(exist_ok=True)
    rows, columns = numpy.indices((side, side))
    profile = ramp_profile(side)
    height = numpy.maximum(profile[numpy.newaxis, :], numpy.roll(profile, 84)[:, numpy.newaxis])
    write_png(folder / 'ramps.png', numpy.dstack((height, height, height, numpy.ones((side, side)))))
    checks = ((rows // CHECK_SIZE + columns // CHECK_SIZE) % 2).astype(float)
    write_png(folder / 'checks.png', numpy.dstack((checks, checks * .6, 1.0 - checks, numpy.ones((side, side)))))


def grown(region, reach):
    result = region.copy()
    for axis in (0, 1):
        for shift in range(-reach, reach + 1):
            result |= numpy.roll(region, shift, axis)
    return result


def gradient(height):
    across = numpy.roll(height, -1, 1) - numpy.roll(height, 1, 1)
    up = numpy.roll(height, -1, 0) - numpy.roll(height, 1, 0)
    return across, up


def steepness(height):
    across, up = gradient(height)
    return numpy.hypot(across, up) * height.shape[0] / 2 / SLOPE_REFERENCE


def height_tilted(height, strength):
    across, up = gradient(height)
    gain = -strength * NORMAL_DEPTH * height.shape[0] / 2
    tilt = numpy.dstack((across * gain, up * gain, numpy.ones_like(height)))
    return tilt / numpy.linalg.norm(tilt, axis=-1, keepdims=True) * .5 + .5


def interior(obj, side, margin=FACE_MARGIN):
    inside = numpy.zeros((side, side), dtype=bool)
    uvs = obj.data.uv_layers.active.data
    for polygon in obj.data.polygons:
        corners = numpy.array([uvs[index].uv[:] for index in polygon.loop_indices]) * side
        (u0, v0), (u1, v1) = numpy.round(corners.min(0)).astype(int), numpy.round(corners.max(0)).astype(int)
        inside[v0 + margin:v1 - margin, u0 + margin:u1 - margin] = True
    return inside


def change(first, second):
    return numpy.abs(first - second).max(-1)


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'slope_normal_export'
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
    check({'normal', 'height'} <= {channel.key for channel in set_channels(data)}, 'the texture set carries normal and height channels')

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

    click(window, region, 'ADD_PAINT')
    yield from settle()
    anchor_uid = active_layer(data).uid
    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def layer():
        return find_layer(data, layer_uid)

    def select_row(uid):
        yield from reveal(window, region, 'ROW_' + uid, 'LAYERS')
        click(window, region, 'ROW_' + uid, fx=.6)
        yield from settle()

    def select_effect(effect_uid):
        yield from reveal(window, region, f'FX_{layer_uid}.{effect_uid}', 'LAYERS')
        click(window, region, f'FX_{layer_uid}.{effect_uid}', fx=.6)
        yield from settle()

    def picker_labels():
        yield from reveal(window, region, 'FX_FILTER')
        click(window, region, 'FX_FILTER')
        yield from settle()
        labels = [item.label for item in editor._active.workspace.controls if item.key.startswith('SET_FXFILTER.')]
        press(window, 'ESC', *middle)
        yield from settle()
        return labels

    for key in ('height', 'normal'):
        yield from reveal(window, region, 'USE.' + key)
        click(window, region, 'USE.' + key)
        yield from settle()
    check(layer().slots['height'].enabled and layer().slots['normal'].enabled, 'the Fill layer carries height and normal')

    texture_dir = scratch / 'slope_textures'
    textures(texture_dir)

    if not editor._active.state.shelf_open:
        click(window, region, 'SHELF_TOGGLE')
        yield from settle()
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(texture_dir), *spot(region, 'TEXTURE_DIR'))
    yield from settle()
    check(library.texture_folder() == str(texture_dir), 'typing the texture folder points the shelf at the generated textures')

    def slot_texture(channel, label):
        yield from menu(window, region, 'SOURCE.' + channel, 'PICK_TEXTURE.' + channel)
        yield from wait_for(lambda: any(item.label == label for item in shelf.items(editor._active.state.shelf_tab)), f'the shelf to list {label}', REFRESH_TIMEOUT)
        click(window, region, f'ITEM.{shelf_index(label)}')
        yield from settle()
        slot = layer().slots[channel]
        check(slot.source == 'IMAGE' and slot.image is not None and slot.image.name.startswith(label), f'{channel} takes the {label} texture')

    yield from slot_texture('base_color', 'checks')
    yield from slot_texture('height', 'ramps')
    yield from reveal(window, region, 'PROJECTION')
    check(layer().projection == 'UV' and control('PROJECTION').text == 'UV', 'the Fill layer maps its textures by UV')
    if editor._active.state.shelf_open:
        click(window, region, 'SHELF_TOGGLE')
        yield from settle()
    sharp = yield from exported()
    height = sharp['Height'][..., 0]
    steep = steepness(height)
    inside = interior(cube, height.shape[0])
    flat_zone, steep_zone = inside & (steep < .02), inside & (steep > .5)
    check(int(flat_zone.sum()) > 2000 and int(steep_zone.sum()) > 2000,
          f'the ramp height has flat and steep areas ({int(flat_zone.sum())} flat, {int(steep_zone.sum())} steep pixels)')

    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    slope_uid = active_effect(data).uid
    labels = yield from picker_labels()
    check('Slope blur' in labels and 'Height to normal' in labels, 'the content filter picker offers Slope blur and Height to normal')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.SLOPE_BLUR')
    check([control('FX_' + field).label if has('FX_' + field) else None for field in ('radius', 'in_low', 'in_high')] == ['Intensity', 'Slope min', 'Slope max'],
          'Slope blur shows Intensity and the Slope range min and max')
    yield from slide(window, region, 'FX_radius', .5)
    check(abs(active_effect(data).radius - 16.0) < 1.0, f'the Intensity slider sets the blur reach ({active_effect(data).radius:.1f} px)')
    yield from slide(window, region, 'FX_opacity', 0.0)
    check(active_effect(data).opacity < .01, 'at zero opacity the Slope blur passes the cached texture below it through unblurred')
    yield from refreshed()
    cached = yield from exported()
    yield from slide(window, region, 'FX_opacity', 1.0)
    check(active_effect(data).opacity > .99, 'the Slope blur goes back to full opacity')
    yield from refreshed()
    sloped = yield from exported()
    moved = change(sloped['BaseColor'], cached['BaseColor'])
    flat_change, steep_change = float(moved[flat_zone].mean()), float(moved[steep_zone].mean())
    check(flat_change < .002 and steep_change > .03,
          f'Slope blur keeps flat areas sharp and blurs steep areas ({flat_change:.4f} flat, {steep_change:.4f} steep)')
    height_moved = change(sloped['Height'], cached['Height'])
    normal_gap = float(change(sloped['Normal'], height_tilted(sloped['Height'][..., 0], data.bump_strength))[inside].max())
    check(normal_gap < .01 and float(height_moved[flat_zone].mean()) < .002,
          f'Slope blur leaves the uniform painted normal untouched, so the exported normal is only the blurred height folded in, '
          f'and keeps flat height as it was ({normal_gap:.4f} normal, {float(height_moved[flat_zone].mean()):.4f} flat height)')
    yield from slide(window, region, 'FX_in_low', .5)
    yield from refreshed()
    narrowed = yield from exported()
    narrow_moved = change(narrowed['BaseColor'], cached['BaseColor'])
    middle_zone = inside & (steep > .3) & (steep < .45)
    narrow_middle, wide_middle = float(narrow_moved[middle_zone].mean()), float(moved[middle_zone].mean())
    check(narrow_middle < wide_middle * .2 and float(narrow_moved[steep_zone].mean()) > steep_change * .5 and float(narrow_moved[flat_zone].mean()) < .002,
          f'raising Slope min keeps gentler slopes sharp ({narrow_middle:.4f} against {wide_middle:.4f} on gentle slopes)')
    yield from slide(window, region, 'FX_in_low', 0.0)
    check(active_effect(data).in_low < .01, 'Slope min returns to zero')

    yield from add_effect(window, region, 'CONTENT', 'FILTER')
    normal_uid = active_effect(data).uid
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.HEIGHT_NORMAL')
    check(has('FX_amount') and control('FX_amount').label == 'Strength', 'Height to normal shows a Strength slider')
    yield from slide(window, region, 'FX_amount', .5)
    yield from height_strength(window, region, middle, False)
    check(data.bump_strength == 0.0, 'the Height strength slider turns off the height folded into the exported normal')
    yield from refreshed()
    shaded = yield from exported()
    check(numpy.array_equal(shaded['Height'], sloped['Height']) and numpy.array_equal(shaded['BaseColor'], sloped['BaseColor']),
          'Height to normal keeps the height and base color as they were')
    normal = shaded['Normal'] * 2 - 1
    surface = shaded['Height'][..., 0]
    across, up = gradient(surface)
    surface_steep = steepness(surface)
    tilted, level_zone = inside & (surface_steep > .5), inside & (surface_steep < .02)
    sloped_x, sloped_y = tilted & (numpy.abs(across) > .01), tilted & (numpy.abs(up) > .01)
    agree = min(float(numpy.mean(numpy.sign(normal[..., 0][sloped_x]) == -numpy.sign(across[sloped_x]))),
                float(numpy.mean(numpy.sign(normal[..., 1][sloped_y]) == -numpy.sign(up[sloped_y]))))
    still_x, still_y = tilted & (numpy.abs(across) < 1e-6), tilted & (numpy.abs(up) < 1e-6)
    sideways = max(float(numpy.abs(normal[..., 0][still_x]).mean()), float(numpy.abs(normal[..., 1][still_y]).mean()))
    level = float(numpy.abs(shaded['Normal'][level_zone] - (.5, .5, 1.0)).max(-1).mean())
    tilt = float(numpy.hypot(normal[..., 0], normal[..., 1])[tilted].mean())
    check(int(sloped_x.sum()) > 1000 and int(sloped_y.sum()) > 1000 and int(still_x.sum()) > 100 and int(still_y.sum()) > 100 and agree > .95 and sideways < .02 and level < .01 and tilt > .2,
          f'Height to normal tilts the tangent normal down the height slope and stays flat where the height is flat '
          f'(direction agrees {agree:.3f}, sideways {sideways:.4f}, flat offset {level:.4f}, steep tilt {tilt:.3f})')
    yield from slide(window, region, 'FX_amount', 1.0)
    yield from refreshed()
    stronger = yield from exported()
    strong_normal = stronger['Normal'] * 2 - 1
    stronger_tilt = float(numpy.hypot(strong_normal[..., 0], strong_normal[..., 1])[tilted].mean())
    check(stronger_tilt > tilt + .05, f'raising Strength tilts the normal further ({stronger_tilt:.3f} against {tilt:.3f})')
    yield from height_strength(window, region, middle, True)
    check(data.bump_strength == 1.0, 'the Height strength slider goes back to full')
    yield from refreshed()
    stronger = yield from exported()
    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'PNF.DIRECTX')
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    check(cube.devil_painter.normal_format == 'DIRECTX', 'the project switches to DirectX normals')
    directx = yield from exported()
    green_range = float(numpy.ptp(stronger['Normal'][..., 1][tilted]))
    format_gap = float(numpy.abs(directx['Normal'] - stronger['Normal'])[tilted].max())
    check(green_range > .3 and format_gap < .01,
          f'in a DirectX project Height to normal writes DirectX normals, so the OpenGL export template exports the same file ({format_gap:.4f}, green spans {green_range:.3f})')
    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'PNF.OPENGL')
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    check(cube.devil_painter.normal_format == 'OPENGL', 'the project goes back to OpenGL normals')

    yield from select_row(anchor_uid)
    yield from set_hex(window, region, 'BRUSH_COLOR', '#000000')
    before = pixels(find_layer(data, anchor_uid).image)[:, 3].reshape(data.resolution, data.resolution)
    stroke(window, region, .42, .45)
    yield from settle()
    painted = pixels(find_layer(data, anchor_uid).image)[:, 3].reshape(data.resolution, data.resolution) - before > .9
    check(int(painted.sum()) > 300, f'a black stroke lands on the anchor layer ({int(painted.sum())} pixels)')
    under = painted & ~grown(~painted, 4)
    away = ~grown(painted, 3)
    yield from select_row(layer_uid)
    for uid in (slope_uid, normal_uid):
        yield from select_effect(uid)
        yield from menu(window, region, 'FX_ANCHOR', f'SET_FXANCHOR.{anchor_uid}')
        yield from menu(window, region, 'FX_ANCHOR_CHANNEL', 'SET_FXANCHORCHANNEL.base_color')
    check([(effect.filter, effect.anchor == anchor_uid) for effect in layer().effects] == [('SLOPE_BLUR', True), ('HEIGHT_NORMAL', True)], 'both filters take the anchor layer as input')
    yield from refreshed()
    anchored = yield from exported()
    slope_held = float(change(anchored['BaseColor'], sharp['BaseColor'])[under & steep_zone].mean())
    slope_free = float(change(anchored['BaseColor'], sharp['BaseColor'])[away & steep_zone].mean())
    normal_held = float(change(anchored['Normal'], sharp['Normal'])[under & tilted].mean())
    normal_free = float(change(anchored['Normal'], sharp['Normal'])[away & tilted].mean())
    check(int((under & steep_zone).sum()) > 20 and slope_free > .1 and slope_held < slope_free * .15 and normal_free > .1 and normal_held < normal_free * .15,
          f'the black anchor stroke switches both filters off under it and leaves them on elsewhere '
          f'(slope {slope_held:.4f} under, {slope_free:.4f} away; normal {normal_held:.4f} under, {normal_free:.4f} away)')

    for uid in (anchor_uid, layer_uid):
        yield from reveal(window, region, 'EYE_' + uid, 'LAYERS')
        click(window, region, 'EYE_' + uid)
        yield from settle()
    check(not find_layer(data, anchor_uid).visible and not layer().visible, 'hiding the anchor and the filtered layer leaves a plain base')
    click(window, region, 'ADD_FILL')
    yield from settle()
    top_uid = active_layer(data).uid
    yield from set_hex(window, region, 'SWATCH.base_color', '#000000')
    unmasked = yield from exported()
    top_color = tuple(round(value, 3) for value in find_layer(data, top_uid).slots['base_color'].color)
    check(top_color == (0.0, 0.0, 0.0) and float(unmasked['BaseColor'][inside].max()) < .01,
          f'the top Fill layer paints the base color black ({top_color}, {float(unmasked["BaseColor"][inside].max()):.3f})')
    yield from reveal(window, region, 'ROW_' + top_uid, 'LAYERS')
    click(window, region, 'ROW_' + top_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'ADD_MASK_WHITE')
    yield from settle()
    yield from add_effect(window, region, 'MASK', 'FILL')
    yield from menu(window, region, 'FX_SOURCE', 'SET_FXPATTERN.STRIPES')
    yield from slide(window, region, 'FX_scale', .04)
    masked = yield from exported()
    check(float(change(masked['BaseColor'], unmasked['BaseColor']).mean()) > .01, 'a striped mask Fill shapes the top layer')
    mask_steep_map = steepness(masked['BaseColor'][..., 0])
    mask_inside = interior(cube, masked['BaseColor'].shape[0])
    mask_flat_zone, mask_steep_zone = mask_inside & (mask_steep_map == 0.0), mask_inside & (mask_steep_map > numpy.percentile(mask_steep_map[mask_inside], 90))
    check(int(mask_flat_zone.sum()) > 2000 and int(mask_steep_zone.sum()) > 2000,
          f'the striped mask has flat and steep areas ({int(mask_flat_zone.sum())} flat, {int(mask_steep_zone.sum())} steep pixels)')
    yield from add_effect(window, region, 'MASK', 'FILTER')
    labels = yield from picker_labels()
    check('Slope blur' in labels and 'Height to normal' not in labels, 'the mask filter picker offers Slope blur but not Height to normal')
    yield from menu(window, region, 'FX_FILTER', 'SET_FXFILTER.SLOPE_BLUR')
    yield from slide(window, region, 'FX_radius', .5)
    top = find_layer(data, top_uid)
    check((top.effects[-1].target, top.effects[-1].filter) == ('MASK', 'SLOPE_BLUR'), 'a Slope blur sits on top of the striped Fill in the mask stack')
    yield from refreshed()
    mask_sloped = yield from exported()
    mask_moved = change(mask_sloped['BaseColor'], masked['BaseColor'])
    mask_flat, mask_steep = float(mask_moved[mask_flat_zone].mean()), float(mask_moved[mask_steep_zone].mean())
    check(mask_flat < .002 and mask_steep > .02, f'the mask Slope blur keeps flat mask areas sharp and blurs steep ones ({mask_flat:.4f} flat, {mask_steep:.4f} steep)')
    settings = [(effect.filter, effect.target, round(effect.radius), round(effect.amount, 2), effect.anchor == anchor_uid)
                for item in data.layers for effect in item.effects if effect.kind == 'FILTER']

    saved_file = scratch / 'slope_normal.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    kept = [(effect.filter, effect.target, round(effect.radius), round(effect.amount, 2), effect.anchor == anchor_uid)
            for item in data.layers for effect in item.effects if effect.kind == 'FILTER']
    check(kept == settings and len(kept) == 3, f'the reopened file keeps both filters and their settings ({kept})')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    reopened = yield from exported()
    gap = max(float(numpy.abs(reopened[name] - mask_sloped[name]).max()) for name in CHANNELS)
    check(gap == 0.0, f'the reopened file exports the same channels ({gap})')
    print('SLOPE NORMAL EVIDENCE', dict(flat_change=round(flat_change, 4), steep_change=round(steep_change, 4), normal_agree=round(agree, 3),
                                        flat_normal=round(level, 4), tilt=(round(tilt, 3), round(stronger_tilt, 3)),
                                        anchor=(round(slope_held, 4), round(slope_free, 4), round(normal_held, 4), round(normal_free, 4)),
                                        mask=(round(mask_flat, 4), round(mask_steep, 4)), reopen_gap=gap))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI SLOPE NORMAL CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI slope normal test')
