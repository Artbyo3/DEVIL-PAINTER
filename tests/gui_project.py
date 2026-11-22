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
import bmesh
from devil_painter import editor, exporting, library, projects, tiles
from devil_painter.actions import owned_images
from devil_painter.document import texture_set
from tools.workspace import prepare_scratch
from tests.gui_harness import bake_landed, check, click, control, finish, has, move, pixels, press, run_journey, settle, type_text, viewport


def field(window, region, key, text):
    click(window, region, key)
    yield from settle()
    rect = control(key).rect
    type_text(window, text, region.x + rect.x + rect.w / 2, region.y + rect.y + rect.h / 2)


def stroke_at(window, region, point):
    x, y = region.x + point[0], region.y + point[1]
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 6):
        move(window, x + step * 3, y + step * 2)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 15), y=int(y + 10))


def loaded(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'Non-Color'
    values = pixels(image)
    result = values, image.is_float, image.channels
    bpy.data.images.remove(image)
    return result


def build_mesh(area):
    cube = bpy.data.objects['Cube']
    mesh = cube.data
    view = area.spaces.active.region_3d
    direction = view.view_rotation @ Vector((0.0, 0.0, -1.0))
    facing = sorted(range(len(mesh.polygons)), key=lambda index: mesh.polygons[index].normal.dot(direction))
    body_low, body_high, trim = facing[0], facing[1], facing[2]
    mesh.materials.clear()
    mesh.materials.append(bpy.data.materials.new('Body'))
    mesh.materials.append(bpy.data.materials.new('Trim'))
    hidden = facing[3:]
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = 1 if index == trim or index == hidden[0] else 0
    layer = mesh.uv_layers.active
    for loop in mesh.polygons[body_high].loop_indices:
        layer.data[loop].uv = (layer.data[loop].uv[0] + 1.0, layer.data[loop].uv[1])
    mesh.update()
    return cube, body_low, body_high, trim


def screen_point(region, area, cube, face):
    center = cube.matrix_world @ cube.data.polygons[face].center
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, center)
    return point.x, point.y


def reimport_without_body(window, region, cube, project):
    body, trim = project.sets[0], project.sets[1]
    check((body.name, trim.name) == ('Body', 'Trim'), 'the project has the Body and Trim sets before the reimport')
    body_layers, trim_layers = len(body.layers), len(trim.layers)
    swapped = cube.data.copy()
    swapped.name = 'Cube v3'
    swapped.materials.clear()
    swapped.materials.append(trim.material)
    swapped.materials.append(bpy.data.materials.new('Strap'))
    for index, polygon in enumerate(swapped.polygons):
        polygon.material_index = index % 2
    update = bpy.data.objects.new('CubeV3', swapped)
    bpy.context.scene.collection.objects.link(update)
    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'REIMPORT_OBJECT')
    yield from settle()
    click(window, region, 'REIMPORT_FROM.CubeV3')
    yield from settle()
    message = editor._active.message
    body, trim = project.sets['Body'], project.sets['Trim']
    slots = [data.slot for data in project.sets]
    used = {polygon.material_index for polygon in cube.data.polygons}
    print('sets after', [(data.name, data.slot) for data in project.sets], 'slots', [slot.material.name if slot.material else '' for slot in cube.material_slots])
    check(len(set(slots)) == len(slots), f'no two texture sets share a material slot after the reimport: {slots}')
    check(trim.slot == 0 and cube.material_slots[0].material == trim.material and len(trim.layers) == trim_layers, 'Trim keeps its layers on the slot that now holds its material')
    check(body.slot not in used and cube.material_slots[body.slot].material == body.material and len(body.layers) == body_layers,
          'Body keeps its layers on an empty slot of its own, so it masks and paints no faces')
    strap = next((data for data in project.sets if data.slot == 1), None)
    check(strap is not None and strap.name == 'Strap' and cube.material_slots[1].material == strap.material and len(strap.layers) == 1,
          'the new Strap slot gets its own texture set with a paint layer')
    check(project.sets[project.active_set].slot in used, 'the active texture set has faces to paint')
    check('Body has no faces' in message and 'New texture set Strap' in message, f'the message names the faceless set and the new one: {message!r}')


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test library lives in scratch, not the user library')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    devil_painter.register()
    yield from settle()
    window, area, region = viewport()
    cube, body_low, body_high, trim = build_mesh(area)
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(control('SETUP_SET.0').label == 'Body' and control('SETUP_SET.1').label == 'Trim', 'the setup card lists one texture set per material slot')
    check(control('SETUP_TILES.0').label == 'UDIM 1001, 1002' and control('SETUP_TILES.1').label == 'Single tile'
          and has('SETUP_UDIM') and control('SETUP_UDIM').active, 'the setup card detects the UDIM tiles each set uses')
    click(window, region, 'SETUP_TEMPLATE')
    yield from settle()
    names = [item['name'] for item in projects.PROJECT_TEMPLATES]
    click(window, region, f'SET_SETUP_TEMPLATE.{names.index("Unreal Engine")}')
    yield from settle()
    check(control('SETUP_TEMPLATE').text == 'Unreal Engine' and control('SETUP_NF.DIRECTX').active and has('SETUP_NS.TANGENT'),
          'a project template presets channels, shader, export, and the DirectX normal format')
    click(window, region, 'RES.0.1024')
    yield from settle()
    click(window, region, 'RES.1.1024')
    yield from settle()
    check(control('RES.1.1024').active, 'each texture set picks its own resolution')
    click(window, region, 'START')
    yield from settle()
    project = cube.devil_painter
    body, trim_set = project.sets[0], project.sets[1]
    check(project.enabled and len(project.sets) == 2 and tiles.numbers(body) == [1001, 1002] and tiles.numbers(trim_set) == [1001],
          'Start painting creates a project with a texture set per slot and its UDIM tiles')
    check(cube.material_slots[0].material == body.material and cube.material_slots[1].material == trim_set.material,
          'each material slot gets the material of its texture set')
    check(project.normal_format == 'DIRECTX' and project.export_template == 'Unreal Engine' and body.channels['ambient_occlusion'].enabled
          and trim_set.channels['emission'].enabled, 'the template sets the channels and export template of every set')
    body_paint = body.layers[0]
    check(tiles.variant(body, body_paint.image, 1002) is not body_paint.image and len(trim_set.layers) == 1,
          'paint layers hold one image per UDIM tile')

    rect = control('BRUSHVAL.roughness').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .9, region.y + rect.y + rect.h / 2)
    yield from settle()
    stroke_at(window, region, screen_point(region, area, cube, body_high))
    yield from settle()
    check(project.active_set == 0 and project.active_tile == 1002, 'clicking a face in tile 1002 switches painting to that tile')
    selected = numpy.empty(len(cube.data.polygons), dtype=bool)
    cube.data.polygons.foreach_get('select', selected)
    check(cube.data.use_paint_mask and selected.sum() == 1 and selected[body_high], 'a face mask keeps the stroke inside the set and tile')
    check(pixels(tiles.variant(body, body_paint.image, 1002))[:, 3].max() > .5 and pixels(body_paint.image)[:, 3].max() == 0.0,
          'the stroke lands only in the tile 1002 image of the Body set')
    canvas = body_paint.slots['roughness'].image
    check(pixels(tiles.variant(body, canvas, 1002))[:, 0].max() > .85, 'the stroke paints roughness into the tile 1002 canvas')

    stroke_at(window, region, screen_point(region, area, cube, trim))
    yield from settle()
    check(project.active_set == 1 and pixels(trim_set.layers[0].image)[:, 3].max() > .5, 'clicking a Trim face paints the Trim set')
    check(pixels(tiles.variant(body, body_paint.image, 1002))[:, 3].max() > .5, 'the Body painting stays in its own set')

    rect = control('SET.1').rect
    move(window, region.x + rect.x + rect.w * .5, region.y + rect.y + rect.h / 2)
    yield from settle()
    check(editor._active.highlight == 1 and editor._active.highlight_cache[1][2] == 4, 'hovering a texture set highlights its faces in the viewport')
    move(window, region.x + region.width * .3, region.y + region.height * .6)
    yield from settle()
    click(window, region, 'SETEYE.1')
    yield from settle()
    output = next(node for node in trim_set.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    check(not trim_set.visible and not trim_set.export and not any(node.type == 'TEX_IMAGE' for node in trim_set.material.node_tree.nodes),
          'disabling a texture set hides its layers and leaves it out of export')
    click(window, region, 'SETEYE.1')
    yield from settle()
    check(trim_set.visible and trim_set.export, 'enabling it again brings the layers back')
    click(window, region, 'CHANNELS')
    yield from settle()
    click(window, region, 'CHANNELS_ALL')
    yield from settle()
    click(window, region, 'CHANSET.user1')
    yield from settle()
    check(body.channels['user1'].enabled and trim_set.channels['user1'].enabled, 'the Channels card adds a channel to every texture set at once')
    press(window, 'ESC', *middle)
    yield from settle()

    click(window, region, 'SET.0')
    yield from settle()
    check(project.active_set == 0 and has('TILE.1001') and has('TILE.1002'), 'the Texture sets panel switches sets and shows their tiles')
    click(window, region, 'TILE.1001')
    yield from settle()
    check(project.active_tile == 1001 and control('TILE.1001').active, 'tile chips switch the painted tile')
    click(window, region, 'SETRES.1')
    yield from settle()
    click(window, region, 'SET_SETRES.1.2048')
    yield from settle()
    check(trim_set.resolution == 2048 and tuple(trim_set.layers[0].image.size) == (2048, 2048), 'a texture set changes resolution and keeps its paint')
    check(pixels(trim_set.layers[0].image)[:, 3].max() > .5, 'the rescaled Trim paint survives')

    click(window, region, 'SET.0')
    yield from settle()
    click(window, region, 'ADD_PAINT')
    yield from settle()
    moved_uid = body.active_uid
    click(window, region, 'ROW_' + moved_uid, kind='RIGHTMOUSE')
    yield from settle()
    click(window, region, 'MOVE_TO_SET.1')
    yield from settle()
    moved = next((layer for layer in trim_set.layers if layer.name == 'Paint 2'), None)
    check(project.active_set == 1 and moved is not None and tuple(moved.image.size) == (2048, 2048)
          and not any(layer.uid == moved_uid for layer in body.layers), 'a layer moves to another texture set at its resolution')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield from settle()
    click(window, region, 'ITEM.0')
    yield from settle()
    check(trim_set.layers[-1].name == 'Red Plastic' or any(layer.name == 'Red Plastic' for layer in trim_set.layers), 'the Trim set gets a red fill')
    click(window, region, 'SET.0')
    yield from settle()

    click(window, region, 'BAKE')
    yield from settle()
    for key in ('curvature', 'thickness', 'position', 'world_normal', 'id'):
        click(window, region, 'BAKEMAP.' + key)
        yield from settle()
    rect = control('BAKE_SAMPLES').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .03, region.y + rect.y + rect.h / 2)
    yield from settle()
    click(window, region, 'BAKE_RUN')
    yield from settle()
    yield from bake_landed()
    ao = body.maps['ao'].image
    low_cover = (pixels(ao)[:, 3] > .5).mean()
    high_cover = (pixels(tiles.variant(body, ao, 1002))[:, 3] > .5).mean()
    check(0 < high_cover < low_cover and 'ao' in trim_set.maps, 'ambient occlusion bakes per tile and per texture set')
    press(window, 'Z', *middle, ctrl=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    check(editor._active is not None and not any(item.image for item in project.sets[0].maps), 'Ctrl+Z undoes the bake')
    press(window, 'Z', *middle, ctrl=True, shift=True)
    yield from settle()
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    body, trim_set = project.sets[0], project.sets[1]
    check(body.maps['ao'].image is not None, 'Ctrl+Shift+Z brings the baked maps back')

    def card():
        if not has('EXPORT_RUN'):
            click(window, region, 'EXPORT')
        yield from settle()

    export_dir = scratch / 'project_export'
    yield from card()
    check(has('EXPORT_TEMPLATE') and has('EXPORT_SET.0') and has('EXPORT_SET.1') and has('EXPORT_PATTERN'),
          'the export card offers templates, texture sets, naming, and the folder')
    click(window, region, 'EXPORT_TEMPLATE')
    yield from settle()
    names = [item['name'] for item in exporting.all_templates()]
    click(window, region, f'SET_TEMPLATE.{names.index("Unreal Engine")}')
    yield from settle()
    yield from card()
    check(control('EXPORT_TEMPLATE').text == 'Unreal Engine' and has('OUT_LABEL.1'), 'picking the Unreal Engine template lists its packed outputs')
    yield from field(window, region, 'EXPORT_DIR', str(export_dir))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    expected = ['Cube_Body_BaseColor.1001.png', 'Cube_Body_BaseColor.1002.png', 'Cube_Body_OcclusionRoughnessMetallic.1002.png',
                'Cube_Body_Normal.1001.png', 'Cube_Trim_BaseColor.png', 'Cube_Trim_OcclusionRoughnessMetallic.png']
    check(all((export_dir / name).is_file() for name in expected), 'export writes every set, with UDIM numbers only for tiled sets')
    orm, _, _ = loaded(export_dir / 'Cube_Body_OcclusionRoughnessMetallic.1002.png')
    covered = orm[orm[:, 0] > .05]
    check(covered[:, 1].max() > .85 and (numpy.abs(covered[:, 1] - .5) < .03).any() and covered[:, 2].max() < .05,
          'the ORM map packs occlusion, painted roughness, and metallic into R, G, and B')
    base, _, _ = loaded(export_dir / 'Cube_Body_BaseColor.1002.png')
    check(base[:, 0].min() < .1 and base[:, 0].max() > .8, 'the tile 1002 base color holds the painted stroke')
    trim_base, _, _ = loaded(export_dir / 'Cube_Trim_BaseColor.png')
    red = (trim_base[:, 0] > .5) & (trim_base[:, 1] < .2)
    check(0 < red.mean() < .5, 'with 16 px padding the Trim color stays near its UV islands')

    yield from card()
    click(window, region, 'TEMPLATE_DUPLICATE')
    yield from settle()
    yield from card()
    check(project.export_template == 'Unreal Engine copy' and has('OUT_SRC.1.0') and has('OUT_FORMAT.1'), 'a custom copy of the template is editable')
    for opener, item in (('OUT_FORMAT.1', 'SET_FORMAT.1.OPEN_EXR'), ('OUT_DEPTH.1', 'SET_DEPTH.1.32'), ('OUT_SRC.1.3', 'SET_SRC.1.3.user1')):
        click(window, region, opener)
        yield from settle()
        click(window, region, item)
        yield from settle()
        yield from card()
    custom = exporting.find_template('Unreal Engine copy')['outputs'][1]
    check(custom['format'] == 'OPEN_EXR' and custom['depth'] == '32' and custom['sources'] == ['ao', 'roughness', 'metallic', 'user1'],
          'outputs take a format, a bit depth, and an extra packed channel')
    click(window, region, 'EXPORT_SET.1')
    yield from settle()
    yield from field(window, region, 'EXPORT_PATTERN', '{set}-{output}-{udim}')
    yield from settle()
    yield from card()
    click(window, region, 'EXPORT_DEPTH')
    yield from settle()
    click(window, region, 'SET_EXPORT_DEPTH.16')
    yield from settle()
    yield from card()
    custom_dir = scratch / 'custom_export'
    yield from field(window, region, 'EXPORT_DIR', str(custom_dir))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    exr = custom_dir / 'Body-OcclusionRoughnessMetallic-1002.exr'
    png = custom_dir / 'Body-BaseColor-1001.png'
    check(exr.is_file() and png.is_file() and not any('Trim' in path.name for path in custom_dir.iterdir()),
          'naming tokens and per-set selection shape the export')
    exr_values, exr_float, exr_channels = loaded(exr)
    _, png_float, _ = loaded(png)
    check(exr_float and exr_channels == 4 and png_float, 'the custom output writes an RGBA EXR and the override writes 16-bit PNGs')
    check(exr_values[:, 3].max() < .01, 'a user channel packs into the alpha of a custom output')

    yield from card()
    click(window, region, 'EXPORT_TEMPLATE')
    yield from settle()
    names = [item['name'] for item in exporting.all_templates()]
    click(window, region, f'SET_TEMPLATE.{names.index("USD Preview Surface")}')
    yield from settle()
    yield from card()
    click(window, region, 'EXPORT_SET.0')
    yield from settle()
    click(window, region, 'EXPORT_SET.1')
    yield from settle()
    for opener, item in (('EXPORT_SIZE', 'SET_EXPORT_SIZE.512'), ('EXPORT_PADDING', 'SET_EXPORT_PADDING.-1')):
        click(window, region, opener)
        yield from settle()
        click(window, region, item)
        yield from settle()
        yield from card()
    usd_dir = scratch / 'usd_export'
    yield from field(window, region, 'EXPORT_DIR', str(usd_dir))
    yield from settle()
    click(window, region, 'EXPORT_RUN')
    yield from settle()
    diffuse, _, _ = loaded(usd_dir / 'Trim-diffuseColor-1001.png')
    red = (diffuse[:, 0] > .5) & (diffuse[:, 1] < .2)
    check(len(diffuse) == 512 * 512 and red.mean() > .97 and (usd_dir / 'Trim-occlusion-1001.png').is_file(),
          'the USD template writes 512 px files with infinite padding filling the whole texture')

    click(window, region, 'SHELF_TAB.ALPHAS')
    yield from settle()
    click(window, region, 'ITEM.2')
    yield from settle()
    alpha_image = texture_set(cube).brush_alpha
    check(alpha_image is not None and alpha_image.packed_file is None and Path(bpy.path.abspath(alpha_image.filepath)).is_file(),
          'the brush alpha comes from an external file')
    saved = scratch / 'project.blend'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    owned = [image for data in project.sets for image in tiles.every_image(data, [key for layer in data.layers for key in owned_images(layer)])]
    check(owned and all(image.packed_file is not None for image in owned), 'saving packs every layer, mask, canvas, and UDIM tile image')
    check(alpha_image.packed_file is not None, 'saving also packs external resources the project uses, so the .blend is self-contained')
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    yield from settle()
    window, area, region = viewport()
    middle = (area.x + area.width / 2, area.y + area.height / 2)
    cube = bpy.data.objects['Cube']
    project = cube.devil_painter
    body = project.sets[0]
    check(editor._active is None and project.enabled and len(project.sets) == 2
          and pixels(tiles.variant(body, body.layers[0].image, 1002))[:, 3].max() > .5, 'reopening the .blend restores the project and its painted tiles')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(editor._active is not None and has('SET.1') and has('TILE.1002'), 'Devil Painter reopens on the saved project')

    detail = cube.data.copy()
    detail.name = 'Cube v2'
    for vertex in detail.vertices:
        vertex.co.z *= 1.2
    update = bpy.data.objects.new('CubeV2', detail)
    bpy.context.scene.collection.objects.link(update)
    old_mesh = cube.data.name
    click(window, region, 'PROJECT')
    yield from settle()
    click(window, region, 'REIMPORT_OBJECT')
    yield from settle()
    click(window, region, 'REIMPORT_FROM.CubeV2')
    yield from settle()
    check(cube.data.name != old_mesh and cube.material_slots[0].material == project.sets[0].material
          and cube.material_slots[1].material == project.sets[1].material and len(project.sets[0].layers) >= 1,
          'reimporting a mesh keeps every texture set and its layers mapped by slot')
    obj_path = scratch / 'reimport.obj'
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.obj_export(filepath=str(obj_path), export_selected_objects=False, export_materials=True)
        bpy.ops.devil_painter.reimport_mesh(filepath=str(obj_path))
    yield from settle()
    check(cube.material_slots[0].material == project.sets[0].material and cube.data.uv_layers and len(project.sets) == 2,
          'reimporting from an OBJ file keeps the texture sets')
    yield from reimport_without_body(window, region, cube, project)

    click(window, region, 'CLOSE')
    yield from settle()
    check(editor._active is None and not cube.data.use_paint_mask, 'closing Devil Painter restores the face mask, even after a save and reopen')
    shape = bmesh.new()
    bmesh.ops.create_cube(shape, size=1.0)
    box_mesh = bpy.data.meshes.new('Box')
    shape.to_mesh(box_mesh)
    shape.free()
    box = bpy.data.objects.new('Box', box_mesh)
    bpy.context.scene.collection.objects.link(box)
    with bpy.context.temp_override(window=window, area=area, region=region):
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    for item in bpy.context.view_layer.objects:
        item.select_set(False)
    box.select_set(True)
    bpy.context.view_layer.objects.active = box
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield from settle()
    check(has('SETUP_UNWRAP.HARD_SURFACE'), 'a mesh without UVs offers smart or hard-surface unwrapping')
    click(window, region, 'SETUP_UNWRAP.HARD_SURFACE')
    yield from settle()
    click(window, region, 'START')
    yield from settle()
    check(box.data.uv_layers and any(edge.use_seam for edge in box.data.edges) and box.devil_painter.enabled,
          'hard-surface unwrapping cuts seams at sharp edges and starts the project')
    click(window, region, 'CLOSE')
    yield from settle()

    devil_painter.unregister()
    check(not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI PROJECT CHECKS PASSED', bpy.app.version_string)
    finish(0)


run_journey(journey(), 'GUI project test')
