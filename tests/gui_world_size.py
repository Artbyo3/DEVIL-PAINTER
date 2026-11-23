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
from devil_painter import brushes, editor, library, painting
from devil_painter.document import find_layer
from devil_painter.minimal import MAX_WORLD_SIZE
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, close_cards, control, drag_slider, finish, has, move, new_layer, press, run_journey, settle, shelf_index, spot, type_text, until, viewport

WORLD_SIZE = .2
NEAR, FAR = 3.0, 9.0
MATCH = .03
EDGE = .5
LOW = .5
JITTER_AMOUNT = .5
RADIAL_REACH = 60


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


def aim(area, perspective, distance):
    view = area.spaces.active.region_3d
    view.view_perspective = perspective
    view.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    view.view_location = (0.0, 0.0, 0.0)
    view.view_distance = distance


def screen_point(area, region, x, y):
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, (x, y, 0.0))
    return float(point.x), float(point.y)


def pixels_per_unit(area, region):
    left, right = screen_point(area, region, 0.0, 0.0), screen_point(area, region, 1.0, 0.0)
    return right[0] - left[0]


def layer_alpha(data, uid):
    image = find_layer(data, uid).image
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(image.size[1], image.size[0], 4)[..., 3].copy()


def texels_per_unit(obj, data):
    return data.resolution / obj.dimensions.x


def footprint(obj, data, alpha):
    return 2 * math.sqrt(float((alpha > EDGE).sum()) / math.pi) / texels_per_unit(obj, data)


def dab(window, area, region, obj, data, pressure=1.0):
    uid = yield from new_layer(window, region, data)
    with bpy.context.temp_override(window=window, area=area, region=region):
        editor._active.run_gesture(bpy.context, [(screen_point(area, region, 0.0, 0.0), pressure)])
    yield from settle()
    return footprint(obj, data, layer_alpha(data, uid))


def hover(window, area, region):
    x, y = screen_point(area, region, 0.0, 0.0)
    for step in range(3):
        move(window, region.x + x + step, region.y + y)
        yield from settle()


def native_size():
    return painting.brush_value(bpy.context.scene, 'size')


def measure(window, area, region, obj, data, perspective, distance):
    aim(area, perspective, distance)
    yield from settle()
    yield from hover(window, area, region)
    size = native_size()
    painted = yield from dab(window, area, region, obj, data)
    return dict(view=perspective, distance=distance, pixels_per_unit=round(pixels_per_unit(area, region), 3), cursor_px=size, footprint=round(painted, 5))


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
    aim(area, 'ORTHO', NEAR)
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
    evidence = {}

    check(data.brush_size_space == 'SCREEN', 'a new texture set sizes the brush in screen pixels')
    check(not editor._active.wants_gesture(bpy.context), 'in Screen mode a Paint stroke stays a native Blender stroke')
    yield from card_click(window, region, 'SIZE_SPACE.SCREEN')
    check(control('SIZE_SPACE.SCREEN').label == 'Screen size' and control('SIZE_SPACE.WORLD').label == 'World size', 'the Brush card offers Screen size and World size')
    check(control('SIZE_SPACE.SCREEN').active and not control('SIZE_SPACE.WORLD').active, 'Screen size is the active choice')
    yield from close_cards(window, middle)

    drag_slider(window, region, 'BRUSH_SIZE', .1)
    yield from settle()
    screen_px = native_size()
    screen = []
    for distance in (NEAR, FAR):
        aim(area, 'PERSP', distance)
        yield from settle()
        painted = yield from dab(window, area, region, cube, data)
        screen.append(dict(distance=distance, footprint=round(painted, 5)))
    check(native_size() == screen_px, f'Screen mode keeps the brush at {screen_px} px whatever the zoom')
    check(screen[1]['footprint'] / screen[0]['footprint'] > 2.0, f'in Screen mode the same brush covers more of the model from further away ({screen})')
    evidence['screen'] = dict(size_px=screen_px, footprints=screen)

    yield from card_click(window, region, 'SIZE_SPACE.WORLD')
    check(data.brush_size_space == 'WORLD' and control('SIZE_SPACE.WORLD').active, 'a click switches the brush to World size')
    check(editor._active.wants_gesture(bpy.context), 'World size routes Paint through the per-dab replay')
    yield from close_cards(window, middle)
    drag_slider(window, region, 'BRUSH_SIZE', WORLD_SIZE / MAX_WORLD_SIZE)
    yield from settle()
    check(abs(data.brush_world_size - WORLD_SIZE) < .005, f'the tool strip Size slider sets the world size ({data.brush_world_size:.4f})')
    check(control('BRUSH_SIZE').text == brushes.world_size_text(data.brush_world_size) and 'px' not in control('BRUSH_SIZE').text,
          f'the Size slider reads in scene units ({control("BRUSH_SIZE").text})')
    world = data.brush_world_size

    near = yield from measure(window, area, region, cube, data, 'PERSP', NEAR)
    far = yield from measure(window, area, region, cube, data, 'PERSP', FAR)
    ortho = yield from measure(window, area, region, cube, data, 'ORTHO', NEAR)
    ortho_far = yield from measure(window, area, region, cube, data, 'ORTHO', FAR)
    footprints = [item['footprint'] for item in (near, far, ortho, ortho_far)]
    spread = (max(footprints) - min(footprints)) / near['footprint']
    check(abs(far['footprint'] / near['footprint'] - 1) < MATCH, f'perspective: the footprint is {near["footprint"]:.4f} near and {far["footprint"]:.4f} far')
    check(abs(ortho['footprint'] / near['footprint'] - 1) < MATCH and abs(ortho_far['footprint'] / near['footprint'] - 1) < MATCH,
          f'orthographic: the footprint is {ortho["footprint"]:.4f} and {ortho_far["footprint"]:.4f} zoomed out')
    check(abs(near['footprint'] / world - 1) < .1, f'the footprint {near["footprint"]:.4f} matches the world size {world:.4f}')
    check(near['cursor_px'] / far['cursor_px'] > 2.0, f'the brush cursor shrinks from {near["cursor_px"]} px to {far["cursor_px"]} px as the view moves away')
    for item in (near, far, ortho, ortho_far):
        expected = world * item['pixels_per_unit']
        check(abs(item['cursor_px'] / expected - 1) < .05, f'{item["view"]} at {item["distance"]}: the cursor is {item["cursor_px"]} px for {expected:.1f} px of world size')
    evidence['world'] = dict(world_size=round(world, 5), measurements=[near, far, ortho, ortho_far], spread=round(spread, 5))

    aim(area, 'PERSP', FAR)
    yield from settle()
    yield from hover(window, area, region)
    still_px = native_size()
    x, y = screen_point(area, region, 0.0, 0.0)
    for _ in range(3):
        window.event_simulate(type='WHEELUPMOUSE', value='PRESS', x=int(region.x + x + 2), y=int(region.y + y))
        yield from settle()
    yield from until(lambda: native_size() != still_px, 'the brush cursor to follow the wheel zoom')
    zoomed = world * pixels_per_unit(area, region)
    check(abs(native_size() / zoomed - 1) < .05, f'a wheel zoom with the pointer still resizes the cursor from {still_px} px to {native_size()} px for {zoomed:.1f} px of world size')
    view = area.spaces.active.region_3d
    stroke = brushes.stroke_size(data, region, view, cube, [(screen_point(area, region, 0.0, 0.0), 1.0)], 7)
    check(abs(stroke / zoomed - 1) < .05, f'dynamics and the merge pass size a World stroke from its footprint ({stroke:.1f} px), not the native 7 px')
    evidence['wheel_zoom'] = dict(before_px=still_px, after_px=native_size(), expected_px=round(zoomed, 2), stroke_px=round(stroke, 2))

    aim(area, 'PERSP', NEAR)
    yield from settle()
    yield from card_click(window, region, 'BRUSH_PRESSURE_SIZE')
    yield from card_click(window, region, 'BRUSH_PRESSURE_OPACITY')
    check(data.brush_pressure_size and not data.brush_pressure_opacity, 'Pressure size is on with World size, Pressure opacity is off to measure the edge')
    yield from close_cards(window, middle)
    full = yield from dab(window, area, region, cube, data, 1.0)
    low = yield from dab(window, area, region, cube, data, LOW)
    aim(area, 'PERSP', FAR)
    yield from settle()
    low_far = yield from dab(window, area, region, cube, data, LOW)
    response = brushes.pressure_response(bpy.context.tool_settings.image_paint.brush.curve_size, LOW, True)
    check(abs(low / full - response) < .05, f'pressure {LOW} scales the world dab to {low / full:.4f} of full size (curve {response:.4f})')
    check(abs(low_far / low - 1) < MATCH, f'the pressure-scaled dab keeps its size on the model from further away ({low:.4f} near, {low_far:.4f} far)')
    evidence['pressure'] = dict(pressure=LOW, response=round(response, 4), full=round(full, 5), low=round(low, 5), low_far=round(low_far, 5))
    yield from card_click(window, region, 'BRUSH_PRESSURE_SIZE')
    yield from card_click(window, region, 'BRUSH_PRESSURE_OPACITY')
    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=JITTER_AMOUNT)
    check(data.brush_jitter_size > 0 and not data.brush_pressure_size, 'Size jitter is on and Pressure size is off')
    yield from close_cards(window, middle)
    jittered = yield from dab(window, area, region, cube, data)
    aim(area, 'PERSP', NEAR)
    yield from settle()
    jittered_near = yield from dab(window, area, region, cube, data)
    point = [(screen_point(area, region, 0.0, 0.0), 1.0)]
    scale = brushes.dab_jitter(data, 1, brushes.jitter_seed(point))[0][0]
    check(abs(jittered_near / full - scale) < .05, f'Size jitter scales the world dab to {jittered_near / full:.4f} (drawn {scale:.4f})')
    check(abs(jittered / jittered_near - 1) < MATCH, f'the jittered dab keeps its size on the model from further away ({jittered_near:.4f} near, {jittered:.4f} far)')
    evidence['jitter'] = dict(amount=round(data.brush_jitter_size, 4), scale_near=round(scale, 4), near=round(jittered_near, 5), far=round(jittered, 5))
    yield from card_click(window, region, 'BRUSH_JITTER_SIZE', fx=0.0)
    yield from close_cards(window, middle)

    yield from hover(window, area, region)
    before_world, before_px = data.brush_world_size, native_size()
    x, y = screen_point(area, region, 0.0, 0.0)
    move(window, region.x + x, region.y + y)
    window.event_simulate(type='F', value='PRESS', x=int(region.x + x), y=int(region.y + y))
    window.event_simulate(type='F', value='RELEASE', x=int(region.x + x), y=int(region.y + y))
    for step in range(1, 6):
        move(window, region.x + x + before_px / 2 + RADIAL_REACH * step / 5, region.y + y)
    press(window, 'LEFTMOUSE', region.x + x + before_px / 2 + RADIAL_REACH, region.y + y)
    yield from settle()
    radial_px = native_size()
    check(radial_px > before_px, f'F opens the radial size control and it grows the brush from {before_px} px to {radial_px} px')
    yield from hover(window, area, region)
    check(data.brush_size_space == 'WORLD' and abs(data.brush_world_size / before_world - radial_px / before_px) < .03,
          f'in World mode the radial sets the world size: {before_world:.4f} to {data.brush_world_size:.4f} for {before_px} to {radial_px} px')
    evidence['radial'] = dict(before=dict(world=round(before_world, 5), px=before_px), after=dict(world=round(data.brush_world_size, 5), px=radial_px))
    radial_world = data.brush_world_size
    press(window, 'RIGHT_BRACKET', *middle)
    yield from settle()
    check(abs(data.brush_world_size / radial_world - 1.15) < .01, f'] grows the world size by one step ({data.brush_world_size:.4f})')
    press(window, 'LEFT_BRACKET', *middle)
    yield from settle()
    check(abs(data.brush_world_size - radial_world) < 1e-4, '[ brings it back')

    export_dir = scratch / 'export_world_size'
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    check(bool(sorted(export_dir.glob('*.png'))), 'the world-size dabs export')

    yield from card_click(window, region, 'SAVE_BRUSH')
    saved = json.loads(settings_path.read_text(encoding='utf-8'))['brush_presets'][-1]
    check(saved['size_space'] == 'WORLD' and abs(saved['world_size'] - data.brush_world_size) < 1e-6,
          f'Save as preset writes World size {saved["world_size"]:.4f} to disk ({saved["name"]})')
    yield from close_cards(window, middle)
    saved_world = data.brush_world_size
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Square")}')
    yield from settle()
    check(data.brush_size_space == 'SCREEN', 'a built-in preset loads Screen size')
    library._cache.clear()
    click(window, region, 'SHELF_TAB.BRUSHES')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index(saved["name"])}')
    yield from settle()
    check(data.brush_size_space == 'WORLD' and abs(data.brush_world_size - saved_world) < 1e-6, 'the preset reloaded from disk brings World size and its size back')

    saved_file = scratch / 'world_size.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    check(data.brush_size_space == 'WORLD' and abs(data.brush_world_size - saved_world) < 1e-6, 'the reopened file keeps World size and its size')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    reopened = yield from measure(window, area, region, cube, data, 'PERSP', FAR)
    check(abs(reopened['footprint'] / saved_world - 1) < .1, f'after reopening, a dab covers {reopened["footprint"]:.4f} of the model for {saved_world:.4f}')
    evidence['reopened'] = reopened
    yield from card_click(window, region, 'SIZE_SPACE.SCREEN')
    check(data.brush_size_space == 'SCREEN' and not editor._active.wants_gesture(bpy.context), 'Screen size returns Paint to native Blender strokes')
    check(control('BRUSH_SIZE').text.endswith(' px'), 'the Size slider reads in pixels again')
    yield from close_cards(window, middle)
    print('WORLD SIZE EVIDENCE', json.dumps(evidence))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI WORLD SIZE CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI world size test')
