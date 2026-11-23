import sys
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
from devil_painter import editor, library, shelf
from devil_painter.document import active_layer, find_layer
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, check, click, context_menu, control, finish, has, keys, move, nodes, png, press, reveal, run_journey, select_row, settle, shown, spot, type_text, until, viewport


def generators(layer):
    return [effect.generator for effect in layer.effects if effect.kind == 'GENERATOR']


def labels():
    return {control(key).label: key for key in keys('ITEM.')}


def open_tab(window, region, tab):
    click(window, region, 'SHELF_TAB.' + tab)
    yield from settle()


def wait_preview(key):
    yield from until(lambda: has(key) and control(key).preview is not None, f'{key} to show its preview')
    return True


def drag_to(window, start, end, steps=10):
    move(window, *start)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(start[0]), y=int(start[1]))
    for step in range(1, steps + 1):
        move(window, start[0] + (end[0] - start[0]) * step / steps, start[1] + (end[1] - start[1]) * step / steps)
    yield from settle()


def release(window, end):
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(end[0]), y=int(end[1]))
    yield from settle()


def row_point(region, uid, fy):
    rect = control('ROW_' + uid).rect
    return region.x + rect.x + rect.w * .6, region.y + rect.y + rect.h * fy


def mesh_point(region, area, obj):
    view = area.spaces.active.region_3d
    direction = view.view_rotation @ Vector((0.0, 0.0, -1.0))
    face = min(range(len(obj.data.polygons)), key=lambda index: obj.data.polygons[index].normal.dot(direction))
    point = view3d_utils.location_3d_to_region_2d(region, view, obj.matrix_world @ obj.data.polygons[face].center)
    return region.x + point.x, region.y + point.y


def order(data):
    return [layer.uid for layer in data.layers]


def search(window, region, text):
    click(window, region, 'SHELF_SEARCH')
    yield from settle()
    type_text(window, text, *spot(region, 'SHELF_SEARCH'))
    yield from settle()
    move(window, region.x + region.width / 2, region.y + region.height / 2)
    yield from settle()


def write_library(folder):
    folder.mkdir(parents=True, exist_ok=True)
    image = bpy.data.images.new('rust_plate', 16, 16, alpha=True)
    image.pixels.foreach_set(numpy.tile(numpy.array((.6, .25, .1, 1.0), dtype=numpy.float32), 16 * 16))
    image.filepath_raw = str(folder / 'rust_plate.png')
    image.file_format = 'PNG'
    image.save()
    material = bpy.data.materials.new('Painted Metal')
    shader = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    shader.inputs['Roughness'].default_value = .33
    shader.inputs['Metallic'].default_value = 1.0
    node = material.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = image
    material.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
    bpy.data.libraries.write(str(folder / 'metals.blend'), {material})
    bpy.data.materials.remove(material)
    bpy.data.images.remove(image)


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    library._cache.clear()
    export_dir = scratch / 'shelf_export'
    library_dir = scratch / 'my_library'
    devil_painter.register()
    yield from settle()
    write_library(library_dir)
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
    click(window, region, 'EXPORT')
    yield from settle()
    click(window, region, 'EXPORT_DIR')
    yield from settle()
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield from settle()
    press(window, 'ESC', *middle)
    yield from settle()

    tabs = {key.removeprefix('SHELF_TAB.') for key in keys('SHELF_TAB.')}
    check({'MATERIALS', 'SMART', 'TEXTURES', 'PATTERNS', 'MASKS', 'GENERATORS', 'FILTERS', 'BRUSHES', 'ALPHAS', 'ENVIRONMENTS'} <= tabs,
          'the shelf browses materials, smart materials, textures, patterns, masks, generators, filters, brushes, alphas, and lighting')
    masks_tab = control('SHELF_TAB.MASKS')
    check(masks_tab.icon == 'MASK' and masks_tab.rect.w == masks_tab.rect.h
          and control('SHELF_TAB.GENERATORS').rect.x - (masks_tab.rect.x + masks_tab.rect.w)
          == control('SHELF_TAB.SMART').rect.x - (control('SHELF_TAB.MATERIALS').rect.x + control('SHELF_TAB.MATERIALS').rect.w),
          'the Masks tab is a square icon chip and the tabs after it close the gap')
    for tab in ('MATERIALS', 'SMART', 'MASKS', 'GENERATORS', 'FILTERS', 'PATTERNS', 'BRUSHES', 'ENVIRONMENTS'):
        yield from open_tab(window, region, tab)
        shown = yield from wait_preview('ITEM.0')
        check(len(keys('ITEM.')) > 0 and shown, f'the {tab.lower()} shelf shows previews')
    yield from open_tab(window, region, 'FILTERS')
    check(len(shelf.visible('FILTERS')) >= 60, 'the filters shelf lists the whole catalog')
    yield from open_tab(window, region, 'GENERATORS')
    check(len(shelf.visible('GENERATORS')) >= 21, 'the generators shelf lists every generator')

    yield from open_tab(window, region, 'MATERIALS')
    yield from search(window, region, 'gold')
    check(editor._active.state.shelf_query == 'gold' and list(labels()) == ['Gold'], 'typing in the search field filters the shelf by name')
    check(has('SAVE_SEARCH'), f'Save search appears {editor._active.state.shelf_query!r} {editor._active.state.text} {[k for k in keys("S")][:20]}')
    click(window, region, 'SAVE_SEARCH')
    yield from settle()
    check(has('SEARCH.0') and control('SEARCH.0').label == 'gold' and shelf.saved_searches(), 'Save search keeps the search as a chip')
    import json
    check(json.loads((library.library_root() / library.SETTINGS_FILE).read_text(encoding='utf-8'))['saved_searches'][0]['query'] == 'gold',
          'saved searches are stored in the library')
    click(window, region, 'SEARCH.0')
    yield from settle()
    check(editor._active.state.shelf_query == '' and len(labels()) > 5, 'clicking the active saved search clears it')
    click(window, region, 'SEARCH.0')
    yield from settle()
    check(list(labels()) == ['Gold'], 'clicking a saved search runs it again')
    click(window, region, 'SEARCH.0')
    yield from settle()
    click(window, region, 'SCOPE.MINE')
    yield from settle()
    builtin = {definition['name'] for definition in library.BUILTIN_MATERIALS}
    check(not builtin & set(labels()), 'the Mine filter hides the built-in materials')
    click(window, region, 'SCOPE.BUILTIN')
    yield from settle()
    check('Steel' in labels(), 'the Built-in filter shows the shipped materials')
    click(window, region, 'SCOPE.ALL')
    yield from settle()
    click(window, region, 'SEARCH.0', kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'DELETE_SEARCH.0')
    yield from settle()
    check(not shelf.saved_searches() and not has('SEARCH.0'), 'a saved search can be deleted')

    click(window, region, 'LIBRARIES')
    yield from settle()
    check(has('LIBRARY_NEW') and has('LIBRARY_BROWSE') and has('IMPORT_RESOURCES'), 'the libraries card adds folders and imports files')
    click(window, region, 'LIBRARY_NEW')
    yield from settle()
    type_text(window, str(library_dir), *spot(region, 'LIBRARY_NEW'))
    yield from settle()
    check(library.libraries() == [str(library_dir)] and has('LIBRARY.0'), 'typing a folder adds it as a library')
    press(window, 'ESC', *middle)
    yield from settle()
    click(window, region, 'SCOPE.MINE')
    yield from settle()
    check('Painted Metal' in labels(), 'the library .blend material appears in the shelf')
    shown = yield from wait_preview(labels()['Painted Metal'])
    check(shown, 'the .blend material gets a rendered preview')
    click(window, region, labels()['Painted Metal'])
    yield from settle()
    metal = active_layer(data)
    metal_uid = metal.uid
    check(metal.name == 'Painted Metal' and metal.slots['base_color'].source == 'IMAGE' and metal.slots['base_color'].image.name.startswith('rust_plate')
          and abs(metal.slots['roughness'].value - .33) < 1e-3 and metal.slots['metallic'].value == 1.0,
          'the .blend material becomes a fill layer with its texture and values')
    yield from open_tab(window, region, 'TEXTURES')
    check('rust_plate' in labels(), 'library images appear among the textures')
    click(window, region, 'LIBRARIES')
    yield from settle()
    click(window, region, 'LIB_REMOVE.0')
    yield from settle()
    check(not library.libraries(), 'a library folder can be removed')
    press(window, 'ESC', *middle)
    yield from settle()
    bpy.ops.devil_painter.import_textures('EXEC_DEFAULT', directory=str(library_dir), files=[dict(name='metals.blend'), dict(name='rust_plate.png')])
    yield from settle()
    library.rescan()
    yield from open_tab(window, region, 'MATERIALS')
    check('Painted Metal' in labels(), 'Import resources copies .blend files into the library so their materials stay')
    click(window, region, 'SCOPE.ALL')
    yield from settle()

    yield from open_tab(window, region, 'MATERIALS')
    click(window, region, 'ADD_PAINT')
    yield from settle()
    paint_uid = active_layer(data).uid
    before = order(data)
    start = spot(region, labels()['Steel'])
    end = row_point(region, metal_uid, .2)
    yield from drag_to(window, start, end)
    check(has('DRAG_GHOST') and control('DRAG_GHOST').label == 'Steel', 'dragging a material shows its preview under the pointer')
    check(has('DROP_LINE'), f'the stack shows where the material will land {editor._active.state.drop}')
    yield from release(window, end)
    steel = active_layer(data)
    steel_uid = steel.uid
    after = order(data)
    check(steel.name == 'Steel' and len(after) == len(before) + 1 and after.index(steel_uid) == after.index(metal_uid) - 1,
          f'dropping a material below a row creates a fill layer right under it {before} {after} {steel_uid} {editor._active.message}')
    check(not has('DRAG_GHOST'), 'the drag preview goes away after the drop')
    yield from reveal(window, region, 'VALUE.roughness')
    click(window, region, 'VALUE.roughness', fx=.8)
    yield from settle()
    check(abs(find_layer(data, steel_uid).slots['roughness'].value - .8) < .05, 'the dropped material is tuned with its sliders')
    yield from open_tab(window, region, 'MASKS')
    yield from drag_to(window, spot(region, labels()['Dirt']), row_point(region, paint_uid, .5))
    check(has('DROP_INTO'), 'dragging a mask over a layer marks that layer')
    yield from release(window, row_point(region, paint_uid, .5))
    check(generators(find_layer(data, paint_uid)) == ['DIRT'] and len(order(data)) == len(after), 'dropping a smart mask onto a layer adds its generator to the mask stack')
    yield from open_tab(window, region, 'FILTERS')
    yield from search(window, region, 'pixel')
    yield from drag_to(window, spot(region, labels()['Pixelate']), row_point(region, steel_uid, .5))
    yield from release(window, row_point(region, steel_uid, .5))
    check(any(effect.kind == 'FILTER' and effect.filter == 'PIXELATE' for effect in find_layer(data, steel_uid).effects), 'dropping a filter onto a layer adds it')
    yield from search(window, region, '')
    yield from open_tab(window, region, 'GENERATORS')
    yield from select_row(window, region, steel_uid)
    click(window, region, labels()['Metal edge wear'])
    yield from settle()
    check(generators(find_layer(data, steel_uid)) == ['METAL_EDGE_WEAR'], 'clicking a generator adds it to the mask stack of the selected layer')
    yield from open_tab(window, region, 'ENVIRONMENTS')
    click(window, region, labels()['forest'])
    yield from settle()
    check(area.spaces.active.shading.studio_light.startswith('forest'), 'clicking a lighting preview lights the viewport with it')

    click(window, region, 'BAKE')
    yield from settle()
    for key in keys('BAKEMAP.'):
        if control(key).active != (key.removeprefix('BAKEMAP.') in {'ao', 'curvature'}):
            click(window, region, key)
            yield from settle()
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    yield from open_tab(window, region, 'SMART')
    top = order(data)[-1]
    count = len(order(data))
    yield from drag_to(window, spot(region, labels()['Rusty Iron']), row_point(region, top, .9))
    yield from release(window, row_point(region, top, .9))
    folder = active_layer(data)
    children = [layer for layer in data.layers if layer.parent == folder.uid]
    check(folder.kind == 'FOLDER' and folder.name == 'Rusty Iron' and len(order(data)) > count and order(data).index(folder.uid) > order(data).index(top) and not folder.parent,
          'dropping a smart material on top of the stack adds its folder there')
    grime = next(layer for layer in children if generators(layer) == ['DIRT'])
    check(any(node.type == 'TEX_IMAGE' and node.image == data.maps['ao'].image for node in nodes(data)),
          'the smart material masks read the baked mesh maps')
    yield from context_menu(window, region, grime.uid, 'EXPORT_MASK')
    mask = png(export_dir / f'{bpy.path.clean_name(grime.name)}_Mask.png')[:, 0]
    check(mask.std() > .05, 'the smart material mask adapts to the mesh')

    view = bpy.context.scene.view_settings
    yield from context_menu(window, region, steel_uid, 'EXPORT_LAYER')
    stem = bpy.path.clean_name(find_layer(data, steel_uid).name)
    plain = png(export_dir / f'{stem}_BaseColor.png')
    click(window, region, 'VIEWPORT')
    yield from settle()
    check(has('CM_VIEW') and has('CM_LOOK') and has('CM_EXPOSURE') and has('CM_GAMMA'), 'the viewport card offers color management')
    click(window, region, 'CM_VIEW')
    yield from settle()
    check(has('SET_CM_VIEW.Standard') and has('SET_CM_VIEW.AgX'), 'the view transform menu lists the OpenColorIO transforms')
    click(window, region, 'SET_CM_VIEW.AgX')
    yield from settle()
    check(view.view_transform == 'AgX', 'picking AgX changes the viewport view transform')
    click(window, region, 'VIEWPORT')
    yield from settle()
    click(window, region, 'CM_LOOK')
    yield from settle()
    looks = keys('SET_CM_LOOK.')
    check(len(looks) > 2, 'the look menu lists the looks of the view transform')
    click(window, region, next(key for key in looks if 'None' not in key))
    yield from settle()
    check(view.look != 'None', 'picking a look applies it')
    click(window, region, 'VIEWPORT')
    yield from settle()
    click(window, region, 'CM_EXPOSURE', fx=.7)
    yield from settle()
    click(window, region, 'CM_GAMMA', fx=.6)
    yield from settle()
    check(abs(view.exposure - 2.0) < .1 and abs(view.gamma - 1.88) < .1, 'the exposure and gamma sliders set the display')
    press(window, 'ESC', *middle)
    yield from settle()
    yield from context_menu(window, region, steel_uid, 'EXPORT_LAYER')
    graded = png(export_dir / f'{stem}_BaseColor.png')
    check(numpy.abs(graded - plain).max() < 1e-6, 'exports keep the raw texture values whatever the viewport color management')

    yield from open_tab(window, region, 'MATERIALS')
    mesh_hit = mesh_point(region, area, cube)
    before_mesh = len(data.layers)
    yield from drag_to(window, spot(region, labels()['Gold']), mesh_hit)
    check(has('DRAG_GHOST') and editor._active.highlight == 0 and editor._active.state.drop[:2] == ('MESH', 0),
          'dragging a material over the mesh highlights its texture set')
    yield from release(window, mesh_hit)
    gold = active_layer(data)
    roots = [layer.uid for layer in data.layers if not layer.parent]
    check(gold.name == 'Gold' and len(data.layers) == before_mesh + 1 and not gold.parent and roots[-1] == gold.uid
          and editor._active.highlight is None and not has('DRAG_GHOST'),
          'dropping a material onto the mesh adds it at the top of the stack and clears the highlight')
    stage = editor._active.workspace.zones.stage
    empty = (region.x + stage.x + 12, region.y + stage.top - 12)
    yield from drag_to(window, spot(region, labels()['Steel']), empty)
    check(editor._active.highlight is None and not editor._active.state.drop,
          'dragging over empty viewport space does not target the mesh')
    yield from release(window, empty)
    check(len(data.layers) == before_mesh + 1, 'releasing over empty viewport space does not add a layer')
    yield from open_tab(window, region, 'MASKS')
    yield from drag_to(window, spot(region, labels()['Dirt']), mesh_hit)
    check(editor._active.highlight is None and not editor._active.state.drop,
          'dragging a mask over the mesh does not target the mesh')
    yield from release(window, mesh_hit)
    check(not generators(gold) and len(data.layers) == before_mesh + 1,
          'releasing a mask over the mesh leaves the layers unchanged')

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None, 'Devil Painter closes')
    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI SHELF CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI shelf test')
