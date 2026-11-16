from .document import set_channels, slot_value, uses_coordinates
from .procedural import contrast_range, pattern_node, set_pattern_values

SIGNATURE_KEY = 'devil_painter_signature'
BUMP_DISTANCE = .05
DISPLAY_GAMMA = 2.2
TRIPLANAR_BLEND = .2
SHADER_INPUTS = {'base_color': 'Base Color', 'roughness': 'Roughness', 'metallic': 'Metallic', 'emission': 'Emission Color',
                 'opacity': 'Alpha'}


def socket(sockets, name, kind):
    return next(item for item in sockets if item.name == name and item.type == kind)


def rgba(value):
    return (*value, 1.0) if len(value) == 3 else (value[0], value[0], value[0], 1.0)


def visible_layers(data):
    return [layer for layer in data.layers if layer.visible]


def slot_signature(slot):
    source = slot.source
    if source == 'IMAGE':
        source += slot.image.name if slot.image else ''
    elif source == 'PATTERN':
        source += slot.pattern
    return slot.name + slot.blend + source


def signature(data):
    channels = ','.join(channel.key for channel in set_channels(data))
    layers = '|'.join(':'.join((layer.uid, layer.kind, layer.projection, layer.image.name if layer.image else '',
                                layer.mask.name if layer.mask else '', *(slot_signature(slot) for slot in layer.slots if slot.enabled)))
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


def layer_coordinates(nodes, links, layer, x):
    coordinates = nodes.new('ShaderNodeTexCoord')
    coordinates.location = (x - 600, -400)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.name = layer.uid + '.mapping'
    mapping.location = (x - 450, -400)
    links.new(coordinates.outputs['Object' if layer.projection == 'TRIPLANAR' else 'UV'], mapping.inputs['Vector'])
    return mapping.outputs['Vector']


def slot_content(nodes, links, layer, slot, vector, name, x, y):
    if slot.source == 'IMAGE' and slot.image:
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = slot.image
        texture.location = (x - 250, y - 120)
        if layer.projection == 'TRIPLANAR':
            texture.projection = 'BOX'
            texture.projection_blend = TRIPLANAR_BLEND
        links.new(vector, texture.inputs['Vector'])
        return texture.outputs['Color']
    if slot.source == 'PATTERN':
        texture, factor = pattern_node(nodes, slot.pattern, name + '.texture', (x - 450, y - 120))
        links.new(vector, texture.inputs['Vector'])
        contrast = nodes.new('ShaderNodeMapRange')
        contrast.name = name + '.contrast'
        contrast.location = (x - 300, y - 120)
        links.new(factor, contrast.inputs['Value'])
        mix = nodes.new('ShaderNodeMix')
        mix.name = name + '.pattern'
        mix.data_type = 'RGBA'
        mix.location = (x - 150, y - 120)
        links.new(contrast.outputs['Result'], socket(mix.inputs, 'Factor', 'VALUE'))
        return socket(mix.outputs, 'Result', 'RGBA')
    return None


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


def solo_shader(nodes, links, channel, result, x, raw):
    emission = nodes.new('ShaderNodeEmission')
    emission.location = (x, 300)
    if raw or channel.srgb:
        links.new(result, emission.inputs['Color'])
    else:
        gamma = nodes.new('ShaderNodeGamma')
        gamma.location = (x - 200, 300)
        gamma.inputs['Gamma'].default_value = DISPLAY_GAMMA
        links.new(result, gamma.inputs['Color'])
        links.new(gamma.outputs['Color'], emission.inputs['Color'])
    return emission.outputs[0]


def build_tree(tree, channels, layers, solo=None, raw=False):
    nodes, links = tree.nodes, tree.links
    nodes.clear()
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
        coverage, painted = layer_coverage(nodes, links, layer, x)
        vector = layer_coordinates(nodes, links, layer, x) if uses_coordinates(layer) else None
        for row, channel in enumerate(channels):
            slot = layer.slots[channel.key]
            if not slot.enabled:
                continue
            name = f'{layer.uid}.{channel.key}'
            y = 300 - 250 * row
            node = nodes.new('ShaderNodeMix')
            node.name = name
            node.data_type = 'RGBA'
            node.blend_type = slot.blend
            node.clamp_result = True
            node.location = (x, y)
            links.new(results[channel.key], socket(node.inputs, 'A', 'RGBA'))
            links.new(coverage, socket(node.inputs, 'Factor', 'VALUE'))
            content = painted if channel.key == 'base_color' and painted is not None else slot_content(nodes, links, layer, slot, vector, name, x, y)
            if content is not None:
                links.new(content, socket(node.inputs, 'B', 'RGBA'))
            results[channel.key] = socket(node.outputs, 'Result', 'RGBA')
    for key, name in SHADER_INPUTS.items():
        if key in results:
            links.new(results[key], shader.inputs[name])
    if 'emission' in results:
        shader.inputs['Emission Strength'].default_value = 1.0
    normal = surface_normal(nodes, links, results, end)
    if normal is not None:
        links.new(normal, shader.inputs['Normal'])
    surface = solo_shader(nodes, links, solo, results[solo.key], end + 300, raw) if solo else shader.outputs[0]
    links.new(surface, output.inputs['Surface'])


def write_values(nodes, channels, layers):
    for layer in layers:
        nodes[layer.uid + '.opacity'].inputs[1].default_value = layer.opacity
        if uses_coordinates(layer):
            nodes[layer.uid + '.mapping'].inputs['Scale'].default_value = (layer.tiling,) * 3
        for channel in channels:
            slot = layer.slots[channel.key]
            if not slot.enabled or (channel.key == 'base_color' and layer.kind == 'PAINT'):
                continue
            name = f'{layer.uid}.{channel.key}'
            if slot.source == 'PATTERN':
                mix = nodes[name + '.pattern']
                socket(mix.inputs, 'A', 'RGBA').default_value = rgba(slot_value(slot))
                socket(mix.inputs, 'B', 'RGBA').default_value = rgba(slot_value(slot, second=True))
                set_pattern_values(nodes[name + '.texture'], slot.pattern, slot.scale, slot.detail)
                contrast = nodes[name + '.contrast']
                contrast.inputs['From Min'].default_value, contrast.inputs['From Max'].default_value = contrast_range(slot.pattern, slot.contrast)
            elif slot.source == 'VALUE' or slot.image is None:
                socket(nodes[name].inputs, 'B', 'RGBA').default_value = rgba(slot_value(slot))


def solo_channel(data):
    return next((channel for channel in set_channels(data) if channel.key == data.solo), None)


def rebuild(data, solo=None, raw=False):
    material = data.material
    build_tree(material.node_tree, set_channels(data), visible_layers(data), solo or solo_channel(data), raw)
    material[SIGNATURE_KEY] = '' if raw else signature(data)


def update_values(data):
    write_values(data.material.node_tree.nodes, set_channels(data), visible_layers(data))


def sync(data):
    if data.material.get(SIGNATURE_KEY) != signature(data):
        rebuild(data)
    update_values(data)


def assign_image_colorspace(image, channel):
    if image.colorspace_settings.is_data == channel.srgb:
        image.colorspace_settings.name = 'sRGB' if channel.srgb else 'Non-Color'
