import json
from pathlib import Path
import sys
import bpy
import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import api
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
uid = api.add_fill(cube, json.dumps(gold))
records = api.layers(cube)
check(records[-1]['uid'] == uid and records[-1]['name'] == 'Gold' and json.loads(json.dumps(records)) == records,
      'add_fill() takes a JSON material and layers() returns JSON-ready records')
api.set_channel(cube, uid, 'roughness', .62)
check(abs(api.layers(cube)[-1]['channels']['roughness'][0] - .62) < 1e-6, 'set_channel() edits a channel value')
api.set_generator(cube, uid, generator='EDGE_WEAR', gen_level=.3)
check(api.layers(cube)[-1]['generator'] == 'EDGE_WEAR', 'set_generator() masks a layer with a generator')
message = api.bake(cube, maps=('ao', 'curvature'))
check('Baked 2' in message and 'ao' in cube.devil_painter.sets[0].maps, 'bake() bakes mesh maps')
captured = json.loads(api.material_of(cube, uid))
check(captured['name'] == 'Gold' and abs(captured['slots']['roughness']['value'] - .62) < 1e-6, 'material_of() returns the layer as JSON content')
smart = json.loads(api.smart_materials())
folder = api.add_smart_material(cube, smart[0])
check(next(item for item in api.layers(cube) if item['uid'] == folder)['kind'] == 'FOLDER', 'add_smart_material() builds a smart material from JSON')
paint = api.add_paint(cube)
check(api.selected(cube) == paint and any(item['uid'] == paint and item['kind'] == 'PAINT' for item in api.layers(cube)), 'add_paint() adds a paint layer and selects it')
api.remove_layer(cube, paint)
check(all(item['uid'] != paint for item in api.layers(cube)), 'remove_layer() deletes a layer')
api.remove_layer(cube, folder)
api.set_generator(cube, uid, generator='NONE')
written = api.export(cube, export_dir)
check(written and all(Path(path).is_file() for path in written), 'export() writes the texture files and returns their paths')
base = next(path for path in written if 'BaseColor' in path or 'Base' in path)
pixels = png(base)
check(pixels[:, 0].max() > .9 and pixels[:, 2].max() < pixels[:, 0].max(), 'the exported base color is gold')
try:
    api.layers(bpy.data.objects.new('Empty', bpy.data.meshes.new('Empty')))
    check(False, 'an object without a project is refused')
except ValueError:
    check(True, 'an object without a project is refused with a clear error')
devil_painter.unregister()
print('ALL API CHECKS PASSED', bpy.app.version_string)
