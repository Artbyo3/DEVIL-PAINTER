import json
import bpy
import numpy
from . import baking, brushes, compositing, library, meshmaps, painting, strokes
from .masks import GENERATOR, GENERATOR_FIELDS
from .meshmaps import MESH_MAP
from .blending import BLEND_MODES, CHANNEL
from .procedural import PATTERN
from .document import SLOT_FIELDS, active_layer, add_set_channels, add_slots, children, descendants, fill_slots, find_layer, layer_index, set_slot_value

KIND_NAMES = {'PAINT': 'Paint', 'FILL': 'Fill', 'FOLDER': 'Folder'}
LAYER_FIELDS = ('kind', 'visible', 'opacity', 'projection', 'tiling', 'material') + GENERATOR_FIELDS


def image_for(obj, data, label, opaque):
    size = data.resolution
    image = bpy.data.images.new(f'DP {obj.name} {label}', size, size, alpha=True)
    image.alpha_mode = 'STRAIGHT'
    pixels = numpy.zeros(size * size * 4, dtype=numpy.float32)
    if opaque:
        pixels[:] = 1.0
    image.pixels.foreach_set(pixels)
    image.pack()
    return image


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
    if not data.brush_slots:
        fill_slots(data.brush_slots)
    strokes.ensure_buffer(obj, data)


def start(context, obj, resolution):
    if obj is None or obj.type != 'MESH':
        raise ValueError('Select a mesh object to paint.')
    unwrapped = ''
    if not has_uvs(obj):
        obj.data.uv_layers.new(name='UVMap')
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project()
        bpy.ops.object.mode_set(mode='OBJECT')
        unwrapped = ' It had no UVs, so it was unwrapped automatically.'
    data = obj.devil_painter
    data.resolution = resolution
    data.enabled = True
    data.channels.clear()
    add_set_channels(data)
    prepare(obj, data)
    material = bpy.data.materials.new(f'Devil Painter {obj.name}')
    data.material = material
    if obj.material_slots:
        for slot in obj.material_slots:
            slot.material = material
    else:
        obj.data.materials.append(material)
    painting.enter_paint_mode(context, obj)
    add_layer(context, obj, data, 'PAINT')
    painting.activate_tool(context, 'PAINT')
    painting.update_canvas(context, data)
    brushes.sync(context, data)
    return f'Painting {obj.name} at {resolution} px.' + unwrapped


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


def remove_images(layer):
    for image in owned_images(layer):
        bpy.data.images.remove(image)


def delete_layer(context, obj, data):
    index = layer_index(data, data.active_uid)
    if index < 0:
        return 'No layer to delete.'
    layer = data.layers[index]
    name, parent = layer.name, layer.parent
    doomed = {layer.uid, *descendants(data.layers, layer.uid)}
    for position in range(len(data.layers) - 1, -1, -1):
        if data.layers[position].uid in doomed:
            remove_images(data.layers[position])
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
            canvas = slot.image.copy()
            canvas.name = f'DP {obj.name} {layer.uid} {slot_name}'
            canvas.pack()
            slot.image = canvas
    for key, image in images.items():
        if image is not None:
            copy = image.copy()
            copy.name = f'DP {obj.name} {layer.uid}' + (' mask' if key == 'mask' else '')
            copy.pack()
            setattr(layer, key, copy)
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


def toggle_set_channel(context, obj, data, key):
    item = data.channels[key]
    item.enabled = not item.enabled
    if not item.enabled and data.solo == key:
        data.solo = ''
    return refresh(context, obj, data, f'{CHANNEL[key].label} {"added to" if item.enabled else "removed from"} the texture set.')


def set_solo(context, obj, data, key):
    data.solo = key
    if key.startswith('map:'):
        return refresh(context, obj, data, f'Viewing the {MESH_MAP[key.removeprefix("map:")].label.lower()} map.')
    return refresh(context, obj, data, f'Viewing {CHANNEL[key].label} only.' if key else 'Viewing the full material.')


def bake_mesh_maps(context, obj, data, keys):
    baked = meshmaps.bake_maps(context, obj, data, keys)
    painting.enter_paint_mode(context, obj)
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
        bpy.data.images.remove(mask)
    data.target = 'CONTENT'
    return refresh(context, obj, data, f'Mask removed from {layer.name}.')


def set_target(context, obj, data, target):
    data.target = target
    painting.update_canvas(context, data)
    return 'Painting edits the mask.' if target == 'MASK' else 'Painting edits the layer.'


def export(context, obj, data, directory):
    written = baking.export(context, obj, data, directory, bpy.path.clean_name(obj.name))
    return f'Exported {len(written)} textures to {directory}.'
