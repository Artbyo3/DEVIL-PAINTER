import json
import math
import sys
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
from devil_painter import editor, library, painting
from devil_painter.document import find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import POLL, check, click, finish, move, new_layer, press, reveal, run_journey, settle, shelf_index, viewport

DISTANCE = 3.0
EDGE = .5
SLACK = 1.0
DRAG_STEPS = 12


def make_plane(obj):
    mesh = bmesh.new()
    mesh.loops.layers.uv.new('UVMap')
    bmesh.ops.create_grid(mesh, x_segments=1, y_segments=1, size=1.0, calc_uvs=True)
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def aim(area):
    view = area.spaces.active.region_3d
    view.view_perspective = 'ORTHO'
    view.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    view.view_location = (0.0, 0.0, 0.0)
    view.view_distance = DISTANCE


def screen_point(area, region, x, y):
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, (x, y, 0.0))
    return float(point.x), float(point.y)


def free_spot(point):
    return not editor._active.workspace.covers(*point) and editor._active.workspace.hit(*point) is None


def texel(obj, data, point):
    found = editor._active.texture_point(obj, data, point)
    return found[1], found[2]


def channel(image, index):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)[..., index].copy()


def layer_alpha(data, uid):
    return channel(find_layer(data, uid).image, 3)


def shift_click(window, region, point):
    press(window, 'LEFTMOUSE', region.x + point[0], region.y + point[1], shift=True)


def distances(painted, start, end):
    rows, columns = numpy.nonzero(painted)
    points = numpy.stack([columns, rows], axis=1).astype(numpy.float64)
    start, end = numpy.array(start), numpy.array(end)
    span = end - start
    length = float(span @ span)
    along = numpy.clip(((points - start) @ span) / length, 0.0, 1.0) if length else numpy.zeros(len(points))
    return numpy.linalg.norm(points - (start + along[:, None] * span), axis=1)


def samples(start, end):
    count = max(1, int(math.dist(start, end)))
    return [(start[0] + (end[0] - start[0]) * index / count, start[1] + (end[1] - start[1]) * index / count) for index in range(count + 1)]


def line_report(painted, start, end, radius):
    away = distances(painted, start, end)
    along = [bool(painted[int(round(v)), int(round(u))]) for u, v in samples(start, end)]
    return dict(length_texels=round(math.dist(start, end), 1), painted=int(painted.sum()), max_distance=round(float(away.max()), 2),
                outside_band=int((away > radius + SLACK).sum()), samples=len(along), gaps=along.count(False))


def check_line(report, radius, label):
    check(report['painted'] > 0, f'{label}: the segment painted {report["painted"]} texels')
    check(report['gaps'] == 0, f'{label}: all {report["samples"]} texel samples along the {report["length_texels"]}-texel segment are painted (no gaps)')
    check(report['outside_band'] == 0, f'{label}: no painted texel lies beyond the single-dab reach {radius:.1f} + {SLACK} of the segment (max {report["max_distance"]})')


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    cube = bpy.data.objects['Cube']
    make_plane(cube)
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    aim(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = cube.devil_painter.sets[0]
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Hard Round")}')
    yield from settle()
    check(painting.active_tool(bpy.context.scene) == 'PAINT' and data.brush_stroke == 'SPACE', 'Paint with the Space stroke method is active')
    check(not editor._active.wants_gesture(bpy.context), 'a plain Paint stroke is a native Blender stroke here')
    point = lambda x, y: screen_point(area, region, x, y)
    a, b, c, d, e, h = point(-.55, -.45), point(.5, .4), point(-.5, .45), point(-.1, .05), point(.45, -.4), point(.3, .55)
    plain = point(.55, -.05)
    for name, item in dict(a=a, b=b, c=c, d=d, e=e, h=h, plain=plain).items():
        check(free_spot(item), f'point {name} lies on the model, clear of the workspace panels')
    evidence = {}

    single = yield from new_layer(window, region, data)
    shift_click(window, region, a)
    yield from settle()
    dab = layer_alpha(data, single) > EDGE
    radius = math.sqrt(dab.sum() / math.pi)
    reach = float(distances(dab, texel(cube, data, a), texel(cube, data, a)).max())
    check(dab.sum() > 0, f'with no anchor, Shift-click paints ({int(dab.sum())} texels)')
    check(reach <= radius * 1.05, f'with no anchor, Shift-click paints one round dab: every texel lies within {reach:.1f} of the click for an area radius {radius:.1f}')
    evidence['single_dab'] = dict(texels=int(dab.sum()), radius=round(radius, 2), reach=round(reach, 2))
    radius = reach

    segment = yield from new_layer(window, region, data)
    shift_click(window, region, b)
    yield from settle()
    report = line_report(layer_alpha(data, segment) > EDGE, texel(cube, data, a), texel(cube, data, b), radius)
    check_line(report, radius, 'Shift-click from the anchor')
    evidence['segment'] = report
    check((layer_alpha(data, single) > EDGE).sum() == dab.sum(), 'the segment lands only on the active layer')

    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    undone = int((layer_alpha(data, segment) > EDGE).sum())
    kept = int((layer_alpha(data, single) > EDGE).sum())
    check(undone == 0, f'one Ctrl+Z removes the whole segment ({report["painted"]} texels to {undone})')
    check(kept == int(dab.sum()), f'the earlier dab is untouched by that undo ({kept} texels)')
    evidence['undo'] = dict(before=report['painted'], after=undone, earlier_dab=kept)

    freehand = yield from new_layer(window, region, data)
    move(window, region.x + c[0], region.y + c[1])
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(region.x + c[0]), y=int(region.y + c[1]))
    for _ in range(5):
        yield POLL
    running = [operator.bl_idname for operator in window.modal_operators]
    check('PAINT_OT_image_paint' in running, 'the freehand drag is a native Blender stroke')
    check(running.index('DEVIL_PAINTER_OT_stroke_end') < running.index('PAINT_OT_image_paint'), 'the stroke-end watcher sits in front of the native stroke')
    for step in range(1, DRAG_STEPS + 1):
        x, y = c[0] + (d[0] - c[0]) * step / DRAG_STEPS, c[1] + (d[1] - c[1]) * step / DRAG_STEPS
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(region.x + x), y=int(region.y + y))
        yield POLL
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(region.x + d[0]), y=int(region.y + d[1]))
    yield from settle()
    check('DEVIL_PAINTER_OT_stroke_end' not in [operator.bl_idname for operator in window.modal_operators], 'the watcher ends with the stroke')
    check((layer_alpha(data, freehand) > EDGE).sum() > 0, 'the freehand drag painted')
    after_freehand = yield from new_layer(window, region, data)
    shift_click(window, region, e)
    yield from settle()
    painted = layer_alpha(data, after_freehand) > EDGE
    report = line_report(painted, texel(cube, data, (int(d[0]), int(d[1]))), texel(cube, data, e), radius)
    check_line(report, radius, 'Shift-click after a freehand stroke starts where the stroke ended')
    start_u, start_v = texel(cube, data, c)
    check(not painted[int(start_v), int(start_u)], 'nothing is painted where the freehand stroke began')
    evidence['after_freehand'] = report

    press(window, 'E', *middle)
    yield from settle()
    check(painting.active_tool(bpy.context.scene) == 'ERASE' and editor._active.wants_gesture(bpy.context), 'E switches to Erase, which paints through the replayed gesture path')
    check(editor._active.line_anchor is None, 'switching the tool clears the anchor')
    f = (d[0] + (e[0] - d[0]) * .3, d[1] + (e[1] - d[1]) * .3)
    g = (d[0] + (e[0] - d[0]) * .7, d[1] + (e[1] - d[1]) * .7)
    before = layer_alpha(data, after_freehand)
    shift_click(window, region, f)
    yield from settle()
    first = layer_alpha(data, after_freehand)
    erased = (before > EDGE) & (first <= EDGE)
    reach = float(distances(erased, texel(cube, data, f), texel(cube, data, f)).max())
    check(erased.sum() > 0 and reach <= radius + SLACK, f'after the tool change, Shift-click erases one dab ({int(erased.sum())} texels within {reach:.1f})')
    shift_click(window, region, g)
    yield from settle()
    erased = (first > EDGE) & (layer_alpha(data, after_freehand) <= EDGE)
    report = line_report(erased | (first <= EDGE) & (before > EDGE), texel(cube, data, f), texel(cube, data, g), reach)
    check_line(report, reach, 'Erase Shift-click')
    evidence['erase'] = report
    press(window, 'B', *middle)
    yield from settle()
    check(painting.active_tool(bpy.context.scene) == 'PAINT', 'B switches back to Paint')

    plain_layer = yield from new_layer(window, region, data)
    press(window, 'LEFTMOUSE', region.x + plain[0], region.y + plain[1])
    yield from settle()
    clicked = int((layer_alpha(data, plain_layer) > EDGE).sum())
    check(abs(dab.sum() / clicked - 1) < .1, f'the no-anchor Shift-click dab ({int(dab.sum())} texels) matches a plain click ({clicked} texels)')
    evidence['plain_click'] = clicked

    masked = yield from new_layer(window, region, data)
    yield from reveal(window, region, 'ROW_' + masked, 'LAYERS')
    click(window, region, 'ROW_' + masked, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'ADD_MASK_BLACK')
    yield from settle()
    check(data.target == 'MASK' and not painting.uses_stroke_buffer(bpy.context, data), 'the black mask is the canvas, painted without the stroke buffer')
    painting.set_brush_value(bpy.context.scene, 'color', (1.0, 1.0, 1.0))
    shift_click(window, region, h)
    yield from settle()
    report = line_report(channel(find_layer(data, masked).mask, 0) > EDGE, texel(cube, data, plain), texel(cube, data, h), radius)
    check_line(report, radius, 'Shift-click on a mask, anchored at the last Paint click')
    evidence['mask'] = report
    print('SHIFT LINE EVIDENCE', json.dumps(evidence))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types, 'DEVIL_PAINTER_OT_stroke_end'), 'the stroke-end watcher unregisters cleanly')
    print('ALL GUI SHIFT LINE CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI shift line test')
