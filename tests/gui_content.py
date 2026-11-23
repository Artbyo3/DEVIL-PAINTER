import sys
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, shelf, smart
from devil_painter.document import active_effect, active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, check, click, control, drag_slider, finish, has, keys, move, pixels, press, reveal, run_journey, set_hex, settle, slide, spot, type_text, viewport

CHANNELS = ('BaseColor', 'Roughness')


def png(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = pixels(image)
    side = image.size[0]
    bpy.data.images.remove(image)
    return values.reshape(side, side, 4)


def menu(window, region, opener, item):
    yield from reveal(window, region, opener)
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


def add_effect(window, region, target, kind):
    yield from menu(window, region, 'ADD_FX_' + target, f'NEW_FX.{target}.{kind}')


def face_pixel(cube, face, resolution):
    mesh = cube.data
    layer = mesh.uv_layers.active
    polygon = mesh.polygons[face]
    center = numpy.array([tuple(layer.data[loop].uv) for loop in polygon.loop_indices]).mean(axis=0) % 1.0
    return int(center[1] * resolution), int(center[0] * resolution)


def stroke(window, region):
    x, y = region.x + region.width * .45, region.y + region.height * .5
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 13):
        move(window, x + step * 6, y + step * 3)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 72), y=int(y + 36))


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'content_export'
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
    top = max(cube.data.polygons, key=lambda polygon: polygon.normal.z).index
    bottom = min(cube.data.polygons, key=lambda polygon: polygon.normal.z).index
    top_pixel, bottom_pixel = face_pixel(cube, top, data.resolution), face_pixel(cube, bottom, data.resolution)

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
        return {name: png(export_dir / f'Cube_Material_{name}.png')[..., :3] for name in CHANNELS}

    def change(first, second):
        return {name: round(float(numpy.abs(first[name] - second[name]).mean()), 4) for name in CHANNELS}

    click(window, region, 'BAKE')
    yield from settle()
    for key in keys('BAKEMAP.'):
        if control(key).active != (key == 'BAKEMAP.world_normal'):
            click(window, region, key)
            yield from settle()
    drag_slider(window, region, 'BAKE_SAMPLES', .03)
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    check('world_normal' in data.maps and data.maps['world_normal'].image is not None, 'the bake card bakes the world normal map')

    click(window, region, 'ADD_FILL')
    yield from settle()
    layer_uid = active_layer(data).uid

    def layer():
        return find_layer(data, layer_uid)

    plain = yield from exported()
    yield from reveal(window, region, 'ADD_FX_CONTENT')
    click(window, region, 'ADD_FX_CONTENT')
    yield from settle()
    offered = [key.removeprefix('NEW_FX.CONTENT.') for key in keys('NEW_FX.CONTENT.')]
    check(offered == ['PAINT', 'FILL', 'LEVELS', 'FILTER', 'GENERATOR'], f'the content effect menu offers {offered}')
    click(window, region, 'NEW_FX.CONTENT.FILL')
    yield from settle()
    fill = active_effect(data)
    fill_uid = fill.uid
    check((fill.kind, fill.target, fill.blend) == ('FILL', 'CONTENT', 'MIX') and has('FX_BLEND') and has('FX_SOURCE'),
          'the content effect menu adds a Fill content effect that replaces the content below it by default and shows its blend')
    yield from menu(window, region, 'FX_SOURCE', 'SET_FXSOURCE.VALUE')
    check(has('FXCOLOR.color') and has('FX_value'), 'a plain-value Fill content effect shows its color and value')
    yield from set_hex(window, region, 'FXCOLOR.color', '#FF0000')
    yield from slide(window, region, 'FX_value', .9)
    filled = yield from exported()
    check(filled['BaseColor'][top_pixel][0] > .95 and filled['BaseColor'][top_pixel][1] < .05 and abs(filled['Roughness'][top_pixel][0] - layer().effects[0].value) < .02,
          'the Fill content effect puts its color in base color and its value in roughness')
    fill_change = change(plain, filled)

    yield from menu(window, region, 'FX_SOURCE', 'SET_FXPATTERN.CHECKER')
    check(has('FXCOLOR.color') and has('FXCOLOR.color_b') and has('FX_PROJECTION'), 'a pattern Fill content effect shows both pattern colors')
    patterned = yield from exported()
    pattern_spread = round(float(patterned['Roughness'][..., 0].std()), 4)
    check(pattern_spread > .1, f'a pattern Fill content effect writes the pattern into the channels (roughness spread {pattern_spread})')
    yield from menu(window, region, 'FX_SOURCE', 'SET_FXSOURCE.VALUE')

    yield from add_effect(window, region, 'CONTENT', 'GENERATOR')
    generator = active_effect(data)
    generator_uid = generator.uid
    check((generator.kind, generator.target, generator.blend) == ('GENERATOR', 'CONTENT', 'MIX') and has('GENERATOR'),
          'the content effect menu adds a Generator content effect')
    yield from menu(window, region, 'GENERATOR', 'SET_GENERATOR.TOP')
    for key in ('GEN_LEVEL', 'GEN_WEIGHT', 'GEN_BREAKUP'):
        yield from reveal(window, region, key)
    yield from slide(window, region, 'GEN_NOISE', 0.0)
    check(f'{layer_uid}.{generator_uid}.gen.range' in data.material.node_tree.nodes, 'the Generator content effect builds its generator nodes once for the layer')
    generated = yield from exported()
    top_bottom = round(float(generated['Roughness'][top_pixel][0] - generated['Roughness'][bottom_pixel][0]), 4)
    check(generated['Roughness'][top_pixel][0] > .9 and generated['Roughness'][bottom_pixel][0] < .1,
          f'the Top surfaces Generator drives the content: bright on top, dark underneath (difference {top_bottom})')
    generator_change = change(filled, generated)

    yield from menu(window, region, 'GEN_BREAKUP', 'SET_BREAKUP.STRIPES')
    yield from slide(window, region, 'GEN_NOISE', .6)
    check(layer().effects[1].gen_breakup == 'STRIPES', 'the Generator content effect takes its own breakup texture')
    broken = yield from exported()
    breakup_change = change(generated, broken)
    check(breakup_change['Roughness'] > .01, f'the breakup changes the generated content ({breakup_change})')
    yield from slide(window, region, 'GEN_NOISE', 0.0)

    yield from reveal(window, region, 'FX_DOWN')
    click(window, region, 'FX_DOWN')
    yield from settle()
    check([effect.uid for effect in layer().effects] == [generator_uid, fill_uid], 'moving the Generator down puts it under the Fill in the content stack')
    reordered = yield from exported()
    check(abs(reordered['Roughness'][top_pixel][0] - reordered['Roughness'][bottom_pixel][0]) < .02 and reordered['BaseColor'][bottom_pixel][0] > .95,
          'with the Fill on top the Fill covers the generated content')
    order_change = change(generated, reordered)
    click(window, region, 'FX_UP')
    yield from settle()
    check([effect.uid for effect in layer().effects] == [fill_uid, generator_uid], 'moving the Generator up restores the order')

    yield from menu(window, region, 'FX_BLEND', 'SET_FXBLEND.MULTIPLY')
    yield from slide(window, region, 'FX_opacity', .5)
    blended = yield from exported()
    expected = layer().effects[0].value * (1 - layer().effects[1].opacity + layer().effects[1].opacity * generated['Roughness'][bottom_pixel][0])
    check(abs(blended['Roughness'][bottom_pixel][0] - expected) < .03 and abs(blended['Roughness'][top_pixel][0] - layer().effects[0].value) < .03,
          f'the Generator multiplies the Fill at half opacity (bottom {blended["Roughness"][bottom_pixel][0]:.3f}, expected {expected:.3f})')
    blend_change = change(generated, blended)

    yield from add_effect(window, region, 'CONTENT', 'PAINT')
    paint = active_effect(data)
    paint_uid = paint.uid
    check((paint.kind, paint.target, paint.blend) == ('PAINT', 'CONTENT', 'MIX') and paint.image is not None and has('FX_BLEND')
          and bpy.context.scene.tool_settings.image_paint.canvas == paint.image, 'the content effect menu adds a Paint content effect and the brush paints into it')
    click(window, region, 'BRUSH_COLOR')
    yield from settle()
    click(window, region, 'COLOR_HEX')
    yield from settle()
    type_text(window, '#00FF00', *spot(region, 'COLOR_HEX'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()
    stroke(window, region)
    yield from settle()
    check(pixels(paint.image)[:, 3].max() > .5, 'a brush stroke in the viewport lands on the Paint content effect')
    painted = yield from exported()
    green = (painted['BaseColor'][..., 1] > .9) & (painted['BaseColor'][..., 0] < .1)
    paint_change = change(blended, painted)
    check(int(green.sum()) > 50 and paint_change['Roughness'] > 0.0, f'the painted stroke shows in base color and roughness ({int(green.sum())} green pixels)')

    yield from reveal(window, region, f'FXEYE_{layer_uid}.{paint_uid}', 'LAYERS')
    click(window, region, f'FXEYE_{layer_uid}.{paint_uid}')
    yield from settle()
    hidden = yield from exported()
    check(all(numpy.array_equal(hidden[name], blended[name]) for name in CHANNELS), 'hiding the Paint content effect restores the exact output below it')
    click(window, region, f'FXEYE_{layer_uid}.{paint_uid}')
    yield from settle()

    yield from reveal(window, region, 'ROW_' + layer_uid, 'LAYERS')
    click(window, region, 'ROW_' + layer_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'SAVE_MATERIAL')
    yield from settle()
    saved = library.user_materials()[-1]
    check([(entry['kind'], entry['target']) for entry in saved['effects']] == [('GENERATOR', 'CONTENT')],
          'saving the layer as a material keeps its Generator in the content stack')
    yield from reveal(window, region, 'ROW_' + layer_uid, 'LAYERS')
    click(window, region, 'ROW_' + layer_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'SAVE_SMART')
    yield from settle()
    stack = [(effect.kind, effect.target, effect.blend, round(effect.opacity, 3)) for effect in layer().effects]
    entry = smart.smart_materials()[-1]['layers'][0]
    check([(item['kind'], item['target'], item['blend'], round(item['opacity'], 3)) for item in entry['effects']] == stack and Path(entry['effects'][2]['image']).is_file(),
          'saving as a smart material keeps every content effect, its blend, opacity, and painted pixels')
    click(window, region, 'SHELF_TAB.SMART')
    yield from settle()
    user_tile = next(index for index, item in enumerate(shelf.items('SMART')) if item.user_index >= 0)
    click(window, region, f'ITEM.{user_tile}')
    yield from settle()
    folder = active_layer(data)
    copy = next(item for item in data.layers if item.parent == folder.uid)
    gap = float(numpy.abs(pixels(copy.effects[2].image) - pixels(layer().effects[2].image)).max())
    check(folder.kind == 'FOLDER' and [(effect.kind, effect.target, effect.blend, round(effect.opacity, 3)) for effect in copy.effects] == stack
          and gap < 1 / 255 + 1e-4, f'applying the smart material rebuilds the same content stack with the painted pixels ({gap:.4f})')
    folder.visible = False
    data.active_uid = layer_uid

    saved_file = scratch / 'content_effects.blend'
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
    check([(effect.kind, effect.target, effect.blend, round(effect.opacity, 3)) for effect in layer().effects] == stack
          and layer().effects[2].image.packed_file is not None, 'the saved file reopens with the same content stack and packed paint')
    reopened = yield from exported()
    gap = max(float(numpy.abs(reopened[name] - painted[name]).max()) for name in CHANNELS)
    check(gap == 0.0, f'the reopened file exports the same channels ({gap})')

    yield from reveal(window, region, f'FX_{layer_uid}.{paint_uid}', 'LAYERS')
    click(window, region, f'FX_{layer_uid}.{paint_uid}', fx=.6)
    yield from settle()
    yield from reveal(window, region, 'FX_DELETE')
    click(window, region, 'FX_DELETE')
    yield from settle()
    check(all(effect.uid != paint_uid for effect in layer().effects), 'deleting removes the Paint content effect')
    print('CONTENT EVIDENCE', dict(offered=offered, fill=fill_change, pattern_spread=pattern_spread, generator=generator_change, top_bottom=top_bottom,
                                   breakup=breakup_change, reorder=order_change, blend_opacity=blend_change, paint=paint_change, green_pixels=int(green.sum())))

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI CONTENT CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI content test')
