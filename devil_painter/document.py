import bpy
from .blending import BLEND_MODES, CHANNEL, CHANNELS
from .masks import GENERATORS
from .procedural import PATTERNS

RESOLUTIONS = (1024, 2048, 4096)
SOURCES = (('VALUE', 'Value', ''), ('IMAGE', 'Texture', ''), ('PATTERN', 'Pattern', ''))
PROJECTIONS = (('UV', 'UV', ''), ('TRIPLANAR', 'Tri-planar', ''))
SLOT_FIELDS = ('enabled', 'source', 'color', 'value', 'color_b', 'value_b', 'blend', 'opacity', 'pattern', 'scale', 'detail', 'contrast')
LAYER_KINDS = (('PAINT', 'Paint', ''), ('FILL', 'Fill', ''), ('FOLDER', 'Folder', ''))


class DEVIL_PAINTER_PG_slot(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)
    color: bpy.props.FloatVectorProperty(size=3, default=(0.8, 0.8, 0.8), min=0.0, max=1.0)
    value: bpy.props.FloatProperty(default=0.5, min=0.0, max=1.0)
    blend: bpy.props.EnumProperty(items=[(key, label, '') for key, label in BLEND_MODES])
    opacity: bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0)
    source: bpy.props.EnumProperty(items=SOURCES)
    image: bpy.props.PointerProperty(type=bpy.types.Image)
    pattern: bpy.props.EnumProperty(items=[(pattern.key, pattern.label, '') for pattern in PATTERNS])
    color_b: bpy.props.FloatVectorProperty(size=3, default=(0.1, 0.1, 0.1), min=0.0, max=1.0)
    value_b: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0)
    scale: bpy.props.FloatProperty(default=8.0, min=0.1, max=1024.0)
    detail: bpy.props.FloatProperty(default=0.5, min=0.0, max=1.0)
    contrast: bpy.props.FloatProperty(default=0.3, min=0.0, max=0.98)


class DEVIL_PAINTER_PG_channel(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)


class DEVIL_PAINTER_PG_map(bpy.types.PropertyGroup):
    image: bpy.props.PointerProperty(type=bpy.types.Image)


class DEVIL_PAINTER_PG_tile(bpy.types.PropertyGroup):
    number: bpy.props.IntProperty(default=1001, min=1001, max=2000)


class DEVIL_PAINTER_PG_tile_image(bpy.types.PropertyGroup):
    key: bpy.props.PointerProperty(type=bpy.types.Image)
    number: bpy.props.IntProperty(default=1001)
    image: bpy.props.PointerProperty(type=bpy.types.Image)


def is_mesh(self, obj):
    return obj.type == 'MESH'


class DEVIL_PAINTER_PG_layer(bpy.types.PropertyGroup):
    uid: bpy.props.StringProperty()
    kind: bpy.props.EnumProperty(items=LAYER_KINDS)
    parent: bpy.props.StringProperty()
    material: bpy.props.StringProperty()
    visible: bpy.props.BoolProperty(default=True)
    opacity: bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0)
    projection: bpy.props.EnumProperty(items=PROJECTIONS)
    generator: bpy.props.EnumProperty(items=[('NONE', 'None', '')] + [(item.key, item.label, '') for item in GENERATORS])
    gen_level: bpy.props.FloatProperty(default=.2, min=-1.0, max=1.0)
    gen_contrast: bpy.props.FloatProperty(default=.5, min=0.0, max=1.0)
    gen_noise: bpy.props.FloatProperty(default=.3, min=0.0, max=1.0)
    gen_scale: bpy.props.FloatProperty(default=20.0, min=.5, max=200.0)
    gen_invert: bpy.props.BoolProperty(default=False)
    tiling: bpy.props.FloatProperty(default=1.0, min=0.05, max=100.0)
    slots: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_slot)
    image: bpy.props.PointerProperty(type=bpy.types.Image)
    mask: bpy.props.PointerProperty(type=bpy.types.Image)


class DEVIL_PAINTER_PG_texture_set(bpy.types.PropertyGroup):
    slot: bpy.props.IntProperty(default=0, min=0)
    tiles: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_tile)
    tile_images: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_tile_image)
    export: bpy.props.BoolProperty(default=True)
    resolution: bpy.props.IntProperty(default=2048, min=64, max=8192)
    channels: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_channel)
    layers: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_layer)
    active_uid: bpy.props.StringProperty()
    target: bpy.props.EnumProperty(items=(('CONTENT', 'Content', ''), ('MASK', 'Mask', '')))
    solo: bpy.props.StringProperty()
    material: bpy.props.PointerProperty(type=bpy.types.Material)
    serial: bpy.props.IntProperty(default=0)
    stroke: bpy.props.PointerProperty(type=bpy.types.Image)
    stroke_owner: bpy.props.StringProperty()
    brush_slots: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_slot)
    brush_opacity: bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0)
    brush_flow: bpy.props.FloatProperty(default=1.0, min=0.01, max=1.0)
    brush_spacing: bpy.props.FloatProperty(default=10.0, min=1.0, max=200.0)
    brush_hardness: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0)
    brush_smoothing: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0)
    brush_jitter: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0)
    brush_random_angle: bpy.props.BoolProperty(default=False)
    brush_pressure_size: bpy.props.BoolProperty(default=False)
    brush_pressure_opacity: bpy.props.BoolProperty(default=True)
    brush_alpha: bpy.props.PointerProperty(type=bpy.types.Image)
    brush_preset: bpy.props.StringProperty(default='Soft Round')
    maps: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_map)
    bake_samples: bpy.props.IntProperty(default=16, min=1, max=256)
    bake_source: bpy.props.PointerProperty(type=bpy.types.Object, poll=is_mesh)


class DEVIL_PAINTER_PG_project(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)
    sets: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_texture_set)
    active_set: bpy.props.IntProperty(default=0, min=0)
    active_tile: bpy.props.IntProperty(default=1001, min=1001, max=2000)
    uv_map: bpy.props.StringProperty()
    export_directory: bpy.props.StringProperty(default='', subtype='DIR_PATH')
    export_template: bpy.props.StringProperty(default='Standard PBR')
    export_depth: bpy.props.StringProperty(default='TEMPLATE')
    export_pattern: bpy.props.StringProperty(default='{mesh}_{set}_{output}')


CLASSES = (DEVIL_PAINTER_PG_slot, DEVIL_PAINTER_PG_channel, DEVIL_PAINTER_PG_map, DEVIL_PAINTER_PG_tile, DEVIL_PAINTER_PG_tile_image,
           DEVIL_PAINTER_PG_layer, DEVIL_PAINTER_PG_texture_set, DEVIL_PAINTER_PG_project)


def project_of(obj):
    if obj is None or obj.type != 'MESH':
        return None
    project = obj.devil_painter
    return project if project.enabled and project.sets else None


def texture_set(obj):
    project = project_of(obj)
    return project.sets[min(project.active_set, len(project.sets) - 1)] if project is not None else None


def active_tile(data):
    project = data.id_data.devil_painter
    numbers = [tile.number for tile in data.tiles] or [1001]
    return project.active_tile if project.active_tile in numbers else numbers[0]


def set_channels(data):
    return [channel for channel in CHANNELS if data.channels[channel.key].enabled]


def add_set_channels(data):
    for channel in CHANNELS:
        item = data.channels.add()
        item.name = channel.key
        item.enabled = channel.on_new_sets


def add_slots(layer):
    fill_slots(layer.slots)


def fill_slots(slots):
    for channel in CHANNELS:
        slot = slots.add()
        slot.name = channel.key
        slot.enabled = channel.on_new_layers
        set_slot_value(slot, channel.default)


def slot_value(slot, second=False):
    if CHANNEL[slot.name].width == 3:
        return tuple(slot.color_b if second else slot.color)
    return (slot.value_b if second else slot.value,)


def set_slot_value(slot, value, second=False):
    if CHANNEL[slot.name].width == 3:
        setattr(slot, 'color_b' if second else 'color', value)
    else:
        setattr(slot, 'value_b' if second else 'value', value[0])


def uses_coordinates(layer):
    return any(slot.enabled and slot.source != 'VALUE' for slot in layer.slots)


def children(layers, parent):
    return [layer for layer in layers if layer.parent == parent]


def descendants(layers, uid):
    found, pending = [], [uid]
    while pending:
        current = pending.pop()
        for layer in layers:
            if layer.parent == current:
                found.append(layer.uid)
                pending.append(layer.uid)
    return found


def shown_layers(layers):
    by_uid = {layer.uid: layer for layer in layers}

    def shown(layer):
        while layer is not None:
            if not layer.visible:
                return False
            layer = by_uid.get(layer.parent)
        return True
    return [layer for layer in layers if shown(layer)]


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
    if editing_mask(data) or layer.kind != 'PAINT':
        return layer.mask
    return layer.image


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.devil_painter = bpy.props.PointerProperty(type=DEVIL_PAINTER_PG_project)


def unregister():
    del bpy.types.Object.devil_painter
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
