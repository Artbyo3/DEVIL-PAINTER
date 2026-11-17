from .document import active_tile, children, set_channels, shown_layers, slot_value, uses_coordinates
from .masks import generator_mask, write_generator
from .procedural import contrast_range, pattern_node, set_pattern_values
from .tiles import numbers, variant

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


def math_node(nodes, links, operation, first, second, x=0, y=0, name=''):
    node = nodes.new('ShaderNodeMath')
    node.operation = operation
    node.location = (x, y)
    if name:
        node.name = name
    for index, value in enumerate((first, second)):
        if isinstance(value, float):
            node.inputs[index].default_value = value
        else:
            links.new(value, node.inputs[index])
    return node.outputs[0]


class Sampler:
    def __init__(self, nodes, links, tile_numbers, lookup, uv_map):
        self.nodes, self.links, self.tile_numbers, self.lookup, self.uv_map = nodes, links, tile_numbers, lookup, uv_map
        self.cache = {}

    def uv(self):
        if 'uv' not in self.cache:
            node = self.nodes.new('ShaderNodeUVMap')
            node.uv_map = self.uv_map
            node.location = (-1400, -1200)
            self.cache['uv'] = node.outputs['UV']
        return self.cache['uv']

    def tile_index(self):
        if 'index' not in self.cache:
            split = self.nodes.new('ShaderNodeSeparateXYZ')
            split.location = (-1250, -1200)
            self.links.new(self.uv(), split.inputs['Vector'])
            column = math_node(self.nodes, self.links, 'FLOOR', split.outputs['X'], 0.0, -1100, -1150)
            row = math_node(self.nodes, self.links, 'FLOOR', split.outputs['Y'], 0.0, -1100, -1250)
            self.cache['index'] = math_node(self.nodes, self.links, 'ADD', math_node(self.nodes, self.links, 'MULTIPLY', row, 10.0, -950, -1200), column, -800, -1200)
        return self.cache['index']

    def is_tile(self, number):
        key = ('tile', number)
        if key not in self.cache:
            node = self.nodes.new('ShaderNodeMath')
            node.operation = 'COMPARE'
            node.location = (-650, -1200)
            self.links.new(self.tile_index(), node.inputs[0])
            node.inputs[1].default_value = float(number - 1001)
            node.inputs[2].default_value = .5
            self.cache[key] = node.outputs[0]
        return self.cache[key]

    def texture(self, image, vector, location):
        node = self.nodes.new('ShaderNodeTexImage')
        node.image = image
        node.location = location
        self.links.new(vector if vector is not None else self.uv(), node.inputs['Vector'])
        return node

    def sample(self, image, vector=None, location=(0, 0)):
        tiles = [(number, self.lookup(image, number)) for number in self.tile_numbers]
        if len({tile.name for _, tile in tiles}) == 1:
            node = self.texture(image, vector, location)
            return node.outputs['Color'], node.outputs['Alpha']
        color = alpha = None
        for index, (number, tile) in enumerate(tiles):
            node = self.texture(tile, None, (location[0], location[1] - 120 * index))
            if color is None:
                color, alpha = node.outputs['Color'], node.outputs['Alpha']
                continue
            mix = self.nodes.new('ShaderNodeMix')
            mix.data_type = 'RGBA'
            self.links.new(self.is_tile(number), socket(mix.inputs, 'Factor', 'VALUE'))
            self.links.new(color, socket(mix.inputs, 'A', 'RGBA'))
            self.links.new(node.outputs['Color'], socket(mix.inputs, 'B', 'RGBA'))
            blend = self.nodes.new('ShaderNodeMix')
            blend.data_type = 'FLOAT'
            self.links.new(self.is_tile(number), socket(blend.inputs, 'Factor', 'VALUE'))
            self.links.new(alpha, socket(blend.inputs, 'A', 'VALUE'))
            self.links.new(node.outputs['Alpha'], socket(blend.inputs, 'B', 'VALUE'))
            color, alpha = socket(mix.outputs, 'Result', 'RGBA'), socket(blend.outputs, 'Result', 'VALUE')
        return color, alpha


class Build:
    def __init__(self, nodes, links, sampler, stroke=None, maps=None, live=False, size=1.0, active=1001):
        self.nodes, self.links, self.sampler, self.stroke = nodes, links, sampler, stroke
        self.maps, self.live, self.size, self.active = maps or {}, live, size, active


def slot_signature(slot):
    source = slot.source
    if source == 'IMAGE':
        source += slot.image.name if slot.image else ''
    elif source == 'PATTERN':
        source += slot.pattern
    return slot.name + slot.blend + source


def signature(data):
    channels = ','.join(channel.key for channel in set_channels(data))
    maps = ','.join(item.name for item in data.maps if item.image is not None)
    layers = '|'.join(':'.join((layer.uid, layer.kind, layer.parent, layer.projection, layer.generator, layer.image.name if layer.image else '',
                                layer.mask.name if layer.mask else '', *(slot_signature(slot) for slot in layer.slots if slot.enabled)))
                      for layer in shown_layers(data.layers))
    stroke = stroke_link(data)
    owner = f'{stroke[0]}:{",".join(stroke[2])}:{active_tile(data)}' if stroke else ''
    tiles = ','.join(str(number) for number in numbers(data))
    return f'{channels};{data.solo};{layers};{owner};{maps};{tiles};{data.id_data.devil_painter.uv_map}'


def stroke_over(build, image, alpha, color, x):
    nodes, links = build.nodes, build.links
    texture = build.sampler.texture(image, None, (x - 300, -1600))
    added = math_node(nodes, links, 'MINIMUM', texture.outputs['Alpha'], 1.0, x - 150, -1600, 'stroke.opacity')
    if len(build.sampler.tile_numbers) > 1:
        added = math_node(nodes, links, 'MULTIPLY', added, build.sampler.is_tile(build.active), x - 150, -1650)
    total = math_node(nodes, links, 'SUBTRACT', math_node(nodes, links, 'ADD', alpha, added, x - 150, -1700),
                      math_node(nodes, links, 'MULTIPLY', alpha, added, x - 150, -1800), x, -1700)
    weight = math_node(nodes, links, 'DIVIDE', added, math_node(nodes, links, 'MAXIMUM', total, 1e-4, x, -1800), x + 150, -1700)
    mix = nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.location = (x + 150, -1500)
    links.new(weight, socket(mix.inputs, 'Factor', 'VALUE'))
    links.new(color, socket(mix.inputs, 'A', 'RGBA'))
    links.new(texture.outputs['Color'], socket(mix.inputs, 'B', 'RGBA'))
    return total, socket(mix.outputs, 'Result', 'RGBA'), weight


def layer_coverage(build, layer, x, stroke=None):
    nodes, links = build.nodes, build.links
    factor = nodes.new('ShaderNodeMath')
    factor.name = layer.uid + '.opacity'
    factor.operation = 'MULTIPLY'
    factor.location = (x - 150, -900)
    factor.inputs[0].default_value = 1.0
    coverage, source, weight = factor.outputs[0], None, None
    if layer.kind == 'PAINT' and layer.image:
        source, alpha = build.sampler.sample(layer.image, None, (x - 300, -1100))
        if stroke is not None:
            alpha, source, weight = stroke_over(build, stroke, alpha, source, x)
        links.new(alpha, factor.inputs[0])
    if layer.mask:
        _, mask = build.sampler.sample(layer.mask, None, (x - 300, -1350))
        coverage = math_node(nodes, links, 'MULTIPLY', coverage, mask, x - 50, -1100)
    if layer.generator != 'NONE':
        generated = generator_mask(nodes, links, layer, build)
        if generated is not None:
            coverage = math_node(nodes, links, 'MULTIPLY', coverage, generated, x - 50, -1250)
    return coverage, source, weight


def layer_coordinates(nodes, links, layer, x):
    coordinates = nodes.new('ShaderNodeTexCoord')
    coordinates.location = (x - 600, -400)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.name = layer.uid + '.mapping'
    mapping.location = (x - 450, -400)
    links.new(coordinates.outputs['Object' if layer.projection == 'TRIPLANAR' else 'UV'], mapping.inputs['Vector'])
    return mapping.outputs['Vector']


def slot_content(build, layer, slot, vector, name, x, y):
    nodes, links = build.nodes, build.links
    if slot.source == 'IMAGE' and slot.image:
        if layer.kind == 'PAINT':
            return build.sampler.sample(slot.image, None, (x - 250, y - 120))[0]
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


def surface_normal(build, results, x):
    nodes, links = build.nodes, build.links
    normal = None
    if 'normal' in results:
        node = nodes.new('ShaderNodeNormalMap')
        node.uv_map = build.sampler.uv_map
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


def channel_mix(nodes, links, name, below, factor, mode, x, y):
    node = nodes.new('ShaderNodeMix')
    node.name = name
    node.data_type = 'RGBA'
    node.blend_type = mode
    node.clamp_result = True
    node.location = (x, y)
    links.new(below, socket(node.inputs, 'A', 'RGBA'))
    links.new(factor, socket(node.inputs, 'Factor', 'VALUE'))
    return node


def compose_layer(build, channels, layer, results, x):
    nodes, links, stroke = build.nodes, build.links, build.stroke
    owner = stroke is not None and stroke[0] == layer.uid
    coverage, painted, weight = layer_coverage(build, layer, x, stroke[1] if owner else None)
    vector = layer_coordinates(nodes, links, layer, x) if uses_coordinates(layer) else None
    for row, channel in enumerate(channels):
        slot = layer.slots[channel.key]
        if not slot.enabled:
            continue
        name = f'{layer.uid}.{channel.key}'
        y = 300 - 250 * row
        factor = math_node(nodes, links, 'MULTIPLY', coverage, 1.0, x - 100, y - 60, name + '.opacity')
        node = channel_mix(nodes, links, name, results[channel.key], factor, slot.blend, x, y)
        content = painted if channel.key == 'base_color' and painted is not None else slot_content(build, layer, slot, vector, name, x, y)
        if owner and channel.key != 'base_color' and channel.key in stroke[2]:
            brushed = nodes.new('ShaderNodeMix')
            brushed.name = name + '.stroke'
            brushed.data_type = 'RGBA'
            brushed.location = (x - 150, y + 60)
            links.new(weight, socket(brushed.inputs, 'Factor', 'VALUE'))
            if content is not None:
                links.new(content, socket(brushed.inputs, 'A', 'RGBA'))
            content = socket(brushed.outputs, 'Result', 'RGBA')
        if content is not None:
            links.new(content, socket(node.inputs, 'B', 'RGBA'))
        results[channel.key] = socket(node.outputs, 'Result', 'RGBA')


def compose(build, channels, layers, parent, results, column):
    for layer in children(layers, parent):
        if not layer.visible:
            continue
        x = 300 * column[0]
        column[0] += 1
        if layer.kind != 'FOLDER':
            compose_layer(build, channels, layer, results, x)
            continue
        below = dict(results)
        inner = compose(build, channels, layers, layer.uid, dict(results), column)
        coverage, _, _ = layer_coverage(build, layer, 300 * column[0])
        for row, channel in enumerate(channels):
            if inner[channel.key] is not below[channel.key]:
                node = channel_mix(build.nodes, build.links, f'{layer.uid}.{channel.key}', below[channel.key], coverage, 'MIX', 300 * column[0],
                                   300 - 250 * row)
                build.links.new(inner[channel.key], socket(node.inputs, 'B', 'RGBA'))
                results[channel.key] = socket(node.outputs, 'Result', 'RGBA')
        column[0] += 1
    return results


def build_tree(build, channels, layers, solo=None, raw=False):
    nodes, links = build.nodes, build.links
    nodes.clear()
    build.sampler.cache.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    results = {}
    for row, channel in enumerate(channels):
        node = nodes.new('ShaderNodeRGB')
        node.outputs[0].default_value = rgba(channel.default)
        node.location = (-400, 300 - 250 * row)
        results[channel.key] = node.outputs[0]
    column = [0]
    results = compose(build, channels, layers, '', results, column)
    end = 300 * column[0]
    output.location, shader.location = (end + 600, 0), (end + 300, 0)
    for key, name in SHADER_INPUTS.items():
        if key in results:
            links.new(results[key], shader.inputs[name])
    if 'emission' in results:
        shader.inputs['Emission Strength'].default_value = 1.0
    normal = surface_normal(build, results, end)
    if normal is not None:
        links.new(normal, shader.inputs['Normal'])
    surface = solo_shader(nodes, links, solo, results[solo.key], end + 300, raw) if solo else shader.outputs[0]
    links.new(surface, output.inputs['Surface'])
    return output


def write_values(nodes, channels, layers, brush=None):
    if brush is not None and 'stroke.opacity' in nodes:
        nodes['stroke.opacity'].inputs[1].default_value = brush[0]
    for layer in shown_layers(layers):
        nodes[layer.uid + '.opacity'].inputs[1].default_value = layer.opacity
        if layer.generator != 'NONE' and layer.uid + '.gen.range' in nodes:
            write_generator(nodes, layer)
        if layer.kind == 'FOLDER':
            continue
        if uses_coordinates(layer):
            nodes[layer.uid + '.mapping'].inputs['Scale'].default_value = (layer.tiling,) * 3
        for channel in channels:
            slot = layer.slots[channel.key]
            if not slot.enabled:
                continue
            name = f'{layer.uid}.{channel.key}'
            nodes[name + '.opacity'].inputs[1].default_value = slot.opacity
            if brush is not None and name + '.stroke' in nodes:
                brushed = nodes[name + '.stroke']
                socket(brushed.inputs, 'B', 'RGBA').default_value = rgba(brush[1][channel.key])
                socket(brushed.inputs, 'A', 'RGBA').default_value = rgba(slot_value(slot))
            if channel.key == 'base_color' and layer.kind == 'PAINT':
                continue
            if slot.source == 'PATTERN':
                mix = nodes[name + '.pattern']
                socket(mix.inputs, 'A', 'RGBA').default_value = rgba(slot_value(slot))
                socket(mix.inputs, 'B', 'RGBA').default_value = rgba(slot_value(slot, second=True))
                set_pattern_values(nodes[name + '.texture'], slot.pattern, slot.scale, slot.detail)
                contrast = nodes[name + '.contrast']
                contrast.inputs['From Min'].default_value, contrast.inputs['From Max'].default_value = contrast_range(slot.pattern, slot.contrast)
            elif slot.source == 'VALUE' or slot.image is None:
                socket(nodes[name].inputs, 'B', 'RGBA').default_value = rgba(slot_value(slot))


def stroke_link(data):
    if not data.stroke_owner or data.stroke is None:
        return None
    return data.stroke_owner, data.stroke, tuple(slot.name for slot in data.brush_slots if slot.enabled)


def brush_values(data):
    return data.brush_opacity, {slot.name: slot_value(slot) for slot in data.brush_slots}


def solo_channel(data):
    return next((channel for channel in set_channels(data) if channel.key == data.solo), None)


def show_map(build, output, image):
    color, _ = build.sampler.sample(image, None, (0, 600))
    gamma = build.nodes.new('ShaderNodeGamma')
    gamma.inputs['Gamma'].default_value = DISPLAY_GAMMA
    emission = build.nodes.new('ShaderNodeEmission')
    build.links.new(color, gamma.inputs['Color'])
    build.links.new(gamma.outputs['Color'], emission.inputs['Color'])
    build.links.new(emission.outputs[0], output.inputs['Surface'])


def viewed_map(data):
    item = data.maps.get(data.solo.removeprefix('map:')) if data.solo.startswith('map:') else None
    return item.image if item is not None else None


def set_build(data, tree, raw=False):
    project = data.id_data.devil_painter
    sampler = Sampler(tree.nodes, tree.links, numbers(data), lambda image, number: variant(data, image, number), project.uv_map)
    maps = {item.name: item.image for item in data.maps if item.image is not None}
    return Build(tree.nodes, tree.links, sampler, None if raw else stroke_link(data), maps, False, 1.0, active_tile(data))


def rebuild(data, solo=None, raw=False):
    material = data.material
    build = set_build(data, material.node_tree, raw)
    output = build_tree(build, set_channels(data), list(data.layers), solo or solo_channel(data), raw)
    if not raw and solo is None and viewed_map(data) is not None:
        show_map(build, output, viewed_map(data))
    material[SIGNATURE_KEY] = '' if raw else signature(data)


def update_values(data):
    write_values(data.material.node_tree.nodes, set_channels(data), list(data.layers), brush_values(data))


def sync(data):
    if data.material.get(SIGNATURE_KEY) != signature(data):
        rebuild(data)
    update_values(data)


def assign_image_colorspace(image, channel):
    if image.colorspace_settings.is_data == channel.srgb:
        image.colorspace_settings.name = 'sRGB' if channel.srgb else 'Non-Color'
