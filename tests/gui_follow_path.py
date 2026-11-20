import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
import bmesh
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Quaternion

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import brushes, editor, library, shelf
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import settle

TIMEOUT = 600
STARTED = time.time()
DAB_REACH = .07
EDGE_LEVEL = .05
STEP = .3
LOW = .5
BASE_ANGLE = 30.0
JITTER_AMOUNT = .3
STRAIGHT_TOLERANCE = 2.0
CURVE_TOLERANCE = 3.0
HAND_TOLERANCE = 12.0
STRAIGHT = dict(right=((-.6, .0), (1.0, .0)), down=((.0, .6), (.0, -1.0)), diagonal=((-.45, -.45), (math.sqrt(.5), math.sqrt(.5))),
                left_up=((.45, -.45), (-math.sqrt(.5), math.sqrt(.5))))
CURVE_RADIUS = .6
CURVE_STEPS = 7
ARROW = 'Arrow'


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


def card_click(window, region, key, fx=.5):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == 'BRUSH'):
        click(window, region, 'BRUSH_CARD')
        yield from settle()
    check(has(key), f'the Brush card shows {key}')
    click(window, region, key, fx=fx)
    yield from settle()


def close_cards(window, middle):
    if editor._active.state.popover is not None:
        press(window, 'ESC', *middle)
    yield from settle()


def shelf_index(label):
    return next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == label)


def make_plane(obj):
    mesh = bmesh.new()
    mesh.loops.layers.uv.new('UVMap')
    bmesh.ops.create_grid(mesh, x_segments=1, y_segments=1, size=1.0, calc_uvs=True)
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def top_view(area):
    view = area.spaces.active.region_3d
    view.view_perspective = 'ORTHO'
    view.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    view.view_location = (0.0, 0.0, 0.0)
    view.view_distance = 3.0


def screen_point(area, region, x, y):
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


def native_dab(window, region, point):
    x, y = round(region.x + point[0]), round(region.y + point[1])
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    return x - region.x, y - region.y


def footprint(alpha, center):
    rows, columns = numpy.indices(alpha.shape)
    near = numpy.hypot(columns - center[0], rows - center[1]) < DAB_REACH * alpha.shape[0]
    return int((near & (alpha > EDGE_LEVEL)).sum())


def center_of(obj, data, point):
    _, u, v = editor._active.texture_point(obj, data, point)
    return u - .5, v - .5


def tip_direction(alpha, center):
    rows, columns = numpy.indices(alpha.shape)
    near = numpy.hypot(columns - center[0], rows - center[1]) < DAB_REACH * alpha.shape[0]
    weight = numpy.where(near & (alpha > EDGE_LEVEL), alpha, 0.0)
    total = float(weight.sum())
    return math.degrees(math.atan2(float((weight * rows).sum()) / total - center[1], float((weight * columns).sum()) / total - center[0]))


def wrap(angle):
    return (angle + 180.0) % 360.0 - 180.0


def spread(values):
    return dict(min=round(float(min(values)), 3), max=round(float(max(values)), 3))


def type_text(window, text, x, y):
    for _ in range(80):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


def new_layer(window, region, data):
    click(window, region, 'ADD_PAINT')
    yield from settle()
    return active_layer(data).uid


def paint_stroke(window, area, region, cube, data, points):
    uid = yield from new_layer(window, region, data)
    stroke(window, area, region, points)
    yield from settle()
    alpha = layer_alpha(data, uid)
    return [tip_direction(alpha, center_of(cube, data, point)) for point, _ in points]


def straight_path(area, region, start, heading, count=5):
    return [screen_point(area, region, start[0] + heading[0] * STEP * index, start[1] + heading[1] * STEP * index) for index in range(count)]


def curve_path(area, region):
    thetas = [math.pi * index / (CURVE_STEPS - 1) for index in range(CURVE_STEPS)]
    return ([screen_point(area, region, CURVE_RADIUS * math.cos(theta), CURVE_RADIUS * math.sin(theta) - .2) for theta in thetas],
            [math.degrees(theta) + 90.0 for theta in thetas])


def screen_heading(points):
    (x0, y0), (x1, y1) = points[0], points[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def arrow_alpha(scratch):
    x, y = brushes.grid(brushes.ALPHA_SIZE)
    shape = numpy.clip((.3 - numpy.hypot(x - .45, y)) * 14, 0, 1).astype(numpy.float32)
    path = scratch / 'arrow_alpha.png'
    brushes.write_gray(path, shape)
    return path


def install_arrow_preset(scratch):
    preset = dict(name=ARROW, alpha=str(arrow_alpha(scratch)), hardness=.9, flow=1.0, spacing=25.0, smoothing=0.0, jitter=0.0, random_angle=False,
                  stroke='SPACE', angle=0.0)
    brushes.user_presets().append(preset)
    library.save_settings()


def hand_jitter_error():
    random = numpy.random.default_rng(186)
    track = [((20.0 + 2.0 * index + random.integers(-1, 2), 300.0 + random.integers(-1, 2)), 1.0) for index in range(200)]
    smoothed = brushes.path_angles(track)[10:-10]
    raw = [math.degrees(math.atan2(b[0][1] - a[0][1], b[0][0] - a[0][0])) for a, b in zip(track[10:-11], track[11:-10])]
    return max(abs(wrap(value)) for value in smoothed), max(abs(wrap(value)) for value in raw)


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
    install_arrow_preset(scratch)
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
    check(not data.brush_follow_path, 'Follow path starts off')
    check(not editor._active.wants_gesture(bpy.context), 'with Follow path off a Paint stroke stays a native Blender stroke')
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    check(control('BRUSH_FOLLOW_PATH').label == 'Follow path' and data.brush_follow_path, 'the Brush card lists Follow path and the click turns it on')
    check(editor._active.wants_gesture(bpy.context), 'Follow path routes Paint through the per-dab replay')
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    check(not data.brush_follow_path and not editor._active.wants_gesture(bpy.context), 'a second click turns Follow path off again')
    yield from close_cards(window, middle)

    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index(ARROW)}')
    yield from settle()
    check(data.brush_alpha is not None and data.brush_smoothing == 0 and not data.brush_random_angle and data.brush_angle == 0,
          'the one-sided Arrow tip loads with lazy mouse, random angle and base angle off')
    click(window, region, 'BRUSH_SIZE', fx=.08)
    yield from settle()
    evidence = {}

    size_uid = yield from new_layer(window, region, data)
    native_spot, replay_spot = screen_point(area, region, -.5, .0), screen_point(area, region, .5, .0)
    check(not editor._active.wants_gesture(bpy.context), 'the reference dab is a native Blender stroke')
    native_spot = native_dab(window, region, native_spot)
    yield from settle()
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    yield from close_cards(window, middle)
    check(data.brush_follow_path and editor._active.wants_gesture(bpy.context), 'Follow path routes the measured dab through the per-dab replay')
    stroke(window, area, region, [(replay_spot, 1.0)])
    yield from settle()
    alpha = layer_alpha(data, size_uid)
    native_area, replay_area = (footprint(alpha, center_of(cube, data, spot)) for spot in (native_spot, replay_spot))
    check(abs(replay_area / native_area - 1) < .05, f'a Follow path dab covers {replay_area} texels against {native_area} for a native dab of the same size')
    evidence['size'] = dict(native_texels=native_area, replay_texels=replay_area, ratio=round(replay_area / native_area, 4))
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    yield from close_cards(window, middle)
    check(not data.brush_follow_path, 'Follow path goes back off for the plain reference stroke')

    probe = straight_path(area, region, (-.6, -.6), (1.0, .0), 5)
    plain = yield from paint_stroke(window, area, region, cube, data, [(point, 1.0) for point in probe])
    reference = plain[0]
    check(max(abs(wrap(value - reference)) for value in plain) < .5, f'with Follow path off every dab points the same way ({spread(plain)})')
    evidence['plain_tip_degrees'] = spread(plain)

    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    check(data.brush_follow_path, 'Follow path is on for the stroke measurements')
    yield from close_cards(window, middle)
    worst = 0.0
    for name, (start, heading) in STRAIGHT.items():
        path = straight_path(area, region, start, heading)
        expected = screen_heading(path)
        measured = yield from paint_stroke(window, area, region, cube, data, [(point, 1.0) for point in path])
        turns = [wrap(value - reference) for value in measured]
        errors = [abs(wrap(turn - expected)) for turn in turns[1:]]
        check(abs(turns[0]) < .5, f'{name}: the first dab keeps the base angle ({turns[0]:.3f} degrees)')
        check(max(errors) < STRAIGHT_TOLERANCE, f'{name}: every later dab points along the stroke at {expected:.1f} degrees, max error {max(errors):.3f}')
        evidence[name] = dict(direction=round(expected, 3), tip_turn=[round(turn, 3) for turn in turns], max_error=round(max(errors), 3))
        worst = max(worst, max(errors))

    path, tangents = curve_path(area, region)
    measured = yield from paint_stroke(window, area, region, cube, data, [(point, 1.0) for point in path])
    turns = [wrap(value - reference) for value in measured]
    predicted = brushes.path_angles([(point, 1.0) for point in path])
    inner = [abs(wrap(turn - tangent)) for turn, tangent in zip(turns[1:-1], tangents[1:-1])]
    rendered = [abs(wrap(turn - heading)) for turn, heading in zip(turns, predicted)]
    rotation = [wrap(b - a) for a, b in zip(turns[1:-1], turns[2:-1])]
    check(abs(turns[0]) < .5, f'curve: the first dab keeps the base angle ({turns[0]:.3f} degrees)')
    check(max(inner) < CURVE_TOLERANCE, f'curve: inner dabs follow the tangent, max error {max(inner):.3f} degrees')
    check(max(rendered) < STRAIGHT_TOLERANCE, f'curve: every dab matches its computed path heading within {max(rendered):.3f} degrees')
    check(all(25.0 < step < 35.0 for step in rotation), f'curve: the tip rotates by about 30 degrees from dab to dab ({spread(rotation)})')
    evidence['curve'] = dict(tangent=[round(value, 3) for value in tangents], tip_turn=[round(turn, 3) for turn in turns],
                             inner_max_error=round(max(inner), 3), heading_max_error=round(max(rendered), 3), end_error=round(abs(wrap(turns[-1] - tangents[-1])), 3))
    evidence['straight_max_error'] = round(worst, 3)

    smoothed, raw = hand_jitter_error()
    check(smoothed < HAND_TOLERANCE and raw > 3 * smoothed, f'a straight stroke with 1 px hand jitter wobbles {smoothed:.2f} degrees at most, against {raw:.2f} point to point')
    evidence['hand_jitter'] = dict(smoothed_max=round(smoothed, 3), raw_max=round(raw, 3))

    yield from card_click(window, region, 'BRUSH_ANGLE', fx=BASE_ANGLE / 360)
    base = data.brush_angle
    yield from close_cards(window, middle)
    path = straight_path(area, region, (-.6, .6), (1.0, .0))
    measured = yield from paint_stroke(window, area, region, cube, data, [(point, 1.0) for point in path])
    turns = [wrap(value - reference) for value in measured]
    errors = [abs(wrap(turn - base - heading)) for turn, heading in zip(turns, brushes.path_angles([(point, 1.0) for point in path]))]
    check(max(errors) < STRAIGHT_TOLERANCE, f'base angle {base:.2f} adds to the path direction, max error {max(errors):.3f} degrees')
    evidence['base_plus_path'] = dict(base=round(base, 3), tip_turn=[round(turn, 3) for turn in turns], max_error=round(max(errors), 3))

    yield from card_click(window, region, 'BRUSH_PRESSURE_ANGLE')
    yield from card_click(window, region, 'BRUSH_JITTER_ANGLE', fx=JITTER_AMOUNT)
    check(data.brush_pressure_angle and data.brush_jitter_angle > 0 and data.brush_follow_path, 'Pressure angle, Angle jitter and Follow path are all on')
    yield from close_cards(window, middle)
    path = curve_path(area, region)[0]
    points = [(point, LOW) for point in path]
    measured = yield from paint_stroke(window, area, region, cube, data, points)
    turns = [wrap(value - reference) for value in measured]
    response = brushes.pressure_response(bpy.context.tool_settings.image_paint.brush.curve_strength, LOW, True)
    jitter = brushes.dab_jitter(data, len(points), brushes.jitter_seed(points))
    expected = [base * response + heading + offset for heading, (_, _, offset) in zip(brushes.path_angles(points), jitter)]
    errors = [abs(wrap(turn - value)) for turn, value in zip(turns, expected)]
    check(max(errors) < STRAIGHT_TOLERANCE, f'angle x pressure + path + jitter matches every dab within {max(errors):.3f} degrees')
    evidence['composed'] = dict(base=round(base, 3), pressure=LOW, response=round(response, 4), expected=[round(wrap(value), 3) for value in expected],
                                tip_turn=[round(turn, 3) for turn in turns], max_error=round(max(errors), 3))
    check(abs(math.degrees(bpy.context.tool_settings.image_paint.brush.mask_texture_slot.angle) - base) < 1e-3, 'the stroke restores the set angle')

    export_dir = scratch / 'export_follow_path'
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    check(bool(sorted(export_dir.glob('*.png'))), 'the follow-path strokes export')

    yield from card_click(window, region, 'SAVE_BRUSH')
    saved = json.loads(settings_path.read_text(encoding='utf-8'))['brush_presets'][-1]
    check(saved['follow_path'] is True, f'Save as preset writes Follow path to disk ({saved["name"]})')
    yield from close_cards(window, middle)
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Square")}')
    yield from settle()
    check(not data.brush_follow_path, 'a built-in preset loads Follow path off')
    library._cache.clear()
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index(saved["name"])}')
    yield from settle()
    check(data.brush_follow_path, 'the preset reloaded from disk brings Follow path back')

    saved_file = scratch / 'follow_path.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    data = bpy.data.objects['Cube'].devil_painter.sets[0]
    check(data.brush_follow_path, 'the reopened file keeps Follow path on')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    yield from card_click(window, region, 'BRUSH_PRESSURE_ANGLE')
    yield from card_click(window, region, 'BRUSH_JITTER_ANGLE', fx=0.0)
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    check(not (data.brush_follow_path or data.brush_pressure_angle or data.brush_jitter_angle), 'Follow path, Pressure angle and Angle jitter go back off')
    check(not editor._active.wants_gesture(bpy.context), 'turning Follow path off returns Paint to native Blender strokes')
    yield from close_cards(window, middle)
    print('FOLLOW PATH EVIDENCE', json.dumps(evidence))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI FOLLOW PATH CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI follow path test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
