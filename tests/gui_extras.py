import sys
from pathlib import Path
import bpy
import numpy
from bpy_extras import view3d_utils
from mathutils import Vector

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import autosave, bridge, editor, library
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, check, click, control, drag_slider, finish, has, keys, move, nodes, pixels, press, reveal, run_journey, set_hex, settle, spot, type_text, until, viewport


def spot_of(region, key, fx=.5, fy=.5):
    return spot(region, key, fx, fy)


def face_center_pixel(obj, face, resolution):
    mesh = obj.data
    layer = mesh.uv_layers.active
    uv = numpy.array([tuple(layer.data[loop].uv) for loop in mesh.polygons[face].loop_indices]).mean(axis=0) % 1.0
    return int(uv[1] * resolution), int(uv[0] * resolution)


def face_of(obj, normal):
    return max(obj.data.polygons, key=lambda polygon: polygon.normal.dot(Vector(normal))).index


def face_point(region, area, obj, face, share=0.0, corner=0):
    polygon = obj.data.polygons[face]
    target = obj.matrix_world @ (polygon.center * (1 - share) + obj.data.vertices[polygon.vertices[corner]].co * share)
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, target)
    return region.x + point.x, region.y + point.y


def image_pixels(image):
    values = pixels(image)
    return values.reshape(image.size[1], image.size[0], 4)


def drag(window, x, y, dx, dy, count=8):
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, count + 1):
        move(window, x + dx * step / count, y + dy * step / count)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def card(window, region, opener, key, kind):
    move(window, region.x + 4, region.y + 4)
    yield from settle()
    if not (editor._active.state.popover is not None and editor._active.state.popover.kind == kind):
        click(window, region, opener)
        yield from settle()
    check(has(key), f'{opener} shows {key}')


def card_click(window, region, opener, key, kind, fx=.5):
    yield from card(window, region, opener, key, kind)
    if control(key).kind == 'SLIDER':
        drag_slider(window, region, key, fx)
    else:
        click(window, region, key, fx=fx)
    yield from settle()


def close(window, middle):
    if editor._active.state.popover is not None:
        press(window, 'ESC', *middle)
    yield from settle()


def covered(layer):
    return int((image_pixels(layer.image)[..., 3] > .5).sum())


def write_svg(path):
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g transform="translate(10,10)">'
                    '<path d="M 0 0 L 80 0 L 80 80 L 0 80 Z M 20 20 L 20 60 L 60 60 L 60 20 Z"/></g></svg>', encoding='utf-8')


def journey():
    scratch = prepare_scratch()
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'extras_export'
    vectors_dir = scratch / 'vectors'
    vectors_dir.mkdir(exist_ok=True)
    write_svg(vectors_dir / 'frame.svg')
    received = scratch / 'received.txt'
    received.unlink(missing_ok=True)
    listener = scratch / 'listener.py'
    listener.write_text(f'import sys\nopen(r"{received}", "w").write("\\n".join(sys.argv[1:]))\n', encoding='utf-8')
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    cube.data.shade_smooth()
    blend = scratch / 'extras.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
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
    resolution = data.resolution
    right, front, top = (face_of(cube, normal) for normal in ((1, 0, 0), (0, -1, 0), (0, 0, 1)))
    spot = {face: face_center_pixel(cube, face, resolution) for face in (right, front, top)}
    drag_slider(window, region, 'BRUSH_SIZE', .05)
    yield from settle()

    yield from card_click(window, region, 'PROJECT', 'TRANSP.DITHERED', 'PROJECT')
    check(data.transparency == 'DITHERED' and data.material.surface_render_method == 'DITHERED', 'order-independent transparency sets the dithered render method')
    yield from card_click(window, region, 'PROJECT', 'TRANSP.BLENDED', 'PROJECT')
    yield from card_click(window, region, 'PROJECT', 'TRANSP_OVERLAP', 'PROJECT')
    check(data.material.surface_render_method == 'BLENDED' and not data.material.use_transparency_overlap, 'blended transparency and its overlap toggle reach the material')
    yield from card_click(window, region, 'PROJECT', 'TRANSP.AUTO', 'PROJECT')
    yield from card_click(window, region, 'PROJECT', 'AUTOSAVE', 'PROJECT')
    yield from card_click(window, region, 'PROJECT', 'AUTOSAVE_MINUTES', 'PROJECT', fx=0.0)
    check(autosave.minutes() == 1 and 'within 1 min' in control('AUTOSAVE_INFO').label, 'autosave turns on every minute')
    yield from close(window, middle)

    click(window, region, 'ADD_PAINT')
    yield from settle()
    ribbon_uid = active_layer(data).uid
    click(window, region, 'PATH')
    yield from settle()
    check(editor._active.state.path_mode == 'RIBBON' and has('PATH.FILLED') and has('PATH_APPLY'), 'the path tool offers ribbon and filled paths')
    for share, corner in ((.6, 0), (.2, 1), (.2, 2), (.6, 3)):
        press(window, 'LEFTMOUSE', *face_point(region, area, cube, front, share, corner))
        yield from settle()
    check(len(editor._active.state.path_points) == 4 and len(control('PATH_POINT.0').points) == 6, 'clicked path points draw on the model')
    px, py = spot_of(region, 'PATH_POINT.1')
    drag(window, px, py, 0, -6, 3)
    yield from settle()
    check(abs(editor._active.state.path_points[1][1] - (py - region.y - 6)) < 2, 'dragging a path point moves it')
    press(window, 'RET', *middle)
    yield from settle()
    ribbon = covered(find_layer(data, ribbon_uid))
    check(ribbon > 200 and not editor._active.state.path_points, 'Enter strokes the brush along the ribbon path')
    click(window, region, 'PATH.FILLED')
    yield from settle()
    click(window, region, 'ADD_PAINT')
    yield from settle()
    filled_uid = active_layer(data).uid
    for corner in (0, 1, 2, 3):
        press(window, 'LEFTMOUSE', *face_point(region, area, cube, top, .7, corner))
        yield from settle()
    click(window, region, 'PATH_APPLY')
    yield from settle()
    filled = find_layer(data, filled_uid)
    check(image_pixels(filled.image)[spot[top]][3] > .5 and covered(filled) > 1000, 'a filled path paints the whole shape it encloses, centered where it was drawn')
    click(window, region, 'PATH')
    yield from settle()

    click(window, region, 'ADD_PAINT')
    yield from settle()
    plain_uid = active_layer(data).uid
    x, y = face_point(region, area, cube, right, .3, 0)
    drag(window, x, y, 0, 8, 4)
    yield from settle()
    plain = covered(find_layer(data, plain_uid))
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_DYNAMICS', 'BRUSH')
    check(all(has('SET_DYNAMICS.' + kind) for kind in ('NONE', 'DRIPS', 'SPLATTER', 'SPEED')), 'dynamics offer drips, splatter, and speed')
    click(window, region, 'SET_DYNAMICS.DRIPS')
    yield from settle()
    yield from close(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    drips_uid = active_layer(data).uid
    drag(window, x, y, 0, 8, 4)
    yield from settle()
    drips = find_layer(data, drips_uid)
    check(covered(drips) > plain * 1.3, f'drips run from the stroke down the surface ({covered(drips)} vs {plain})')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_DYNAMICS', 'BRUSH')
    click(window, region, 'SET_DYNAMICS.SPLATTER')
    yield from settle()
    yield from close(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    splat_uid = active_layer(data).uid
    drag(window, x, y, 0, 8, 4)
    yield from settle()
    splat_alpha = image_pixels(find_layer(data, splat_uid).image)[..., 3]
    stroke_alpha = image_pixels(find_layer(data, plain_uid).image)[..., 3]
    scattered, stroke_area = int(((splat_alpha > 0) & (stroke_alpha == 0)).sum()), int((stroke_alpha > 0).sum())
    check(scattered > stroke_area * 1.3, f'splatter scatters dabs around the stroke ({scattered} texels outside a plain stroke that covers {stroke_area})')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_DYNAMICS', 'BRUSH')
    click(window, region, 'SET_DYNAMICS.NONE')
    yield from settle()
    yield from close(window, middle)
    fx, fy = face_point(region, area, cube, front, .6, 0)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    fast_uid = active_layer(data).uid
    drag(window, fx, fy, 70, 0, 2)
    yield from settle()
    fast = covered(find_layer(data, fast_uid))
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_DYNAMICS', 'BRUSH')
    click(window, region, 'SET_DYNAMICS.SPEED')
    yield from settle()
    yield from close(window, middle)
    click(window, region, 'ADD_PAINT')
    yield from settle()
    speed_uid = active_layer(data).uid
    drag(window, fx, fy, 70, 0, 2)
    yield from settle()
    check(0 < covered(find_layer(data, speed_uid)) < fast * .9, f'speed dynamics thin out a fast stroke ({covered(find_layer(data, speed_uid))} vs {fast})')
    yield from card_click(window, region, 'BRUSH_CARD', 'BRUSH_DYNAMICS', 'BRUSH')
    click(window, region, 'SET_DYNAMICS.NONE')
    yield from settle()
    yield from close(window, middle)

    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_TEXT', 'STENCIL')
    type_text(window, 'DP', *spot_of(region, 'STENCIL_TEXT'))
    yield from settle()
    stencil = data.brush_stencil
    alpha = image_pixels(stencil)[..., 3] if stencil is not None else numpy.zeros(1)
    check(stencil is not None and stencil.name == 'DP Text Stencil' and alpha.min() == 0 and alpha.max() == 1 and .05 < alpha.mean() < .8,
          'typed text becomes a stencil drawn with Blender\'s font')
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_FONT', 'STENCIL')
    yield from until(lambda: has('SET_FONT.'), 'the font menu to list its fonts')
    fonts = [key for key in keys('SET_FONT.') if key != 'SET_FONT.']
    check(has('SET_FONT.') and len(fonts) > 0, f'the font menu lists the Blender font and the system fonts {editor._active.state.popover} {editor._active.state.text} {editor._active.message} {len(editor._active.fonts)}')
    click(window, region, fonts[0])
    yield from settle()
    check(data.stencil_font.lower().endswith(('.ttf', '.otf')), 'a system font can be picked for text stencils')
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_TEXT', 'STENCIL')
    type_text(window, 'Ab', *spot_of(region, 'STENCIL_TEXT'))
    yield from settle()
    check(image_pixels(data.brush_stencil)[..., 3].max() == 1, 'the system font draws the text stencil')
    yield from close(window, middle)
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'LIBRARIES')
    yield from settle()
    click(window, region, 'LIBRARY_NEW')
    yield from settle()
    type_text(window, str(vectors_dir), *spot_of(region, 'LIBRARY_NEW'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    check('frame' in labels and control(labels['frame']).preview is not None or 'frame' in labels, 'the SVG file appears in the textures shelf')
    click(window, region, labels['frame'])
    yield from settle()
    shape = image_pixels(data.brush_stencil)[..., 3]
    middle_row, middle_column = shape.shape[0] // 2, shape.shape[1] // 2
    check(data.brush_stencil.name == 'DP frame Stencil' and shape[middle_row, middle_column] == 0 and shape[middle_row, 5] == 1,
          'clicking the SVG makes a stencil with its hole cut out')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    stamp_uid = active_layer(data).uid
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_SCALE', 'STENCIL', fx=.03)
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_PROJECT', 'STENCIL')
    yield from settle()
    stamped = image_pixels(find_layer(data, stamp_uid).image)[..., 3] > .5
    check(stamped.sum() > 200, f'the SVG stamps onto the model ({int(stamped.sum())} texels, {editor._active.message})')
    yield from card_click(window, region, 'STENCIL_CARD', 'STENCIL_CLEAR', 'STENCIL')
    yield from close(window, middle)

    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    labels = {control(key).label: key for key in keys('ITEM.')}
    click(window, region, labels['Wood'])
    yield from settle()
    wood_uid = active_layer(data).uid
    check(active_layer(data).name == 'Wood', f'Wood is added {active_layer(data).name} {data.target} {editor._active.message} {editor._active.state.shelf_tab}')
    yield from reveal(window, region, 'PROJECTION')
    click(window, region, 'PROJECTION')
    yield from settle()
    click(window, region, 'SET_PROJECTION.PLANAR')
    yield from settle()
    check(all(has(f'GIZMO_PIN.{index}') for index in range(4)), 'the planar projector shows four corner warp handles')
    gx, gy = spot_of(region, 'GIZMO_PIN.2')
    drag(window, gx, gy, 30, 20, 4)
    yield from settle()
    wood = find_layer(data, wood_uid)
    check(any(abs(value) > .02 for value in wood.proj_warp) and sum(1 for node in nodes(data) if node.type == 'MATH' and node.operation == 'MULTIPLY') > 20,
          f'dragging a corner warps the projection {tuple(round(v, 3) for v in wood.proj_warp)} {sum(1 for node in nodes(data) if node.type == "MATH" and node.operation == "MULTIPLY")} {editor._active.state.drag} {editor._active.message}')
    yield from reveal(window, region, 'PROJ_BEND')
    drag_slider(window, region, 'PROJ_BEND', .6)
    yield from settle()
    check(abs(find_layer(data, wood_uid).proj_bend - .6) < .05, 'the bend slider wraps the projection around a curve')
    yield from reveal(window, region, 'PROJ_SNAP')
    click(window, region, 'PROJ_SNAP')
    yield from settle()
    wood = find_layer(data, wood_uid)
    check(abs(max(abs(value) for value in wood.proj_offset) - 1.0) < .05, 'Snap to surface places the projector on the surface under it')
    yield from reveal(window, region, 'PROJ_UNWARP')
    click(window, region, 'PROJ_UNWARP')
    yield from settle()
    check(not any(find_layer(data, wood_uid).proj_warp), 'Reset warp squares the corners again')

    import bmesh
    detail = bpy.data.meshes.new('HighPoly')
    shape = bmesh.new()
    bmesh.ops.create_uvsphere(shape, u_segments=48, v_segments=24, radius=1.12)
    for face in shape.faces:
        face.smooth = True
    shape.to_mesh(detail)
    shape.free()
    high = bpy.data.objects.new('HighPoly', detail)
    bpy.context.scene.collection.objects.link(high)
    yield from settle()
    yield from card_click(window, region, 'BAKE', 'BAKE_SOURCE', 'BAKE')
    click(window, region, 'SET_SOURCE.HighPoly')
    yield from settle()
    yield from card(window, region, 'BAKE', 'BAKE_RUN', 'BAKE')
    for key in keys('BAKEMAP.'):
        if control(key).active != (key.removeprefix('BAKEMAP.') in {'normal', 'height'}):
            click(window, region, key)
            yield from settle()
    drag_slider(window, region, 'BAKE_SAMPLES', .02)
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    baseline = image_pixels(data.maps['normal'].image).copy()
    height_before = image_pixels(data.maps['height'].image).copy()
    check(abs(height_before[spot[front]][0] - .5) > .02, 'the height bake finds the high-poly in front of the face')
    yield from card_click(window, region, 'BAKE', 'BAKE_PAINT.CAGE', 'BAKE')
    check(data.bake_paint == 'CAGE' and data.cage_map is not None and image_pixels(data.cage_map)[..., 0].min() > .99,
          'Paint cage starts a white cage map that reaches the full distance')
    check(any(node.type == 'TEX_IMAGE' and node.image == data.cage_map for node in nodes(data)), 'the viewport shows the cage map while painting it')
    yield from close(window, middle)
    yield from set_hex(window, region, 'BRUSH_COLOR', '000000')
    click(window, region, 'POLYFILL')
    yield from settle()
    press(window, 'LEFTMOUSE', *face_point(region, area, cube, front))
    yield from settle()
    check(image_pixels(data.cage_map)[spot[front]][0] < .05, 'polygon fill paints zero reach into the cage map on that face')
    yield from card_click(window, region, 'BAKE', 'BAKE_PAINT.CAGE', 'BAKE')
    check(data.bake_paint == '', 'Paint cage turns off again')
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    height_after = image_pixels(data.maps['height'].image)
    check(abs(height_after[spot[front]][0] - .5) < .01 and abs(height_after[spot[right]][0] - height_before[spot[right]][0]) < .02,
          'the painted cage stops rays on that face and leaves the rest of the bake alone')
    normal_after = image_pixels(data.maps['normal'].image)
    check(numpy.abs(normal_after[spot[front]][:3] - numpy.array((.5, .5, 1.0))).max() < .02, 'rays the cage stops give a flat normal')
    yield from card_click(window, region, 'BAKE', 'BAKE_UNPAINT.CAGE', 'BAKE')
    check(data.cage_map is None, 'the cage map can be cleared')
    yield from card_click(window, region, 'BAKE', 'BAKE_PAINT.SKEW', 'BAKE')
    yield from close(window, middle)
    yield from set_hex(window, region, 'BRUSH_COLOR', 'FFFFFF')
    press(window, 'LEFTMOUSE', *face_point(region, area, cube, front))
    yield from settle()
    check(image_pixels(data.skew_map)[spot[front]][0] > .95 and image_pixels(data.skew_map)[spot[right]][0] < .05, 'skew is painted on one face')
    yield from card_click(window, region, 'BAKE', 'BAKE_PAINT.SKEW', 'BAKE')
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    skewed = image_pixels(data.maps['normal'].image)
    unpainted = skewed[..., 3] > .5
    front_mask = (image_pixels(data.skew_map)[..., 0] > .5) & unpainted & (baseline[..., 3] > .5)
    rest = unpainted & ~front_mask & (baseline[..., 3] > .5)
    check(numpy.median(numpy.abs(skewed[..., :3] - baseline[..., :3])[rest]) < .06, 'without skew the per-pixel normal bake matches Blender\'s')
    check(numpy.abs(skewed[..., :3] - baseline[..., :3])[front_mask].max(axis=-1).mean() > .02, f'painted skew bends the rays on that face {numpy.abs(skewed[..., :3] - baseline[..., :3])[front_mask].max(axis=-1).mean():.3f}')
    click(window, region, 'POLYFILL')
    yield from settle()

    click(window, region, 'VIEWPORT')
    yield from settle()
    click(window, region, 'POST')
    yield from settle()
    scene = bpy.context.scene
    tree = scene.compositing_node_group
    check(tree is not None and tree.name.startswith('Devil Painter Post') and area.spaces.active.shading.use_compositor == 'ALWAYS',
          'post effects turn on the viewport compositor')
    yield from card_click(window, region, 'VIEWPORT', 'POST_BLOOM', 'VIEWPORT', fx=.8)
    yield from card_click(window, region, 'VIEWPORT', 'POST_VIGNETTE', 'VIEWPORT', fx=.6)
    check(abs(tree.nodes['post.bloom'].inputs['Strength'].default_value - .8) < .05 and not tree.nodes['post.shade'].mute,
          'bloom and vignette sliders drive the compositor')
    yield from card_click(window, region, 'VIEWPORT', 'POST', 'VIEWPORT')
    check(area.spaces.active.shading.use_compositor == 'DISABLED', 'post effects turn off')
    engine = scene.render.engine
    yield from card_click(window, region, 'VIEWPORT', 'PATH_TRACED', 'VIEWPORT')
    check(area.spaces.active.shading.type == 'RENDERED' and scene.render.engine == 'CYCLES', 'the path-traced preview renders the viewport with Cycles')
    yield from card_click(window, region, 'VIEWPORT', 'PREVIEW_SAMPLES', 'VIEWPORT', fx=.25)
    check(250 <= scene.cycles.preview_samples <= 262, 'the samples slider sets the preview samples')
    yield from card_click(window, region, 'VIEWPORT', 'PATH_TRACED', 'VIEWPORT')
    check(area.spaces.active.shading.type == 'MATERIAL' and scene.render.engine == engine, 'turning it off restores the material preview and engine')
    yield from close(window, middle)

    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot_of(region, 'EXPORT_DIR'))
    yield from settle()
    command = f'"{sys.executable}" "{listener}" {{files}}'
    yield from card_click(window, region, 'EXPORT', 'BRIDGE_COMMAND', 'EXPORT')
    type_text(window, command, *spot_of(region, 'BRIDGE_COMMAND'))
    yield from settle()
    check(bridge.command() == command, 'the export card stores the app command')
    yield from card_click(window, region, 'EXPORT', 'SEND', 'EXPORT')
    yield from until(lambda: received.is_file(), 'received.is_file()')
    sent = received.read_text().splitlines() if received.is_file() else []
    check(sent and all(Path(path).is_file() and Path(path).parent == export_dir for path in sent), 'Export & send launches the app with the exported files')

    yield from until(lambda: (scratch / 'extras_autosave.blend').is_file(), '(scratch / "extras_autosave.blend").is_file()')
    saved = scratch / 'extras_autosave.blend'
    check(saved.is_file(), 'autosave writes a copy next to the file in the background')
    with bpy.data.libraries.load(str(saved)) as (source, _):
        names = list(source.images)
    check(find_layer(data, ribbon_uid).image.name in names, 'the autosave holds the painted layer images')
    saved.unlink()
    saved.mkdir()
    autosave._state['last'] -= 3600
    yield from until(lambda: editor._active.message.startswith('Autosave failed'), 'the blocked autosave to report its failure')
    check(bpy.app.timers.is_registered(autosave.tick), f'a failed autosave is reported and the autosave timer keeps running: {editor._active.message!r}')
    move(window, *middle)
    yield from settle()
    yield from card(window, region, 'PROJECT', 'AUTOSAVE_INFO', 'PROJECT')
    check(control('AUTOSAVE_INFO').label.startswith('Autosave failed at'), f'the project card says the last autosave failed: {control("AUTOSAVE_INFO").label!r}')
    yield from close(window, middle)
    saved.rmdir()
    autosave._state['last'] -= 3600
    yield from until(lambda: saved.is_file(), 'the next autosave to succeed once the cause is fixed')
    check(saved.is_file(), 'the next autosave succeeds once the cause is fixed')
    move(window, *middle)
    yield from settle()
    yield from card(window, region, 'PROJECT', 'AUTOSAVE_INFO', 'PROJECT')
    check('Saved' in control('AUTOSAVE_INFO').label, 'the project card shows when the last autosave happened')
    yield from card_click(window, region, 'PROJECT', 'AUTOSAVE', 'PROJECT')
    check(autosave.minutes() == 0, 'autosave turns off')
    yield from close(window, middle)

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI EXTRAS CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI extras test')
