import os
import sys
import time
import traceback
from pathlib import Path
import bpy
import gpu
import numpy
from mathutils import Matrix

bpy.context.preferences.view.show_splash = False
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
import devil_painter
from devil_painter import editor, library, painting, shelf, thumbnails
from devil_painter.compositing import SIGNATURE_KEY, socket
from devil_painter.ui_system import SURFACE_FLOATING
from tools.workspace import prepare_scratch

TIMEOUT = 180
STARTED = time.time()
HIDDEN = ('show_region_header', 'show_region_tool_header', 'show_region_toolbar', 'show_gizmo_navigate')


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


def spot(region, key, fx=.5, fy=.5):
    rect = control(key).rect
    return region.x + rect.x + rect.w * fx, region.y + rect.y + rect.h * fy


def click(window, region, key, kind='LEFTMOUSE', fx=.5, fy=.5):
    press(window, kind, *spot(region, key, fx, fy))


def drag(window, region, key, dx, dy):
    x, y = spot(region, key)
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 7):
        move(window, x + dx * step / 6, y + dy * step / 6)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + dx), y=int(y + dy))


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.top and b.y < a.top


def type_text(window, text, x, y):
    for _ in range(80):
        window.event_simulate(type='BACK_SPACE', value='PRESS', x=int(x), y=int(y))
    for character in text:
        window.event_simulate(type='A', value='PRESS', x=int(x), y=int(y), unicode=character)
    window.event_simulate(type='RET', value='PRESS', x=int(x), y=int(y))


def write_png(path, color):
    image = bpy.data.images.new(path.stem, 16, 16, alpha=False)
    image.pixels.foreach_set(numpy.tile(numpy.array(color, dtype=numpy.float32), 16 * 16))
    image.filepath_raw = str(path)
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def shelf_index(label):
    return next(index for index, item in enumerate(shelf.items(editor._active.state.shelf_tab)) if item.label == label)


def tile_shown(key):
    if not has(key):
        return False
    item = control(key)
    return item.clip.contains(item.rect.x, item.rect.y) and item.clip.contains(item.rect.x + item.rect.w, item.rect.top)


def png_pixels(path):
    image = bpy.data.images.load(str(path))
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    bpy.data.images.remove(image)
    return values.reshape(-1, 4)


def stroke(window, region):
    x, y = region.x + region.width * .42, region.y + region.height * .45
    move(window, x, y)
    window.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    for step in range(1, 13):
        move(window, x + step * 6, y + step * 3)
    window.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x + 72), y=int(y + 36))


def alpha(image):
    pixels = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(-1, 4)[:, 3]


def rendered_pixel(window, area, region, point):
    offscreen = gpu.types.GPUOffScreen(region.width, region.height)
    with offscreen.bind():
        framebuffer = gpu.state.active_framebuffer_get()
        framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0))
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            gpu.matrix.load_projection_matrix(Matrix(((2 / region.width, 0, 0, -1), (0, 2 / region.height, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1))))
            with bpy.context.temp_override(window=window, area=area, region=region):
                editor._active.workspace = editor._active.make_layout()
                editor._active.renderer.draw(editor._active)
        pixel = tuple(framebuffer.read_color(int(point[0]), int(point[1]), 1, 1, 4, 0, 'FLOAT').to_list()[0][0])
    offscreen.free()
    return pixel


def journey():
    scratch = prepare_scratch()
    check(library.library_root().resolve().is_relative_to(scratch.resolve()), 'the test material library lives in scratch, not the user library')
    (library.library_root() / library.SETTINGS_FILE).unlink(missing_ok=True)
    for managed in library.managed_folder().iterdir():
        managed.unlink()
    devil_painter.register()
    yield 0.5
    window, area, region = viewport()
    space = area.spaces.active
    cube = bpy.data.objects['Cube']
    middle = (area.x + area.width / 2, area.y + area.height / 2)

    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None, 'Ctrl+Alt+P opens Devil Painter over the 3D viewport')
    check(not any(getattr(space, name) for name in HIDDEN), "Blender's header, tool header, toolbar and navigation gizmo are hidden")
    check(control('TARGET').label == 'Cube', 'the start card offers to paint the selected mesh')

    click(window, region, 'RES_1024')
    yield 0.3
    click(window, region, 'START')
    yield 1.5
    data = cube.devil_painter
    paint_layer = data.layers[0]
    check(data.enabled and data.resolution == 1024 and len(data.layers) == 1 and paint_layer.kind == 'PAINT', 'Start painting creates a 1K stack with a paint layer')
    check(cube.mode == 'TEXTURE_PAINT' and space.shading.type == 'MATERIAL', 'the viewport switches to texture paint with material preview')
    check(bpy.context.scene.tool_settings.image_paint.canvas == paint_layer.image, 'the brush paints on the selected layer')
    check(has('PANEL_LAYERS') and has('PANEL_PROPERTIES'), 'the right column shows the layers and properties panels')
    check(control('SET_NAME').label.startswith('Cube'), 'the workspace bar names the texture set')
    zones = editor._active.workspace.zones
    check(not any(overlaps(a, b) for a, b in ((zones.bar, zones.strip), (zones.bar, zones.column), (zones.strip, zones.column),
                                               (zones.dock, zones.column), (zones.dock, zones.stage), (zones.stage, zones.column))),
          'the workspace bar, tool strip, dock, stage and column never overlap')
    size_rect = control('BRUSH_SIZE').rect
    check(zones.strip.contains(size_rect.x + 1, size_rect.y + 1) and zones.strip.y < zones.bar.y, 'brush settings sit in the tool strip under the workspace bar')
    check(not space.show_region_tool_header, 'the tool header stays hidden after a brush is activated')

    stroke(window, region)
    yield 1.0
    check(alpha(paint_layer.image).max() > .5, 'a brush stroke in the viewport paints the layer')

    click(window, region, 'ADD_FILL')
    yield 0.5
    fill = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(len(data.layers) == 2 and fill.kind == 'FILL' and data.layers[1].uid == fill.uid, '+ Fill adds a fill layer above the paint layer')
    check(all(has(f'USE.{key}') for key in ('base_color', 'roughness', 'metallic', 'normal', 'height')) and not has('USE.emission'),
          'Properties lists one row per texture set channel')
    rect = control('VALUE.metallic').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w - 1, region.y + rect.y + rect.h / 2)
    yield 0.5
    metallic_slot = fill.slots['metallic']
    check(metallic_slot.value > .95, 'dragging the metallic slider sets the fill metallic')
    nodes = data.material.node_tree.nodes
    check(abs(socket(nodes[fill.uid + '.metallic'].inputs, 'B', 'RGBA').default_value[0] - metallic_slot.value) < 1e-5,
          'the material preview follows the metallic value')

    click(window, region, 'USE.height')
    yield 0.4
    rect = control('VALUE.height').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .9, region.y + rect.y + rect.h / 2)
    yield 0.5
    nodes = data.material.node_tree.nodes
    shader = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
    bump = next(node for node in nodes if node.type == 'BUMP')
    check(fill.slots['height'].enabled and fill.slots['height'].value > .85 and fill.uid + '.height' in nodes,
          'turning height on and dragging it adds the fill to the height channel')
    check(shader.inputs['Normal'].links[0].from_node == bump and bump.inputs['Height'].is_linked,
          'height drives a bump on the material normal')

    click(window, region, 'SWATCH.base_color')
    yield 0.4
    check(editor._active.state.popover is not None and has('COLOR_SV') and has('COLOR_HUE'), 'the fill swatch opens the custom color picker')
    click(window, region, 'COLOR_HUE', fx=.001)
    yield 0.2
    click(window, region, 'COLOR_SV', fx=.999, fy=.999)
    yield 0.4
    color = fill.slots['base_color'].color
    check(color[0] > .9 and color[1] < .05 and color[2] < .05, 'picking hue and saturation sets the fill color')
    click(window, region, 'COLOR_HEX')
    yield 0.2
    x, y = spot(region, 'COLOR_HEX')
    type_text(window, '#0000FF', x, y)
    yield 0.4
    color = fill.slots['base_color'].color
    check(color[2] > .9 and color[0] < .05, 'typing a hex color sets the fill color')
    press(window, 'LEFTMOUSE', region.x + region.width * .3, region.y + region.height * .1)
    yield 0.4
    check(editor._active.state.popover is None, 'clicking outside closes the color picker')

    click(window, region, 'BLEND.base_color')
    yield 0.4
    click(window, region, 'SET_BLEND.base_color.MULTIPLY')
    yield 0.4
    nodes = data.material.node_tree.nodes
    check(fill.slots['base_color'].blend == 'MULTIPLY' and nodes[fill.uid + '.base_color'].blend_type == 'MULTIPLY'
          and fill.slots['height'].blend == 'MIX', 'the base color blend dropdown sets Multiply for that channel only')

    click(window, region, 'CHANNELS')
    yield 0.4
    check(has('SET_CHANNEL.emission') and not control('SET_CHANNEL.emission').active, 'the Channels menu lists the channels the set can add')
    click(window, region, 'SET_CHANNEL.emission')
    yield 0.5
    check(data.channels['emission'].enabled and has('SWATCH.emission'), 'adding emission to the texture set shows its row in Properties')
    press(window, 'Z', *middle, ctrl=True)
    yield 0.8
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter
    check(editor._active is not None and has('ADD_PAINT'), 'Ctrl+Z keeps Devil Painter open')
    check(not data.channels['emission'].enabled and not has('SWATCH.emission'), 'Ctrl+Z undoes adding emission')
    press(window, 'Z', *middle, ctrl=True, shift=True)
    yield 0.8
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter
    check(data.channels['emission'].enabled, 'Ctrl+Shift+Z redoes it')
    click(window, region, 'UNDO')
    yield 0.8
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter
    check(editor._active is not None and not data.channels['emission'].enabled, 'the dock Undo button undoes without closing Devil Painter')
    click(window, region, 'REDO')
    yield 0.8
    cube = bpy.data.objects['Cube']
    data = cube.devil_painter
    paint_layer, fill = data.layers[0], data.layers[1]
    check(editor._active is not None and data.channels['emission'].enabled and has('SWATCH.emission'), 'the dock Redo button redoes it')

    click(window, region, 'VIEW')
    yield 0.4
    click(window, region, 'SOLO.roughness')
    yield 0.5
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    check(data.solo == 'roughness' and output.inputs['Surface'].links[0].from_node.type == 'EMISSION' and control('VIEW').text == 'Roughness',
          'View shows the roughness channel on its own')
    click(window, region, 'VIEW')
    yield 0.4
    click(window, region, 'SOLO.')
    yield 0.5
    output = next(node for node in data.material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL')
    check(not data.solo and output.inputs['Surface'].links[0].from_node.type == 'BSDF_PRINCIPLED', 'View goes back to the full material')

    click(window, region, 'EYE_' + fill.uid)
    yield 0.5
    check(not fill.visible and fill.uid not in data.material[SIGNATURE_KEY], 'the eye hides the fill layer from the material')
    click(window, region, 'EYE_' + fill.uid)
    yield 0.5
    check(fill.visible and fill.uid in data.material[SIGNATURE_KEY], 'the eye shows the fill layer again')

    click(window, region, 'ROW_' + fill.uid, kind='RIGHTMOUSE')
    yield 0.4
    check(has('DUPLICATE') and has('ADD_MASK_BLACK'), 'right-clicking a layer opens its context menu')
    click(window, region, 'ADD_MASK_BLACK')
    yield 0.5
    check(fill.mask is not None and alpha(fill.mask).max() == 0.0, 'the menu adds a black mask')
    check(bpy.context.scene.tool_settings.image_paint.canvas == fill.mask, 'painting now edits the mask')
    stroke(window, region)
    yield 1.0
    check(alpha(fill.mask).max() > .5, 'a brush stroke reveals the fill through its mask')
    check(control('MASKTHUMB_' + fill.uid).active and has('MASK_INFO') and not has('OPACITY'), 'with the mask selected, Properties shows the mask')
    click(window, region, 'SELECT_LAYER')
    yield 0.4
    check(data.target == 'CONTENT' and has('OPACITY') and not control('MASKTHUMB_' + fill.uid).active, 'Back to layer shows the layer properties again')
    click(window, region, 'MASKTHUMB_' + fill.uid)
    yield 0.4
    check(data.target == 'MASK' and has('MASK_INFO') and bpy.context.scene.tool_settings.image_paint.canvas == fill.mask,
          'clicking the mask thumbnail selects the mask for painting and editing')

    row = control('ROW_' + paint_layer.uid).rect
    card = next(rect for rect, _ in editor._active.workspace.cards if rect.contains(row.x + row.w / 2, row.y + row.h / 2))
    pixel = rendered_pixel(window, area, region, (card.x + card.w - 3, card.y + 3))
    check(all(abs(a - b) < .03 for a, b in zip(pixel[:3], SURFACE_FLOATING)), 'the layers panel renders in the Devil palette')

    click(window, region, 'ROW_' + fill.uid)
    click(window, region, 'ROW_' + fill.uid)
    yield 0.4
    check(editor._active.state.text is not None, 'double-clicking a layer starts renaming it in place')
    type_text(window, 'Rust', *spot(region, 'ROW_' + fill.uid))
    yield 0.4
    check(fill.name == 'Rust', 'typing a name and pressing Enter renames the layer')

    click(window, region, 'ROW_' + fill.uid, kind='RIGHTMOUSE')
    yield 0.4
    click(window, region, 'DUPLICATE')
    yield 0.6
    copy = data.layers[2]
    check(data.active_uid == copy.uid, 'the copy is selected above its source')
    check(len(data.layers) == 3 and copy.name == 'Rust copy' and copy.mask is not None and copy.mask != data.layers[1].mask,
          'Duplicate copies the layer with its own mask')

    scale = editor._active.workspace.scale
    red = numpy.zeros((data.resolution * data.resolution, 4), dtype=numpy.float32)
    red[:] = (1.0, 0.0, 0.0, 1.0)
    paint_layer = data.layers[0]
    paint_layer.image.pixels.foreach_set(red.ravel())
    paint_layer.image.update()
    row = control('ROW_' + paint_layer.uid).rect
    paint_thumb = rendered_pixel(window, area, region, (row.x + 46 * scale, row.y + row.h / 2))
    check(paint_thumb[0] > .9 and paint_thumb[1] < .1 and paint_thumb[2] < .1, 'the paint layer thumbnail shows the painted image')

    export_dir = scratch / 'export'
    click(window, region, 'EXPORT')
    yield 0.4
    check(has('EXPORT_DIR') and has('EXPORT_RUN') and has('BROWSE'), 'Export textures opens the custom export card')
    click(window, region, 'EXPORT_DIR')
    yield 0.2
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield 0.3
    check(Path(data.export_directory) == export_dir, 'typing the folder sets the export directory')
    click(window, region, 'EXPORT_RUN')
    yield 1.0
    files = {suffix: export_dir / f'Cube_{suffix}.png' for suffix in ('BaseColor', 'Roughness', 'Metallic', 'Normal', 'Height', 'Emission')}
    check(all(path.is_file() for path in files.values()), 'Export writes one PNG per texture set channel')
    check(not (export_dir / 'Cube_Opacity.png').exists(), 'channels outside the texture set are not exported')
    height = bpy.data.images.load(str(files['Height']))
    values = numpy.empty(len(height.pixels), dtype=numpy.float32)
    height.pixels.foreach_get(values)
    check(values.max() > .8 and abs(values.min() - .5) < .02, 'exported height rises only where the fill shows through its mask')
    bpy.data.images.remove(height)
    metallic = bpy.data.images.load(str(files['Metallic']))
    values = numpy.empty(len(metallic.pixels), dtype=numpy.float32)
    metallic.pixels.foreach_get(values)
    check(values.max() > .9 and values.min() < .1, 'exported metallic is high only where the masks were painted')
    bpy.data.images.remove(metallic)

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.wm.save_as_mainfile(filepath=str(scratch / 'painted.blend'), copy=True)
    check(all(layer.image is None or layer.image.packed_file is not None for layer in data.layers), 'saving packs the painted layers into the .blend')

    check(has('SHELF_TAB.MATERIALS') and control('SHELF_TAB.MATERIALS').active and has('ITEM.0'), 'the material shelf shows material tiles')
    check(not any(overlaps(editor._active.workspace.zones.shelf, zone) for zone in (zones.dock, zones.column, editor._active.workspace.zones.stage)),
          'the shelf sits in its own zone under the stage')
    first = library.BUILTIN_MATERIALS[0]
    for _ in range(60):
        if thumbnails.cache_path(first).is_file() and control('ITEM.0').preview is not None:
            break
        yield 0.3
    check(thumbnails.cache_path(first).is_file() and control('ITEM.0').preview is not None, 'material tiles get rendered sphere thumbnails')
    tile = control('ITEM.0').rect
    tile_pixel = rendered_pixel(window, area, region, (tile.x + tile.w / 2, tile.top - tile.w / 2))
    check(tile_pixel[0] > .2 and tile_pixel[0] > tile_pixel[2] * 2, 'the red plastic thumbnail renders red in the shelf')

    click(window, region, f'ITEM.{shelf_index("Gold")}')
    yield 0.6
    gold = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(gold.name == 'Gold' and gold.kind == 'FILL' and gold.slots['metallic'].value == 1.0 and not gold.slots['height'].enabled,
          'clicking Gold in the shelf adds a gold fill layer')
    click(window, region, f'ITEM.{shelf_index("Rust")}')
    yield 0.8
    rust = next(layer for layer in data.layers if layer.uid == data.active_uid)
    nodes = data.material.node_tree.nodes
    check(rust.slots['base_color'].source == 'PATTERN' and nodes[rust.uid + '.base_color.texture'].type == 'TEX_NOISE',
          'Rust lays down a procedural grunge pattern')
    check(has('SCALE.base_color') and has('SWATCHB.base_color') and has('PROJECTION') and control('PROJECTION').text == 'Tri-planar',
          'Properties shows the pattern parameters and the tri-planar projection')
    mapping = nodes[rust.uid + '.mapping']
    check(mapping.inputs['Vector'].links[0].from_socket.name == 'Object', 'tri-planar patterns use object coordinates')
    rect = control('SCALE.base_color').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .8, region.y + rect.y + rect.h / 2)
    yield 0.4
    nodes = data.material.node_tree.nodes
    check(abs(nodes[rust.uid + '.base_color.texture'].inputs['Scale'].default_value - rust.slots['base_color'].scale) < 1e-4
          and rust.slots['base_color'].scale > 50, 'the scale slider sets the pattern scale in the material')
    click(window, region, 'PROJECTION')
    yield 0.3
    click(window, region, 'SET_PROJECTION.UV')
    yield 0.5
    nodes = data.material.node_tree.nodes
    check(rust.projection == 'UV' and nodes[rust.uid + '.mapping'].inputs['Vector'].links[0].from_socket.name == 'UV',
          'the projection dropdown switches the layer to UV mapping')

    click(window, region, 'SOURCE.roughness')
    yield 0.3
    click(window, region, 'PICK_PATTERN.roughness')
    yield 0.4
    check(editor._active.state.armed == 'roughness' and editor._active.state.shelf_tab == 'PATTERNS' and has('ARM_INFO'),
          'choosing Pattern from the shelf opens the pattern tab for roughness')
    click(window, region, f'ITEM.{shelf_index("Cells")}')
    yield 0.6
    check(rust.slots['roughness'].source == 'PATTERN' and rust.slots['roughness'].pattern == 'CELLS' and not editor._active.state.armed,
          'clicking a pattern drives the armed channel')

    textures = scratch / 'textures'
    textures.mkdir(exist_ok=True)
    write_png(textures / 'brick_basecolor.png', (.6, .2, .1, 1.0))
    write_png(textures / 'brick_roughness.png', (.7, .7, .7, 1.0))
    write_png(textures / 'brick_normal_gl.png', (.4, .6, 1.0, 1.0))
    write_png(textures / 'lone.png', (.1, .8, .2, 1.0))
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield 0.3
    check(has('SHELF_EMPTY') and has('TEXTURE_DIR'), 'the texture tab asks for a folder')
    click(window, region, 'TEXTURE_DIR')
    yield 0.2
    type_text(window, str(textures), *spot(region, 'TEXTURE_DIR'))
    yield 0.6
    check(library.texture_folder() == str(textures) and sum(item.key.startswith('ITEM.') for item in editor._active.workspace.controls) == 4,
          'typing a folder lists its textures in the shelf')
    for _ in range(20):
        if control('ITEM.0').preview is not None:
            break
        yield 0.2
    check(control('ITEM.0').preview is not None, 'texture tiles show the image thumbnails')
    click(window, region, 'SOURCE.base_color')
    yield 0.3
    click(window, region, 'PICK_TEXTURE.base_color')
    yield 0.3
    click(window, region, f'ITEM.{shelf_index("lone")}')
    yield 0.6
    slot = rust.slots['base_color']
    check(slot.source == 'IMAGE' and slot.image.name == 'lone.png' and has('IMAGE_NAME.base_color'), 'clicking a texture drives the armed channel')

    click(window, region, 'SHELF_TAB.MATERIALS')
    yield 0.3
    key = f'ITEM.{shelf_index("Brick")}'
    for _ in range(12):
        if tile_shown(key):
            break
        x, y = spot(region, 'ITEM.0')
        move(window, x, y)
        window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
        yield 0.2
    check(tile_shown(key), 'the material shelf scrolls to the texture set found in the folder')
    click(window, region, key)
    yield 0.8
    brick = next(layer for layer in data.layers if layer.uid == data.active_uid)
    check(brick.name == 'Brick' and brick.slots['roughness'].image.name == 'brick_roughness.png'
          and brick.slots['normal'].image.colorspace_settings.is_data and not brick.slots['metallic'].enabled,
          'a folder texture set becomes one fill layer with each map on its channel')

    rust_index = next(index for index, layer in enumerate(data.layers) if layer.uid == rust.uid)
    click(window, region, 'ROW_' + rust.uid, kind='RIGHTMOUSE')
    yield 0.3
    click(window, region, 'SAVE_MATERIAL')
    yield 0.4
    check(library.user_materials() and library.user_materials()[-1]['name'] == data.layers[rust_index].name
          and (library.library_root() / library.SETTINGS_FILE).is_file(), 'Save as material stores the layer in the user library')
    saved = next(index for index, item in enumerate(shelf.items('MATERIALS')) if item.user_index >= 0)
    check(shelf.items('MATERIALS')[saved].payload['slots']['base_color']['image'].endswith('lone.png'), 'the saved material keeps its texture file')

    export_dir = scratch / 'export_shelf'
    click(window, region, 'EXPORT')
    yield 0.4
    click(window, region, 'EXPORT_DIR')
    yield 0.2
    type_text(window, str(export_dir), *spot(region, 'EXPORT_DIR'))
    yield 0.3
    click(window, region, 'EXPORT_RUN')
    yield 1.5
    normal = png_pixels(export_dir / 'Cube_Normal.png')
    match = (numpy.abs(normal[:, 0] - .4) < .03) & (numpy.abs(normal[:, 1] - .6) < .03)
    check(editor._active.message.startswith('Exported 6 textures') and match.mean() > .3,
          'export bakes the texture set normal map into the normal channel')

    def active():
        return next(layer for layer in data.layers if layer.uid == data.active_uid)

    def drag_to(key, fraction):
        rect = control(key).rect
        press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * fraction, region.y + rect.y + rect.h / 2)

    click(window, region, 'ADD_FOLDER')
    yield 0.5
    folder = active()
    folder_uid = folder.uid
    check(folder.kind == 'FOLDER' and has('FOLD_' + folder.uid) and has('OPACITY') and has('ADD_MASK_BLACK') and not has('USE.base_color'),
          '+ Folder adds a folder with its own opacity and mask')
    click(window, region, f'ITEM.{shelf_index("Copper")}')
    yield 0.8
    copper = active()
    check(copper.parent == folder.uid and control('MATERIAL_NAME').label == 'Material · Copper',
          'a material added while a folder is selected lands inside it as a material layer')
    for _ in range(40):
        if control('ROW_' + copper.uid).preview is not None:
            break
        yield 0.3
    check(control('ROW_' + copper.uid).preview is not None, 'the material layer row shows its rendered material')
    drag_to('CHOPACITY.roughness', .5)
    yield 0.4
    nodes = data.material.node_tree.nodes
    check(abs(copper.slots['roughness'].opacity - .5) < .05 and abs(nodes[copper.uid + '.roughness.opacity'].inputs[1].default_value - copper.slots['roughness'].opacity) < 1e-5,
          'the per-channel opacity slider sets that channel opacity in the material')
    drag_to('VALUE.metallic', .02)
    yield 0.4
    check(copper.slots['metallic'].value < .1, 'editing the material layer changes its channel')
    click(window, region, 'RESET_MATERIAL')
    yield 0.5
    check(copper.slots['metallic'].value == 1.0, 'Reset restores the material values')
    click(window, region, 'ADD_MASK_BLACK')
    yield 0.5
    mask = copper.mask
    click(window, region, 'SELECT_LAYER')
    yield 0.3
    click(window, region, 'REPLACE_MATERIAL')
    yield 0.3
    check(editor._active.state.armed and editor._active.state.shelf_tab == 'MATERIALS' and has('ARM_INFO'), 'Replace asks for a material from the shelf')
    click(window, region, f'ITEM.{shelf_index("Gold")}')
    yield 0.6
    check(copper.name == 'Gold' and abs(copper.slots['base_color'].color[2] - .336) < 1e-3 and copper.mask == mask,
          'replacing the material swaps every channel and keeps the mask')
    material_uid = copper.uid
    click(window, region, 'ROW_' + material_uid, kind='RIGHTMOUSE')
    yield 0.3
    click(window, region, 'MOVE_OUT')
    yield 0.5
    moved = next(layer for layer in data.layers if layer.uid == material_uid)
    order = [layer.uid for layer in data.layers]
    check(moved.parent == '' and order.index(material_uid) > order.index(folder_uid), 'Move out of folder puts the layer above the folder')
    click(window, region, 'ROW_' + material_uid, kind='RIGHTMOUSE')
    yield 0.3
    click(window, region, 'MOVE_INTO')
    yield 0.5
    moved = next(layer for layer in data.layers if layer.uid == material_uid)
    check(moved.parent == folder_uid, 'Move into folder below puts it back inside')
    click(window, region, 'FOLD_' + folder_uid)
    yield 0.3
    check(not has('ROW_' + material_uid), 'folding the folder hides its layers')
    click(window, region, 'FOLD_' + folder_uid)
    yield 0.3
    check(has('ROW_' + material_uid), 'unfolding shows them again')
    click(window, region, 'ROW_' + folder_uid)
    yield 0.3
    drag_to('OPACITY', .3)
    yield 0.4
    nodes = data.material.node_tree.nodes
    check(abs(nodes[folder_uid + '.opacity'].inputs[1].default_value - next(layer for layer in data.layers if layer.uid == folder_uid).opacity) < 1e-5 and next(layer for layer in data.layers if layer.uid == folder_uid).opacity < .4
          and folder_uid + '.base_color' in nodes, 'folder opacity mixes the whole folder into the stack')

    library.import_textures([textures / 'lone.png'])
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.devil_painter.import_textures(directory=str(textures), files=[{'name': 'brick_roughness.png'}])
    click(window, region, 'SHELF_TAB.TEXTURES')
    yield 0.4
    check(has('TEXTURE_IMPORT'), 'the texture tab offers Import')
    managed = [item for item in shelf.items('TEXTURES') if item.managed]
    check(len(managed) == 2 and all(library.is_managed(item.payload) for item in managed), 'Import copies textures into the library')
    click(window, region, 'ROW_' + material_uid)
    yield 0.3
    click(window, region, 'ITEM.0', kind='RIGHTMOUSE')
    yield 0.3
    check(has('ASSIGN_TEXTURE.roughness.0') and has('REMOVE_TEXTURE.0') and has('TEXTURE_FILL.0'), 'right-clicking a texture lists every channel to use it for')
    click(window, region, 'ASSIGN_TEXTURE.roughness.0')
    yield 0.5
    moved = next(layer for layer in data.layers if layer.uid == material_uid)
    check(moved.slots['roughness'].source == 'IMAGE' and moved.slots['roughness'].image.colorspace_settings.is_data,
          'Use for roughness assigns the texture as non-color data')
    removed = shelf.items('TEXTURES')[0].payload
    click(window, region, 'ITEM.0', kind='RIGHTMOUSE')
    yield 0.3
    click(window, region, 'REMOVE_TEXTURE.0')
    yield 0.4
    check(not Path(removed).exists() and len([item for item in shelf.items('TEXTURES') if item.managed]) == 1, 'Remove from library deletes the imported copy')
    click(window, region, 'SHELF_TAB.MATERIALS')
    yield 0.3

    click(window, region, 'ROW_' + folder_uid, kind='RIGHTMOUSE')
    yield 0.3
    click(window, region, 'DELETE')
    yield 0.5
    check(not any(layer.uid in {folder_uid, material_uid} for layer in data.layers), 'deleting a folder deletes the layers inside it')

    click(window, region, 'SHELF_TOGGLE')
    yield 0.3
    check(not editor._active.state.shelf_open and not has('ITEM.0') and has('SHELF_TAB.MATERIALS'), 'the shelf collapses to its tabs')
    click(window, region, 'SHELF_TOGGLE')
    yield 0.3
    check(has('ITEM.0'), 'the shelf opens again')

    for _ in range(30):
        if 'LAYERS' in editor._active.workspace.scroll_areas and 'PROPERTIES' in editor._active.workspace.scroll_areas:
            break
        click(window, region, 'ADD_PAINT')
        yield 0.2
    check('LAYERS' in editor._active.workspace.scroll_areas, 'a long layer stack becomes scrollable')
    width = control('PANEL_LAYERS').rect.w
    drag(window, region, 'COLUMN_EDGE', -80, 0)
    yield 0.4
    check(control('PANEL_LAYERS').rect.w > width + 40, 'dragging the column edge widens the right column')
    check(has('SPLITTER'), 'a divider appears between layers and properties when they do not fit')
    layers_view = editor._active.workspace.scroll_areas['LAYERS'][0].h
    drag(window, region, 'SPLITTER', 0, -60)
    yield 0.4
    check(editor._active.workspace.scroll_areas['LAYERS'][0].h > layers_view + 30, 'dragging the divider gives the layers more room')
    before = editor._active.state.scroll.get('LAYERS', 0.0)
    x, y = spot(region, 'PANEL_LAYERS', fy=-1.0)
    move(window, x, y)
    window.event_simulate(type='WHEELDOWNMOUSE', value='PRESS', x=int(x), y=int(y))
    yield 0.3
    check(editor._active.state.scroll['LAYERS'] > before, 'the mouse wheel scrolls the layer stack')

    rows = sum(item.key.startswith('ROW_') for item in editor._active.workspace.controls)
    check(rows < len(data.layers), 'layer rows scrolled out of view are not built or drawn')
    layers_view = editor._active.workspace.scroll_areas['LAYERS'][0].h
    click(window, region, 'PANEL_PROPERTIES')
    yield 0.3
    check('PROPERTIES' in editor._active.state.collapsed and not has('OPACITY'), 'clicking a panel header collapses it')
    check(editor._active.workspace.scroll_areas['LAYERS'][0].h > layers_view + 30, 'collapsing properties gives its room to the layers')
    click(window, region, 'PANEL_PROPERTIES')
    yield 0.3
    check(has('OPACITY'), 'clicking it again expands it')

    rect = control('BRUSH_STRENGTH').rect
    press(window, 'LEFTMOUSE', region.x + rect.x + rect.w * .25, region.y + rect.y + rect.h / 2)
    yield 0.3
    check(abs(painting.brush_value(bpy.context.scene, 'strength') - .25) < .03, 'the strength slider sets the strength the brush uses')
    click(window, region, 'ERASE')
    yield 0.5
    check(control('ERASE').active, 'the dock switches to the eraser')

    click(window, region, 'CLOSE')
    yield 0.5
    check(editor._active is None, 'the close button closes Devil Painter')
    check(space.show_region_header and space.show_region_toolbar and space.show_gizmo_navigate, "closing restores Blender's header, toolbar and gizmo")
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is not None and has('ADD_PAINT'), 'reopening shows the layer stack')
    press(window, 'P', *middle, ctrl=True, alt=True)
    yield 0.5
    check(editor._active is None, 'Ctrl+Alt+P closes Devil Painter again')

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.object.mode_set(mode='OBJECT')
    devil_painter.unregister()
    check(not hasattr(bpy.types, 'DEVIL_PAINTER_OT_editor') and not hasattr(bpy.types.Object, 'devil_painter'), 'Devil Painter unregisters cleanly')
    print('ALL GUI EDITOR CHECKS PASSED', bpy.app.version_string)
    finish(0)


steps = journey()


def advance():
    try:
        if time.time() - STARTED > TIMEOUT:
            raise AssertionError('GUI editor test timed out')
        return next(steps)
    except Exception:
        traceback.print_exc()
        print('GUI TEST FAILED')
        finish(1)


bpy.app.timers.register(advance, first_interval=1.0)
