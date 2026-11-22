import hashlib
import json
import math
import sys
from pathlib import Path
import bmesh
import bpy
import numpy
from bpy_extras import view3d_utils

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import brushes, editor, library
from devil_painter.document import find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, close_cards, control, finish, has, native_dab, new_layer, press, run_journey, settle, shelf_index, spot, top_view, type_text, viewport

GRID = tuple((x, y) for y in (-.5, 0.0, .5) for x in (-.6, -.2, .2, .6))
LOW = .5
EDGE_LEVEL = .02
DAB_REACH = .09
AMOUNT = .6


def card_click(window, region, key, fx=.5):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == 'BRUSH'):
        click(window, region, 'BRUSH_CARD')
        yield from settle()
    check(has(key), f'the Brush card shows {key}')
    click(window, region, key, fx=fx)
    yield from settle()


def make_plane(obj):
    mesh = bmesh.new()
    mesh.loops.layers.uv.new('UVMap')
    bmesh.ops.create_grid(mesh, x_segments=1, y_segments=1, size=1.0, calc_uvs=True)
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def screen_point(area, region, x, y=0.0):
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, (x, y, 0.0))
    return float(point.x), float(point.y)


def layer_alpha(data, uid):
    image = find_layer(data, uid).image
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)[..., 3].copy()


def stroke(window, area, region, points):
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor._active.run_gesture(bpy.context, points)


def center_of(obj, data, point):
    _, u, v = editor._active.texture_point(obj, data, point)
    return int(u), int(v)


def distance_from(alpha, center):
    rows, columns = numpy.indices(alpha.shape)
    return numpy.hypot(columns - center[0], rows - center[1])


def coverage(alpha, center):
    return float(alpha[center[1], center[0]])


def radius(alpha, center):
    distance = distance_from(alpha, center)
    return float(distance[(distance < DAB_REACH * alpha.shape[0]) & (alpha > EDGE_LEVEL)].max())


def orientation(alpha, center):
    distance = distance_from(alpha, center)
    rows, columns = numpy.indices(alpha.shape)
    near = distance < DAB_REACH * alpha.shape[0]
    edge = float(distance[near & (alpha > EDGE_LEVEL)].max())
    weight = numpy.where(near & (distance > .6 * edge), alpha, 0.0)
    phi = numpy.arctan2(rows - center[1], columns - center[0])
    fourfold = math.atan2(float((weight * numpy.sin(4 * phi)).sum()), float((weight * numpy.cos(4 * phi)).sum()))
    return math.degrees((fourfold - math.pi) / 4)


def turn(a, b):
    return (b - a + 45.0) % 90.0 - 45.0


def spread(values):
    return dict(min=round(float(min(values)), 4), max=round(float(max(values)), 4), spread=round(float(max(values) - min(values)), 4))


def paint_plain(window, region, cube, data, points, metric):
    check(not editor._active.wants_gesture(bpy.context), 'the reference dabs are native Blender strokes')
    uid = yield from new_layer(window, region, data)
    spots = [native_dab(window, region, point) for point in points]
    yield from settle()
    alpha = layer_alpha(data, uid)
    return [metric(alpha, center_of(cube, data, spot)) for spot in spots]


def paint_jittered(window, area, region, cube, data, points, pressure, metric):
    uid = yield from new_layer(window, region, data)
    stroke(window, area, region, [(point, pressure) for point in points])
    yield from settle()
    alpha = layer_alpha(data, uid)
    predicted = brushes.dab_jitter(data, len(points), brushes.jitter_seed([(point, pressure) for point in points]))
    return [metric(alpha, center_of(cube, data, point)) for point in points], predicted, uid


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    settings_path = library.library_root() / library.SETTINGS_FILE
    settings_path.unlink(missing_ok=True)
    library._cache.clear()
    cube = bpy.data.objects['Cube']
    make_plane(cube)
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    top_view(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    top_view(area)
    yield from settle()
    data = cube.devil_painter.sets[0]
    check(data.brush_jitter_size == 0 and data.brush_jitter_flow == 0 and data.brush_jitter_angle == 0, 'size, flow and angle jitter start at 0')
    check(not editor._active.wants_gesture(bpy.context), 'with every jitter at 0 a Paint stroke stays a native Blender stroke')

    yield from card_click(window, region, 'BRUSH_PRESSURE_OPACITY')
    check(not data.brush_pressure_opacity, 'opacity pressure turns off for isolated measurements')
    check([control(key).label for key in ('BRUSH_JITTER', 'BRUSH_JITTER_SIZE', 'BRUSH_JITTER_FLOW', 'BRUSH_JITTER_ANGLE')]
          == ['Jitter', 'Size jitter', 'Flow jitter', 'Angle jitter'], 'the Brush card lists size, flow and angle jitter after position jitter')
    check([control(key).text for key in ('BRUSH_JITTER_SIZE', 'BRUSH_JITTER_FLOW', 'BRUSH_JITTER_ANGLE')] == ['0%', '0%', '0%'],
          'the new jitter sliders read 0%')
    click(window, region, 'BRUSH_STROKE')
    yield from settle()
    click(window, region, 'SET_STROKE.DOTS')
    yield from settle()
    check(data.brush_stroke == 'DOTS', 'Dots stroke keeps the measured grid dabs separate')
    yield from close_cards(window, middle)
    click(window, region, 'BRUSH_SIZE', fx=.1)
    yield from settle()
    points = [screen_point(area, region, x, y) for x, y in GRID]
    evidence = {}

    plain = yield from paint_plain(window, region, cube, data, points, radius)
    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=AMOUNT)
    amount = data.brush_jitter_size
    check(abs(amount - AMOUNT) < .03 and editor._active.wants_gesture(bpy.context), f'Size jitter is set to {amount:.3f} and routes Paint through the per-dab replay')
    yield from close_cards(window, middle)
    varied, predicted, _ = yield from paint_jittered(window, area, region, cube, data, points, 1.0, radius)
    reference = sum(plain) / len(plain)
    ratios = [value / reference for value in varied]
    errors = [abs(ratio - scale) for ratio, (scale, _, _) in zip(ratios, predicted)]
    check(max(plain) - min(plain) <= 1.0, f'without jitter every native dab has the same radius ({spread(plain)})')
    check(all(1 - amount - .05 <= ratio <= 1.03 for ratio in ratios), f'replayed dab radii stay inside 1 - amount to 1 of the native dab radius ({spread(ratios)})')
    check(max(ratios) - min(ratios) > amount * .4 and max(errors) < .06, f'each dab gets its own size, matching the seeded draw within {max(errors):.4f}')
    evidence['size'] = dict(amount=round(amount, 4), plain_radius_px=spread(plain), jittered_ratio=spread(ratios),
                            predicted_ratio=spread([scale for scale, _, _ in predicted]), max_error=round(max(errors), 4))
    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=0.0)
    check(data.brush_jitter_size == 0, 'Size jitter goes back to 0')

    yield from close_cards(window, middle)
    plain = yield from paint_plain(window, region, cube, data, points, coverage)
    yield from card_click(window, region, 'BRUSH_JITTER_FLOW', fx=AMOUNT)
    amount = data.brush_jitter_flow
    yield from close_cards(window, middle)
    varied, predicted, first_uid = yield from paint_jittered(window, area, region, cube, data, points, 1.0, coverage)
    errors = [abs(value - scale) for value, (_, scale, _) in zip(varied, predicted)]
    check(max(plain) - min(plain) < .01 and min(plain) > .97, f'without jitter every dab lays down full flow ({spread(plain)})')
    check(all(1 - amount - .03 <= value <= 1.0 for value in varied), f'jittered dab flow stays inside 1 - amount to 1 ({spread(varied)})')
    check(max(varied) - min(varied) > amount * .4 and max(errors) < .03, f'each dab gets its own flow, matching the seeded draw within {max(errors):.4f}')
    evidence['flow'] = dict(amount=round(amount, 4), plain=spread(plain), jittered=spread(varied),
                            predicted=spread([scale for _, scale, _ in predicted]), max_error=round(max(errors), 4))

    uid = yield from new_layer(window, region, data)
    stroke(window, area, region, [(point, 1.0) for point in points])
    yield from settle()
    first, second = layer_alpha(data, first_uid), layer_alpha(data, uid)
    check(numpy.array_equal(first, second), 'the same stroke with the same seed paints bit-identical pixels')
    export_dir = scratch / 'export_jitter'
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    exported = sorted(export_dir.glob('*.png'))
    check(bool(exported), f'the jittered strokes export ({len(exported)} textures)')
    evidence['export_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in exported}

    yield from card_click(window, region, 'BRUSH_PRESSURE_FLOW')
    check(data.brush_pressure_flow and data.brush_jitter_flow > 0, 'Pressure flow and flow jitter are both on')
    yield from close_cards(window, middle)
    uid = yield from new_layer(window, region, data)
    stroke(window, area, region, [(point, LOW) for point in points])
    yield from settle()
    alpha = layer_alpha(data, uid)
    predicted = brushes.dab_jitter(data, len(points), brushes.jitter_seed([(point, LOW) for point in points]))
    combined = [coverage(alpha, center_of(cube, data, point)) for point in points]
    errors = [abs(value - LOW * scale) for value, (_, scale, _) in zip(combined, predicted)]
    check(max(errors) < .03, f'pressure and flow jitter multiply: each dab lays down pressure x jitter within {max(errors):.4f}')
    evidence['flow_with_pressure'] = dict(pressure=LOW, jittered=spread(combined), predicted=spread([LOW * scale for _, scale, _ in predicted]),
                                          max_error=round(max(errors), 4))
    yield from card_click(window, region, 'BRUSH_PRESSURE_FLOW')
    yield from card_click(window, region, 'BRUSH_JITTER_FLOW', fx=0.0)
    check(data.brush_jitter_flow == 0 and not data.brush_pressure_flow, 'flow jitter and pressure flow go back off')
    check(abs(bpy.context.tool_settings.image_paint.brush.strength - data.brush_flow) < 1e-6, 'the stroke leaves the brush flow at its set value')
    yield from close_cards(window, middle)

    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Square")}')
    yield from settle()
    check(data.brush_alpha is not None and not data.brush_random_angle and not data.brush_pressure_opacity,
          'the Square preset gives the brush an alpha without random angle, and opacity pressure stays off')
    yield from card_click(window, region, 'BRUSH_SMOOTHING', fx=0.0)
    check(data.brush_smoothing == 0, 'lazy mouse goes to 0 so the dabs land where they are measured')
    click(window, region, 'BRUSH_STROKE')
    yield from settle()
    click(window, region, 'SET_STROKE.DOTS')
    yield from settle()
    check(data.brush_stroke == 'DOTS', 'Dots stroke keeps the square grid dabs separate')
    yield from close_cards(window, middle)
    plain = yield from paint_plain(window, region, cube, data, points, orientation)
    yield from card_click(window, region, 'BRUSH_JITTER_ANGLE', fx=AMOUNT)
    amount = data.brush_jitter_angle
    yield from close_cards(window, middle)
    varied, predicted, _ = yield from paint_jittered(window, area, region, cube, data, points, 1.0, orientation)
    reference = plain[0]
    turns = [turn(reference, value) for value in varied]
    offsets = [offset for _, _, offset in predicted]
    fits = {sign: max(abs(turn(sign * offset, measured)) for offset, measured in zip(offsets, turns)) for sign in (1, -1)}
    check(max(abs(turn(reference, value)) for value in plain) < 1.0, f'without jitter every dab has the same tip angle ({spread(plain)})')
    check(all(abs(offset) <= amount * 180 + 1e-6 for offset in offsets) and max(offsets) - min(offsets) > amount * 90,
          f'the seeded angle offsets stay inside +/- {amount * 180:.1f} degrees ({spread(offsets)})')
    check(min(fits.values()) < 3.0, f'each dab turns by its own seeded offset, matching within {min(fits.values()):.3f} degrees (modulo the square tip\'s 90 degree symmetry)')
    check(abs(math.degrees(bpy.context.tool_settings.image_paint.brush.mask_texture_slot.angle) - data.brush_angle) < 1e-3, 'the stroke restores the set angle')
    evidence['angle'] = dict(amount=round(amount, 4), plain_degrees=spread(plain), predicted_offsets=spread(offsets),
                             measured_turn_mod_90=spread(turns), max_error=round(min(fits.values()), 4))

    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=.3)
    yield from card_click(window, region, 'BRUSH_JITTER_FLOW', fx=.4)
    saved_amounts = (data.brush_jitter_size, data.brush_jitter_flow, data.brush_jitter_angle)
    yield from card_click(window, region, 'SAVE_BRUSH')
    saved = json.loads(settings_path.read_text(encoding='utf-8'))['brush_presets'][-1]
    check(all(abs(saved[field] - value) < 1e-6 for field, value in zip(brushes.JITTER_FIELDS, saved_amounts)),
          f'Save as preset writes the three jitter amounts to disk ({saved["name"]})')
    yield from close_cards(window, middle)
    click(window, region, f'ITEM.{shelf_index("Chalk")}')
    yield from settle()
    check(data.brush_random_angle and data.brush_jitter_angle == 0 and data.brush_jitter_size == 0 and data.brush_jitter_flow == 0,
          'a built-in preset keeps its random angle and loads every new jitter at 0')
    check(bpy.context.tool_settings.image_paint.brush.mask_texture_slot.use_random and not editor._active.wants_gesture(bpy.context),
          'Random angle still drives Blender\'s own random tip rotation on a native stroke')
    library._cache.clear()
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index(saved["name"])}')
    yield from settle()
    check(all(abs(getattr(data, 'brush_' + field) - value) < 1e-6 for field, value in zip(brushes.JITTER_FIELDS, saved_amounts)),
          'the preset reloaded from disk brings every jitter amount back')

    saved_file = scratch / 'jitter.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    check(all(abs(getattr(data, 'brush_' + field) - value) < 1e-6 for field, value in zip(brushes.JITTER_FIELDS, saved_amounts)),
          'the reopened file keeps every jitter amount exactly')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    for key in ('BRUSH_JITTER_SIZE', 'BRUSH_JITTER_FLOW', 'BRUSH_JITTER_ANGLE'):
        yield from card_click(window, region, key, fx=0.0)
    check(not editor._active.wants_gesture(bpy.context), 'turning every jitter to 0 returns Paint to native Blender strokes')
    yield from close_cards(window, middle)
    print('JITTER EVIDENCE', json.dumps(evidence))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI JITTER CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI jitter test')
