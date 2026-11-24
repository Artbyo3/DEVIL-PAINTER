import json
from pathlib import Path
import shutil
import sys
import bpy
import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import api, compositing, strokes
from devil_painter.actions import new_effect
from devil_painter.document import find_layer
from tools.workspace import prepare_scratch


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def png(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    bpy.data.images.remove(image)
    return values.reshape(-1, 4)


export_dir = prepare_scratch() / 'api_export'
devil_painter.register()
cube = bpy.data.objects['Cube']
check(set(api.__all__) <= set(dir(api)) and {'start', 'add_fill', 'bake', 'export', 'layers'} <= set(api.__all__), 'the Python API exports its functions')
sets = api.start(cube, resolution=256)
check(len(sets) == 1 and sets[0]['resolution'] == 256 and 'base_color' in sets[0]['channels'], 'start() creates a project and reports its texture sets')
catalog = json.loads(api.materials())
gold = next(item for item in catalog if item['name'] == 'Gold')
check(len(catalog) >= 13, 'materials() lists the material library as JSON')
from devil_painter import library
imported = {item['name']: set(item['slots']) for item in library.texture_sets(
    [Path('Cloth') / f'Cloth_{word}.png' for word in ('albedo', 'normal', 'specular', 'glossiness', 'displacement', 'anisotropy_level', 'anisotropy_angle',
                                                       'transmission', 'scattering', 'sheen', 'coat', 'ior')])}
check(imported.get('Cloth', set()) >= {'base_color', 'normal', 'specular', 'glossiness', 'displacement', 'anisotropy_level', 'anisotropy_angle',
                                       'transmission', 'scattering', 'sheen', 'coat', 'ior'}, 'a texture set with the PBR channel files fills every channel on import')
uid = api.add_fill(cube, json.dumps(gold))
records = api.layers(cube)
check(records[-1]['uid'] == uid and records[-1]['name'] == 'Gold' and json.loads(json.dumps(records)) == records,
      'add_fill() takes a JSON material and layers() returns JSON-ready records')
api.set_channel(cube, uid, 'roughness', .62)
check(abs(api.layers(cube)[-1]['channels']['roughness'][0] - .62) < 1e-6, 'set_channel() edits a channel value')
masked = api.add_fill(cube, json.dumps(gold))
api.add_generator(cube, masked, generator='EDGE_WEAR', gen_level=.3)
api.add_generator(cube, masked, generator='DIRT')
check(next(item for item in api.layers(cube) if item['uid'] == masked)['generators'] == ['EDGE_WEAR', 'DIRT'], 'add_generator() stacks generators in the mask of a layer')
message = api.bake(cube, maps=('ao', 'curvature'))
check('Baked 2' in message and 'ao' in cube.devil_painter.sets[0].maps, 'bake() bakes mesh maps')
captured = json.loads(api.material_of(cube, uid))
check(captured['name'] == 'Gold' and abs(captured['slots']['roughness']['value'] - .62) < 1e-6, 'material_of() returns the layer as JSON content')
smart = json.loads(api.smart_materials())
folder = api.add_smart_material(cube, smart[0])
children = [item for item in api.layers(cube) if item['parent'] == folder]
check(next(item for item in api.layers(cube) if item['uid'] == folder)['kind'] == 'FOLDER'
      and len(children) == len(smart[0]['layers']), 'add_smart_material() builds a smart material from JSON')
paint = api.add_paint(cube)
check(api.selected(cube) == paint and any(item['uid'] == paint and item['kind'] == 'PAINT' for item in api.layers(cube)), 'add_paint() adds a paint layer and selects it')
api.remove_layer(cube, paint)
check(all(item['uid'] != paint for item in api.layers(cube)), 'remove_layer() deletes a layer')
api.remove_layer(cube, folder)
check(all(item['uid'] != folder and item['parent'] != folder for item in api.layers(cube))
      and {item['uid'] for item in api.layers(cube)} == {records[0]['uid'], uid, masked},
      'remove_layer() deletes a smart-material folder and every layer inside it')
api.remove_layer(cube, masked)
written = api.export(cube, export_dir)
check(written and all(Path(path).is_file() for path in written), 'export() writes the texture files and returns their paths')
base = next(path for path in written if 'BaseColor' in path or 'Base' in path)
pixels = png(base)
check(pixels[:, 0].max() > .9 and pixels[:, 2].max() < pixels[:, 0].max(), 'the exported base color is gold')
body = cube.devil_painter.sets[0]
body.isolate = body.layers[0].uid
isolated = png(next(path for path in api.export(cube, export_dir) if path == base))
body.isolate = ''
check(numpy.abs(isolated - pixels).max() < 1e-6, 'showing only one layer leaves exported textures unchanged')
mesh = cube.data.copy()
mesh.materials.clear()
mesh.materials.append(bpy.data.materials.new('Body'))
mesh.materials.append(bpy.data.materials.new('Trim'))
for index, polygon in enumerate(mesh.polygons):
    polygon.material_index = index % 2
two = bpy.data.objects.new('Two', mesh)
bpy.context.scene.collection.objects.link(two)
bpy.context.view_layer.objects.active = two
check(len(api.start(two, resolution=64)) == 2, 'a mesh with two materials starts with two texture sets')
clash_dir = prepare_scratch() / 'api_export_clash'
shutil.rmtree(clash_dir, ignore_errors=True)
two.devil_painter.export_pattern = '{mesh}_{output}'
try:
    api.export(two, clash_dir)
    check(False, 'an export whose names collide is refused')
except ValueError as refusal:
    check('{set}' in str(refusal) and 'Body' in str(refusal) and 'Trim' in str(refusal), f'an export whose file names collide is refused with a clear message: {refusal}')
check(not clash_dir.exists() or not any(clash_dir.iterdir()), 'the refused export writes no files')
two.devil_painter.export_pattern = '{mesh}_{set}_{output}'
written = api.export(two, clash_dir)
check(len(written) == len({path.lower() for path in written}) and all(Path(path).is_file() for path in written) and len(list(clash_dir.iterdir())) == len(written),
      f'with {{set}} in the pattern every texture set exports its own {len(written)} files')
two.devil_painter.sets[1].bake = False
check('Baked 1' in api.bake(two, maps=('position',)) and 'position' in two.devil_painter.sets[0].maps
      and 'position' not in two.devil_painter.sets[1].maps, 'bake() covers only the texture sets enabled for baking')
two.devil_painter.sets[0].bake = False
check('Pick at least one texture set' in api.bake(two, maps=('position',)), 'bake() asks for a texture set when none are enabled')
two.devil_painter.sets[0].bake = two.devil_painter.sets[1].bake = True
two.devil_painter.sets[0].bake_resolution = 128
check('Baked 1' in api.bake(two, maps=('ao',)) and tuple(two.devil_painter.sets[0].maps['ao'].image.size) == (128, 128)
      and tuple(two.devil_painter.sets[1].maps['ao'].image.size) == (128, 128) and two.devil_painter.sets[0].resolution == 64,
      'bake_resolution bakes mesh maps separately from the texture set resolution')
check(any('AO' in path for path in api.export(two, clash_dir, template='Standard PBR')),
      'exporting still reads baked AO whose resolution differs from the texture set')
two.devil_painter.sets[0].bake_resolution = 0
api.add_paint(two, set_index=1)
check(two.devil_painter.active_set == 1, 'an edit on another texture set switches to that set')
body_layer = api.add_paint(two, set_index=0)
trim_layer = api.add_paint(two, set_index=1)
api.layers(two, set_index=0)
api.selected(two, 0)
api.material_of(two, body_layer, 0)
check(two.devil_painter.active_set == 1, 'read-only API calls on another texture set leave the active set alone')
trim_faces = numpy.empty(len(two.data.polygons), dtype=bool)
two.data.polygons.foreach_get('select', trim_faces)
trim_slots = numpy.array([polygon.material_index for polygon in two.data.polygons]) == two.devil_painter.sets[1].slot
check(numpy.array_equal(trim_faces, trim_slots), 'face masking still belongs to the active texture set after read-only API calls')
api.set_channel(two, body_layer, 'roughness', .4, set_index=0)
body_faces = numpy.empty(len(two.data.polygons), dtype=bool)
two.data.polygons.foreach_get('select', body_faces)
body_slots = numpy.array([polygon.material_index for polygon in two.data.polygons]) == two.devil_painter.sets[0].slot
check(two.devil_painter.active_set == 0 and numpy.array_equal(body_faces, body_slots),
      'an edit on another texture set switches face masking to that set the way the UI does')
check(api.selected(two, 1) == trim_layer and api.selected(two, 0) == body_layer, 'each texture set keeps its own selected layer')
two_body = two.devil_painter.sets[0]
under_uid = api.add_paint(two, set_index=0)
blurred_uid = api.add_fill(two, json.dumps(gold), set_index=0)
new_effect(two_body, find_layer(two_body, blurred_uid), 'FILTER', 'CONTENT').filter = 'BLUR'
over_uid = api.add_paint(two, set_index=0)
fresh_stamp = compositing.below_stamp(two_body)
api.set_channel(two, over_uid, 'roughness', .3, set_index=0)
over_image = find_layer(two_body, over_uid).image
strokes.write(over_image, strokes.read(over_image))
check(compositing.below_stamp(two_body) == fresh_stamp, 'an edit and a stroke on a layer above a Blur keep the texture under the Blur fresh, so nothing rebakes')
under_image = find_layer(two_body, under_uid).image
strokes.write(under_image, strokes.read(under_image))
painted_stamp = compositing.below_stamp(two_body)
check(painted_stamp != fresh_stamp, 'a stroke on a layer under a Blur marks the texture under the Blur stale')
api.set_channel(two, blurred_uid, 'roughness', .3, set_index=0)
check(compositing.below_stamp(two_body) != painted_stamp, 'an edit on the blurred layer marks the texture under the Blur stale')
canvas = numpy.random.default_rng(3).random((1024, 1024, 4), dtype=numpy.float32)
ys, xs = numpy.ogrid[:1024, :1024]
dab = numpy.clip(1.0 - numpy.hypot(xs - 300, ys - 700) / 40, 0.0, 1.0).astype(numpy.float32)
whole = canvas + dab[..., None] * (strokes.box_blur(canvas, 6.0) - canvas)
local = canvas.copy()
strokes.blur_touched(local, dab, 6.0)
check(numpy.abs(local - whole).max() < 1e-4 and numpy.array_equal(local[dab == 0], canvas[dab == 0]),
      'the Blur brush blurs only around its stroke and matches a whole-image blur there')
try:
    api.layers(bpy.data.objects.new('Empty', bpy.data.meshes.new('Empty')))
    check(False, 'an object without a project is refused')
except ValueError:
    check(True, 'an object without a project is refused with a clear error')
devil_painter.unregister()
print('ALL API CHECKS PASSED', bpy.app.version_string)
