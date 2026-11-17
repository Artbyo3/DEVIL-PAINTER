import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor
from devil_painter.meshmaps import id_color
from tools.workspace import prepare_scratch

TIMEOUT = 600
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


def keys(prefix):
    return [item.key for item in editor._active.workspace.controls if item.key.startswith(prefix)]


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5, **modifiers):
    press(window, kind, *spot(region, key, fx, fy), **modifiers)


def pixels(image):
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    return values.reshape(-1, 4)


def dominant(values, count):
    covered = numpy.round(values[values[:, 3] > .5][:, :3], 2)
    colors, counts = numpy.unique(covered, axis=0, return_counts=True)
    order = numpy.argsort(-counts)[:count]
    return colors[order], counts[order] / len(covered)


def near(color, target):
    return float(numpy.abs(numpy.asarray(color) - numpy.asarray(target[:3])).max()) < .03


def sphere(name, radius, materials):
    import bmesh
    mesh = bpy.data.meshes.new(name)
    shape = bmesh.new()
    bmesh.ops.create_uvsphere(shape, u_segments=48, v_segments=24, radius=radius)
    for face in shape.faces:
        face.smooth = True
    shape.to_mesh(mesh)
    shape.free()
    for material in materials:
        mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = 1 if polygon.center.z > 0 else 0
    item = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(item)
    return item


def open_card(window, region):
    if not has('BAKE_RUN'):
        click(window, region, 'BAKE')
        yield 0.4
    check(has('BAKE_RUN'), 'the bake card is open')


def toggle_maps(window, region, wanted):
    yield from open_card(window, region)
    for key in keys('BAKEMAP.'):
        if control(key).active != (key.removeprefix('BAKEMAP.') in wanted):
            click(window, region, key)
            yield 0.1
    check({key.removeprefix('BAKEMAP.') for key in keys('BAKEMAP.') if control(key).active} == set(wanted), f'the bake card selects {sorted(wanted)}')


def choose(window, region, opener, item):
    yield from open_card(window, region)
    click(window, region, opener)
    yield 0.3
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield 0.4


def bake(window, region, wait=2.5):
    yield from open_card(window, region)
    click(window, region, 'BAKE_RUN')
    yield wait


def journey():
    prepare_scratch()
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    cube = bpy.data.objects['Cube']
    cube.name = 'Crate_low'
    mesh = cube.data
    colors = mesh.color_attributes.new('Paint', 'BYTE_COLOR', 'CORNER')
    for polygon in mesh.polygons:
        for loop in polygon.loop_indices:
            colors.data[loop].color = (1.0, 0.0, 0.0, 1.0) if polygon.normal.z > .5 else (0.0, 0.0, 1.0, 1.0)
    mesh.color_attributes.render_color_index = mesh.color_attributes.active_color_index = 0
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.6
    click(window, region, 'RES.0.1024')
    yield 0.2
    click(window, region, 'START')
    yield 2.0
    data = cube.devil_painter.sets[0]

    yield from open_card(window, region)
    check(all(has(key) for key in ('BAKEMAP.normal', 'BAKEMAP.height', 'BAKE_ID', 'BAKE_SAMPLES', 'BAKE_MATCH', 'BAKE_SOURCE', 'BAKE_CAGE',
                                   'BAKE_EXTRUSION', 'BAKE_AUTO')), 'the bake card offers every map and bake setting')
    check('needs high-poly' in control('BAKEMAP.height').label and 'needs' not in control('BAKEMAP.normal').label,
          'height asks for a high-poly while normal also bakes from the mesh itself')
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield 0.2
    check(data.bake_samples <= 6, 'the samples slider lowers the bake quality')

    yield from toggle_maps(window, region, {'normal', 'height'})
    yield from bake(window, region)
    tangent = pixels(data.maps['normal'].image)
    covered = tangent[tangent[:, 3] > .5]
    check(numpy.median(covered[:, 2]) > .95 and (covered[:, 2] < .9).mean() > .01,
          'with no high-poly the normal map bakes from the mesh itself, flat faces with rounded edges')
    check('height' not in data.maps and 'Baked 1' in editor._active.message, 'height is skipped without a high-poly source')
    normal_map = next(node for node in data.material.node_tree.nodes if node.type == 'NORMAL_MAP')
    check(normal_map.inputs['Color'].links[0].from_node.type == 'VECT_MATH', 'the self-baked normal blends into the material normal')

    yield from toggle_maps(window, region, {'id'})
    yield from choose(window, region, 'BAKE_ID', 'SET_BAKE_ID.VERTEX')
    check(data.bake_id == 'VERTEX', 'the ID dropdown picks vertex colors')
    yield from bake(window, region)
    found, share = dominant(pixels(data.maps['id'].image), 2)
    check(len(found) == 2 and min(share) > .1 and {tuple(numpy.round(color)) for color in found} == {(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)},
          'the ID map colors the mesh by its vertex colors')
    yield from choose(window, region, 'BAKE_ID', 'SET_BAKE_ID.OBJECT')
    yield from bake(window, region)
    found, share = dominant(pixels(data.maps['id'].image), 1)
    check(share[0] > .95 and near(found[0], id_color('Crate_low')), 'the ID map colors the mesh by object')

    red, blue = bpy.data.materials.new('Painted red'), bpy.data.materials.new('Painted blue')
    high = sphere('Crate_high', 1.08, (red, blue))
    cage = bpy.data.objects.new('Crate_cage', mesh.copy())
    cage.scale = (1.35, 1.35, 1.35)
    bpy.context.scene.collection.objects.link(cage)
    high.hide_set(True)
    cage.hide_set(True)
    yield 0.3
    yield from open_card(window, region)
    click(window, region, 'BAKE_MATCH')
    yield 0.4
    check(data.bake_match and has('BAKE_MATCHED') and 'Crate_high' in control('BAKE_MATCHED').label
          and 'Crate_cage' in control('BAKE_MATCHED_CAGE').label and not has('BAKE_SOURCE'),
          'Match by name pairs Crate_low with Crate_high and Crate_cage')
    yield from choose(window, region, 'BAKE_ID', 'SET_BAKE_ID.MATERIAL')
    yield from toggle_maps(window, region, {'normal', 'height', 'id'})
    yield from bake(window, region, 5.0)
    check('Baked 3' in editor._active.message, 'normal, height, and ID bake from the matched high-poly')
    tangent = pixels(data.maps['normal'].image)
    covered = tangent[tangent[:, 3] > .5]
    check(numpy.median(covered[:, 2]) > .8 and covered[:, 0].std() > .02, 'the normal map bakes the high-poly sphere in tangent space')
    found, share = dominant(pixels(data.maps['id'].image), 2)
    check(len(found) == 2 and min(share) > .2 and all(near(color, id_color('Painted red')) or near(color, id_color('Painted blue')) for color in found),
          'the ID map colors the high-poly by its materials')
    height = pixels(data.maps['height'].image)
    values = height[height[:, 3] > .5][:, 0]
    check(values.max() > .6 and values.min() < .4, 'the height map records where the high-poly rises above and sinks below the low-poly')
    check(high.hide_get() and cage.hide_get() and [slot.material for slot in high.material_slots] == [red, blue]
          and not any(item.name.startswith('DP Bake source') for item in bpy.data.materials),
          'baking restores the hidden high-poly and its materials')
    yield from open_card(window, region)
    check(control('BAKETHUMB.height').preview == data.maps['height'].image, 'the bake card shows the height thumbnail')

    click(window, region, 'BAKE_MATCH')
    yield 0.3
    yield from choose(window, region, 'BAKE_SOURCE', 'SET_SOURCE.Crate_high')
    yield from choose(window, region, 'BAKE_CAGE', 'SET_CAGE.Crate_high')
    check(data.bake_source == high and data.bake_cage == high, 'the high-poly and cage dropdowns pick meshes by hand')
    yield from toggle_maps(window, region, {'normal'})
    yield from bake(window, region)
    check(editor._active.message.startswith('Bake failed'), 'a cage that does not match the low-poly reaches the baker and is reported')
    yield from choose(window, region, 'BAKE_CAGE', 'SET_CAGE.Crate_cage')
    yield from bake(window, region)
    check(data.bake_cage == cage and 'Baked 1' in editor._active.message, 'the hand-picked cage bakes')
    yield from open_card(window, region)
    rect = control('BAKE_EXTRUSION').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .2, region.y + rect.y + rect.h / 2)
    yield 0.2
    check(abs(data.bake_extrusion - .1) < .02, 'the ray distance slider sets how far rays search')

    yield from toggle_maps(window, region, {'normal', 'height', 'id'})
    click(window, region, 'BAKE_AUTO')
    yield 0.3
    check(data.bake_auto and control('BAKE_AUTO').active, 'automatic rebaking turns on')
    yield 4.0
    before = pixels(data.maps['height'].image).copy()
    signature = data.bake_signature
    high.scale = (1.06, 1.06, 1.06)
    yield 5.0
    after = pixels(data.maps['height'].image)
    check(data.bake_signature != signature and numpy.abs(after - before).max() > .02 and editor._active.message.startswith('Rebaked'),
          'moving the high-poly rebakes the baked maps automatically')
    yield from choose(window, region, 'BAKE_ID', 'SET_BAKE_ID.OBJECT')
    yield 5.0
    found, share = dominant(pixels(data.maps['id'].image), 1)
    check(share[0] > .9 and near(found[0], id_color('Crate_high')), 'changing the ID setting rebakes the ID map from the high-poly object')
    stable = data.bake_signature
    yield 2.0
    check(data.bake_signature == stable, 'nothing rebakes while settings and meshes stay the same')
    yield from open_card(window, region)
    click(window, region, 'BAKE_AUTO')
    yield 0.3
    check(not data.bake_auto, 'automatic rebaking turns off')

    press(window, 'ESC', *middle)
    yield 0.3
    check(has('MAP.height') and control('MAP.height').preview == data.maps['height'].image, 'the mesh maps panel shows the height thumbnail')
    click(window, region, 'MAP.height')
    yield 0.6
    check(data.solo == 'map:height' and control('VIEW').text == 'Height', 'clicking the height thumbnail views it on the model')
    click(window, region, 'VIEW')
    yield 0.3
    click(window, region, 'SOLO.')
    yield 0.5

    click(window, region, 'CLOSE')
    yield 0.6
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI BAKING CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI baking test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0, persistent=True)
