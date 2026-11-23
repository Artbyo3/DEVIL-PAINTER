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
from devil_painter import editor, library, painting, shelf
from devil_painter.document import find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, close_cards, control, drag_slider, finish, has, move, new_layer, press, run_journey, settle, spot, top_view, type_text, viewport

RESOLUTION = 1024
TEXTURE_SIZE = 256
STRIPES = 4
SOLID = .95
MEASURED_TEXELS = 1000
BAND = .5
ANGLE_TOLERANCE = 3.0
CURVE_TOLERANCE = 4.0
REPEAT_TOLERANCE = .05
CURVE_REPEAT_TOLERANCE = .08
MATERIAL = 'Stripes'
HORIZONTAL = ((-.8, .6), (.0, .6))
VERTICAL = ((.5, -.6), (.5, .2))
DIAGONAL = ((-.75, -.15), (-.15, .45))
MIRRORED = ((.25, -.75), (.75, -.25))
RADIAL = ((.3, .15), (.8, .15))
CURVE_CENTER = (.0, -.1)
CURVE_RADIUS = .5
CURVE_POINTS = 48
CURVE_SAMPLES = (30.0, 50.0, 70.0, 90.0, 110.0, 130.0, 150.0)


def card_click(window, region, opener, key, popover, fx=.5):
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == popover):
        click(window, region, opener)
        yield from settle()
    check(has(key), f'{opener} shows {key}')
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


def screen_point(area, region, x, y):
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, (x, y, 0.0))
    return float(point.x), float(point.y)


def texel(x, y):
    return numpy.array(((x + 1) / 2 * RESOLUTION, (y + 1) / 2 * RESOLUTION))


def write_texture(path, red, green, blue):
    pixels = numpy.ones((TEXTURE_SIZE, TEXTURE_SIZE, 4), dtype=numpy.float32)
    pixels[..., 0], pixels[..., 1], pixels[..., 2] = red, green, blue
    image = bpy.data.images.new(path.stem, TEXTURE_SIZE, TEXTURE_SIZE, alpha=False)
    try:
        image.pixels.foreach_set(pixels.ravel())
        image.filepath_raw = str(path)
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)
    return str(path)


def install_material(scratch):
    columns = (numpy.arange(TEXTURE_SIZE) + .5) / TEXTURE_SIZE
    across = numpy.broadcast_to(columns[:, None], (TEXTURE_SIZE, TEXTURE_SIZE))
    along = numpy.broadcast_to(columns[None, :], (TEXTURE_SIZE, TEXTURE_SIZE))
    stripes = .5 + .5 * numpy.sin(math.tau * STRIPES * along)
    base = write_texture(scratch / 'stripes_basecolor.png', stripes, .2, across)
    ramp = write_texture(scratch / 'stripes_roughness.png', along, along, along)
    library.add_user_material(library.material(MATERIAL, base_color=dict(source='IMAGE', image=base), roughness=dict(source='IMAGE', image=ramp)))


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)


def orientation(values, mask):
    gy, gx = numpy.gradient(values)
    xx, yy, xy = (float((part * mask).sum()) for part in (gx * gx, gy * gy, gx * gy))
    return math.degrees(.5 * math.atan2(2 * xy, xx - yy)) % 180.0


def angle_error(measured, expected):
    return abs((measured - expected + 90.0) % 180.0 - 90.0)


def band(shape, start, end, radius):
    rows, columns = numpy.indices(shape)
    direction = (end - start) / numpy.linalg.norm(end - start)
    relative = numpy.stack((columns - start[0], rows - start[1]), axis=-1)
    along = relative @ direction / numpy.linalg.norm(end - start)
    across = numpy.abs(relative @ numpy.array((-direction[1], direction[0])))
    return (along > .25) & (along < .75) & (across < BAND * radius)


def disc(shape, center, radius):
    rows, columns = numpy.indices(shape)
    return numpy.hypot(columns - center[0], rows - center[1]) < BAND * radius


def straight_orientation(layer, start, end, radius):
    values = pixels(layer.image)
    mask = band(values.shape[:2], start, end, radius) & (values[..., 3] > SOLID)
    return round(orientation(values[..., 0], mask), 3), int(mask.sum())


def repeat_length(layer, track):
    values = pixels(layer.slots['roughness'].image)
    samples = numpy.array([values[int(round(y)), int(round(x)), 0] for x, y in track])
    steps = numpy.diff(samples)
    steps = numpy.where(steps < -.5, steps + 1, numpy.where(steps > .5, steps - 1, steps))
    travel = float(numpy.hypot(*numpy.diff(numpy.array(track), axis=0).T).sum())
    advance = float(steps.sum())
    return dict(min_step=round(float(steps.min()), 4), advance=round(advance, 4),
                repeat_texels=round(travel / advance, 2) if advance > 1e-3 else None)


def straight_track(start, end, low=.25, high=.75):
    length = numpy.linalg.norm(end - start)
    return [tuple(start + (end - start) * share) for share in numpy.linspace(low, high, max(2, int(length * (high - low))))]


def curve_world(theta):
    return CURVE_CENTER[0] + CURVE_RADIUS * math.cos(theta), CURVE_CENTER[1] + CURVE_RADIUS * math.sin(theta)


def stroke(window, area, region, world_points):
    points = [(screen_point(area, region, x, y), 1.0) for x, y in world_points]
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor._active.run_gesture(bpy.context, points)


def line(start, end, count=24):
    return [(start[0] + (end[0] - start[0]) * index / (count - 1), start[1] + (end[1] - start[1]) * index / (count - 1)) for index in range(count)]


def paint_line(window, area, region, data, start, end):
    uid = yield from new_layer(window, region, data)
    stroke(window, area, region, line(start, end))
    yield from settle()
    return find_layer(data, uid)


def drag(window, area, region, start, end, count=24):
    points = [screen_point(area, region, *point) for point in line(start, end, count)]
    x, y = region.x + points[0][0], region.y + points[0][1]
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    yield from settle()
    for px, py in points[1:]:
        move(window, region.x + px, region.y + py)
    yield from settle()
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(region.x + points[-1][0]), y=int(region.y + points[-1][1]))
    yield from settle()


def save_still(folder, name, layer):
    values = pixels(layer.image)
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


def brush_radius(cube, data, area, region):
    first = screen_point(area, region, 0.0, 0.0)
    size = painting.brush_value(bpy.context.scene, 'size')
    near = editor._active.texture_point(cube, data, first)
    far = editor._active.texture_point(cube, data, (first[0] + size, first[1]))
    return math.dist(near[1:], far[1:])


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    stills = scratch / 'material_stroke'
    stills.mkdir(exist_ok=True)
    cube = bpy.data.objects['Cube']
    make_plane(cube)
    devil_painter.register()
    yield from settle()
    install_material(scratch)
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
    check(not editor._active.wants_gesture(bpy.context), 'a plain brush paints with a native Blender stroke')

    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    hard = next(index for index, item in enumerate(shelf.items('BRUSHES')) if item.label == 'Hard Round')
    click(window, region, f'ITEM.{hard}')
    yield from settle()
    drag_slider(window, region, 'BRUSH_SIZE', .06)
    yield from settle()
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    item = next(item.key for item in editor._active.workspace.controls if item.key.startswith('ITEM.') and item.label == MATERIAL)
    click(window, region, item, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, f'PAINT_MATERIAL.{item.removeprefix("ITEM.")}')
    yield from settle()
    check(data.brush_material == MATERIAL and data.brush_slots['base_color'].source == 'IMAGE' and data.brush_slots['roughness'].source == 'IMAGE',
          'the striped material puts its base color and roughness textures on the brush')
    routed = editor._active.wants_gesture(bpy.context)
    radius = brush_radius(cube, data, area, region)
    evidence = dict(radius_texels=round(radius, 2), expected_repeat_texels=round(2 * radius, 2), routed_through_replay=routed)

    measured = {}
    for name, (start, end), expected in (('0_degrees', HORIZONTAL, 0.0), ('90_degrees', VERTICAL, 90.0)):
        layer = yield from paint_line(window, area, region, data, start, end)
        save_still(stills, name, layer)
        angle, count = straight_orientation(layer, texel(*start), texel(*end), radius)
        measured[name] = (angle, expected)
        evidence[name] = dict(stroke_degrees=expected, pattern_degrees=angle, error=round(angle_error(angle, expected), 3), texels=count,
                              phase=repeat_length(layer, straight_track(texel(*start), texel(*end))))

    uid = yield from new_layer(window, region, data)
    yield from drag(window, area, region, *DIAGONAL)
    layer = find_layer(data, uid)
    save_still(stills, 'drag_45_degrees', layer)
    angle, count = straight_orientation(layer, texel(*DIAGONAL[0]), texel(*DIAGONAL[1]), radius)
    measured['drag_45_degrees'] = (angle, 45.0)
    evidence['drag_45_degrees'] = dict(stroke_degrees=45.0, pattern_degrees=angle, error=round(angle_error(angle, 45.0), 3), texels=count)

    uid = yield from new_layer(window, region, data)
    thetas = [math.pi * index / (CURVE_POINTS - 1) for index in range(CURVE_POINTS)]
    stroke(window, area, region, [curve_world(theta) for theta in thetas])
    yield from settle()
    layer = find_layer(data, uid)
    save_still(stills, 'curve', layer)
    values = pixels(layer.image)
    samples = []
    for degrees in CURVE_SAMPLES:
        mask = disc(values.shape[:2], texel(*curve_world(math.radians(degrees))), radius) & (values[..., 3] > SOLID)
        angle = round(orientation(values[..., 0], mask), 3)
        samples.append(dict(at=degrees, tangent=(degrees + 90.0) % 180.0, pattern_degrees=angle, error=round(angle_error(angle, degrees + 90.0), 3)))
    arc = [tuple(texel(*curve_world(math.radians(degrees)))) for degrees in numpy.linspace(30.0, 150.0, 400)]
    evidence['curve'] = dict(samples=samples, phase=repeat_length(layer, arc))

    yield from card_click(window, region, 'SYMMETRY', 'MIRROR.X', 'SYMMETRY')
    yield from close_cards(window, middle)
    check(data.brush_mirror[0], 'Mirror X is on for the symmetry stroke')
    layer = yield from paint_line(window, area, region, data, *MIRRORED)
    save_still(stills, 'mirror', layer)
    copy = tuple((-x, y) for x, y in MIRRORED)
    evidence['mirror'] = dict(primary=straight_orientation(layer, texel(*MIRRORED[0]), texel(*MIRRORED[1]), radius)[0],
                              copy=straight_orientation(layer, texel(*copy[0]), texel(*copy[1]), radius)[0])
    yield from card_click(window, region, 'SYMMETRY', 'MIRROR.X', 'SYMMETRY')
    yield from card_click(window, region, 'SYMMETRY', 'RADIAL', 'SYMMETRY', fx=.2)
    yield from card_click(window, region, 'SYMMETRY', 'RADIAL_AXIS.Z', 'SYMMETRY')
    yield from close_cards(window, middle)
    check(data.brush_radial == 4 and not data.brush_mirror[0], 'radial symmetry makes four copies around Z')
    layer = yield from paint_line(window, area, region, data, *RADIAL)
    save_still(stills, 'radial', layer)
    turned = {}
    for name, (cosine, sine) in dict(quarter=(0.0, 1.0), half=(-1.0, 0.0), three_quarter=(0.0, -1.0)).items():
        start, end = ((cosine * x - sine * y, sine * x + cosine * y) for x, y in RADIAL)
        turned[name] = straight_orientation(layer, texel(*start), texel(*end), radius)[0]
    evidence['radial'] = turned
    yield from card_click(window, region, 'SYMMETRY', 'RADIAL', 'SYMMETRY', fx=0.0)
    yield from close_cards(window, middle)
    print('MATERIAL STROKE EVIDENCE', json.dumps(evidence))

    check(routed, 'a material brush stroke runs through the per-dab replay so its path is known')
    for name, (angle, expected) in measured.items():
        check(evidence[name]['texels'] > MEASURED_TEXELS, f'{name}: the stroke painted {evidence[name]["texels"]} solid texels to measure')
        check(angle_error(angle, expected) < ANGLE_TOLERANCE, f'{name}: the material pattern runs along the stroke at {angle:.2f} degrees')
    for name in ('0_degrees', '90_degrees'):
        phase = evidence[name]['phase']
        check(phase['min_step'] > -.02 and phase['repeat_texels'] is not None and abs(phase['repeat_texels'] / (2 * radius) - 1) < REPEAT_TOLERANCE,
              f'{name}: the texture advances monotonically and repeats every {phase["repeat_texels"]} texels for a {2 * radius:.1f} texel brush')
    worst = max(sample['error'] for sample in samples)
    check(worst < CURVE_TOLERANCE, f'curve: the pattern follows the tangent at every sample, max error {worst:.2f} degrees')
    phase = evidence['curve']['phase']
    check(phase['min_step'] > -.02 and phase['repeat_texels'] is not None and abs(phase['repeat_texels'] / (2 * radius) - 1) < CURVE_REPEAT_TOLERANCE,
          f'curve: the texture advances along the arc without re-anchoring, repeating every {phase["repeat_texels"]} texels')
    check(angle_error(evidence['mirror']['primary'], 45.0) < ANGLE_TOLERANCE and angle_error(evidence['mirror']['copy'], 135.0) < ANGLE_TOLERANCE,
          f'Mirror X: the copy runs along its own mirrored stroke ({evidence["mirror"]})')
    check(all(angle_error(turned[name], expected) < ANGLE_TOLERANCE for name, expected in (('quarter', 90.0), ('half', 0.0), ('three_quarter', 90.0))),
          f'radial: every rotated copy runs along its own stroke ({turned})')

    export_dir = scratch / 'export_material_stroke'
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    check(bool(sorted(export_dir.glob('*.png'))), 'the material strokes export')

    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_MATERIAL_CLEAR', 'BRUSH')
    yield from close_cards(window, middle)
    check(data.brush_material == '' and not editor._active.wants_gesture(bpy.context), 'clearing the material returns Paint to native Blender strokes')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI MATERIAL STROKE CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI material stroke test')
