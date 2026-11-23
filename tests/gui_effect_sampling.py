import sys
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, shelf
from devil_painter.document import TRIPLANAR_BLEND, active_effect, active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import check, click, control, finish, has, press, reveal, run_journey, settle, slide, spot, type_text, until, viewport

TEXTURE_SIDE = 64


def write_texture(path, seed):
    pixels = numpy.ones((TEXTURE_SIDE, TEXTURE_SIDE, 4), dtype=numpy.float32)
    pixels[..., :3] = numpy.random.default_rng(seed).random((TEXTURE_SIDE, TEXTURE_SIDE, 3), dtype=numpy.float32)
    image = bpy.data.images.new(path.stem, TEXTURE_SIDE, TEXTURE_SIDE, alpha=False)
    image.pixels.foreach_set(pixels.ravel())
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def menu(window, region, opener, item):
    yield from reveal(window, region, opener)
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


def effect_nodes(data, effect):
    return [node for node in data.material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image == effect.texture]


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    textures = scratch / 'effect_sampling_textures'
    textures.mkdir(exist_ok=True)
    write_texture(textures / 'speckle.png', 243)
    write_texture(textures / 'grain.png', 249)
    cube = bpy.data.objects['Cube']
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

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield from settle()
    click(window, region, 'TEXTURE_DIR')
    yield from settle()
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield from until(lambda: any(item.key.startswith('ITEM.') for item in editor._active.workspace.controls), 'the texture folder lists its texture')

    def textured_fill(target, texture):
        yield from menu(window, region, 'ADD_FX_' + target, f'NEW_FX.{target}.FILL')
        uid = active_effect(data).uid
        check(not has('FX_WRAP') and not has('FX_FILTERING'), f'a pattern Fill {target.lower()} effect shows no texture sampling choices')
        yield from menu(window, region, 'FX_SOURCE', 'FX_PICK_TEXTURE')
        click(window, region, f'ITEM.{next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == texture)}')
        yield from settle()
        effect = active_effect(data)
        check(effect.uid == uid and effect.target == target and effect.source == 'IMAGE' and effect.texture is not None,
              f'the Fill {target.lower()} effect takes the {texture} texture from the shelf')
        return uid

    def check_sampling(uid, target):
        effect = next(item for item in find_layer(data, layer_uid).effects if item.uid == uid)
        found = effect_nodes(data, effect)
        check(found and all((node.extension, node.interpolation) == (effect.wrap, effect.filtering) for node in found),
              f'the {target.lower()} effect texture samples with {effect.wrap} wrap and {effect.filtering} filtering')
        return effect, found

    for target, texture in (('CONTENT', 'speckle'), ('MASK', 'grain')):
        uid = yield from textured_fill(target, texture)
        effect, found = check_sampling(uid, target)
        yield from reveal(window, region, 'FX_WRAP')
        check(control('FX_WRAP').label == 'Wrap' and control('FX_WRAP').text == 'Repeat' and control('FX_FILTERING').label == 'Filtering'
              and control('FX_FILTERING').text == 'Linear', f'the {target.lower()} effect shows Wrap Repeat and Filtering Linear by default')
        check((effect.wrap, effect.filtering) == ('REPEAT', 'Linear') and all(node.projection == 'FLAT' for node in found),
              f'the {target.lower()} effect keeps the previous fixed Repeat and Linear sampling by default')
        check(not has('FX_TRIPLANAR_HARDNESS'), f'the Automatic (UV) projection of a textured {target.lower()} effect shows no hardness')
        for field, mode, label in (('WRAP', 'MIRROR', 'Mirror'), ('WRAP', 'EXTEND', 'Clamp'), ('FILTERING', 'Closest', 'Closest'), ('FILTERING', 'Cubic', 'Cubic')):
            yield from menu(window, region, 'FX_' + field, f'SET_FX{field}.{mode}')
            effect, _ = check_sampling(uid, target)
            check(getattr(effect, field.lower()) == mode and control('FX_' + field).text == label, f'the {target.lower()} effect {field.lower()} dropdown picks {label}')

        yield from menu(window, region, 'FX_PROJECTION', 'SET_FXPROJECTION.TRIPLANAR')
        effect, found = check_sampling(uid, target)
        check(effect.triplanar_blend == numpy.float32(TRIPLANAR_BLEND) and all(node.projection == 'BOX' and node.projection_blend == effect.triplanar_blend for node in found),
              f'a tri-planar {target.lower()} effect starts at the previous fixed blend {TRIPLANAR_BLEND}')
        yield from reveal(window, region, 'FX_TRIPLANAR_HARDNESS')
        check(control('FX_TRIPLANAR_HARDNESS').label == 'Hardness' and control('FX_TRIPLANAR_HARDNESS').text == '0.80',
              f'the tri-planar {target.lower()} effect shows its Hardness slider at the default 0.80')
        for fx in (.95, .4):
            yield from slide(window, region, 'FX_TRIPLANAR_HARDNESS', fx)
            effect, found = check_sampling(uid, target)
            check(abs((1.0 - effect.triplanar_blend) - fx) < .05 and all(node.projection_blend == effect.triplanar_blend for node in found)
                  and control('FX_TRIPLANAR_HARDNESS').text == f'{1.0 - effect.triplanar_blend:.2f}',
                  f'the {target.lower()} effect hardness {1.0 - effect.triplanar_blend:.2f} reaches the material')

    stored = [(effect.uid, effect.wrap, effect.filtering, effect.projection, effect.triplanar_blend) for effect in find_layer(data, layer_uid).effects]
    saved_file = scratch / 'effect_sampling.blend'
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
    effects = find_layer(data, layer_uid).effects
    check([(effect.uid, effect.wrap, effect.filtering, effect.projection, effect.triplanar_blend) for effect in effects] == stored,
          'the reopened file keeps every effect wrap, filtering, and hardness')
    for effect in effects:
        found = effect_nodes(data, effect)
        check(found and all((node.extension, node.interpolation, node.projection_blend) == (effect.wrap, effect.filtering, effect.triplanar_blend) for node in found),
              f'the reopened {effect.target.lower()} effect rebuilds with its saved sampling and hardness')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI EFFECT SAMPLING CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI effect sampling test')
