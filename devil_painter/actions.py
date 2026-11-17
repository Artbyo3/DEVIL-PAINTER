import json
import bpy
from . import brushes, compositing, exporting, library, meshmaps, painting, projects, sets, smart, strokes, tiles
from .masks import GENERATOR, GENERATOR_FIELDS
from .meshmaps import MESH_MAP
from .blending import BLEND_MODES, CHANNEL
from .procedural import PATTERN
from .document import SLOT_FIELDS, active_layer, add_set_channels, add_slots, children, descendants, fill_slots, find_layer, layer_index, set_slot_value

KIND_NAMES = {'PAINT': 'Paint', 'FILL': 'Fill', 'FOLDER': 'Folder'}
LAYER_FIELDS = ('kind', 'visible', 'opacity', 'projection', 'tiling', 'material') + GENERATOR_FIELDS


def image_for(obj, data, label, opaque):
    return tiles.create(data, f'DP {obj.name} {data.name} {label}', (1.0, 1.0, 1.0, 1.0) if opaque else (0.0, 0.0, 0.0, 0.0))


def has_uvs(obj):
    return bool(obj.data.uv_layers)


def refresh(context, obj, data, message):
    strokes.ensure_canvases(obj, data)
    compositing.sync(data)
    painting.update_canvas(context, data)
    bpy.ops.ed.undo_push(message='Devil Painter: ' + message)
    strokes.record(None)
    return message


def prepare(obj, data):
    fill_slots(data.brush_slots)
    add_set_channels(data)
    for layer in data.layers:
        if layer.kind != 'FOLDER':
            fill_slots(layer.slots)
    strokes.ensure_buffer(obj, data)


def start(context, obj, resolutions, use_udim, template_name, normal_format, normal_space, unwrap_mode):
    if obj is None or obj.type != 'MESH':
        raise ValueError('Select a mesh object to paint.')
    unwrapped = ''
    if not has_uvs(obj):
        obj.data.uv_layers.new(name='UVMap')
        projects.unwrap(context, obj, unwrap_mode)
        unwrapped = f' It had no UVs, so it was unwrapped ({dict(projects.UNWRAP_MODES)[unwrap_mode]}).'
    template = projects.find_template(template_name)
    project = obj.devil_painter
    project.sets.clear()
    project.uv_map = sets.uv_name(obj)
    project.active_set, project.active_tile = 0, tiles.FIRST_TILE
    project.template, project.normal_format, project.normal_space = template['name'], normal_format, normal_space
    layout = sets.detect(obj, use_udim)
    if not obj.material_slots:
        obj.data.materials.append(None)
    for index, (name, found) in enumerate(layout):
        data = project.sets.add()
        data.name, data.slot = name, index
        data.resolution = resolutions[index] if index < len(resolutions) else resolutions[-1]
        for number in found:
            data.tiles.add().number = number
        prepare(obj, data)
        projects.apply_template(project, data, template)
        data.material = bpy.data.materials.new(f'Devil Painter {obj.name} {name}')
        obj.material_slots[index].material = data.material
    project.enabled = True
    painting.enter_paint_mode(context, obj)
    for data in project.sets:
        project.active_set = list(project.sets).index(data)
        add_layer(context, obj, data, 'PAINT')
    project.active_set = 0
    project.active_tile = tiles.numbers(project.sets[0])[0]
    painting.activate_tool(context, 'PAINT')
    sets.mask_faces(obj, project)
    painting.update_canvas(context, project.sets[0])
    brushes.sync(context, project.sets[0])
    tile_count = sum(len(tiles.numbers(data)) for data in project.sets)
    return f'Painting {obj.name}: {len(project.sets)} texture sets, {tile_count} tiles.' + unwrapped


def activate(context, obj, project, index, tile):
    if index == project.active_set and tile == project.active_tile:
        return ''
    project.active_set = index
    data = project.sets[index]
    project.active_tile = tile if tile in tiles.numbers(data) else tiles.numbers(data)[0]
    sets.mask_faces(obj, project)
    painting.update_canvas(context, data)
    compositing.sync(data)
    brushes.sync(context, data)
    count = len(tiles.numbers(data))
    return f'Painting {data.name}' + (f', tile {project.active_tile}.' if count > 1 else '.')


def toggle_set_visible(context, obj, project, index):
    data = project.sets[index]
    data.visible = not data.visible
    data.export = data.visible
    compositing.sync(data)
    bpy.ops.ed.undo_push(message='Devil Painter: texture set visibility')
    strokes.record(None)
    return f'{data.name} {"enabled" if data.visible else "disabled"}.'


def set_channel_enabled(context, obj, project, key, enabled, every_set):
    targets = list(project.sets) if every_set else [project.sets[project.active_set]]
    for data in targets:
        data.channels[key].enabled = enabled
        if not enabled and data.solo == key:
            data.solo = ''
        strokes.ensure_canvases(obj, data)
        compositing.sync(data)
    data = project.sets[project.active_set]
    scope = 'every texture set' if every_set else data.name
    return refresh(context, obj, data, f'{CHANNEL[key].label} {"added to" if enabled else "removed from"} {scope}.')


def set_project_value(context, obj, project, field, value):
    setattr(project, field, value)
    for data in project.sets:
        compositing.sync(data)
    return refresh(context, obj, project.sets[project.active_set], 'Project settings updated.')


def set_set_value(context, obj, data, field, value, commit):
    setattr(data, field, value)
    if commit:
        return refresh(context, obj, data, f'{data.name} shader settings updated.')
    compositing.sync(data)
    return ''


def carry(obj, source, target, key, name):
    created = None
    for number in tiles.numbers(target):
        origin = tiles.variant(source, key, number) if number in tiles.numbers(source) else None
        image = origin.copy() if origin is not None else tiles.blank(name, target.resolution, (0.0, 0.0, 0.0, 0.0), key.colorspace_settings.is_data)
        image.name = name if created is None else f'{name} {number}'
        if tuple(image.size) != (target.resolution, target.resolution):
            image.scale(target.resolution, target.resolution)
        image.pack()
        if created is None:
            created = image
        else:
            tiles.register(target, created, number, image)
    return created


def transfer(obj, source, target, layer, parent):
    target.serial += 1
    uid = f'L{target.serial}'
    values = {key: getattr(layer, key) for key in LAYER_FIELDS}
    copy = target.layers.add()
    for key, value in values.items():
        setattr(copy, key, value)
    copy.uid, copy.parent, copy.name = uid, parent, layer.name
    base = f'DP {obj.name} {target.name} {uid}'
    for slot in layer.slots:
        item = copy.slots.add()
        item.name = slot.name
        for key in SLOT_FIELDS + ('image',):
            setattr(item, key, getattr(slot, key))
        if layer.kind == 'PAINT' and slot.source == 'IMAGE' and slot.image is not None:
            item.image = carry(obj, source, target, slot.image, f'{base} {slot.name}')
    if layer.image is not None:
        copy.image = carry(obj, source, target, layer.image, base)
    if layer.mask is not None:
        copy.mask = carry(obj, source, target, layer.mask, base + ' mask')
    for child in children(source.layers, layer.uid):
        transfer(obj, source, target, child, uid)
    return uid


def move_to_set(context, obj, project, index):
    source = project.sets[project.active_set]
    target = project.sets[index]
    layer = active_layer(source)
    name = layer.name
    uid = transfer(obj, source, target, layer, '')
    doomed = {layer.uid, *descendants(source.layers, layer.uid)}
    for position in range(len(source.layers) - 1, -1, -1):
        if source.layers[position].uid in doomed:
            remove_images(source, source.layers[position])
            source.layers.remove(position)
    source.active_uid = source.layers[-1].uid if source.layers else ''
    compositing.sync(source)
    target.active_uid = uid
    prepare(obj, target)
    message = activate(context, obj, project, index, project.active_tile)
    return refresh(context, obj, target, f'Moved {name} to {target.name}. {message}')


def reimport_mesh(context, obj, project, mesh):
    mode = obj.mode
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    kept = projects.swap_mesh(obj, project, mesh)
    for data in project.sets:
        prepare(obj, data)
        strokes.ensure_canvases(obj, data)
        data.material[compositing.SIGNATURE_KEY] = ''
        compositing.sync(data)
    painting.enter_paint_mode(context, obj)
    sets.mask_faces(obj, project)
    return refresh(context, obj, project.sets[project.active_set], f'Reimported the mesh. {kept} texture sets kept their layers.')


def set_resolution(context, obj, data, size):
    keys = [image for layer in data.layers for image in owned_images(layer)] + [item.image for item in data.maps if item.image is not None]
    for image in tiles.every_image(data, keys):
        image.scale(size, size)
        image.pack()
    data.resolution = size
    if data.stroke is not None:
        data.stroke.scale(size, size)
    return refresh(context, obj, data, f'{data.name} now paints at {size} px.')


def new_layer(data, kind):
    data.serial += 1
    active = active_layer(data)
    index = layer_index(data, data.active_uid)
    parent = '' if active is None else active.uid if active.kind == 'FOLDER' else active.parent
    layer = data.layers.add()
    layer.uid = f'L{data.serial}'
    layer.kind = kind
    layer.parent = parent
    data.layers.move(len(data.layers) - 1, index + 1)
    layer = data.layers[index + 1]
    data.active_uid = layer.uid
    data.target = 'CONTENT'
    return layer


def add_layer(context, obj, data, kind):
    layer = new_layer(data, kind)
    layer.name = f'{KIND_NAMES[kind]} {sum(1 for item in data.layers if item.kind == kind)}'
    if kind != 'FOLDER':
        add_slots(layer)
    if kind == 'PAINT':
        layer.image = image_for(obj, data, layer.uid, False)
    return refresh(context, obj, data, f'Added {layer.name}.')


def apply_material(layer, definition):
    layer.material = json.dumps(definition)
    library.apply_definition(layer, definition)


def add_material(context, obj, data, definition):
    layer = new_layer(data, 'FILL')
    layer.name = definition['name']
    add_slots(layer)
    apply_material(layer, definition)
    return refresh(context, obj, data, f'Added {layer.name}.')


def add_smart_material(context, obj, data, definition):
    folder = new_layer(data, 'FOLDER')
    folder.name = definition['name']
    folder_uid = folder.uid
    smart.build(obj, data, definition, folder, image_for)
    data.active_uid = folder_uid
    return refresh(context, obj, data, f'Added the {definition["name"]} smart material.')


def replace_material(context, obj, data, definition):
    layer = active_layer(data)
    apply_material(layer, definition)
    layer.name = definition['name']
    return refresh(context, obj, data, f'{layer.name} now carries the {definition["name"]} material and keeps its mask.')


def reset_material(context, obj, data):
    layer = active_layer(data)
    apply_material(layer, json.loads(layer.material))
    return refresh(context, obj, data, f'{layer.name} reset to its material.')


def owned_images(layer):
    canvases = [slot.image for slot in layer.slots if slot.source == 'IMAGE'] if layer.kind == 'PAINT' else []
    return [image for image in (layer.image, layer.mask, *canvases) if image is not None]


def remove_images(data, layer):
    for image in owned_images(layer):
        tiles.remove(data, image)


def delete_layer(context, obj, data):
    index = layer_index(data, data.active_uid)
    if index < 0:
        return 'No layer to delete.'
    layer = data.layers[index]
    name, parent = layer.name, layer.parent
    doomed = {layer.uid, *descendants(data.layers, layer.uid)}
    for position in range(len(data.layers) - 1, -1, -1):
        if data.layers[position].uid in doomed:
            remove_images(data, data.layers[position])
            data.layers.remove(position)
    siblings = children(data.layers, parent)
    data.active_uid = siblings[-1].uid if siblings else find_layer(data, parent).uid if parent else data.layers[-1].uid if data.layers else ''
    data.target = 'CONTENT'
    return refresh(context, obj, data, f'Deleted {name}.')


def move_layer(context, obj, data, step):
    layer = active_layer(data)
    siblings = [index for index, item in enumerate(data.layers) if item.parent == layer.parent]
    position = siblings.index(layer_index(data, layer.uid))
    if not 0 <= position + step < len(siblings):
        return 'The layer is already at the edge of its stack.'
    name = layer.name
    data.layers.move(siblings[position], siblings[position + step])
    return refresh(context, obj, data, f'Moved {name} {"up" if step > 0 else "down"}.')


def folder_below(data, layer):
    siblings = [item for item in data.layers if item.parent == layer.parent]
    position = next(index for index, item in enumerate(siblings) if item.uid == layer.uid)
    return next((item for item in reversed(siblings[:position]) if item.kind == 'FOLDER'), None)


def move_into_folder(context, obj, data):
    layer = active_layer(data)
    folder = folder_below(data, layer)
    if folder is None:
        return 'There is no folder under this layer to move it into.'
    layer.parent = folder.uid
    return refresh(context, obj, data, f'Moved {layer.name} into {folder.name}.')


def move_out_of_folder(context, obj, data):
    layer = active_layer(data)
    folder = find_layer(data, layer.parent)
    if folder is None:
        return 'The layer is not in a folder.'
    layer.parent = folder.parent
    message = f'Moved {layer.name} out of {folder.name}.'
    source, target = layer_index(data, layer.uid), layer_index(data, folder.uid)
    data.layers.move(source, target + 1 if source > target else target)
    return refresh(context, obj, data, message)


def select_layer(context, obj, data, uid, mask=False):
    layer = find_layer(data, uid)
    data.active_uid = uid
    data.target = 'MASK' if mask and layer.mask is not None else 'CONTENT'
    painting.update_canvas(context, data)
    return f'{layer.name}{" mask" if data.target == "MASK" else ""} selected.'


def toggle_visible(context, obj, data, uid):
    layer = find_layer(data, uid)
    layer.visible = not layer.visible
    return refresh(context, obj, data, f'{layer.name} {"shown" if layer.visible else "hidden"}.')


def set_blend(context, obj, data, key, mode):
    layer = active_layer(data)
    layer.slots[key].blend = mode
    return refresh(context, obj, data, f'{CHANNEL[key].label} of {layer.name} blends with {dict(BLEND_MODES)[mode]}.')


def rename_layer(context, obj, data, uid, name):
    layer = find_layer(data, uid)
    layer.name = name.strip() or layer.name
    return refresh(context, obj, data, f'Renamed to {layer.name}.')


def copy_layer(obj, data, source, parent, position):
    data.serial += 1
    values = {key: getattr(source, key) for key in LAYER_FIELDS}
    slots = [(slot.name, {key: getattr(slot, key) for key in SLOT_FIELDS + ('image',)}) for slot in source.slots]
    images = {key: getattr(source, key) for key in ('image', 'mask')}
    name, uid = source.name, source.uid
    layer = data.layers.add()
    for key, value in values.items():
        setattr(layer, key, value)
    layer.uid, layer.parent, layer.name = f'L{data.serial}', parent, name + (' copy' if position is not None else '')
    for slot_name, slot_values in slots:
        slot = layer.slots.add()
        slot.name = slot_name
        for key, value in slot_values.items():
            setattr(slot, key, value)
        if values['kind'] == 'PAINT' and slot.image is not None:
            slot.image = tiles.copy(data, slot.image, f'DP {obj.name} {data.name} {layer.uid} {slot_name}')
    for key, image in images.items():
        if image is not None:
            setattr(layer, key, tiles.copy(data, image, f'DP {obj.name} {data.name} {layer.uid}' + (' mask' if key == 'mask' else '')))
    new_uid = layer.uid
    if position is not None:
        data.layers.move(len(data.layers) - 1, position)
    for child in [item.uid for item in data.layers if item.parent == uid]:
        copy_layer(obj, data, find_layer(data, child), new_uid, None)
    return new_uid


def duplicate_layer(context, obj, data):
    source = active_layer(data)
    if source is None:
        return 'No layer to duplicate.'
    name = source.name
    data.active_uid = copy_layer(obj, data, source, source.parent, layer_index(data, source.uid) + 1)
    data.target = 'CONTENT'
    return refresh(context, obj, data, f'Duplicated {name}.')


def toggle_slot(context, obj, data, key):
    layer = active_layer(data)
    slot = layer.slots[key]
    slot.enabled = not slot.enabled
    return refresh(context, obj, data, f'{CHANNEL[key].label} {"on" if slot.enabled else "off"} for {layer.name}.')


def set_opacity(context, obj, data, value):
    active_layer(data).opacity = max(0.0, min(1.0, value))
    compositing.update_values(data)


def set_channel_value(context, obj, data, key, value, second=False):
    set_slot_value(active_layer(data).slots[key], tuple(max(0.0, min(1.0, part)) for part in value), second)
    compositing.update_values(data)


def set_slot_field(context, obj, data, key, field, value):
    setattr(active_layer(data).slots[key], field, value)
    compositing.update_values(data)


def set_tiling(context, obj, data, value):
    active_layer(data).tiling = value
    compositing.update_values(data)


def set_projection(context, obj, data, projection):
    layer = active_layer(data)
    layer.projection = projection
    return refresh(context, obj, data, f'{layer.name} projects {"tri-planar" if projection == "TRIPLANAR" else "by UV"}.')


def use_value(context, obj, data, key):
    layer = active_layer(data)
    layer.slots[key].source = 'VALUE'
    return refresh(context, obj, data, f'{CHANNEL[key].label} of {layer.name} is a plain value.')


def assign_image(context, obj, data, key, image):
    layer = active_layer(data)
    slot = layer.slots[key]
    slot.enabled, slot.source, slot.image = True, 'IMAGE', image
    compositing.assign_image_colorspace(image, CHANNEL[key])
    return refresh(context, obj, data, f'{image.name} drives {CHANNEL[key].label.lower()} of {layer.name}.')


def assign_pattern(context, obj, data, key, pattern):
    layer = active_layer(data)
    slot = layer.slots[key]
    slot.enabled, slot.source, slot.pattern = True, 'PATTERN', pattern
    return refresh(context, obj, data, f'{PATTERN[pattern].label} drives {CHANNEL[key].label.lower()} of {layer.name}.')


def commit_value(context, obj, data, label):
    return refresh(context, obj, data, f'{label} of {active_layer(data).name} set.')


def set_solo(context, obj, data, key):
    data.solo = key
    if key.startswith('map:'):
        return refresh(context, obj, data, f'Viewing the {MESH_MAP[key.removeprefix("map:")].label.lower()} map.')
    return refresh(context, obj, data, f'Viewing {CHANNEL[key].label} only.' if key else 'Viewing the full material.')


def bake_mesh_maps(context, obj, data, keys):
    project = obj.devil_painter
    baked = meshmaps.bake_maps(context, obj, project, list(range(len(project.sets))), keys, data.bake_source, data.bake_samples)
    painting.enter_paint_mode(context, obj)
    sets.mask_faces(obj, project)
    if not baked:
        return 'Nothing to bake. Pick a high-poly source for the normal map.'
    return refresh(context, obj, data, f'Baked {len(baked)} mesh maps.')


def set_bake_source(context, obj, data, name):
    data.bake_source = bpy.data.objects.get(name) if name else None
    return refresh(context, obj, data, f'Normal maps bake from {name}.' if name else 'No high-poly source.')


def set_generator(context, obj, data, values):
    layer = active_layer(data)
    library.apply_generator(layer, values)
    if layer.generator == 'NONE':
        return refresh(context, obj, data, f'{layer.name} has no generator.')
    generator = GENERATOR[layer.generator]
    missing = '' if generator.map_key in data.maps and data.maps[generator.map_key].image else f' Bake the {MESH_MAP[generator.map_key].label.lower()} map to see it.'
    return refresh(context, obj, data, f'{generator.label} masks {layer.name}.{missing}')


def set_generator_value(context, obj, data, field, value):
    setattr(active_layer(data), field, value)
    compositing.update_values(data)


def add_mask(context, obj, data, white):
    layer = active_layer(data)
    layer.mask = image_for(obj, data, layer.uid + ' mask', white)
    data.target = 'MASK'
    return refresh(context, obj, data, f'{"White" if white else "Black"} mask added to {layer.name}. Painting now edits the mask.')


def remove_mask(context, obj, data):
    layer = active_layer(data)
    mask = layer.mask
    layer.mask = None
    if mask is not None:
        tiles.remove(data, mask)
    data.target = 'CONTENT'
    return refresh(context, obj, data, f'Mask removed from {layer.name}.')


def set_target(context, obj, data, target):
    data.target = target
    painting.update_canvas(context, data)
    return 'Painting edits the mask.' if target == 'MASK' else 'Painting edits the layer.'


def export(context, obj, project, directory):
    wanted = [index for index, data in enumerate(project.sets) if data.export]
    if not wanted:
        return 'Pick at least one texture set to export.'
    template = exporting.find_template(project.export_template)
    written = exporting.export(context, obj, project, template, wanted, directory, project.export_pattern, project.export_depth,
                               project.export_size, project.export_padding)
    painting.enter_paint_mode(context, obj)
    sets.mask_faces(obj, project)
    painting.update_canvas(context, project.sets[project.active_set])
    return f'Exported {len(written)} textures to {directory}.'
