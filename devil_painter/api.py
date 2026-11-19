import json
from pathlib import Path
import bpy
from . import actions, exporting, library, smart
from .document import active_layer, find_layer, set_channels, set_slot_value, slot_value
from .effects import effect_label

__all__ = ['start', 'texture_sets', 'layers', 'add_fill', 'add_paint', 'add_smart_material', 'set_channel', 'add_generator', 'remove_layer',
           'bake', 'export', 'materials', 'material_of', 'smart_materials', 'selected']


def content(value):
    return json.loads(value) if isinstance(value, str) else value


def texture_set_of(obj, set_index=None):
    project = obj.devil_painter
    if not project.sets:
        raise ValueError(f'{obj.name} has no Devil Painter project. Call start() first.')
    index = project.active_set if set_index is None else set_index
    project.active_set = index
    return project.sets[index]


def start(obj, resolution=2048, template='PBR Metal Rough', udim=False, normal_format='OPENGL', normal_space='TANGENT', unwrap='SMART'):
    bpy.context.view_layer.objects.active = obj
    actions.start(bpy.context, obj, (resolution,), udim, template, normal_format, normal_space, unwrap)
    return texture_sets(obj)


def texture_sets(obj):
    return [dict(name=data.name, resolution=data.resolution, channels=[channel.key for channel in set_channels(data)],
                 tiles=[tile.number for tile in data.tiles] or [1001], layers=len(data.layers)) for data in obj.devil_painter.sets]


def layer_record(layer):
    channels = {slot.name: list(slot_value(slot)) for slot in layer.slots if slot.enabled and slot.source == 'VALUE'}
    return dict(uid=layer.uid, name=layer.name, kind=layer.kind, parent=layer.parent, visible=layer.visible, opacity=layer.opacity,
                generators=[effect.generator for effect in layer.effects if effect.kind == 'GENERATOR'], mask=layer.mask is not None, channels=channels,
                effects=[dict(uid=effect.uid, kind=effect.kind, target=effect.target, label=effect_label(effect)) for effect in layer.effects])


def layers(obj, set_index=None):
    data = texture_set_of(obj, set_index)
    return [layer_record(layer) for layer in data.layers]


def add_fill(obj, definition, set_index=None):
    data = texture_set_of(obj, set_index)
    actions.add_material(bpy.context, obj, data, content(definition))
    return data.active_uid


def add_paint(obj, set_index=None):
    data = texture_set_of(obj, set_index)
    actions.add_layer(bpy.context, obj, data, 'PAINT')
    return data.active_uid


def add_smart_material(obj, definition, set_index=None):
    data = texture_set_of(obj, set_index)
    actions.add_smart_material(bpy.context, obj, data, content(definition))
    return data.active_uid


def chosen(obj, uid, set_index):
    data = texture_set_of(obj, set_index)
    layer = find_layer(data, uid)
    if layer is None:
        raise KeyError(f'No layer {uid} in {data.name}.')
    data.active_uid = uid
    return data, layer


def set_channel(obj, uid, channel, value, set_index=None):
    data, layer = chosen(obj, uid, set_index)
    slot = layer.slots[channel]
    slot.enabled, slot.source = True, 'VALUE'
    set_slot_value(slot, tuple(value) if isinstance(value, (list, tuple)) else (float(value),))
    return actions.refresh(bpy.context, obj, data, f'{layer.name} {channel} set from Python.')


def add_generator(obj, uid, set_index=None, **values):
    data, _ = chosen(obj, uid, set_index)
    return actions.add_generator(bpy.context, obj, data, values)


def remove_layer(obj, uid, set_index=None):
    data, _ = chosen(obj, uid, set_index)
    return actions.delete_layer(bpy.context, obj, data)


def bake(obj, maps=('ao', 'curvature', 'position', 'world_normal'), set_index=None):
    data = texture_set_of(obj, set_index)
    return actions.bake_mesh_maps(bpy.context, obj, data, list(maps))


def export(obj, directory, template=None):
    project = obj.devil_painter
    wanted = [index for index, data in enumerate(project.sets) if data.export]
    written = exporting.export(bpy.context, obj, project, exporting.find_template(template or project.export_template), wanted, str(directory),
                               project.export_pattern, project.export_depth, project.export_size, project.export_padding)
    return [str(Path(path)) for path in written]


def materials():
    return json.dumps([*library.BUILTIN_MATERIALS, *library.user_materials()])


def smart_materials():
    return json.dumps([*smart.BUILTIN_SMART, *smart.smart_materials()])


def material_of(obj, uid, set_index=None):
    _, layer = chosen(obj, uid, set_index)
    return json.dumps(library.capture(layer))


def selected(obj, set_index=None):
    layer = active_layer(texture_set_of(obj, set_index))
    return None if layer is None else layer.uid
