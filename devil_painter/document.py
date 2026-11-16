import bpy
from .blending import BLEND_MODES, CHANNEL, CHANNELS

RESOLUTIONS = (1024, 2048, 4096)


class DEVIL_PAINTER_PG_slot(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)
    color: bpy.props.FloatVectorProperty(size=3, default=(0.8, 0.8, 0.8), min=0.0, max=1.0)
    value: bpy.props.FloatProperty(default=0.5, min=0.0, max=1.0)
    blend: bpy.props.EnumProperty(items=[(key, label, '') for key, label in BLEND_MODES])


class DEVIL_PAINTER_PG_channel(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)


class DEVIL_PAINTER_PG_layer(bpy.types.PropertyGroup):
    uid: bpy.props.StringProperty()
    kind: bpy.props.EnumProperty(items=(('PAINT', 'Paint', ''), ('FILL', 'Fill', '')))
    visible: bpy.props.BoolProperty(default=True)
    opacity: bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0)
    slots: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_slot)
    image: bpy.props.PointerProperty(type=bpy.types.Image)
    mask: bpy.props.PointerProperty(type=bpy.types.Image)


class DEVIL_PAINTER_PG_texture_set(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)
    resolution: bpy.props.IntProperty(default=2048, min=64, max=8192)
    channels: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_channel)
    layers: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_layer)
    active_uid: bpy.props.StringProperty()
    target: bpy.props.EnumProperty(items=(('CONTENT', 'Content', ''), ('MASK', 'Mask', '')))
    solo: bpy.props.StringProperty()
    material: bpy.props.PointerProperty(type=bpy.types.Material)
    serial: bpy.props.IntProperty(default=0)
    export_directory: bpy.props.StringProperty(default='', subtype='DIR_PATH')


CLASSES = (DEVIL_PAINTER_PG_slot, DEVIL_PAINTER_PG_channel, DEVIL_PAINTER_PG_layer, DEVIL_PAINTER_PG_texture_set)


def texture_set(obj):
    if obj is None or obj.type != 'MESH':
        return None
    data = obj.devil_painter
    return data if data.enabled else None


def set_channels(data):
    return [channel for channel in CHANNELS if data.channels[channel.key].enabled]


def add_set_channels(data):
    for channel in CHANNELS:
        item = data.channels.add()
        item.name = channel.key
        item.enabled = channel.on_new_sets


def add_slots(layer):
    for channel in CHANNELS:
        slot = layer.slots.add()
        slot.name = channel.key
        slot.enabled = channel.on_new_layers
        set_slot_value(slot, channel.default)


def slot_value(slot):
    return tuple(slot.color) if CHANNEL[slot.name].width == 3 else (slot.value,)


def set_slot_value(slot, value):
    if CHANNEL[slot.name].width == 3:
        slot.color = value
    else:
        slot.value = value[0]


def layer_index(data, uid):
    return next((index for index, layer in enumerate(data.layers) if layer.uid == uid), -1)


def find_layer(data, uid):
    index = layer_index(data, uid)
    return data.layers[index] if index >= 0 else None


def active_layer(data):
    return find_layer(data, data.active_uid)


def editing_mask(data):
    layer = active_layer(data)
    return layer is not None and data.target == 'MASK' and layer.mask is not None


def paint_target(data):
    layer = active_layer(data)
    if layer is None:
        return None
    if editing_mask(data) or layer.kind == 'FILL':
        return layer.mask
    return layer.image


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.devil_painter = bpy.props.PointerProperty(type=DEVIL_PAINTER_PG_texture_set)


def unregister():
    del bpy.types.Object.devil_painter
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
