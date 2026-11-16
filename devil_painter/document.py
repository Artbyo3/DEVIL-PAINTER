import bpy
from .blending import BASE_METALLIC, BASE_ROUGHNESS, BLEND_MODES

RESOLUTIONS = (1024, 2048, 4096)


class DEVIL_PAINTER_PG_layer(bpy.types.PropertyGroup):
    uid: bpy.props.StringProperty()
    kind: bpy.props.EnumProperty(items=(('PAINT', 'Paint', ''), ('FILL', 'Fill', '')))
    visible: bpy.props.BoolProperty(default=True)
    opacity: bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0)
    blend: bpy.props.EnumProperty(items=[(key, label, '') for key, label in BLEND_MODES])
    color: bpy.props.FloatVectorProperty(subtype='COLOR', size=3, default=(0.8, 0.8, 0.8), min=0.0, max=1.0)
    use_color: bpy.props.BoolProperty(default=True)
    roughness: bpy.props.FloatProperty(default=BASE_ROUGHNESS, min=0.0, max=1.0)
    use_roughness: bpy.props.BoolProperty(default=True)
    metallic: bpy.props.FloatProperty(default=BASE_METALLIC, min=0.0, max=1.0)
    use_metallic: bpy.props.BoolProperty(default=True)
    image: bpy.props.PointerProperty(type=bpy.types.Image)
    mask: bpy.props.PointerProperty(type=bpy.types.Image)


class DEVIL_PAINTER_PG_texture_set(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(default=False)
    resolution: bpy.props.IntProperty(default=2048, min=64, max=8192)
    layers: bpy.props.CollectionProperty(type=DEVIL_PAINTER_PG_layer)
    active: bpy.props.IntProperty(default=0, min=0)
    paint_mask: bpy.props.BoolProperty(default=False)
    material: bpy.props.PointerProperty(type=bpy.types.Material)
    serial: bpy.props.IntProperty(default=0)
    export_directory: bpy.props.StringProperty(default='', subtype='DIR_PATH')


CLASSES = (DEVIL_PAINTER_PG_layer, DEVIL_PAINTER_PG_texture_set)


def texture_set(obj):
    if obj is None or obj.type != 'MESH':
        return None
    data = obj.devil_painter
    return data if data.enabled else None


def active_layer(data):
    if not data.layers:
        return None
    return data.layers[min(data.active, len(data.layers) - 1)]


def paint_target(data):
    layer = active_layer(data)
    if layer is None:
        return None
    if data.paint_mask or layer.kind == 'FILL':
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
