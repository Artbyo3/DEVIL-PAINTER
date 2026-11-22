import sys
from pathlib import Path
import bpy
import numpy

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import bakejob, editor
from devil_painter.document import map_extrusion, map_samples
from devil_painter.meshmaps import id_color
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, check, click, control, finish, has, keys, pixels, press, run_journey, settle, until, viewport


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
        yield from settle()
    check(has('BAKE_RUN'), 'the bake card is open')


def toggle_maps(window, region, wanted):
    yield from open_card(window, region)
    for key in keys('BAKEMAP.'):
        if control(key).active != (key.removeprefix('BAKEMAP.') in wanted):
            click(window, region, key)
            yield from settle()
    check({key.removeprefix('BAKEMAP.') for key in keys('BAKEMAP.') if control(key).active} == set(wanted), f'the bake card selects {sorted(wanted)}')


def choose(window, region, opener, item):
    yield from open_card(window, region)
    click(window, region, opener)
    yield from settle()
    check(has(item), f'{opener} offers {item}')
    click(window, region, item)
    yield from settle()


def bake(window, region):
    yield from open_card(window, region)
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()


def journey():
    prepare_scratch()
    devil_painter.register()
    yield from settle()
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
    yield from settle()
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    data = cube.devil_painter.sets[0]

    yield from open_card(window, region)
    check(all(has(key) for key in ('BAKEMAP.normal', 'BAKEMAP.height', 'BAKE_SET.0', 'BAKE_ID', 'BAKE_SAMPLES', 'BAKE_RESOLUTION', 'BAKE_MATCH', 'BAKE_SOURCE', 'BAKE_CAGE',
                                   'BAKE_EXTRUSION', 'BAKE_AUTO')), 'the bake card offers every map and bake setting')
    check('needs high-poly' in control('BAKEMAP.height').label and 'needs' not in control('BAKEMAP.normal').label,
          'height asks for a high-poly while normal also bakes from the mesh itself')
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(data.bake_samples <= 6, 'the samples slider lowers the bake quality')

    yield from open_card(window, region)
    click(window, region, 'BAKE_RUN')
    yield from settle()
    check(bakejob.running() and has('BAKE_PROGRESS') and has('BAKE_CANCEL') and not has('BAKE_RUN') and control('BAKE').label.startswith('Baking'),
          'the bake runs in the background with progress and Cancel in the bake card')
    click(window, region, 'BAKE_CANCEL')
    yield from settle()
    check(not bakejob.running() and not any(item.image is not None for item in data.maps) and editor._active.message.startswith('Bake canceled')
          and has('BAKE_RUN'), 'Cancel stops the bake and leaves no mesh maps behind')

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
    yield from settle()
    yield from open_card(window, region)
    click(window, region, 'BAKE_MATCH')
    yield from settle()
    check(data.bake_match and has('BAKE_MATCHED') and 'Crate_high' in control('BAKE_MATCHED').label
          and 'Crate_cage' in control('BAKE_MATCHED_CAGE').label and not has('BAKE_SOURCE'),
          'Match by name pairs Crate_low with Crate_high and Crate_cage')
    yield from choose(window, region, 'BAKE_ID', 'SET_BAKE_ID.MATERIAL')
    yield from toggle_maps(window, region, {'normal', 'height', 'id'})
    yield from bake(window, region)
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
    yield from settle()
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
    yield from settle()
    check(abs(data.bake_extrusion - .1) < .02, 'the ray distance slider sets how far rays search')

    yield from toggle_maps(window, region, {'normal', 'height', 'id'})
    click(window, region, 'BAKE_AUTO')
    yield from settle()
    check(data.bake_auto and control('BAKE_AUTO').active, 'automatic rebaking turns on')
    yield from settle()
    before = pixels(data.maps['height'].image).copy()
    signature = data.bake_signature
    high.scale = (1.06, 1.06, 1.06)
    yield from until(lambda: data.bake_signature != signature, 'the automatic rebake after the high-poly moved')
    after = pixels(data.maps['height'].image)
    check(data.bake_signature != signature and numpy.abs(after - before).max() > .02 and editor._active.message.startswith('Rebaked'),
          'moving the high-poly rebakes the baked maps automatically')
    signature = data.bake_signature
    yield from choose(window, region, 'BAKE_ID', 'SET_BAKE_ID.OBJECT')
    yield from until(lambda: data.bake_signature != signature, 'the automatic rebake after the ID setting changed')
    found, share = dominant(pixels(data.maps['id'].image), 1)
    check(share[0] > .9 and near(found[0], id_color('Crate_high')), 'changing the ID setting rebakes the ID map from the high-poly object')
    stable = data.bake_signature
    yield from settle()
    check(data.bake_signature == stable, 'nothing rebakes while settings and meshes stay the same')
    yield from open_card(window, region)
    click(window, region, 'BAKE_AUTO')
    yield from settle()
    check(not data.bake_auto, 'automatic rebaking turns off')

    yield from open_card(window, region)
    check(all(has(key) for key in ('BAKE_SELECT.ao', 'BAKE_SELECT.curvature', 'BAKE_SELECT.thickness', 'BAKE_SELECT.normal', 'BAKE_SELECT.height', 'BAKE_SELECT.id'))
          and has('BAKE_AO_DISTANCE') and has('BAKE_AO_SPREAD') and has('BAKE_MAP_SAMPLES'),
          'the bake card shows per-map settings starting on ambient occlusion')
    rect = control('BAKE_MAP_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .5, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(map_samples(data, 'ao') != data.bake_samples and map_samples(data, 'thickness') == data.bake_samples
          and control('BAKE_SELECT.ao').label == 'Custom' and control('BAKE_MAP_SAMPLES_RESET').label == 'Reset',
          'per-map samples override only the selected map')
    click(window, region, 'BAKE_MAP_SAMPLES_RESET')
    yield from settle()
    check(map_samples(data, 'ao') == data.bake_samples and control('BAKE_MAP_SAMPLES_RESET').label == 'Shared',
          'Reset returns per-map samples to the shared value')
    rect = control('BAKE_AO_DISTANCE').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .4, region.y + rect.y + rect.h / 2)
    yield from settle()
    rect = control('BAKE_AO_SPREAD').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .45, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(data.bake_ao_distance > .5 and data.bake_ao_spread < 120.0 and control('BAKE_SELECT.ao').label == 'Custom',
          'AO distance and spread sliders update the ambient occlusion settings')

    click(window, region, 'BAKE_SELECT.curvature')
    yield from settle()
    check(has('BAKE_CURVATURE') and has('BAKE_MAP_SAMPLES') and not has('BAKE_MAP_EXTRUSION'),
          'curvature settings offer the curvature method and per-map samples')
    yield from toggle_maps(window, region, {'curvature'})
    yield from bake(window, region)
    curv_pixel = pixels(data.maps['curvature'].image).copy()
    yield from choose(window, region, 'BAKE_CURVATURE', 'SET_BAKE_CURVATURE.PER_VERTEX')
    check(data.bake_curvature == 'PER_VERTEX', 'curvature method switches to per-vertex')
    yield from open_card(window, region)
    check(not has('BAKE_MAP_SAMPLES'), 'per-vertex curvature hides the ray-traced samples slider')
    yield from bake(window, region)
    curv_vertex = pixels(data.maps['curvature'].image).copy()
    check(numpy.abs(curv_vertex - curv_pixel).max() > .05, 'per-vertex curvature produces a different map from per-pixel')
    yield from choose(window, region, 'BAKE_CURVATURE', 'SET_BAKE_CURVATURE.NORMAL')
    check(data.bake_curvature == 'NORMAL', 'curvature method switches to from-normal')
    yield from open_card(window, region)
    check(has('BAKE_MAP_SAMPLES') and has('BAKE_MAP_EXTRUSION'), 'from-normal curvature exposes samples and ray distance overrides')
    yield from bake(window, region)
    curv_normal = pixels(data.maps['curvature'].image)
    covered = curv_normal[curv_normal[:, 3] > .5][:, 0]
    check(covered.max() > .55 and numpy.abs(curv_normal - curv_vertex).max() > .05, 'from-normal curvature derives convexity from tangent-space normals')
    yield from choose(window, region, 'BAKE_CURVATURE', 'SET_BAKE_CURVATURE.PER_PIXEL')

    yield from open_card(window, region)
    click(window, region, 'BAKE_SELECT.thickness')
    yield from settle()
    check(has('BAKE_THICKNESS_RANGE'), 'thickness settings expose thickness range')
    yield from toggle_maps(window, region, {'thickness'})
    rect = control('BAKE_THICKNESS_RANGE').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield from settle()
    yield from bake(window, region)
    thick_low = pixels(data.maps['thickness'].image)
    low_mean = float(thick_low[thick_low[:, 3] > .5][:, 0].mean())
    yield from open_card(window, region)
    rect = control('BAKE_THICKNESS_RANGE').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .9, region.y + rect.y + rect.h / 2)
    yield from settle()
    yield from bake(window, region)
    thick_high = pixels(data.maps['thickness'].image)
    high_mean = float(thick_high[thick_high[:, 3] > .5][:, 0].mean())
    check(high_mean > low_mean + .05, 'a larger thickness range detects deeper opposite walls')

    yield from open_card(window, region)
    click(window, region, 'BAKE_SELECT.height')
    yield from settle()
    check(has('BAKE_MAP_EXTRUSION') and has('BAKE_MAP_EXTRUSION_RESET'), 'height settings expose per-map ray distance')
    rect = control('BAKE_MAP_EXTRUSION').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .7, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(abs(map_extrusion(data, 'height') - data.bake_extrusion) > .1 and map_extrusion(data, 'normal') == data.bake_extrusion,
          'per-map ray distance overrides only the selected map')
    click(window, region, 'BAKE_MAP_EXTRUSION_RESET')
    yield from settle()
    check(map_extrusion(data, 'height') == data.bake_extrusion, 'Reset returns per-map ray distance to the shared value')

    yield from choose(window, region, 'BAKE_RESOLUTION', 'SET_BAKE_RESOLUTION.512')
    check(data.bake_resolution == 512, 'the resolution dropdown picks a separate bake resolution')
    yield from toggle_maps(window, region, {'position'})
    yield from bake(window, region)
    check(tuple(data.maps['position'].image.size) == (512, 512) and data.resolution == 1024 and tuple(data.layers[0].image.size) == (1024, 1024),
          'baking writes mesh maps at the bake resolution without changing the texture set resolution')
    yield from choose(window, region, 'BAKE_RESOLUTION', 'SET_BAKE_RESOLUTION.0')
    check(data.bake_resolution == 0, 'the resolution dropdown returns to the texture set size')
    yield from bake(window, region)
    check(tuple(data.maps['position'].image.size) == (1024, 1024), 'returning to texture set size rebakes at the texture set resolution')

    press(window, 'ESC', *middle)
    yield from settle()
    check(has('MAP.height') and control('MAP.height').preview == data.maps['height'].image, 'the mesh maps panel shows the height thumbnail')
    click(window, region, 'MAP.height')
    yield from settle()
    check(data.solo == 'map:height' and control('VIEW').text == 'Height', 'clicking the height thumbnail views it on the model')
    click(window, region, 'VIEW')
    yield from settle()
    click(window, region, 'SOLO.')
    yield from settle()

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI BAKING CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI baking test')
