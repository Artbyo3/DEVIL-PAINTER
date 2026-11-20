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
from devil_painter import editor, painting, shelf
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import settle

TIMEOUT = 600
STARTED = time.time()
RESOLUTION = 1024
UV_SCALE = .4
TEXELS_PER_UNIT = UV_SCALE * RESOLUTION
CORE = .35
SOLID = .99
UNTOUCHED = .05
MEASURED_TEXELS = 500
SEAM_TOLERANCE = 4.0
BROKEN_SHARE = .02
SEAM = dict(source=(-.7, -.4), path=((-.45, .35), (.45, .35)))
ISLAND = dict(source=(-.75, .65), path=((-.75, -.15), (-.3, -.6)))
COMPOSED = dict(source=(-.7, .65), path=((-.8, -.15), (-.35, -.55)))


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


def toggle_mirror(window, region, middle):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == 'SYMMETRY'):
        click(window, region, 'SYMMETRY')
        yield from settle()
    check(has('MIRROR.X'), 'the symmetry card shows Mirror X')
    click(window, region, 'MIRROR.X')
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()


def island_uv(x, y):
    if x < 0:
        return .05 + (x + 1) * UV_SCALE, .1 + (y + 1) * UV_SCALE
    return .95 - x * UV_SCALE, .9 - (y + 1) * UV_SCALE


def make_seamed_plane(obj):
    mesh = bmesh.new()
    layer = mesh.loops.layers.uv.new('UVMap')
    bmesh.ops.create_grid(mesh, x_segments=2, y_segments=1, size=1.0)
    for face in mesh.faces:
        left = face.calc_center_median().x < 0
        for loop in face.loops:
            x, y = loop.vert.co.x, loop.vert.co.y
            loop[layer].uv = island_uv(x - 1e-6 if left else x + 1e-6, y)
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def texel_positions():
    centers = (numpy.arange(RESOLUTION) + .5) / RESOLUTION
    u, v = numpy.meshgrid(centers, centers)
    left = (u >= .05) & (u <= .45) & (v >= .1) & (v <= .9)
    right = (u >= .55) & (u <= .95) & (v >= .1) & (v <= .9)
    x = numpy.where(left, (u - .05) / UV_SCALE - 1, numpy.where(right, (.95 - u) / UV_SCALE, numpy.nan))
    y = numpy.where(left, (v - .1) / UV_SCALE - 1, numpy.where(right, (.9 - v) / UV_SCALE - 1, numpy.nan))
    return numpy.stack((x, y), axis=-1), left | right


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)


def fill_positions(image, positions, inside):
    values = numpy.zeros((RESOLUTION, RESOLUTION, 4), dtype=numpy.float32)
    values[inside, 0] = (positions[inside, 0] + 1) / 2
    values[inside, 1] = (positions[inside, 1] + 1) / 2
    values[inside, 2] = .5
    values[inside, 3] = 1.0
    image.pixels.foreach_set(values.ravel())
    image.update()


def top_view(area):
    view = area.spaces.active.region_3d
    view.view_perspective = 'ORTHO'
    view.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    view.view_location = (0.0, 0.0, 0.0)
    view.view_distance = 3.0


def screen_point(area, region, x, y):
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, (x, y, 0.0))
    return float(point.x), float(point.y)


def line(start, end, count=32):
    return [(start[0] + (end[0] - start[0]) * index / (count - 1), start[1] + (end[1] - start[1]) * index / (count - 1)) for index in range(count)]


def world_radius(area, region):
    size = painting.brush_value(bpy.context.scene, 'size')
    left, right = screen_point(area, region, 0.0, 0.0), screen_point(area, region, 1.0, 0.0)
    return size / (right[0] - left[0])


def near_path(positions, path, reach):
    start, end = numpy.array(path[0]), numpy.array(path[1])
    direction = end - start
    share = numpy.clip(((positions - start) @ direction) / (direction @ direction), 0.0, 1.0)
    gap = positions - (start + share[..., None] * direction)
    return numpy.hypot(gap[..., 0], gap[..., 1]) < reach


def clone_errors(values, positions, inside, path, offset, reach):
    core = inside & near_path(numpy.nan_to_num(positions), path, reach)
    decoded = numpy.stack((values[..., 0] * 2 - 1, values[..., 1] * 2 - 1), axis=-1)
    shift = -numpy.array(offset)
    blend = numpy.clip(((decoded - positions) @ shift) / (shift @ shift), 0.0, 1.0)
    error = numpy.hypot(*(decoded - positions - blend[..., None] * shift).transpose(2, 0, 1)) * TEXELS_PER_UNIT
    solid = values[..., 3] > SOLID
    untouched = core & solid & (blend <= UNTOUCHED)
    return core & ~untouched, untouched, numpy.where(solid, error, numpy.inf)


def summary(error, mask, untouched):
    picked = error[mask]
    finite = picked[numpy.isfinite(picked)]
    return dict(texels=int(mask.sum()), untouched=int(untouched.sum()),
                median_texels=round(float(numpy.median(finite)), 2) if finite.size else None,
                p95_texels=round(float(numpy.percentile(finite, 95)), 2) if finite.size else None,
                max_texels=round(float(finite.max()), 2) if finite.size else None,
                emptied=int((~numpy.isfinite(picked)).sum()),
                broken_share=round(float((~(picked <= SEAM_TOLERANCE)).mean()), 4) if picked.size else None)


def seam_profile(error, y):
    rows = []
    for x in numpy.round(numpy.linspace(-.4, .4, 9), 2):
        u, v = island_uv(float(x), y)
        row, column = int(v * RESOLUTION), int(u * RESOLUTION)
        measured = None if not numpy.isfinite(error[row, column]) else round(float(error[row, column]), 2)
        rows.append(dict(x=float(x), error_texels=measured))
    return rows


def save_still(folder, name, values):
    shown = numpy.ones_like(values)
    shown[..., :3] = .18 + values[..., 3:] * (values[..., :3] - .18)
    image = bpy.data.images.new(name, values.shape[1], values.shape[0], alpha=False)
    try:
        image.pixels.foreach_set(shown.ravel())
        image.filepath_raw = str(folder / f'{name}.png')
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)


def fresh_layer(window, region, data, positions, inside):
    click(window, region, 'ADD_PAINT')
    yield from settle()
    layer = active_layer(data)
    fill_positions(layer.image, positions, inside)
    yield from settle()
    return layer.uid


def set_source(window, area, region, source):
    x, y = screen_point(area, region, *source)
    move(window, region.x + x, region.y + y)
    yield from settle()
    before = editor._active.state.clone_source
    press(window, 'LEFTMOUSE', region.x + x, region.y + y, ctrl=True)
    yield from settle()
    check(editor._active.state.clone_source not in (None, before), f'Ctrl+click sets the clone source at {source}')


def clone_stroke(window, area, region, path, pressures=None):
    world = line(*path)
    pressures = pressures or [1.0] * len(world)
    points = [(screen_point(area, region, x, y), pressure) for (x, y), pressure in zip(world, pressures)]
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor._active.run_gesture(bpy.context, points)
    yield from settle()


def clone_drag(window, area, region, path):
    points = [screen_point(area, region, *point) for point in line(*path)]
    move(window, region.x + points[0][0], region.y + points[0][1])
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(region.x + points[0][0]), y=int(region.y + points[0][1]))
    yield from settle()
    for x, y in points[1:]:
        move(window, region.x + x, region.y + y)
    yield from settle()
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(region.x + points[-1][0]), y=int(region.y + points[-1][1]))
    yield from settle()


def offset_of(case):
    return tuple(case['path'][0][axis] - case['source'][axis] for axis in (0, 1))


def run_case(window, area, region, data, positions, inside, case, stroke, folder, name, pressures=None):
    uid = yield from fresh_layer(window, region, data, positions, inside)
    yield from set_source(window, area, region, case['source'])
    if stroke == 'drag':
        yield from clone_drag(window, area, region, case['path'])
    else:
        yield from clone_stroke(window, area, region, case['path'], pressures)
    values = pixels(find_layer(data, uid).image).copy()
    save_still(folder, name, values)
    numpy.save(folder / f'{name}.npy', values)
    return values


def journey():
    scratch = prepare_scratch()
    folder = scratch / 'clone_surface'
    folder.mkdir(exist_ok=True)
    cube = bpy.data.objects['Cube']
    make_seamed_plane(cube)
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    top_view(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, f'RES.0.{RESOLUTION}')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    top_view(area)
    yield from settle()
    data = cube.devil_painter.sets[0]
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    hard = next(index for index, item in enumerate(shelf.items('BRUSHES')) if item.label == 'Hard Round')
    click(window, region, f'ITEM.{hard}')
    yield from settle()
    click(window, region, 'BRUSH_SIZE', fx=.06)
    yield from settle()
    click(window, region, 'CLONE')
    yield from settle()
    check(painting.active_tool(bpy.context.scene) == 'CLONE', 'the Clone tool is active')
    positions, inside = texel_positions()
    radius = world_radius(area, region)
    reach = CORE * radius
    evidence = dict(radius_world=round(radius, 4), radius_texels=round(radius * TEXELS_PER_UNIT, 2), texels_per_unit=TEXELS_PER_UNIT,
                    quantization_texels=round(2 / 255 * TEXELS_PER_UNIT, 2))

    values = yield from run_case(window, area, region, data, positions, inside, SEAM, 'drag', folder, 'seam')
    core, untouched, error = clone_errors(values, positions, inside, SEAM['path'], offset_of(SEAM), reach)
    left, right = (numpy.nan_to_num(positions[..., 0]) < 0), (numpy.nan_to_num(positions[..., 0]) > 0)
    evidence['seam'] = dict(offset=offset_of(SEAM), left_island=summary(error, core & left, untouched & left),
                            right_island=summary(error, core & right, untouched & right), profile=seam_profile(error, SEAM['path'][0][1]))

    values = yield from run_case(window, area, region, data, positions, inside, ISLAND, 'stroke', folder, 'island')
    core, untouched, error = clone_errors(values, positions, inside, ISLAND['path'], offset_of(ISLAND), reach)
    evidence['island'] = dict(offset=offset_of(ISLAND), core=summary(error, core, untouched))

    data.brush_spacing = 25.0
    data.brush_jitter_size = .4
    data.brush_jitter_flow = .3
    data.brush_pressure_size = True
    yield from toggle_mirror(window, region, middle)
    check(data.brush_mirror[0], 'Mirror X is on for the composed clone stroke')
    pressures = list(numpy.linspace(.35, 1.0, 32))
    values = yield from run_case(window, area, region, data, positions, inside, COMPOSED, 'stroke', folder, 'composed', pressures)
    mirrored = tuple((-x, y) for x, y in COMPOSED['path'])
    core, untouched, error = clone_errors(values, positions, inside, COMPOSED['path'], offset_of(COMPOSED), reach)
    copy, copy_untouched, copy_error = clone_errors(values, positions, inside, mirrored, offset_of(COMPOSED), reach)
    evidence['composed'] = dict(offset=offset_of(COMPOSED), primary=summary(error, core, untouched), mirrored_copy=summary(copy_error, copy, copy_untouched))
    yield from toggle_mirror(window, region, middle)
    check(not data.brush_mirror[0], 'Mirror X is off again')
    data.brush_pressure_size = False
    data.brush_jitter_size = data.brush_jitter_flow = 0.0
    data.brush_spacing = 10.0
    print('CLONE SURFACE EVIDENCE', json.dumps(evidence))
    (folder / 'evidence.json').write_text(json.dumps(evidence, indent=1), encoding='utf-8')

    for name, measured in (('seam left island', evidence['seam']['left_island']), ('seam right island', evidence['seam']['right_island']),
                           ('single island', evidence['island']['core']), ('composed stroke', evidence['composed']['primary']),
                           ('mirrored copy', evidence['composed']['mirrored_copy'])):
        check(measured['texels'] > MEASURED_TEXELS, f'{name}: {measured["texels"]} core texels were measured')
        check(measured['broken_share'] <= BROKEN_SHARE,
              f'{name}: cloned texels sample the surface offset (median {measured["median_texels"]}, p95 {measured["p95_texels"]} texels, {measured["broken_share"]:.2%} off)')

    click(window, region, 'PAINT')
    yield from settle()
    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI CLONE SURFACE CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI clone surface test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
