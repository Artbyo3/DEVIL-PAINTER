from dataclasses import dataclass
import bpy
from . import compositing
from .baking import bake_scene
from .signals import map_signal

BAKE_MARGIN = 16
CAGE_EXTRUSION = .1


@dataclass(frozen=True)
class MeshMap:
    key: str
    label: str
    needs_source: bool = False


MESH_MAPS = (MeshMap('ao', 'Ambient occlusion'), MeshMap('curvature', 'Curvature'), MeshMap('thickness', 'Thickness'),
             MeshMap('position', 'Position'), MeshMap('world_normal', 'World normal'), MeshMap('id', 'ID'),
             MeshMap('normal', 'Normal', needs_source=True))
MESH_MAP = {item.key: item for item in MESH_MAPS}


def object_size(obj):
    return max(max(obj.dimensions), 1e-3)


def map_image(obj, data, key):
    item = data.maps.get(key)
    if item is None:
        item = data.maps.add()
        item.name = key
    image = item.image
    if image is None or tuple(image.size) != (data.resolution, data.resolution):
        image = bpy.data.images.new(f'DP {obj.name} {key} map', data.resolution, data.resolution, alpha=True)
        image.colorspace_settings.name = 'Non-Color'
        item.image = image
    image.generated_color = (0.0, 0.0, 0.0, 0.0)
    image.source = 'GENERATED'
    return image


def target_node(tree, image):
    target = tree.nodes.new('ShaderNodeTexImage')
    target.image = image
    tree.nodes.active = target
    return target


def bake_signal(tree, key, size, image):
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    emission = nodes.new('ShaderNodeEmission')
    links.new(map_signal(nodes, links, key, size), emission.inputs['Color'])
    links.new(emission.outputs[0], output.inputs['Surface'])
    target_node(tree, image)
    bpy.ops.object.bake(type='EMIT', margin=BAKE_MARGIN, use_clear=True, target='IMAGE_TEXTURES')


def bake_normal(context, obj, data, image):
    source = data.bake_source
    tree = data.material.node_tree
    tree.nodes.clear()
    target_node(tree, image)
    source.hide_render = False
    source.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT', use_selected_to_active=True, cage_extrusion=CAGE_EXTRUSION * object_size(obj),
                        margin=BAKE_MARGIN, use_clear=True, target='IMAGE_TEXTURES')
    source.select_set(False)


def bake_maps(context, obj, data, keys):
    size = object_size(obj)
    baked = []
    with bake_scene(context, obj, data.bake_samples):
        try:
            for key in keys:
                if MESH_MAP[key].needs_source and data.bake_source is None:
                    continue
                image = map_image(obj, data, key)
                if key == 'normal':
                    bake_normal(context, obj, data, image)
                else:
                    bake_signal(data.material.node_tree, key, size, image)
                image.pack()
                baked.append(key)
        finally:
            data.material[compositing.SIGNATURE_KEY] = ''
            compositing.sync(data)
    return baked

