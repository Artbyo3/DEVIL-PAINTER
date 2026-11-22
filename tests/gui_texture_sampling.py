import hashlib
import shutil
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
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, has, move, press, reveal, run_journey, settle, spot, type_text, until, viewport

TEXELS = 16
SIDE = 1024
BYTE = 1.0 / 255.0
TOLERANCE = 1.5 * BYTE
BOUNDARY = .01
WRAPS = {'REPEAT': 'Repeat', 'EXTEND': 'Clamp', 'MIRROR': 'Mirror'}
FILTERS = {'Linear': 'Linear', 'Closest': 'Closest', 'Cubic': 'Cubic'}


def png(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    side = image.size[0]
    bpy.data.images.remove(image)
    return values.reshape(side, side, 4)[..., :3]


def write_cells(path):
    generator = numpy.random.default_rng(183)
    colors = generator.integers(0, 256, (TEXELS, TEXELS, 3)).astype(numpy.float32) / 255.0
    pixels = numpy.ones((TEXELS, TEXELS, 4), dtype=numpy.float32)
    pixels[..., :3] = colors
    image = bpy.data.images.new(path.stem, TEXELS, TEXELS, alpha=False)
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    return colors


def make_plane(obj):
    mesh = bmesh.new()
    uv = mesh.loops.layers.uv.new('UVMap')
    corners = [mesh.verts.new(point) for point in ((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0))]
    face = mesh.faces.new(corners)
    for loop, coordinate in zip(face.loops, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        loop[uv].uv = coordinate
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def texel_columns(shifted, wrap):
    if wrap == 'REPEAT':
        place = numpy.mod(shifted, 1.0)
    elif wrap == 'EXTEND':
        place = shifted
    else:
        place = numpy.mod(shifted, 2.0)
        place = numpy.where(place > 1.0, 2.0 - place, place)
    return numpy.clip(numpy.floor(place * TEXELS), 0, TEXELS - 1).astype(int)


def reference(colors, offset, wrap):
    centers = (numpy.arange(SIDE) + .5) / SIDE
    shifted = centers - offset
    columns = texel_columns(shifted, wrap)
    rows = numpy.floor(centers * TEXELS).astype(int)
    expected = colors[rows[:, None], columns[None, :]]
    near = numpy.abs(shifted * TEXELS - numpy.round(shifted * TEXELS)) < BOUNDARY
    return expected, ~near


def steps(row):
    jumps = numpy.abs(numpy.diff(row, axis=0)).max(axis=1)
    return dict(changed_steps=int((jumps > .5 * BYTE).sum()), largest_step=round(float(jumps.max()), 4), levels=int(len(numpy.unique(numpy.round(row / BYTE), axis=0))))


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'sampling_export'
    stills = scratch / 'sampling_stills'
    stills.mkdir(exist_ok=True)
    textures = scratch / 'sampling_textures'
    textures.mkdir(exist_ok=True)
    colors = write_cells(textures / 'cells.png')
    cube = bpy.data.objects['Cube']
    make_plane(cube)
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
    check(data.resolution == SIDE, f'the texture set is {SIDE} px')

    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    def exported(label):
        click(window, region, 'EXPORT')
        yield from settle()
        click(window, region, 'EXPORT_RUN')
        yield from settle()
        press(window, 'ESC', *middle)
        yield from settle()
        path = export_dir / 'Cube_Material_BaseColor.png'
        shutil.copyfile(path, stills / f'{label}.png')
        return png(path), digest(path)

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def slot():
        return find_layer(data, layer_uid).slots['base_color']

    def samplers():
        return [node for node in data.material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image is not None and node.image.name == 'cells.png']

    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield from until(lambda: any(item.key.startswith('ITEM.') for item in editor._active.workspace.controls), 'the texture folder lists its texture')
    yield from reveal(window, region, 'SOURCE.base_color')
    check(not has('WRAP.base_color') and not has('FILTERING.base_color'), 'a plain value channel shows no wrap or filtering')
    click(window, region, 'SOURCE.base_color')
    yield from settle()
    click(window, region, 'PICK_TEXTURE.base_color')
    yield from settle()
    click(window, region, f'ITEM.{next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == "cells")}')
    yield from settle()
    check(slot().source == 'IMAGE' and slot().image.name == 'cells.png', 'the Fill layer base color is the cells texture')
    check(slot().wrap == 'REPEAT' and slot().filtering == 'Linear', 'a new texture slot starts on Repeat wrap and Linear filtering')
    check(len(samplers()) == 1 and samplers()[0].extension == 'REPEAT' and samplers()[0].interpolation == 'Linear',
          'the default slot builds the same Repeat and Linear sampler as before')
    yield from reveal(window, region, 'WRAP.base_color')
    check(control('WRAP.base_color').label == 'Wrap' and control('WRAP.base_color').text == 'Repeat' and control('WRAP.base_color').kind == 'DROPDOWN',
          'the texture channel shows a Wrap dropdown on Repeat')
    check(control('FILTERING.base_color').label == 'Filtering' and control('FILTERING.base_color').text == 'Linear' and control('FILTERING.base_color').kind == 'DROPDOWN',
          'the texture channel shows a Filtering dropdown on Linear')
    check(control('WRAP.base_color').rect.y < control('SOURCE.base_color').rect.y and abs(control('WRAP.base_color').rect.y - control('SOURCE.base_color').rect.y) < 3 * control('SOURCE.base_color').rect.h,
          'the wrap and filtering row sits right under the texture channel row')

    def choose(field, mode, names):
        key = f'{field.upper()}.base_color'
        yield from reveal(window, region, key)
        click(window, region, key)
        yield from settle()
        check(has(f'SET_SAMPLING.{field}.base_color.{mode}'), f'the {field} menu offers {names[mode]}')
        click(window, region, f'SET_SAMPLING.{field}.base_color.{mode}')
        yield from settle()
        attribute = 'extension' if field == 'wrap' else 'interpolation'
        check(getattr(slot(), field) == mode and all(getattr(node, attribute) == mode for node in samplers()) and samplers(),
              f'choosing {names[mode]} {field} reaches the material sampler live')
        yield from reveal(window, region, key)
        check(control(key).text == names[mode], f'the {field} dropdown reads {names[mode]}')

    linear, default_digest = yield from exported('filtering_linear')
    print('DEFAULT BASECOLOR SHA256', default_digest)
    filtered = dict(Linear=linear)
    for mode in ('Closest', 'Cubic'):
        yield from choose('filtering', mode, FILTERS)
        filtered[mode], _ = yield from exported(f'filtering_{mode.lower()}')
    row = SIDE // TEXELS * 4 + SIDE // TEXELS // 2
    nearest, clear = reference(colors, 0.0, 'REPEAT')
    filtering = {mode: steps(result[row]) for mode, result in filtered.items()}
    closest_gap = float(numpy.abs(filtered['Closest'] - nearest)[:, clear].max())
    texel_jump = float(numpy.abs(numpy.diff(colors[4], axis=0)).max())
    check(closest_gap <= TOLERANCE and filtering['Closest']['changed_steps'] <= TEXELS and filtering['Closest']['largest_step'] >= texel_jump - TOLERANCE,
          f'Closest keeps every texel a hard square ({filtering["Closest"]}, gap to nearest texel {closest_gap:.4f})')
    check(filtering['Linear']['changed_steps'] > 10 * filtering['Closest']['changed_steps'] and filtering['Linear']['largest_step'] < filtering['Closest']['largest_step'] / 4,
          f'Linear blends between texels in small steps ({filtering["Linear"]}, largest texel jump {texel_jump:.4f})')
    check(filtering['Cubic']['changed_steps'] > 10 * filtering['Closest']['changed_steps'] and float(numpy.abs(filtered['Cubic'] - linear).max()) > 2 * BYTE,
          f'Cubic is smooth and differs from Linear ({filtering["Cubic"]})')

    yield from choose('filtering', 'Closest', FILTERS)
    yield from reveal(window, region, 'UV_OFFSET_X')
    start = spot(region, 'UV_OFFSET_X', .5)
    move(window, *start)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(start[0]), y=int(start[1]))
    yield from settle()
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(start[0]), y=int(start[1]))
    yield from settle()
    offset = float(find_layer(data, layer_uid).uv_offset[0])
    check(.3 < offset < .7, f'the Offset X slider moves the texture across the UV border ({offset:.4f})')
    border = int(round(offset * SIDE))
    wraps = {}
    for mode in ('REPEAT', 'EXTEND', 'MIRROR'):
        if mode != 'REPEAT':
            yield from choose('wrap', mode, WRAPS)
        result, _ = yield from exported(f'wrap_{WRAPS[mode].lower()}')
        expected, clear = reference(colors, offset, mode)
        gap = float(numpy.abs(result - expected)[:, clear].max())
        past = result[:, :border - 2]
        wraps[mode] = dict(result=result, gap=gap, matched=float((numpy.abs(result - expected)[:, clear].max(axis=2) <= TOLERANCE).mean()))
        check(gap <= TOLERANCE, f'{WRAPS[mode]} matches its texel reference past the UV border (max gap {gap:.4f})')
        if mode == 'REPEAT':
            check(numpy.abs(past - expected[:, :border - 2]).max() <= TOLERANCE and float(numpy.abs(past[:, -1] - colors[numpy.floor((numpy.arange(SIDE) + .5) / SIDE * TEXELS).astype(int), -1]).max()) <= TOLERANCE,
                  'Repeat tiles the texture: the last texel column comes back right before the border')
        elif mode == 'EXTEND':
            check(float(numpy.abs(past - past[:, -1:]).max()) <= TOLERANCE, 'Clamp extends the edge pixels: every column past the border repeats the edge column')
        else:
            width = min(border - 2, SIDE - border - 2)
            left, right = border - 1 - numpy.arange(width), border + numpy.arange(width)
            texel_place = ((numpy.arange(SIDE) + .5) / SIDE - offset) * TEXELS
            steady = numpy.abs(texel_place - numpy.round(texel_place)) > 1.5 * TEXELS / SIDE
            paired = steady[left] & steady[right]
            mirrored = float(numpy.abs(result[:, left[paired]] - result[:, right[paired]]).max())
            wraps[mode]['mirror_gap'] = mirrored
            check(mirrored <= TOLERANCE, f'Mirror flips the texture at the border (max gap {mirrored:.4f})')
    check(float(numpy.abs(wraps['REPEAT']['result'][:, border:] - wraps['EXTEND']['result'][:, border:]).max()) <= TOLERANCE
          and float(numpy.abs(wraps['REPEAT']['result'][:, :border - 2] - wraps['EXTEND']['result'][:, :border - 2]).max()) > 10 * BYTE,
          'the wrap modes agree inside the UVs and differ only past the border')

    saved_file = scratch / 'texture_sampling.blend'
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
    check(slot().wrap == 'MIRROR' and slot().filtering == 'Closest', 'the reopened file keeps Mirror wrap and Closest filtering')
    check(samplers() and all(node.extension == 'MIRROR' and node.interpolation == 'Closest' for node in samplers()), 'the reopened material samples with Mirror and Closest')
    reopened, _ = yield from exported('reopened')
    gap = float(numpy.abs(reopened - wraps['MIRROR']['result']).max())
    check(gap == 0.0, f'the reopened file exports the same pixels ({gap})')
    print('TEXTURE SAMPLING EVIDENCE', dict(
        default_sha256=default_digest, filtering_row=row, filtering=filtering, closest_gap_to_nearest=round(closest_gap, 4), texel_jump=round(texel_jump, 4),
        offset=round(offset, 4), border_column=border,
        wraps={WRAPS[mode]: dict(max_gap=round(item['gap'], 4), matched=item['matched'], **({'mirror_gap': round(item['mirror_gap'], 4)} if 'mirror_gap' in item else {}))
               for mode, item in wraps.items()},
        border_row={WRAPS[mode]: [[round(float(value), 3) for value in item['result'][row, column]] for column in (border - 96, border - 32, border + 32, border + 96)]
                    for mode, item in wraps.items()},
        reopened_gap=gap))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI TEXTURE SAMPLING CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps_run = journey()


run_journey(journey(), 'GUI texture sampling test')
