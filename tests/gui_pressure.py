import json
import math
import sys
import time
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
from devil_painter import brushes, editor, library, painting
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, close_cards, control, drag_slider, finish, has, move, native_dab, press, run_journey, settle, shelf_index, top_view, viewport

LOW, MIDDLE, HIGH = .25, .5, 1.0
DAB_SPOTS = (-.6, -.2, .2, .6)
CORE_LEVEL = .97
EDGE_LEVEL = .02
TIMED_POINTS = 100
DAB_REACH = .09


def card_click(window, region, key, fx=.5):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == 'BRUSH'):
        click(window, region, 'BRUSH_CARD')
        yield from settle()
    check(has(key), f'the Brush card shows {key}')
    if control(key).kind == 'SLIDER':
        drag_slider(window, region, key, fx)
    else:
        click(window, region, key, fx=fx)
    yield from settle()


def make_plane(obj):
    mesh = bmesh.new()
    mesh.loops.layers.uv.new('UVMap')
    bmesh.ops.create_grid(mesh, x_segments=1, y_segments=1, size=1.0, calc_uvs=True)
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def screen_point(area, region, x):
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, (x, 0.0, 0.0))
    return float(point.x), float(point.y)


def layer_pixels(layer):
    image = layer.image
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)


def dab(window, area, region, points):
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor._active.run_gesture(bpy.context, points)


def center_of(obj, data, point):
    _, u, v = editor._active.texture_point(obj, data, point)
    return int(u), int(v)


def radial(alpha, center):
    u, v = center
    rows, columns = numpy.indices(alpha.shape)
    distance = numpy.hypot(columns - u, rows - v)
    return distance


def profile(alpha, center):
    distance = radial(alpha, center)
    peak = float(alpha[center[1], center[0]])
    near = distance < DAB_REACH * alpha.shape[0]
    edge = float(distance[near & (alpha > EDGE_LEVEL)].max())
    core = float(distance[near & (alpha > CORE_LEVEL * peak)].max())
    return peak, core / edge, edge


def orientation(alpha, center):
    distance = radial(alpha, center)
    rows, columns = numpy.indices(alpha.shape)
    window_mask = distance < DAB_REACH * alpha.shape[0]
    edge = float(distance[window_mask & (alpha > EDGE_LEVEL)].max())
    weight = numpy.where(window_mask & (distance > .6 * edge), alpha, 0.0)
    phi = numpy.arctan2(rows - center[1], columns - center[0])
    fourfold = math.atan2(float((weight * numpy.sin(4 * phi)).sum()), float((weight * numpy.cos(4 * phi)).sum()))
    return math.degrees((fourfold - math.pi) / 4)


def turn(a, b):
    return (b - a + 45.0) % 90.0 - 45.0


def path_samples(alpha, start, end):
    count = max(1, int(math.dist(start, end)))
    return [float(alpha[int(round(start[1] + (end[1] - start[1]) * index / count)),
                        int(round(start[0] + (end[0] - start[0]) * index / count))]) for index in range(count + 1)]


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
    check(not (data.brush_pressure_flow or data.brush_pressure_hardness or data.brush_pressure_angle) and data.brush_pressure_opacity,
          'flow, hardness and angle pressure start off and opacity pressure keeps its default')
    check(not editor._active.wants_gesture(bpy.context), 'with the new mappings off a Paint stroke stays a native Blender stroke')

    yield from card_click(window, region, 'BRUSH_PRESSURE_OPACITY')
    check(not data.brush_pressure_opacity and control('BRUSH_PRESSURE_OPACITY').label == 'Pressure opacity', 'opacity pressure turns off for isolated measurements')
    check(all(has(key) for key in ('BRUSH_PRESSURE_SIZE', 'BRUSH_PRESSURE_OPACITY', 'BRUSH_PRESSURE_FLOW', 'BRUSH_PRESSURE_HARDNESS', 'BRUSH_PRESSURE_ANGLE')),
          'the Brush card lists flow, hardness and angle pressure with size and opacity pressure')
    check([control(key).label for key in ('BRUSH_PRESSURE_FLOW', 'BRUSH_PRESSURE_HARDNESS', 'BRUSH_PRESSURE_ANGLE')]
          == ['Pressure flow', 'Pressure hardness', 'Pressure angle'], 'the new pressure toggles are labelled by parameter')
    yield from close_cards(window, middle)
    edge_left, edge_right = screen_point(area, region, -1.0), screen_point(area, region, 1.0)
    pixels_per_unit = (edge_right[0] - edge_left[0]) / 2
    drag_slider(window, region, 'BRUSH_SIZE', .1)
    yield from settle()
    size = painting.brush_value(bpy.context.scene, 'size')
    check(0 < size < pixels_per_unit * .15, f'the brush is small enough for separate dabs ({size} px, {pixels_per_unit:.0f} px per unit)')
    points = [screen_point(area, region, x) for x in DAB_SPOTS]

    click(window, region, 'ADD_PAINT')
    yield from settle()
    flow_uid = active_layer(data).uid
    yield from card_click(window, region, 'BRUSH_PRESSURE_FLOW')
    check(data.brush_pressure_flow, 'Pressure flow turns on')
    yield from close_cards(window, middle)
    check(editor._active.wants_gesture(bpy.context), 'a pressure-mapped Paint stroke goes through the pressure replay')
    dab(window, area, region, [(points[0], LOW)])
    dab(window, area, region, [(points[1], HIGH)])
    yield from settle()
    alpha = layer_pixels(find_layer(data, flow_uid))[..., 3]
    low_flow, high_flow = (float(alpha[center_of(cube, data, point)[1], center_of(cube, data, point)[0]]) for point in points[:2])
    check(abs(high_flow - 1.0) < .02 and abs(low_flow / high_flow - LOW) < .03,
          f'flow tracks pressure: dab center coverage {low_flow:.4f} at {LOW} and {high_flow:.4f} at {HIGH} (ratio {low_flow / high_flow:.4f})')
    check(abs(data.brush_flow - 1.0) < 1e-6 and abs(bpy.context.tool_settings.image_paint.brush.strength - 1.0) < 1e-6,
          'the stroke leaves the brush flow at its set value')

    start_uv, end_uv = center_of(cube, data, points[0]), center_of(cube, data, points[3])
    click(window, region, 'ADD_PAINT')
    yield from settle()
    continuity_uid = active_layer(data).uid
    dab(window, area, region, [(points[0], LOW), (points[3], HIGH)])
    yield from settle()
    ramp = path_samples(layer_pixels(find_layer(data, continuity_uid))[..., 3], start_uv, end_uv)
    check(min(ramp) > EDGE_LEVEL and ramp[-1] >= ramp[0],
          f'fast pressure-mapped drag stays continuous along the path ({len(ramp)} samples, min {min(ramp):.3f}, {ramp[0]:.3f} to {ramp[-1]:.3f})')
    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=.3)
    yield from close_cards(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    jitter_uid = active_layer(data).uid
    dab(window, area, region, [(points[0], 1.0), (points[3], 1.0)])
    yield from settle()
    jitter_line = path_samples(layer_pixels(find_layer(data, jitter_uid))[..., 3], start_uv, end_uv)
    check(min(jitter_line) > EDGE_LEVEL, f'fast jittered drag stays continuous along the path ({len(jitter_line)} samples, min {min(jitter_line):.3f})')
    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=0.0)
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    yield from close_cards(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    follow_uid = active_layer(data).uid
    dab(window, area, region, [(points[0], 1.0), (points[3], 1.0)])
    yield from settle()
    follow_line = path_samples(layer_pixels(find_layer(data, follow_uid))[..., 3], start_uv, end_uv)
    check(min(follow_line) > EDGE_LEVEL, f'fast Follow path drag stays continuous along the path ({len(follow_line)} samples, min {min(follow_line):.3f})')
    yield from card_click(window, region, 'BRUSH_FOLLOW_PATH')
    yield from card_click(window, region, 'BRUSH_SPACING', fx=.98)
    yield from close_cards(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    spaced_uid = active_layer(data).uid
    dab(window, area, region, [(points[0], 1.0), (points[3], 1.0)])
    yield from settle()
    wide_line = path_samples(layer_pixels(find_layer(data, spaced_uid))[..., 3], start_uv, end_uv)
    check(max(wide_line) > EDGE_LEVEL and min(wide_line) <= EDGE_LEVEL,
          f'wide spacing ({data.brush_spacing:.0f}%) separates replayed dabs along the path (min {min(wide_line):.3f}, max {max(wide_line):.3f})')
    yield from card_click(window, region, 'BRUSH_SPACING', fx=10.0 / 200.0)
    yield from close_cards(window, middle)

    click(window, region, 'ADD_PAINT')
    yield from settle()
    hardness_uid = active_layer(data).uid
    yield from card_click(window, region, 'BRUSH_PRESSURE_FLOW')
    yield from card_click(window, region, 'BRUSH_HARDNESS', fx=.8)
    yield from close_cards(window, middle)
    check(not editor._active.wants_gesture(bpy.context), 'with every pressure mapping off the reference dab is a native Blender stroke')
    native_spot = native_dab(window, region, points[2])
    yield from settle()
    yield from card_click(window, region, 'BRUSH_PRESSURE_HARDNESS')
    hardness = data.brush_hardness
    check(data.brush_pressure_hardness and not data.brush_pressure_flow and .7 < hardness < .9, f'Pressure hardness is on at hardness {hardness:.3f}')
    yield from close_cards(window, middle)
    dab(window, area, region, [(points[0], LOW)])
    dab(window, area, region, [(points[1], HIGH)])
    yield from settle()
    alpha = layer_pixels(find_layer(data, hardness_uid))[..., 3]
    low_peak, low_core, low_edge = profile(alpha, center_of(cube, data, points[0]))
    high_peak, high_core, high_edge = profile(alpha, center_of(cube, data, points[1]))
    check(abs(low_edge - high_edge) <= 2 and low_peak > .97 and high_peak > .97, f'both dabs keep the same size ({low_edge:.1f} and {high_edge:.1f} px)')
    _, _, native_edge = profile(alpha, center_of(cube, data, native_spot))
    check(abs(high_edge - native_edge) <= 2, f'a replayed dab paints at the brush size: {high_edge:.1f} px against {native_edge:.1f} px for a native dab')
    check(abs(high_core - hardness) < .12 and abs(low_core - hardness * LOW) < .12 and high_core / max(low_core, 1e-3) > 2.5,
          f'hardness tracks pressure: solid core {low_core:.3f} of the radius at {LOW} (expected {hardness * LOW:.3f}) and {high_core:.3f} at {HIGH} (expected {hardness:.3f})')
    check(abs(bpy.context.tool_settings.image_paint.brush.get('dp_hardness') - hardness) < 1e-4, 'the stroke restores the set hardness')

    yield from card_click(window, region, 'BRUSH_PRESSURE_HARDNESS')
    yield from card_click(window, region, 'BRUSH_PRESSURE_ANGLE')
    yield from card_click(window, region, 'BRUSH_PRESSURE_SIZE')
    check(data.brush_pressure_size and data.brush_pressure_angle and not data.brush_pressure_hardness and editor._active.wants_gesture(bpy.context),
          'Pressure size is on while Pressure angle keeps the round brush in the pressure replay')
    yield from close_cards(window, middle)
    dab(window, area, region, [(points[3], LOW)])
    yield from settle()
    _, _, sized_edge = profile(layer_pixels(find_layer(data, hardness_uid))[..., 3], center_of(cube, data, points[3]))
    size_response = brushes.pressure_response(bpy.context.tool_settings.image_paint.brush.curve_size, LOW, True)
    check(abs(sized_edge / high_edge - size_response) < .05,
          f'size tracks pressure in the replay: the dab at {LOW} is {sized_edge / high_edge:.4f} of full size (curve {size_response:.4f})')
    yield from card_click(window, region, 'BRUSH_PRESSURE_SIZE')
    yield from card_click(window, region, 'BRUSH_PRESSURE_ANGLE')
    yield from card_click(window, region, 'BRUSH_PRESSURE_HARDNESS')
    check(data.brush_pressure_hardness and not data.brush_pressure_size and not data.brush_pressure_angle, 'the pressure toggles go back to Pressure hardness only')
    yield from close_cards(window, middle)

    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Square")}')
    yield from settle()
    check(data.brush_alpha is not None and not data.brush_pressure_hardness, 'the Square preset gives the brush an alpha and its own pressure settings')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    angle_uid = active_layer(data).uid
    yield from card_click(window, region, 'BRUSH_ANGLE', fx=40 / 360)
    yield from card_click(window, region, 'BRUSH_PRESSURE_ANGLE')
    angle = data.brush_angle
    check(data.brush_pressure_angle and 30 < angle < 45, f'Pressure angle is on at angle {angle:.2f} degrees')
    yield from close_cards(window, middle)
    for point, pressure in zip(points[:3], (LOW, MIDDLE, HIGH)):
        dab(window, area, region, [(point, pressure)])
    yield from settle()
    alpha = layer_pixels(find_layer(data, angle_uid))[..., 3]
    turns = [orientation(alpha, center_of(cube, data, point)) for point in points[:3]]
    low_to_middle, low_to_high = abs(turn(turns[0], turns[1])), abs(turn(turns[0], turns[2]))
    check(abs(low_to_high - angle * (HIGH - LOW)) < 3 and abs(low_to_middle - angle * (MIDDLE - LOW)) < 3,
          f'angle tracks pressure: the tip turns {low_to_middle:.2f} degrees from {LOW} to {MIDDLE} (expected {angle * (MIDDLE - LOW):.2f}) '
          f'and {low_to_high:.2f} degrees from {LOW} to {HIGH} (expected {angle * (HIGH - LOW):.2f})')
    check(abs(math.degrees(bpy.context.tool_settings.image_paint.brush.mask_texture_slot.angle) - angle) < 1e-3, 'the stroke restores the set angle')

    yield from card_click(window, region, 'BRUSH_PRESSURE_FLOW')
    yield from card_click(window, region, 'BRUSH_PRESSURE_HARDNESS')
    check(data.brush_pressure_flow and data.brush_pressure_hardness and data.brush_pressure_angle, 'all three pressure mappings are on')
    start = screen_point(area, region, -.6)
    timed = [((start[0] + index * 2.0, start[1]), .2 + .8 * index / (TIMED_POINTS - 1)) for index in range(TIMED_POINTS)]
    began = time.perf_counter()
    dab(window, area, region, timed)
    mapped_ms = (time.perf_counter() - began) * 1000
    yield from close_cards(window, middle)
    drag_point = screen_point(area, region, .6)
    drag_from = (drag_point[0] + region.x, drag_point[1] + region.y)
    move(window, *drag_from)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(drag_from[0]), y=int(drag_from[1]))
    for step in range(1, 9):
        move(window, drag_from[0], drag_from[1] + step * 4)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(drag_from[0]), y=int(drag_from[1] + 32))
    yield from settle()
    alpha = layer_pixels(find_layer(data, angle_uid))[..., 3]
    tip = center_of(cube, data, (drag_point[0], drag_point[1] + 16))
    check(float(alpha[tip[1], tip[0]]) > .5, 'a mouse stroke with every mapping on still paints through the pressure replay')

    yield from card_click(window, region, 'SAVE_BRUSH')
    saved = json.loads(settings_path.read_text(encoding='utf-8'))['brush_presets'][-1]
    check(saved['pressure_flow'] is True and saved['pressure_hardness'] is True and saved['pressure_angle'] is True,
          f'Save as preset writes the pressure toggles to disk ({saved["name"]})')
    yield from close_cards(window, middle)
    click(window, region, f'ITEM.{shelf_index("Soft Round")}')
    yield from settle()
    check(not (data.brush_pressure_flow or data.brush_pressure_hardness or data.brush_pressure_angle), 'a built-in preset turns the pressure mappings off')
    library._cache.clear()
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index(saved["name"])}')
    yield from settle()
    check(data.brush_pressure_flow and data.brush_pressure_hardness and data.brush_pressure_angle, 'the preset reloaded from disk brings every pressure mapping back')

    saved_file = scratch / 'pressure.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    check(data.brush_pressure_flow and data.brush_pressure_hardness and data.brush_pressure_angle and not data.brush_pressure_opacity,
          'the reopened file keeps every pressure toggle exactly')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    yield from card_click(window, region, 'BRUSH_PRESSURE_ANGLE')
    yield from card_click(window, region, 'BRUSH_PRESSURE_HARDNESS')
    yield from card_click(window, region, 'BRUSH_PRESSURE_FLOW')
    check(not editor._active.wants_gesture(bpy.context), 'turning the mappings off returns Paint to native Blender strokes')
    began = time.perf_counter()
    top_view(area)
    start = screen_point(area, region, -.6)
    dab(window, area, region, [((start[0] + index * 2.0, start[1]), .2 + .8 * index / (TIMED_POINTS - 1)) for index in range(TIMED_POINTS)])
    plain_ms = (time.perf_counter() - began) * 1000
    yield from close_cards(window, middle)
    print('PRESSURE EVIDENCE', dict(flow=dict(low=round(low_flow, 4), high=round(high_flow, 4), ratio=round(low_flow / high_flow, 4), expected=LOW),
                                    hardness=dict(set=round(hardness, 4), low_core=round(low_core, 4), high_core=round(high_core, 4),
                                                  expected_low=round(hardness * LOW, 4), expected_high=round(hardness, 4), radius_px=round(high_edge, 1),
                                                  native_radius_px=round(native_edge, 1)),
                                    size=dict(pressure=LOW, ratio=round(sized_edge / high_edge, 4), expected=round(size_response, 4)),
                                    angle=dict(set=round(angle, 3), orientations=[round(value, 3) for value in turns], low_to_middle=round(low_to_middle, 3),
                                               low_to_high=round(low_to_high, 3), expected_low_to_middle=round(angle * (MIDDLE - LOW), 3),
                                               expected_low_to_high=round(angle * (HIGH - LOW), 3)),
                                    stroke_ms=dict(points=TIMED_POINTS, mapped=round(mapped_ms, 1), unmapped=round(plain_ms, 1))))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI PRESSURE CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI pressure test')
