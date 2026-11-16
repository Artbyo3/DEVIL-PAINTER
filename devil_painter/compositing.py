from pathlib import Path
import bpy
import numpy
from .blending import BASE_COLOR, BASE_METALLIC, BASE_ROUGHNESS, composite, linear_to_srgb, srgb_to_linear

SIGNATURE_KEY = 'devil_painter_signature'
EXPORT_CHANNELS = (('base_color', 'BaseColor', 'sRGB'), ('roughness', 'Roughness', 'Non-Color'), ('metallic', 'Metallic', 'Non-Color'))


def socket(sockets, name, kind):
    return next(item for item in sockets if item.name == name and item.type == kind)


def signature(data):
    return '|'.join(':'.join((layer.uid, layer.kind, layer.blend, str(int(layer.use_color)), str(int(layer.use_roughness)),
                              str(int(layer.use_metallic)), layer.image.name if layer.image else '', layer.mask.name if layer.mask else ''))
                    for layer in data.layers if layer.visible)


def mix_node(nodes, links, kind, name, below, x, y):
    node = nodes.new('ShaderNodeMix')
    node.name = name
    node.data_type = kind
    node.clamp_result = True
    node.location = (x, y)
    links.new(below, socket(node.inputs, 'A', kind if kind == 'RGBA' else 'VALUE'))
    return node


def constant(nodes, kind, value, x, y):
    node = nodes.new('ShaderNodeRGB' if kind == 'RGBA' else 'ShaderNodeValue')
    node.outputs[0].default_value = (*value, 1.0) if kind == 'RGBA' else value
    node.location = (x, y)
    return node.outputs[0]


def rebuild(data):
    material = data.material
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    output.location, shader.location = (400 + 300 * len(data.layers), 0), (100 + 300 * len(data.layers), 0)
    links.new(shader.outputs[0], output.inputs[0])
    color = constant(nodes, 'RGBA', BASE_COLOR, -400, 300)
    roughness = constant(nodes, 'VALUE', BASE_ROUGHNESS, -400, 0)
    metallic = constant(nodes, 'VALUE', BASE_METALLIC, -400, -200)
    for index, layer in enumerate(item for item in data.layers if item.visible):
        x = 300 * index
        factor = nodes.new('ShaderNodeMath')
        factor.name = layer.uid + '.opacity'
        factor.operation = 'MULTIPLY'
        factor.location = (x - 150, -500)
        factor.inputs[0].default_value = 1.0
        coverage = factor.outputs[0]
        source = None
        if layer.kind == 'PAINT' and layer.image:
            texture = nodes.new('ShaderNodeTexImage')
            texture.image = layer.image
            texture.location = (x - 300, -700)
            links.new(texture.outputs['Alpha'], factor.inputs[0])
            source = texture.outputs['Color']
        if layer.mask:
            mask = nodes.new('ShaderNodeTexImage')
            mask.image = layer.mask
            mask.location = (x - 300, -950)
            masked = nodes.new('ShaderNodeMath')
            masked.operation = 'MULTIPLY'
            masked.location = (x - 50, -700)
            links.new(coverage, masked.inputs[0])
            links.new(mask.outputs['Alpha'], masked.inputs[1])
            coverage = masked.outputs[0]
        if layer.use_color:
            node = mix_node(nodes, links, 'RGBA', layer.uid + '.color', color, x, 300)
            node.blend_type = layer.blend
            links.new(coverage, socket(node.inputs, 'Factor', 'VALUE'))
            if source is not None:
                links.new(source, socket(node.inputs, 'B', 'RGBA'))
            color = socket(node.outputs, 'Result', 'RGBA')
        for channel, below in (('roughness', roughness), ('metallic', metallic)):
            if not getattr(layer, 'use_' + channel):
                continue
            node = mix_node(nodes, links, 'FLOAT', layer.uid + '.' + channel, below, x, 0 if channel == 'roughness' else -200)
            links.new(coverage, socket(node.inputs, 'Factor', 'VALUE'))
            if channel == 'roughness':
                roughness = socket(node.outputs, 'Result', 'VALUE')
            else:
                metallic = socket(node.outputs, 'Result', 'VALUE')
    links.new(color, shader.inputs['Base Color'])
    links.new(roughness, shader.inputs['Roughness'])
    links.new(metallic, shader.inputs['Metallic'])
    material[SIGNATURE_KEY] = signature(data)


def update_values(data):
    nodes = data.material.node_tree.nodes
    for layer in data.layers:
        if not layer.visible:
            continue
        nodes[layer.uid + '.opacity'].inputs[1].default_value = layer.opacity
        if layer.use_color and layer.kind == 'FILL':
            socket(nodes[layer.uid + '.color'].inputs, 'B', 'RGBA').default_value = (*layer.color, 1.0)
        if layer.use_roughness:
            socket(nodes[layer.uid + '.roughness'].inputs, 'B', 'VALUE').default_value = layer.roughness
        if layer.use_metallic:
            socket(nodes[layer.uid + '.metallic'].inputs, 'B', 'VALUE').default_value = layer.metallic


def sync(data):
    if data.material.get(SIGNATURE_KEY) != signature(data) or not data.material.node_tree:
        rebuild(data)
    update_values(data)


def alpha_of(image, size):
    if image.size[0] != size or image.size[1] != size:
        raise ValueError(f'{image.name} is {image.size[0]} x {image.size[1]}, not {size} x {size}.')
    pixels = numpy.empty(size * size * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(size, size, 4)


def layer_inputs(data):
    size = data.resolution
    result = []
    for layer in data.layers:
        if not layer.visible:
            continue
        color = numpy.array(layer.color, dtype=numpy.float32)
        coverage = None
        if layer.kind == 'PAINT' and layer.image:
            pixels = alpha_of(layer.image, size)
            color = srgb_to_linear(pixels[..., :3])
            coverage = pixels[..., 3:]
        mask = alpha_of(layer.mask, size)[..., 3:] if layer.mask else None
        result.append(dict(opacity=layer.opacity, coverage=coverage, mask=mask, blend=layer.blend, color=color,
                           use_color=layer.use_color, roughness=layer.roughness, use_roughness=layer.use_roughness,
                           metallic=layer.metallic, use_metallic=layer.use_metallic))
    return result


def export(data, directory, stem):
    size = data.resolution
    channels = composite(size, layer_inputs(data))
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for key, suffix, colorspace in EXPORT_CHANNELS:
        values = channels[key]
        if key == 'base_color':
            values = linear_to_srgb(values)
        rgba = numpy.ones((size, size, 4), dtype=numpy.float32)
        rgba[..., :3] = values
        image = bpy.data.images.new(f'{stem}_{suffix}', size, size, alpha=False)
        try:
            image.colorspace_settings.name = colorspace
            image.pixels.foreach_set(rgba.ravel())
            path = folder / f'{stem}_{suffix}.png'
            image.filepath_raw = str(path)
            image.file_format = 'PNG'
            image.save()
            written.append(path)
        finally:
            bpy.data.images.remove(image)
    return written
