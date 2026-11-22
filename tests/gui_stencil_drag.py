import json
import math
import sys
from pathlib import Path
import bmesh
import bpy
import numpy
from mathutils import Quaternion

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, painting
from devil_painter.document import active_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import POLL, check, control, finish, keys, run_journey, settle, spot, type_text, until, viewport

DISTANCE = 2.4
STEPS = 10
EDGE = .5
SLACK = 3.0
BRUSH_RADIUS = 1000
MOVE = (-120, 70)
SCALE_FROM, SCALE_TO = 60, 90
TURN = 40


def move(window, x, y, **modifiers):
    window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(round(x)), y=int(round(y)), **modifiers)


def press(window, kind, x, y, **modifiers):
    move(window, x, y)
    window.event_simulate(type=kind, value='PRESS', x=int(round(x)), y=int(round(y)), **modifiers)
    window.event_simulate(type=kind, value='RELEASE', x=int(round(x)), y=int(round(y)), **modifiers)


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5):
    press(window, kind, *spot(region, key, fx, fy))


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


def write_decal(folder):
    folder.mkdir(exist_ok=True)
    decal = bpy.data.images.new('decal', 32, 32, alpha=True)
    decal.pixels.foreach_set(numpy.tile(numpy.array((1.0, 0.0, 0.0, 1.0), dtype=numpy.float32), 32 * 32))
    decal.filepath_raw = str(folder / 'decal.png')
    decal.file_format = 'PNG'
    decal.save()
    bpy.data.images.remove(decal)


def brush():
    return bpy.context.tool_settings.image_paint.brush


def stencil_state(data):
    return dict(x=data.stencil_x, y=data.stencil_y, scale=data.stencil_scale, angle=data.stencil_angle,
                pos=tuple(brush().stencil_pos), dimension=tuple(brush().stencil_dimension), rotation=math.degrees(brush().texture_slot.angle) % 360)


def free_spot(point):
    return not editor._active.workspace.covers(*point) and editor._active.workspace.hit(*point) is None


def native_drag(window, region, path, **modifiers):
    first = path[0]
    move(window, region.x + first[0], region.y + first[1], **modifiers)
    window.event_simulate(type='RIGHTMOUSE', value='PRESS', x=int(round(region.x + first[0])), y=int(round(region.y + first[1])), **modifiers)
    yield POLL
    running = [operator.bl_idname for operator in window.modal_operators]
    middle = None
    for index, point in enumerate(path[1:], 1):
        move(window, region.x + point[0], region.y + point[1], **modifiers)
        yield POLL
        if index == len(path) // 2:
            middle = (tuple(brush().stencil_pos), math.degrees(brush().texture_slot.angle) % 360, tuple(brush().stencil_dimension))
    last = path[-1]
    window.event_simulate(type='RIGHTMOUSE', value='RELEASE', x=int(round(region.x + last[0])), y=int(round(region.y + last[1])), **modifiers)
    yield from settle()
    yield from until(lambda: not editor._active.stencil_pending, 'the editor to read the finished gesture back')
    return running, middle


def line(start, end):
    return [(start[0] + (end[0] - start[0]) * step / STEPS, start[1] + (end[1] - start[1]) * step / STEPS) for step in range(STEPS + 1)]


def layer_alpha(data):
    image = active_layer(data).image
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)[..., 3]


def texel_to_screen(obj, data, points):
    texels = numpy.array([editor._active.texture_point(obj, data, point)[1:] for point in points])
    solve = numpy.linalg.solve(numpy.column_stack([texels, numpy.ones(3)]), numpy.array(points))
    return solve, abs(numpy.linalg.det(solve[:2]))


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    textures = scratch / 'stencil_textures'
    write_decal(textures)
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
    check(data.brush_stencil is not None and brush().texture_slot.map_mode == 'STENCIL', 'Use as stencil puts the decal on screen as a brush stencil')
    click(window, region, 'STENCIL_CARD')
    yield from settle()
    click(window, region, 'STENCIL_SCALE', fx=.05)
    yield from settle()
    check(abs(data.stencil_scale - .2) < .01, f'the scale slider sets a small stencil ({data.stencil_scale:.3f})')
    width, height = region.width, region.height
    evidence = dict(region=(width, height))

    before = stencil_state(data)
    center = before['pos']
    path = line(center, (center[0] + MOVE[0], center[1] + MOVE[1]))
    check(all(free_spot(point) for point in path), 'the move gesture runs over the bare viewport')
    check(editor._active.state.popover is not None, 'the stencil card is open when the move gesture starts')
    running, live = yield from native_drag(window, region, path)
    after = stencil_state(data)
    check(running[0] == 'BRUSH_OT_stencil_control', "a right-drag over the viewport starts Blender's own stencil move")
    check(math.dist(live[0], (center[0] + MOVE[0] / 2, center[1] + MOVE[1] / 2)) < 1.5, f'the stencil follows the drag live (halfway at {live[0][0]:.1f}, {live[0][1]:.1f})')
    moved = (after['x'] - before['x'], after['y'] - before['y'])
    expected = (MOVE[0] / width, MOVE[1] / height)
    check(max(abs(moved[0] - expected[0]), abs(moved[1] - expected[1])) < 1e-3,
          f'the stored position moved ({moved[0]:.4f}, {moved[1]:.4f}) for a pointer move of ({expected[0]:.4f}, {expected[1]:.4f}) of the view')
    start_texel = editor._active.texture_point(cube, data, path[0])[1:]
    end_texel = editor._active.texture_point(cube, data, path[-1])[1:]
    centre_before = editor._active.texture_point(cube, data, center)[1:]
    centre_after = editor._active.texture_point(cube, data, (after['x'] * width, after['y'] * height))[1:]
    pointer_texels = (end_texel[0] - start_texel[0], end_texel[1] - start_texel[1])
    stencil_texels = (centre_after[0] - centre_before[0], centre_after[1] - centre_before[1])
    check(math.dist(pointer_texels, stencil_texels) < 1.0,
          f'in texture space the stencil centre moved ({stencil_texels[0]:.1f}, {stencil_texels[1]:.1f}) texels for a pointer move of ({pointer_texels[0]:.1f}, {pointer_texels[1]:.1f})')
    check(math.dist(after['pos'], (after['x'] * width, after['y'] * height)) < .5, 'the brush stencil sits where the stored values say')
    check(editor._active.state.popover is None, 'the right-drag closes the stencil card')
    evidence['move'] = dict(pointer_px=MOVE, stored_delta=moved, expected_delta=expected, pointer_texels=pointer_texels, stencil_texels=stencil_texels)

    click(window, region, 'STENCIL_CARD')
    yield from settle()
    shown = {key: control(key).value * top for key, top in (('STENCIL_X', 1.0), ('STENCIL_Y', 1.0))}
    check(abs(shown['STENCIL_X'] - after['x']) < 1e-6 and abs(shown['STENCIL_Y'] - after['y']) < 1e-6,
          f"the card's position sliders show the dragged values ({control('STENCIL_X').text}, {control('STENCIL_Y').text})")
    press(window, 'ESC', *middle)
    yield from settle()

    before = stencil_state(data)
    center = before['pos']
    path = line((center[0] + SCALE_FROM, center[1]), (center[0] + SCALE_TO, center[1]))
    check(all(free_spot(point) for point in path), 'the scale gesture runs over the bare viewport')
    running, live = yield from native_drag(window, region, path, shift=True)
    after = stencil_state(data)
    factor = after['scale'] / before['scale']
    check(running[0] == 'BRUSH_OT_stencil_control', "Shift+right-drag starts Blender's own stencil scale")
    check(abs(factor - SCALE_TO / SCALE_FROM) < .02, f'the stored scale grew {factor:.3f}x for a pointer pulled from {SCALE_FROM} to {SCALE_TO} px off the centre ({SCALE_TO / SCALE_FROM:.3f}x)')
    check(math.dist(after['pos'], before['pos']) < .5, 'scaling keeps the stencil centre')
    check(abs(after['dimension'][1] - after['scale'] * min(width, height) / 2) < .5, 'the brush stencil size matches the stored scale')
    evidence['scale'] = dict(before=before['scale'], after=after['scale'], factor=factor, expected=SCALE_TO / SCALE_FROM)

    before = stencil_state(data)
    center = before['pos']
    arc = [(center[0] + SCALE_FROM * math.cos(math.radians(TURN * step / STEPS)), center[1] + SCALE_FROM * math.sin(math.radians(TURN * step / STEPS)))
           for step in range(STEPS + 1)]
    check(all(free_spot(point) for point in arc), 'the rotate gesture runs over the bare viewport')
    running, live = yield from native_drag(window, region, arc, ctrl=True)
    after = stencil_state(data)
    turned = (after['angle'] - before['angle'] + 180) % 360 - 180
    check(running[0] == 'BRUSH_OT_stencil_control', "Ctrl+right-drag starts Blender's own stencil rotation")
    check(abs(abs(turned) - TURN) < .5, f'the stored rotation turned {turned:.2f} degrees for a {TURN} degree arc of the pointer around the centre')
    check(abs((after['rotation'] - after['angle'] + 180) % 360 - 180) < .01, 'the brush stencil rotation matches the stored angle')
    evidence['rotate'] = dict(before=before['angle'], after=after['angle'], turned=turned, arc=TURN)

    click(window, region, 'STENCIL_CARD')
    yield from settle()
    shown = dict(scale=control('STENCIL_SCALE').value * 4.0, angle=control('STENCIL_ANGLE').value * 360.0)
    check(abs(shown['scale'] - data.stencil_scale) < 1e-6 and abs(shown['angle'] - data.stencil_angle) < 1e-4,
          f"the card's scale and rotation sliders show the dragged values ({control('STENCIL_SCALE').text}, {control('STENCIL_ANGLE').text})")
    press(window, 'ESC', *middle)
    yield from settle()

    painting.set_brush_value(bpy.context.scene, 'size', BRUSH_RADIUS)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    frame = stencil_state(data)
    center = frame['pos']
    check(free_spot(center), 'the stencil centre is on the bare viewport')
    press(window, 'LEFTMOUSE', region.x + center[0], region.y + center[1])
    yield from settle()
    painted = layer_alpha(data) > EDGE
    rows, columns = numpy.nonzero(painted)
    probes = [(center[0] - 40, center[1] - 30), (center[0] + 50, center[1] - 20), (center[0] - 10, center[1] + 45)]
    mapping, texel_area = texel_to_screen(cube, data, probes)
    screen = numpy.column_stack([columns + .5, rows + .5, numpy.ones(len(rows))]) @ mapping
    angle = math.radians(frame['rotation'])
    offset = screen - numpy.array(center)
    local = numpy.column_stack([offset[:, 0] * math.cos(angle) + offset[:, 1] * math.sin(angle), -offset[:, 0] * math.sin(angle) + offset[:, 1] * math.cos(angle)])
    half = numpy.array(frame['dimension'])
    beyond = numpy.clip(numpy.abs(local) - half, 0.0, None).max(axis=1)
    covered = len(rows) * texel_area / (4 * half[0] * half[1])
    check(len(rows) > 0, f'the dab through the moved stencil painted {len(rows)} texels')
    check(int((beyond > SLACK).sum()) == 0, f'every painted texel lies inside the stencil frame shown on screen (worst {beyond.max():.2f} px outside)')
    check(covered > .9, f'the dab fills the stencil frame ({covered:.3f} of its area)')
    evidence['dab'] = dict(texels=len(rows), worst_outside_px=float(beyond.max()), frame_coverage=covered, frame_half_px=tuple(half), rotation=frame['rotation'])

    click(window, region, 'STENCIL_CARD')
    yield from settle()
    click(window, region, 'STENCIL_X', fx=.3)
    yield from settle()
    after = stencil_state(data)
    check(abs(data.stencil_x - .3) < .01 and abs(after['pos'][0] - data.stencil_x * width) < .5,
          f'moving the slider afterwards puts the stencil where the slider says (x {data.stencil_x:.3f}, {after["pos"][0]:.1f} px)')
    check(abs(after['pos'][1] - frame['y'] * height) < .5 and abs(after['angle'] - frame['angle']) < 1e-4 and abs(after['scale'] - frame['scale']) < 1e-6,
          'the slider change keeps the dragged height, scale and rotation')
    evidence['slider'] = dict(x=data.stencil_x, pos=after['pos'][0], expected=data.stencil_x * width)
    press(window, 'ESC', *middle)
    yield from settle()
    print('STENCIL DRAG EVIDENCE', json.dumps(evidence))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    print('ALL GUI STENCIL DRAG CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI stencil drag test')
