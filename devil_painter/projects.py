import math
import bpy
from .document import add_set_channels
from .tiles import adopt, face_slots, numbers, slot_tiles

BASIC = ['base_color', 'roughness', 'metallic', 'normal', 'height']
PROJECT_TEMPLATES = (
    dict(name='PBR Metal Rough', channels=BASIC, export='Standard PBR', shader='PRINCIPLED', normal_format='OPENGL'),
    dict(name='PBR Emissive and Transparent', channels=BASIC + ['emission', 'opacity'], export='glTF', shader='PRINCIPLED', normal_format='OPENGL'),
    dict(name='Unreal Engine', channels=BASIC + ['ambient_occlusion', 'emission'], export='Unreal Engine', shader='PRINCIPLED', normal_format='DIRECTX'),
    dict(name='Unity HDRP', channels=BASIC + ['ambient_occlusion'], export='Unity HDRP', shader='PRINCIPLED', normal_format='OPENGL'),
    dict(name='USD Preview Surface', channels=BASIC + ['ambient_occlusion', 'emission', 'opacity'], export='USD Preview Surface', shader='PRINCIPLED',
         normal_format='OPENGL'),
    dict(name='Hand-painted Unlit', channels=['base_color', 'opacity'], export='Standard PBR', shader='UNLIT', normal_format='OPENGL'),
)
UNWRAP_MODES = (('SMART', 'Smart UV'), ('HARD_SURFACE', 'Hard surface'))
SHARP_ANGLE = 30.0
ISLAND_MARGIN = .01
REIMPORT_FORMATS = {'.obj': 'wm.obj_import', '.fbx': 'import_scene.fbx', '.gltf': 'import_scene.gltf', '.glb': 'import_scene.gltf',
                    '.ply': 'wm.ply_import', '.stl': 'wm.stl_import'}


def find_template(name):
    return next((item for item in PROJECT_TEMPLATES if item['name'] == name), PROJECT_TEMPLATES[0])


def apply_template(project, data, template):
    add_set_channels(data)
    for item in data.channels:
        item.enabled = item.name in template['channels']
    data.shader = template['shader']
    project.export_template = template['export']


def unwrap(context, obj, mode):
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    if mode == 'HARD_SURFACE':
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(SHARP_ANGLE))
        bpy.ops.mesh.mark_seam(clear=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=ISLAND_MARGIN)
        bpy.ops.uv.pack_islands(margin=ISLAND_MARGIN)
    else:
        bpy.ops.uv.smart_project(island_margin=ISLAND_MARGIN)
    bpy.ops.object.mode_set(mode='OBJECT')


def owned_keys(data):
    keys = [item.image for item in data.maps if item.image is not None]
    for layer in data.layers:
        keys += [image for image in (layer.image, layer.mask) if image is not None]
        keys += [effect.image for effect in layer.effects if effect.kind == 'PAINT' and effect.image is not None]
        if layer.kind == 'PAINT':
            keys += [slot.image for slot in layer.slots if slot.source == 'IMAGE' and slot.image is not None]
    return keys


def add_tiles(data, found):
    for number in found:
        if number not in numbers(data):
            data.tiles.add().number = number
            for key in owned_keys(data):
                adopt(data, key, (0.0, 0.0, 0.0, 0.0) if not key.colorspace_settings.is_data else (0.5, 0.5, 0.5, 1.0))


def slot_matches(names, slot_materials):
    matches = {}
    for index, name in enumerate(slot_materials):
        match = next((position for position, item in enumerate(names) if name and name in item and position not in matches.values()), None)
        if match is not None:
            matches[index] = match
    for index in range(len(slot_materials)):
        if index not in matches and index < len(names) and index not in matches.values():
            matches[index] = index
    return matches


def swap_mesh(obj, project, mesh):
    names = [{data.name, data.material.name if data.material else ''} for data in project.sets]
    old = obj.data
    obj.data = mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)
    uv = mesh.uv_layers.active
    project.uv_map = uv.name if uv is not None else ''
    matches = slot_matches(names, [slot.material.name if slot.material is not None else '' for slot in obj.material_slots])
    new_slots = [index for index in range(len(obj.material_slots)) if index not in matches]
    for position in range(len(project.sets)):
        if position not in matches.values():
            mesh.materials.append(None)
            matches[len(obj.material_slots) - 1] = position
    used = set(face_slots(mesh).tolist())
    for index, position in matches.items():
        data = project.sets[position]
        data.slot = index
        obj.material_slots[index].material = data.material
        if uv is not None and index in used:
            add_tiles(data, slot_tiles(mesh, uv.name, index, numbers(data) != [1001]))
    faceless = [project.sets[position].name for index, position in sorted(matches.items()) if index not in used]
    return faceless, new_slots


def imported_mesh(filepath):
    suffix = '.' + filepath.rsplit('.', 1)[-1].lower()
    if suffix not in REIMPORT_FORMATS:
        raise ValueError('Reimport supports OBJ, FBX, glTF, PLY, and STL files.')
    before = set(bpy.data.objects)
    group, name = REIMPORT_FORMATS[suffix].split('.')
    getattr(getattr(bpy.ops, group), name)(filepath=filepath)
    created = [item for item in bpy.data.objects if item not in before]
    mesh = next((item.data for item in created if item.type == 'MESH'), None)
    for item in created:
        bpy.data.objects.remove(item)
    if mesh is None:
        raise ValueError('The file has no mesh to reimport.')
    return mesh
