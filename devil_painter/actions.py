import bpy
import numpy
from . import compositing, painting
from .blending import BLEND_MODES
from .document import active_layer

KIND_NAMES = {'PAINT': 'Paint', 'FILL': 'Fill'}


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
    compositing.sync(data)
    painting.update_canvas(context, data)
    bpy.ops.ed.undo_push(message='Devil Painter: ' + message)
    return message


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
    return f'Painting {obj.name} at {resolution} px.' + unwrapped


def add_layer(context, obj, data, kind):
    data.serial += 1
    insert_at = min(data.active + 1, len(data.layers)) if data.layers else 0
    layer = data.layers.add()
    layer.uid = f'L{data.serial}'
    layer.kind = kind
    layer.name = f'{KIND_NAMES[kind]} {sum(1 for item in data.layers if item.kind == kind)}'
    if kind == 'PAINT':
        layer.image = image_for(obj, data, layer.uid, False)
    data.layers.move(len(data.layers) - 1, insert_at)
    data.active = insert_at
    data.paint_mask = False
    return refresh(context, obj, data, f'Added {layer.name}.')


def delete_layer(context, obj, data):
    layer = active_layer(data)
    if layer is None:
        return 'No layer to delete.'
    name = layer.name
    for image in (layer.image, layer.mask):
        if image is not None:
            bpy.data.images.remove(image)
    data.layers.remove(data.active)
    data.active = max(0, min(data.active, len(data.layers) - 1))
    data.paint_mask = False
    return refresh(context, obj, data, f'Deleted {name}.')


def move_layer(context, obj, data, step):
    target = data.active + step
    if not 0 <= target < len(data.layers):
        return 'The layer is already at the edge of the stack.'
    data.layers.move(data.active, target)
    data.active = target
    return refresh(context, obj, data, 'Moved ' + data.layers[target].name + (' up.' if step > 0 else ' down.'))


def select_layer(context, obj, data, index):
    data.active = index
    data.paint_mask = data.paint_mask and data.layers[index].mask is not None
    painting.update_canvas(context, data)
    return f'{data.layers[index].name} selected.'


def toggle_visible(context, obj, data, index):
    layer = data.layers[index]
    layer.visible = not layer.visible
    return refresh(context, obj, data, f'{layer.name} {"shown" if layer.visible else "hidden"}.')


def cycle_blend(context, obj, data):
    layer = active_layer(data)
    keys = [key for key, _ in BLEND_MODES]
    layer.blend = keys[(keys.index(layer.blend) + 1) % len(keys)]
    return refresh(context, obj, data, f'{layer.name} blends with {dict(BLEND_MODES)[layer.blend]}.')


def toggle_channel(context, obj, data, channel):
    layer = active_layer(data)
    key = 'use_' + channel
    setattr(layer, key, not getattr(layer, key))
    return refresh(context, obj, data, f'{channel.title()} {"on" if getattr(layer, key) else "off"} for {layer.name}.')


def set_value(context, obj, data, key, value):
    layer = active_layer(data)
    setattr(layer, key, max(0.0, min(1.0, value)))
    compositing.update_values(data)


def commit_value(context, obj, data, key):
    return refresh(context, obj, data, f'{key.title()} of {active_layer(data).name} set.')


def add_mask(context, obj, data, white):
    layer = active_layer(data)
    layer.mask = image_for(obj, data, layer.uid + ' mask', white)
    data.paint_mask = True
    return refresh(context, obj, data, f'{"White" if white else "Black"} mask added to {layer.name}. Painting now edits the mask.')


def remove_mask(context, obj, data):
    layer = active_layer(data)
    mask = layer.mask
    layer.mask = None
    if mask is not None:
        bpy.data.images.remove(mask)
    data.paint_mask = False
    return refresh(context, obj, data, f'Mask removed from {layer.name}.')


def set_paint_mask(context, obj, data, enabled):
    data.paint_mask = enabled
    painting.update_canvas(context, data)
    return 'Painting edits the mask.' if enabled else 'Painting edits the layer.'


def export(context, obj, data, directory):
    written = compositing.export(data, directory, bpy.path.clean_name(obj.name))
    return f'Exported {len(written)} textures to {directory}.'
