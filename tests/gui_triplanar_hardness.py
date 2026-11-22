import hashlib
import math
import sys
from pathlib import Path
import bmesh
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, shelf
from devil_painter.document import TRIPLANAR_BLEND, active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, has, move, press, reveal, run_journey, settle, spot, type_text, until, viewport

CELLS = 16
TEXTURE_SIDE = 512
EQUATOR_ROWS = 8
BAND_THRESHOLD = .02
SEAMS = 4


def png(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    side = image.size[0]
    bpy.data.images.remove(image)
    return values.reshape(side, side, 4)[..., :3]


def write_cells(path):
    generator = numpy.random.default_rng(182)
    colors = generator.random((CELLS, CELLS, 3), dtype=numpy.float32)
    cell = TEXTURE_SIDE // CELLS
    pixels = numpy.ones((TEXTURE_SIDE, TEXTURE_SIDE, 4), dtype=numpy.float32)
    pixels[..., :3] = numpy.repeat(numpy.repeat(colors, cell, axis=0), cell, axis=1)
    image = bpy.data.images.new(path.stem, TEXTURE_SIDE, TEXTURE_SIDE, alpha=False)
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def make_sphere(obj):
    mesh = bmesh.new()
    mesh.loops.layers.uv.new('UVMap')
    bmesh.ops.create_uvsphere(mesh, u_segments=64, v_segments=32, radius=1.0, calc_uvs=True)
    for face in mesh.faces:
        face.smooth = True
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def equator(obj, side):
    layer = obj.data.uv_layers.active
    loops = [layer.data[loop.index].uv for loop in obj.data.loops if abs(obj.data.vertices[loop.vertex_index].co.z) < 1e-4]
    row = round(sum(uv[1] for uv in loops) / len(loops) * side)
    low, high = min(uv[0] for uv in loops), max(uv[0] for uv in loops)
    return slice(row - EQUATOR_ROWS, row + EQUATOR_ROWS), slice(int(math.ceil(low * side)) + 1, int(math.floor(high * side)) - 1)


def band_degrees(result, hard, rows, columns):
    difference = numpy.abs(result - hard)[rows, columns].mean(axis=(0, 2))
    banded = difference > BAND_THRESHOLD
    return float(banded.sum()) / banded.size * 360.0 / SEAMS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'triplanar_export'
    textures = scratch / 'triplanar_textures'
    textures.mkdir(exist_ok=True)
    write_cells(textures / 'cells.png')
    cube = bpy.data.objects['Cube']
    make_sphere(cube)
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = cube.devil_painter.sets[0]
    rows, columns = equator(cube, data.resolution)

    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    def exported():
        click(window, region, 'EXPORT')
        yield from settle()
        click(window, region, 'EXPORT_RUN')
        yield from settle()
        press(window, 'ESC', *middle)
        yield from settle()
        path = export_dir / 'Cube_Material_BaseColor.png'
        return png(path), digest(path)

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def layer():
        return find_layer(data, layer_uid)

    def box():
        return data.material.node_tree.nodes[layer_uid + '.base_color.box']

    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield from until(lambda: any(item.key.startswith('ITEM.') for item in editor._active.workspace.controls), 'the texture folder lists its texture')
    yield from reveal(window, region, 'SOURCE.base_color')
    click(window, region, 'SOURCE.base_color')
    yield from settle()
    click(window, region, 'PICK_TEXTURE.base_color')
    yield from settle()
    click(window, region, f'ITEM.{next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == "cells")}')
    yield from settle()
    check(layer().slots['base_color'].source == 'IMAGE' and layer().slots['base_color'].image.name == 'cells.png', 'the Fill layer base color is the cells texture')
    yield from reveal(window, region, 'PROJECTION')
    check(not has('TRIPLANAR_HARDNESS'), 'the UV projection shows no tri-planar hardness')
    click(window, region, 'PROJECTION')
    yield from settle()
    click(window, region, 'SET_PROJECTION.TRIPLANAR')
    yield from settle()
    check(layer().projection == 'TRIPLANAR' and box().projection == 'BOX', 'the projection dropdown switches the texture to tri-planar box mapping')
    check(layer().triplanar_blend == numpy.float32(TRIPLANAR_BLEND) and box().projection_blend == layer().triplanar_blend,
          f'a new layer starts at the previous fixed blend {TRIPLANAR_BLEND}')
    yield from reveal(window, region, 'TRIPLANAR_HARDNESS')
    check(control('TRIPLANAR_HARDNESS').label == 'Hardness' and control('TRIPLANAR_HARDNESS').text == '0.80',
          'the tri-planar projection shows its Hardness slider at the default 0.80')
    default, default_digest = yield from exported()
    print('DEFAULT BASECOLOR SHA256', default_digest)

    def drag(fx_start, fx_end):
        yield from reveal(window, region, 'TRIPLANAR_HARDNESS')
        start = spot(region, 'TRIPLANAR_HARDNESS', fx_start)
        end = spot(region, 'TRIPLANAR_HARDNESS', fx_end)
        move(window, *start)
        window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(start[0]), y=int(start[1]))
        yield from settle()
        move(window, *end)
        yield from settle()
        live = (layer().triplanar_blend, box().projection_blend)
        window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(end[0]), y=int(end[1]))
        yield from settle()
        return live

    live = yield from drag(.5, 1.5)
    check(live == (0.0, 0.0), f'dragging the slider past its end updates the material live before release {live}')
    check(layer().triplanar_blend == 0.0 and control('TRIPLANAR_HARDNESS').text == '1.00', 'hardness 1 makes the projections meet at a hard line')
    hard, _ = yield from exported()

    def setting(label, fx):
        yield from drag(fx, fx)
        check(box().projection_blend == layer().triplanar_blend and control('TRIPLANAR_HARDNESS').text == f'{1.0 - layer().triplanar_blend:.2f}',
              f'the {label} hardness {1.0 - layer().triplanar_blend:.2f} reaches the material')
        result, _ = yield from exported()
        return result

    harder = yield from setting('harder', .95)
    harder_hardness = round(1.0 - layer().triplanar_blend, 4)
    softer = yield from setting('softer', .5)
    softer_hardness = round(1.0 - layer().triplanar_blend, 4)
    widths = dict(default=band_degrees(default, hard, rows, columns), harder=band_degrees(harder, hard, rows, columns), softer=band_degrees(softer, hard, rows, columns))
    check(widths['harder'] < widths['default'] < widths['softer'] and widths['default'] > 5.0,
          f'harder narrows and softer widens the transition band (degrees per seam {widths})')

    stored = layer().triplanar_blend
    saved_file = scratch / 'triplanar_hardness.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved_file))
    bpy.ops.wm.open_mainfile(filepath=str(saved_file))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter.sets[0]
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(layer().triplanar_blend == stored, f'the reopened file keeps the exact hardness ({1.0 - stored})')
    reopened, _ = yield from exported()
    gap = float(numpy.abs(reopened - softer).max())
    check(gap == 0.0, f'the reopened file exports the same tri-planar blend ({gap})')
    print('TRIPLANAR HARDNESS EVIDENCE', dict(default_hardness=round(1.0 - TRIPLANAR_BLEND, 4), harder_hardness=harder_hardness, softer_hardness=softer_hardness,
                                              band_degrees_per_seam={key: round(value, 2) for key, value in widths.items()}, reopened_gap=gap,
                                              default_sha256=default_digest))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI TRIPLANAR HARDNESS CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI tri-planar hardness test')
