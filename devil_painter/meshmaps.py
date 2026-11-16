from dataclasses import dataclass
import bpy
from . import compositing
from .baking import bake_scene

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


def node(nodes, kind, **inputs):
    item = nodes.new(kind)
    for name, value in inputs.items():
        item.inputs[name].default_value = value
    return item


def operate(nodes, links, operation, first, second):
    item = nodes.new('ShaderNodeMath')
    item.operation = operation
    item.use_clamp = operation in {'ADD', 'MULTIPLY'}
    for index, value in enumerate((first, second)):
        if isinstance(value, float):
            item.inputs[index].default_value = value
        else:
            links.new(value, item.inputs[index])
    return item.outputs[0]


def map_signal(nodes, links, key, size):
    if key == 'ao':
        return node(nodes, 'ShaderNodeAmbientOcclusion', Distance=size * .25).outputs['AO']
    if key == 'thickness':
        occlusion = nodes.new('ShaderNodeAmbientOcclusion')
        occlusion.inside = True
        occlusion.inputs['Distance'].default_value = size * .5
        return operate(nodes, links, 'SUBTRACT', 1.0, occlusion.outputs['AO'])
    if key == 'curvature':
        geometry = nodes.new('ShaderNodeNewGeometry')
        bevel = node(nodes, 'ShaderNodeBevel', Radius=size * .02)
        dot = nodes.new('ShaderNodeVectorMath')
        dot.operation = 'DOT_PRODUCT'
        links.new(bevel.outputs['Normal'], dot.inputs[0])
        links.new(geometry.outputs['Normal'], dot.inputs[1])
        edge = operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'SUBTRACT', 1.0, dot.outputs['Value']), 12.0)
        local = nodes.new('ShaderNodeAmbientOcclusion')
        local.only_local = True
        local.inputs['Distance'].default_value = size * .04
        sign = operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'SUBTRACT', local.outputs['AO'], .8), 5.0)
        signed = nodes.new('ShaderNodeClamp')
        signed.inputs['Min'].default_value = -1.0
        links.new(sign, signed.inputs['Value'])
        return operate(nodes, links, 'ADD', .5, operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'MULTIPLY', edge, .5), signed.outputs['Result']))
    if key == 'position':
        return nodes.new('ShaderNodeTexCoord').outputs['Generated']
    if key == 'world_normal':
        geometry = nodes.new('ShaderNodeNewGeometry')
        scaled = nodes.new('ShaderNodeVectorMath')
        scaled.operation = 'MULTIPLY_ADD'
        links.new(geometry.outputs['Normal'], scaled.inputs[0])
        scaled.inputs[1].default_value = (.5, .5, .5)
        scaled.inputs[2].default_value = (.5, .5, .5)
        return scaled.outputs['Vector']
    geometry = nodes.new('ShaderNodeNewGeometry')
    color = nodes.new('ShaderNodeCombineColor')
    color.mode = 'HSV'
    links.new(geometry.outputs['Random Per Island'], color.inputs[0])
    color.inputs[1].default_value, color.inputs[2].default_value = .75, .9
    return color.outputs['Color']


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

