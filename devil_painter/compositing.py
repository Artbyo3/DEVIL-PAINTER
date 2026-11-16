from pathlib import Path
import bpy
import numpy
from .blending import composite, linear_to_srgb, srgb_to_linear
from .document import set_channels, slot_value

SIGNATURE_KEY = 'devil_painter_signature'
BUMP_DISTANCE = .05
DISPLAY_GAMMA = 2.2
SHADER_INPUTS = {'base_color': 'Base Color', 'roughness': 'Roughness', 'metallic': 'Metallic', 'emission': 'Emission Color',
                 'opacity': 'Alpha'}


def socket(sockets, name, kind):
    return next(item for item in sockets if item.name == name and item.type == kind)


def rgba(value):
    return (*value, 1.0) if len(value) == 3 else (value[0], value[0], value[0], 1.0)


def visible_layers(data):
    return [layer for layer in data.layers if layer.visible]


def signature(data):
    channels = ','.join(channel.key for channel in set_channels(data))
    layers = '|'.join(':'.join((layer.uid, layer.kind, layer.image.name if layer.image else '', layer.mask.name if layer.mask else '',
                                *(slot.name + slot.blend for slot in layer.slots if slot.enabled)))
                      for layer in visible_layers(data))
    return f'{channels};{data.solo};{layers}'


def layer_coverage(nodes, links, layer, x):
    factor = nodes.new('ShaderNodeMath')
    factor.name = layer.uid + '.opacity'
    factor.operation = 'MULTIPLY'
    factor.location = (x - 150, -900)
    factor.inputs[0].default_value = 1.0
    coverage, source = factor.outputs[0], None
    if layer.kind == 'PAINT' and layer.image:
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = layer.image
        texture.location = (x - 300, -1100)
        links.new(texture.outputs['Alpha'], factor.inputs[0])
        source = texture.outputs['Color']
    if layer.mask:
        mask = nodes.new('ShaderNodeTexImage')
        mask.image = layer.mask
        mask.location = (x - 300, -1350)
        masked = nodes.new('ShaderNodeMath')
        masked.operation = 'MULTIPLY'
        masked.location = (x - 50, -1100)
        links.new(coverage, masked.inputs[0])
        links.new(mask.outputs['Alpha'], masked.inputs[1])
        coverage = masked.outputs[0]
    return coverage, source


def surface_normal(nodes, links, results, x):
    normal = None
    if 'normal' in results:
        node = nodes.new('ShaderNodeNormalMap')
        node.location = (x, -600)
        links.new(results['normal'], node.inputs['Color'])
        normal = node.outputs['Normal']
    if 'height' in results:
        bump = nodes.new('ShaderNodeBump')
        bump.location = (x, -800)
        bump.inputs['Distance'].default_value = BUMP_DISTANCE
        links.new(results['height'], bump.inputs['Height'])
        if normal is not None:
            links.new(normal, bump.inputs['Normal'])
        normal = bump.outputs['Normal']
    return normal


def solo_shader(nodes, links, channel, result, x):
    emission = nodes.new('ShaderNodeEmission')
    emission.location = (x, 300)
    if channel.srgb:
        links.new(result, emission.inputs['Color'])
    else:
        gamma = nodes.new('ShaderNodeGamma')
        gamma.location = (x - 200, 300)
        gamma.inputs['Gamma'].default_value = DISPLAY_GAMMA
        links.new(result, gamma.inputs['Color'])
        links.new(gamma.outputs['Color'], emission.inputs['Color'])
    return emission.outputs[0]


def rebuild(data):
    material = data.material
    material.use_nodes = True
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    channels = set_channels(data)
    layers = visible_layers(data)
    end = 300 * len(layers)
    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    output.location, shader.location = (end + 600, 0), (end + 300, 0)
    results = {}
    for row, channel in enumerate(channels):
        node = nodes.new('ShaderNodeRGB')
        node.outputs[0].default_value = rgba(channel.default)
        node.location = (-400, 300 - 250 * row)
        results[channel.key] = node.outputs[0]
    for index, layer in enumerate(layers):
        x = 300 * index
        coverage, source = layer_coverage(nodes, links, layer, x)
        for row, channel in enumerate(channels):
            slot = layer.slots[channel.key]
            if not slot.enabled:
                continue
            node = nodes.new('ShaderNodeMix')
            node.name = f'{layer.uid}.{channel.key}'
            node.data_type = 'RGBA'
            node.blend_type = slot.blend
            node.clamp_result = True
            node.location = (x, 300 - 250 * row)
            links.new(results[channel.key], socket(node.inputs, 'A', 'RGBA'))
            links.new(coverage, socket(node.inputs, 'Factor', 'VALUE'))
            if channel.key == 'base_color' and source is not None:
                links.new(source, socket(node.inputs, 'B', 'RGBA'))
            results[channel.key] = socket(node.outputs, 'Result', 'RGBA')
    for key, name in SHADER_INPUTS.items():
        if key in results:
            links.new(results[key], shader.inputs[name])
    if 'emission' in results:
        shader.inputs['Emission Strength'].default_value = 1.0
    normal = surface_normal(nodes, links, results, end)
    if normal is not None:
        links.new(normal, shader.inputs['Normal'])
    solo = next((channel for channel in channels if channel.key == data.solo), None)
    surface = solo_shader(nodes, links, solo, results[solo.key], end + 300) if solo else shader.outputs[0]
    links.new(surface, output.inputs['Surface'])
    material[SIGNATURE_KEY] = signature(data)


def update_values(data):
    nodes = data.material.node_tree.nodes
    channels = set_channels(data)
    for layer in visible_layers(data):
        nodes[layer.uid + '.opacity'].inputs[1].default_value = layer.opacity
        for channel in channels:
            slot = layer.slots[channel.key]
            if not slot.enabled or (channel.key == 'base_color' and layer.kind == 'PAINT'):
                continue
            socket(nodes[f'{layer.uid}.{channel.key}'].inputs, 'B', 'RGBA').default_value = rgba(slot_value(slot))


def sync(data):
    if data.material.get(SIGNATURE_KEY) != signature(data) or not data.material.node_tree:
        rebuild(data)
    update_values(data)


def pixels_of(image, size):
    if image.size[0] != size or image.size[1] != size:
        raise ValueError(f'{image.name} is {image.size[0]} x {image.size[1]}, not {size} x {size}.')
    pixels = numpy.empty(size * size * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(size, size, 4)


def layer_inputs(data):
    size = data.resolution
    result = []
    for layer in visible_layers(data):
        coverage = painted = None
        if layer.kind == 'PAINT' and layer.image:
            pixels = pixels_of(layer.image, size)
            painted = srgb_to_linear(pixels[..., :3])
            coverage = pixels[..., 3:]
        mask = pixels_of(layer.mask, size)[..., 3:] if layer.mask else None
        channels = {slot.name: (painted if slot.name == 'base_color' and painted is not None else slot_value(slot), slot.blend)
                    for slot in layer.slots if slot.enabled}
        result.append(dict(opacity=layer.opacity, coverage=coverage, mask=mask, channels=channels))
    return result


def export(data, directory, stem):
    size = data.resolution
    channels = set_channels(data)
    results = composite(size, channels, layer_inputs(data))
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for channel in channels:
        values = results[channel.key]
        if channel.srgb:
            values = linear_to_srgb(values)
        rgba_pixels = numpy.ones((size, size, 4), dtype=numpy.float32)
        rgba_pixels[..., :3] = values
        image = bpy.data.images.new(f'{stem}_{channel.suffix}', size, size, alpha=False)
        try:
            image.colorspace_settings.name = 'sRGB' if channel.srgb else 'Non-Color'
            image.pixels.foreach_set(rgba_pixels.ravel())
            path = folder / f'{stem}_{channel.suffix}.png'
            image.filepath_raw = str(path)
            image.file_format = 'PNG'
            image.save()
            written.append(path)
        finally:
            bpy.data.images.remove(image)
    return written
