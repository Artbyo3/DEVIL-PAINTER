import math
import bpy
from .document import add_set_channels
from .tiles import adopt, numbers, slot_tiles

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
        if layer.kind == 'PAINT':
            keys += [slot.image for slot in layer.slots if slot.source == 'IMAGE' and slot.image is not None]
    return keys


def add_tiles(data, found):
    for number in found:
        if number not in numbers(data):
            data.tiles.add().number = number
            for key in owned_keys(data):
                adopt(data, key, (0.0, 0.0, 0.0, 0.0) if not key.colorspace_settings.is_data else (0.5, 0.5, 0.5, 1.0))


def swap_mesh(obj, project, mesh):
    names = [{data.name, data.material.name if data.material else ''} for data in project.sets]
    old = obj.data
    obj.data = mesh
    if old.users == 0:
        bpy.data.meshes.remove(old)
    uv = mesh.uv_layers.active
    project.uv_map = uv.name if uv is not None else ''
    while len(obj.material_slots) < len(project.sets):
        mesh.materials.append(None)
    claimed = set()
    for index, slot in enumerate(obj.material_slots):
        name = slot.material.name if slot.material is not None else ''
        match = next((position for position, item in enumerate(names) if name in item and position not in claimed), None)
        if match is None and index < len(names) and index not in claimed:
            match = index
        if match is None:
            continue
        claimed.add(match)
        data = project.sets[match]
        data.slot = index
        slot.material = data.material
        if uv is not None:
            add_tiles(data, slot_tiles(mesh, uv.name, index, numbers(data) != [1001]))
    return len(claimed)


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
