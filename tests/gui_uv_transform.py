import math
import sys
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, press, reveal, run_journey, settle, shelf_index, slide, spot, type_text, viewport

ISLAND_MARGIN = 3


def png(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    side = image.size[0]
    bpy.data.images.remove(image)
    return values.reshape(side, side, 4)[..., 0]


def islands(cube, side):
    inside = numpy.zeros((side, side), dtype=bool)
    layer = cube.data.uv_layers.active
    for polygon in cube.data.polygons:
        uvs = numpy.array([tuple(layer.data[loop].uv) for loop in polygon.loop_indices]) * side
        low, high = numpy.ceil(uvs.min(axis=0)).astype(int) + ISLAND_MARGIN, numpy.floor(uvs.max(axis=0)).astype(int) - ISLAND_MARGIN
        inside[low[1]:high[1], low[0]:high[0]] = True
    return inside


def predicted(base, inside, offset, angle):
    side = base.shape[0]
    rows, columns = numpy.mgrid[0:side, 0:side]
    du, dv = (columns + .5) / side - .5 - offset[0], (rows + .5) / side - .5 - offset[1]
    cos, sin = math.cos(angle), math.sin(angle)
    x = (cos * du + sin * dv + .5) * side - .5
    y = (cos * dv - sin * du + .5) * side - .5
    x0, y0 = numpy.floor(x).astype(int), numpy.floor(y).astype(int)
    valid = inside & (x0 >= 0) & (y0 >= 0) & (x0 < side - 1) & (y0 < side - 1)
    x0, y0 = numpy.clip(x0, 0, side - 2), numpy.clip(y0, 0, side - 2)
    valid &= inside[y0, x0] & inside[y0, x0 + 1] & inside[y0 + 1, x0] & inside[y0 + 1, x0 + 1]
    fx, fy = x - x0, y - y0
    value = (base[y0, x0] * (1 - fx) * (1 - fy) + base[y0, x0 + 1] * fx * (1 - fy)
             + base[y0 + 1, x0] * (1 - fx) * fy + base[y0 + 1, x0 + 1] * fx * fy)
    return value, valid


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'uv_transform_export'
    devil_painter.register()
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
    inside = islands(cube, data.resolution)

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
        return png(export_dir / 'Cube_Material_Roughness.png')

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def layer():
        return find_layer(data, layer_uid)

    def transform():
        return data.material.node_tree.nodes[layer_uid + ':uv_transform']

    yield from reveal(window, region, 'SOURCE.roughness')
    click(window, region, 'SOURCE.roughness')
    yield from settle()
    click(window, region, 'PICK_PATTERN.roughness')
    yield from settle()
    click(window, region, f'ITEM.{shelf_index("Noise")}')
    yield from settle()
    check(layer().slots['roughness'].source == 'PATTERN' and layer().projection == 'UV', 'the Fill layer roughness is a Noise pattern on the UV projection')
    check(tuple(layer().uv_offset) == (0.0, 0.0) and layer().uv_rotation == 0.0, 'a new Fill layer starts at offset 0 and rotation 0')
    for key in ('UV_OFFSET_X', 'UV_OFFSET_Y', 'UV_SPIN', 'TILE_MATCH'):
        yield from reveal(window, region, key)
    check(control('UV_SPIN').text == '0°' and control('UV_OFFSET_X').text == '0.00', 'the UV projection shows its offset and spin controls')
    base = yield from exported()
    spread = float(base[inside].std())
    check(spread > .02, f'the Noise pattern varies across the UVs ({spread:.4f})')

    def measured(label, result):
        value, valid = predicted(base, inside, tuple(layer().uv_offset), layer().uv_rotation)
        gap = float(numpy.abs(result - value)[valid].mean())
        unmoved = float(numpy.abs(result - base)[inside].mean())
        check(valid.sum() > 20000 and gap < .004 and unmoved > 10 * gap,
              f'{label} matches the pattern moved by the set amount (gap {gap:.5f} on {int(valid.sum())} pixels, unmoved {unmoved:.4f})')
        return dict(offset=tuple(round(value, 4) for value in layer().uv_offset), degrees=round(math.degrees(layer().uv_rotation), 2),
                    gap=round(gap, 5), unmoved=round(unmoved, 4), pixels=int(valid.sum()))

    yield from slide(window, region, 'UV_OFFSET_X', .25)
    check(abs(layer().uv_offset[0] - .25) < .02 and layer().uv_offset[1] == 0.0 and control('UV_OFFSET_X').text == f'{layer().uv_offset[0]:.2f}',
          f'the Offset X slider slides the projection ({layer().uv_offset[0]:.4f})')
    check(tuple(transform().inputs['Location'].default_value)[:2] == tuple(numpy.float32(value) for value in layer().uv_offset),
          'the offset reaches the UV transform')
    shifted = yield from exported()
    offset_evidence = measured('the offset export', shifted)

    yield from slide(window, region, 'UV_OFFSET_X', 0.0)
    check(layer().uv_offset[0] == 0.0, 'the Offset X slider returns to 0')
    returned = yield from exported()
    gap = float(numpy.abs(returned - base).max())
    check(gap == 0.0, f'offset 0 exports the untouched pattern exactly ({gap})')

    yield from slide(window, region, 'UV_SPIN', .25)
    degrees = math.degrees(layer().uv_rotation)
    check(abs(degrees - 90) < 3 and control('UV_SPIN').text == f'{degrees % 360:.0f}°', f'the Spin slider turns the projection ({degrees:.2f}°)')
    check(abs(transform().inputs['Rotation'].default_value[2] - layer().uv_rotation) < 1e-6, 'the rotation reaches the UV transform')
    turned = yield from exported()
    turn_evidence = measured('the rotated export', turned)

    yield from slide(window, region, 'UV_OFFSET_Y', .6)
    check(abs(layer().uv_offset[1] - .6) < .02, f'the Offset Y slider slides the projection up ({layer().uv_offset[1]:.4f})')
    combined = yield from exported()
    combined_evidence = measured('the offset and rotated export', combined)
    stored = (tuple(layer().uv_offset), layer().uv_rotation)

    saved_file = scratch / 'uv_transform.blend'
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
    check((tuple(layer().uv_offset), layer().uv_rotation) == stored, f'the reopened file keeps the exact offset and rotation {stored}')
    reopened = yield from exported()
    gap = float(numpy.abs(reopened - combined).max())
    check(gap == 0.0, f'the reopened file exports the same transformed pattern ({gap})')
    print('UV TRANSFORM EVIDENCE', dict(spread=round(spread, 4), offset=offset_evidence, rotation=turn_evidence, combined=combined_evidence, reopened_gap=gap))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI UV TRANSFORM CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI UV transform test')
