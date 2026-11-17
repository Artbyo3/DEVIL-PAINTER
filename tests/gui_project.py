import os
import sys
import time
import traceback
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
from devil_painter import editor, exporting, library, tiles
from devil_painter.document import texture_set
from tools.workspace import prepare_scratch

TIMEOUT = 300
STARTED = time.time()


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


def click(window, region, key, kind='LEFTMOUSE', fx=.5):
    rect = control(key).rect
    press(window, kind, region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h / 2)


def type_text(window, text, x, y):
    for _ in range(120):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


def field(window, region, key, text):
    click(window, region, key)
    rect = control(key).rect
    type_text(window, text, region.x + rect.x + rect.w / 2, region.y + rect.y + rect.h / 2)


def stroke_at(window, region, point):
    x, y = region.x + point[0], region.y + point[1]
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 6):
        move(window, x + step * 3, y + step * 2)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 15), y=int(y + 10))


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(-1, 4)


def loaded(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = pixels(image)
    result = values, image.is_float, image.channels
    bpy.data.images.remove(image)
    return result


def build_mesh(area):
    cube = bpy.data.objects['Cube']
    mesh = cube.data
    view = area.spaces.active.region_3d
    direction = view.view_rotation @ Vector((0.0, 0.0, -1.0))
    facing = sorted(range(len(mesh.polygons)), key=lambda index: mesh.polygons[index].normal.dot(direction))
    body_low, body_high, trim = facing[0], facing[1], facing[2]
    mesh.materials.clear()
    mesh.materials.append(bpy.data.materials.new('Body'))
    mesh.materials.append(bpy.data.materials.new('Trim'))
    hidden = facing[3:]
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = 1 if index == trim or index == hidden[0] else 0
    layer = mesh.uv_layers.active
    for loop in mesh.polygons[body_high].loop_indices:
        layer.data[loop].uv = (layer.data[loop].uv[0] + 1.0, layer.data[loop].uv[1])
    mesh.update()
    return cube, body_low, body_high, trim


def screen_point(region, area, cube, face):
    center = cube.matrix_world @ cube.data.polygons[face].center
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, center)
    return point.x, point.y


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch, not the user library')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    cube, body_low, body_high, trim = build_mesh(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.6
    check(control('SETUP_SET.0').label == 'Body' and control('SETUP_SET.1').label == 'Trim', 'the setup card lists one texture set per material slot')
    check(control('SETUP_TILES.0').label == 'UDIM 1001, 1002' and control('SETUP_TILES.1').label == 'Single tile'
          and has('SETUP_UDIM') and control('SETUP_UDIM').active, 'the setup card detects the UDIM tiles each set uses')
    click(window, region, 'RES.0.1024')
    yield 0.2
    click(window, region, 'RES.1.1024')
    yield 0.2
    check(control('RES.1.1024').active, 'each texture set picks its own resolution')
    click(window, region, 'START')
    yield 2.0
    project = cube.devil_painter
    body, trim_set = project.sets[0], project.sets[1]
    check(project.enabled and len(project.sets) == 2 and tiles.numbers(body) == [1001, 1002] and tiles.numbers(trim_set) == [1001],
          'Start painting creates a project with a texture set per slot and its UDIM tiles')
    check(cube.material_slots[0].material == body.material and cube.material_slots[1].material == trim_set.material,
          'each material slot gets the material of its texture set')
    body_paint = body.layers[0]
    check(tiles.variant(body, body_paint.image, 1002) is not body_paint.image and len(trim_set.layers) == 1,
          'paint layers hold one image per UDIM tile')

    rect = control('BRUSHVAL.roughness').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .9, region.y + rect.y + rect.h / 2)
    yield 0.3
    stroke_at(window, region, screen_point(region, area, cube, body_high))
    yield 1.2
    check(project.active_set == 0 and project.active_tile == 1002, 'clicking a face in tile 1002 switches painting to that tile')
    selected = numpy.empty(len(cube.data.polygons), dtype=bool)
    cube.data.polygons.foreach_get('select', selected)
    check(cube.data.use_paint_mask and selected.sum() == 1 and selected[body_high], 'a face mask keeps the stroke inside the set and tile')
    check(pixels(tiles.variant(body, body_paint.image, 1002))[:, 3].max() > .5 and pixels(body_paint.image)[:, 3].max() == 0.0,
          'the stroke lands only in the tile 1002 image of the Body set')
    canvas = body_paint.slots['roughness'].image
    check(pixels(tiles.variant(body, canvas, 1002))[:, 0].max() > .85, 'the stroke paints roughness into the tile 1002 canvas')

    stroke_at(window, region, screen_point(region, area, cube, trim))
    yield 1.2
    check(project.active_set == 1 and pixels(trim_set.layers[0].image)[:, 3].max() > .5, 'clicking a Trim face paints the Trim set')
    check(pixels(tiles.variant(body, body_paint.image, 1002))[:, 3].max() > .5, 'the Body painting stays in its own set')

    click(window, region, 'SET.0')
    yield 0.5
    check(project.active_set == 0 and has('TILE.1001') and has('TILE.1002'), 'the Texture sets panel switches sets and shows their tiles')
    click(window, region, 'TILE.1001')
    yield 0.5
    check(project.active_tile == 1001 and control('TILE.1001').active, 'tile chips switch the painted tile')
    click(window, region, 'SETRES.1')
    yield 0.3
    click(window, region, 'SET_SETRES.1.2048')
    yield 1.0
    check(trim_set.resolution == 2048 and tuple(trim_set.layers[0].image.size) == (2048, 2048), 'a texture set changes resolution and keeps its paint')
    check(pixels(trim_set.layers[0].image)[:, 3].max() > .5, 'the rescaled Trim paint survives')

    click(window, region, 'BAKE')
    yield 0.4
    for key in ('curvature', 'thickness', 'position', 'world_normal', 'id'):
        click(window, region, 'BAKEMAP.' + key)
        yield 0.05
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield 0.2
    click(window, region, 'BAKE_RUN')
    yield 2.0
    ao = body.maps['ao'].image
    low_cover = (pixels(ao)[:, 3] > .5).mean()
    high_cover = (pixels(tiles.variant(body, ao, 1002))[:, 3] > .5).mean()
    check(0 < high_cover < low_cover and 'ao' in trim_set.maps, 'ambient occlusion bakes per tile and per texture set')

    def card():
        if not has('EXPORT_RUN'):
            click(window, region, 'EXPORT')
        yield 0.4

    export_dir = scratch / 'project_export'
    yield from card()
    check(has('EXPORT_TEMPLATE') and has('EXPORT_SET.0') and has('EXPORT_SET.1') and has('EXPORT_PATTERN'),
          'the export card offers templates, texture sets, naming, and the folder')
    click(window, region, 'EXPORT_TEMPLATE')
    yield 0.3
    names = [item['name'] for item in exporting.all_templates()]
    click(window, region, f'SET_TEMPLATE.{names.index("Unreal Engine")}')
    yield 0.3
    yield from card()
    check(control('EXPORT_TEMPLATE').text == 'Unreal Engine' and has('OUT_LABEL.1'), 'picking the Unreal Engine template lists its packed outputs')
    field(window, region, 'EXPORT_DIR', str(export_dir))
    yield 0.3
    click(window, region, 'EXPORT_RUN')
    yield 3.0
    expected = ['Cube_Body_BaseColor.1001.png', 'Cube_Body_BaseColor.1002.png', 'Cube_Body_OcclusionRoughnessMetallic.1002.png',
                'Cube_Body_Normal.1001.png', 'Cube_Trim_BaseColor.png', 'Cube_Trim_OcclusionRoughnessMetallic.png']
    check(all((export_dir / name).is_file() for name in expected), 'export writes every set, with UDIM numbers only for tiled sets')
    orm, _, _ = loaded(export_dir / 'Cube_Body_OcclusionRoughnessMetallic.1002.png')
    covered = orm[orm[:, 0] > .05]
    check(covered[:, 1].max() > .85 and (numpy.abs(covered[:, 1] - .5) < .03).any() and covered[:, 2].max() < .05,
          'the ORM map packs occlusion, painted roughness, and metallic into R, G, and B')
    base, _, _ = loaded(export_dir / 'Cube_Body_BaseColor.1002.png')
    check(base[:, 0].min() < .1 and base[:, 0].max() > .8, 'the tile 1002 base color holds the painted stroke')

    yield from card()
    click(window, region, 'TEMPLATE_DUPLICATE')
    yield 0.3
    yield from card()
    check(project.export_template == 'Unreal Engine copy' and has('OUT_SRC.1.0') and has('OUT_FORMAT.1'), 'a custom copy of the template is editable')
    for opener, item in (('OUT_FORMAT.1', 'SET_FORMAT.1.OPEN_EXR'), ('OUT_DEPTH.1', 'SET_DEPTH.1.32'), ('OUT_SRC.1.3', 'SET_SRC.1.3.height')):
        click(window, region, opener)
        yield 0.3
        click(window, region, item)
        yield 0.3
        yield from card()
    custom = exporting.find_template('Unreal Engine copy')['outputs'][1]
    check(custom['format'] == 'OPEN_EXR' and custom['depth'] == '32' and custom['sources'] == ['ao', 'roughness', 'metallic', 'height'],
          'outputs take a format, a bit depth, and an extra packed channel')
    click(window, region, 'EXPORT_SET.1')
    yield 0.3
    field(window, region, 'EXPORT_PATTERN', '{set}-{output}-{udim}')
    yield 0.3
    yield from card()
    click(window, region, 'EXPORT_DEPTH')
    yield 0.3
    click(window, region, 'SET_EXPORT_DEPTH.16')
    yield 0.3
    yield from card()
    custom_dir = scratch / 'custom_export'
    field(window, region, 'EXPORT_DIR', str(custom_dir))
    yield 0.3
    click(window, region, 'EXPORT_RUN')
    yield 3.0
    exr = custom_dir / 'Body-OcclusionRoughnessMetallic-1002.exr'
    png = custom_dir / 'Body-BaseColor-1001.png'
    check(exr.is_file() and png.is_file() and not any('Trim' in path.name for path in custom_dir.iterdir()),
          'naming tokens and per-set selection shape the export')
    _, exr_float, exr_channels = loaded(exr)
    _, png_float, _ = loaded(png)
    check(exr_float and exr_channels == 4 and png_float, 'the custom output writes an RGBA EXR and the override writes 16-bit PNGs')

    click(window, region, 'CLOSE')
    yield 0.5
    check(editor._active is None and not cube.data.use_paint_mask, 'closing Devil Painter restores the face mask')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI PROJECT CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI project test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0)
