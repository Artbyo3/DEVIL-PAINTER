import math
from .blending import MIX_NODE_BLENDS
from .document import PROJECTORS, active_tile, children, folder_mode, geometry_attribute, isolated_uids, linked_layer, set_channels, shown_layers, slot_value, uses_coordinates
from .effects import COMPONENT_FIELDS, CONTENT_KINDS, EFFECT_FIELDS
from .caches import revision, tile, tile_variant
from .filters import FILTER, HEIGHT_FILTERS, filter_color, filter_value, height_normal, slope_blur, slope_weight, wrap_sampling
from .masks import GENERATOR_VALUES, generator_mask, generator_name, id_selection, write_generators
from .nodes import gray, link_or_set, math_node, mix_color, mix_value, socket, vector_math
from .procedural import contrast_range, pattern_node, set_pattern_values
from .tiles import numbers

SIGNATURE_KEY = 'devil_painter_signature'
QUICK_TINT = (1.0, .08, .15, 1.0)
QUICK_SHOW = .6
PIN_CORNERS = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
PREVIEW_TOOLS = {'PAINT', 'FILL', ''}
BUMP_DISTANCE = .05
DISPLAY_GAMMA = 2.2
TRIPLANAR_BLEND = .2
MASK_MIXES = {'MINIMUM': 'DARKEN', 'MAXIMUM': 'LIGHTEN'}
SHADER_INPUTS = {'base_color': 'Base Color', 'roughness': 'Roughness', 'metallic': 'Metallic', 'emission': 'Emission Color',
                 'opacity': 'Alpha'}


def rgba(value):
    return (*value, 1.0) if len(value) == 3 else (value[0], value[0], value[0], 1.0)


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
            node = self.texture(tile, vector, (location[0], location[1] - 120 * index))
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
    def __init__(self, nodes, links, sampler, stroke=None, maps=None, live=False, size=1.0, active=1001, shading=None, data=None, resolution=1024):
        self.nodes, self.links, self.sampler, self.stroke = nodes, links, sampler, stroke
        self.maps, self.live, self.size, self.active = maps or {}, live, size, active
        self.shading = shading or dict(shader='PRINCIPLED', normal_format='OPENGL', normal_space='TANGENT')
        self.shaded = None
        self.data, self.resolution = data, resolution
        self.masks, self.anchors, self.layer_map, self.below, self.slopes = {}, {}, {}, {}, {}


class Instance:
    def __init__(self, link, source):
        self.link, self.source = link, source

    def __getattr__(self, name):
        return getattr(self.source, name)

    @property
    def uid(self):
        return self.link.uid

    @property
    def parent(self):
        return self.link.parent

    @property
    def visible(self):
        return self.link.visible

    @property
    def opacity(self):
        return self.link.opacity

    @property
    def name(self):
        return self.link.name

    @property
    def geo_mask(self):
        return False


def resolved(layers):
    result = []
    for layer in layers:
        if layer.kind != 'INSTANCE':
            result.append(layer)
            continue
        source = linked_layer(layer)
        if source is not None:
            result.append(Instance(layer, source))
    return result


def slot_signature(slot):
    source = slot.source
    if source == 'IMAGE':
        source += slot.image.name if slot.image else ''
    elif source == 'PATTERN':
        source += slot.pattern
    return slot.name + slot.blend + source


def effect_signature(effect):
    values = '/'.join(str(getattr(effect, field)) if field not in {'texture'} else (effect.texture.name if effect.texture else '') for field in EFFECT_FIELDS
                      if field not in GENERATOR_VALUES)
    components = ','.join(f'{value:.4f}' for field in COMPONENT_FIELDS for value in getattr(effect, field))
    extra = ','.join(f'{value:.4f}' for item in effect.id_colors for value in item.color)
    return f'{effect.uid}={values}={effect.image.name if effect.image else ""}={components}={extra}'


def layer_signature(layer):
    return ':'.join((layer.uid, layer.kind, layer.parent, layer.projection, str(layer.tile_match), f'{layer.proj_bend:.3f}',
                     ','.join(f'{value:.3f}' for value in layer.proj_warp), layer.folder_blend, str(layer.geo_mask),
                     ','.join(f'{item.name}={item.blend}' for item in layer.channel_blends),
                     layer.image.name if layer.image else '', layer.mask.name if layer.mask else '',
                     *(slot_signature(slot) for slot in layer.slots if slot.enabled), *(effect_signature(effect) for effect in layer.effects)))


def signature(data):
    channels = ','.join(channel.key for channel in set_channels(data))
    maps = ','.join(item.name for item in data.maps if item.image is not None)
    layers = '|'.join(layer_signature(layer) for layer in shown_layers(resolved(data.layers)))
    stroke = stroke_link(data)
    owner = f'{stroke[0]}:{",".join(stroke[2])}:{active_tile(data)}:{data.stroke_tool}' if stroke else ''
    tiles = ','.join(str(number) for number in numbers(data))
    project = data.id_data.devil_painter
    shading = f'{data.visible}{data.shader}{project.normal_format}{project.normal_space}'
    quick = data.quick_mask.name if data.quick_mask is not None else ''
    return f'{channels};{data.solo};{data.isolate};{layers};{owner};{maps};{tiles};{project.uv_map};{shading};{quick};{data.bake_paint}'


def stroke_over(build, image, alpha, color, x):
    nodes, links = build.nodes, build.links
    texture = build.sampler.texture(image, None, (x - 300, -1600))
    added = math_node(nodes, links, 'MINIMUM', texture.outputs['Alpha'], 1.0, x - 150, -1600, 'stroke.opacity')
    if len(build.sampler.tile_numbers) > 1:
        added = math_node(nodes, links, 'MULTIPLY', added, build.sampler.is_tile(build.active), x - 150, -1650)
    total = math_node(nodes, links, 'SUBTRACT', math_node(nodes, links, 'ADD', alpha, added, x - 150, -1700),
                      math_node(nodes, links, 'MULTIPLY', alpha, added, x - 150, -1800), x, -1700)
    weight = math_node(nodes, links, 'DIVIDE', added, math_node(nodes, links, 'MAXIMUM', total, 1e-4, x, -1800), x + 150, -1700)
    return total, mix_color(build, color, texture.outputs['Color'], weight), weight


def positional(effect):
    return effect.enabled and effect.kind == 'FILTER' and FILTER[effect.filter].sampling


def coverage_sampling(build, layer, key):
    chain = build.sampler.sample
    for effect in layer.effects:
        if positional(effect) and effect.target == 'CONTENT' and effect.channel in {'ALL', key} and effect.filter not in HEIGHT_FILTERS:
            chain = anchored_sampling(build, effect, chain, wrap_sampling(build, effect, chain))
    return lambda image: chain(image, build.sampler.uv())[1]


def below_image(build, layer, effect, key, below):
    if build.data is None:
        return None
    name = f'{layer.uid}.{effect.uid}.{key}'
    build.below[name] = below
    return tile(build.data, name, numbers(build.data)[0])


def height_below(build, layer, effect, key, content):
    if key == 'height':
        return below_image(build, layer, effect, key, content)
    if (build.data is None or effect.channel not in {'ALL', 'height'} or 'height' not in {channel.key for channel in set_channels(build.data)}
            or not blended(layer.slots['height'])):
        return None
    return tile(build.data, f'{layer.uid}.{effect.uid}.height', numbers(build.data)[0])


def shared_slope(build, effect, source, height):
    name = (effect.uid, source.name)
    if name not in build.slopes:
        build.slopes[name] = slope_weight(build, effect, height, build.sampler.uv())
    return build.slopes[name]


def height_filtered(build, layer, effect, key, content):
    if effect.filter == 'HEIGHT_NORMAL' and key not in {'height', 'normal'}:
        return content
    height = height_below(build, layer, effect, key, content)
    if build.data is None:
        return content
    vector = build.sampler.uv()
    if effect.filter == 'HEIGHT_NORMAL':
        if key != 'normal' or height is None:
            return content
        result = height_normal(build, effect, lambda spot: gray(build, build.sampler.sample(height, spot)[0]), vector)
        if build.shading['normal_format'] == 'DIRECTX':
            result = flip_green(build.nodes, build.links, result)
        result = mix_color(build, content, result, effect.opacity)
    else:
        image = height if key == 'height' else below_image(build, layer, effect, key, content)
        source = image if height is None else height
        weight = shared_slope(build, effect, source, lambda spot: gray(build, build.sampler.sample(source, spot)[0]))
        result = slope_blur(build, effect, build.sampler.sample, image, weight, vector)[0]
    strength = anchor_strength(build, effect)
    return result if strength is None else mix_color(build, content, result, strength)


def filtered_content(build, layer, effect, key, content):
    if effect.filter in HEIGHT_FILTERS:
        return height_filtered(build, layer, effect, key, content)
    image = below_image(build, layer, effect, key, content)
    if image is None:
        return content
    result = wrap_sampling(build, effect, build.sampler.sample)(image, build.sampler.uv())[0]
    strength = anchor_strength(build, effect)
    return result if strength is None else mix_color(build, content, result, strength)


def filtered_mask(build, layer, effect, value):
    if effect.filter == 'HEIGHT_NORMAL':
        return value
    image = below_image(build, layer, effect, 'MASK', value)
    if image is None:
        return value

    def taps(image, vector):
        split = build.nodes.new('ShaderNodeSeparateColor')
        build.links.new(build.sampler.sample(image, vector)[0], split.inputs['Color'])
        return split.outputs['Red'], split.outputs['Red']
    if effect.filter == 'SLOPE_BLUR':
        weight = shared_slope(build, effect, image, lambda spot: taps(image, spot)[1])
        result = slope_blur(build, effect, taps, image, weight, build.sampler.uv())[1]
    else:
        result = wrap_sampling(build, effect, taps)(image, build.sampler.uv())[1]
    strength = anchor_strength(build, effect)
    return result if strength is None else mix_value(build, value, result, strength)


def levels_value(build, value, effect):
    nodes, links = build.nodes, build.links
    return leveled(build, value, (effect.in_low, effect.in_high, effect.gamma, effect.out_low, effect.out_high), effect.clamp)


def leveled(build, value, levels, clamp):
    nodes, links = build.nodes, build.links
    in_low, in_high, gamma, out_low, out_high = levels
    ranged = nodes.new('ShaderNodeMapRange')
    ranged.clamp = clamp
    link_or_set(build, ranged.inputs['Value'], value)
    ranged.inputs['From Min'].default_value, ranged.inputs['From Max'].default_value = in_low, max(in_high, in_low + 1e-3)
    curved = math_node(nodes, links, 'POWER', ranged.outputs['Result'], 1.0 / gamma)
    output = nodes.new('ShaderNodeMapRange')
    output.clamp = clamp
    links.new(curved, output.inputs['Value'])
    output.inputs['To Min'].default_value, output.inputs['To Max'].default_value = out_low, out_high
    return output.outputs['Result']


def component_levels(build, color, effect):
    split = build.nodes.new('ShaderNodeSeparateColor')
    build.links.new(color, split.inputs['Color'])
    join = build.nodes.new('ShaderNodeCombineColor')
    for index in range(3):
        levels = tuple(getattr(effect, field)[index] for field in COMPONENT_FIELDS)
        result = split.outputs[index] if levels == (0.0, 1.0, 1.0, 0.0, 1.0) else leveled(build, split.outputs[index], levels, effect.clamp)
        build.links.new(result, join.inputs[index])
    return join.outputs['Color']


def levels_color(build, color, effect):
    nodes, links = build.nodes, build.links
    ranged = nodes.new('ShaderNodeMapRange')
    ranged.data_type = 'FLOAT_VECTOR'
    ranged.clamp = effect.clamp
    links.new(color, socket(ranged.inputs, 'Vector', 'VECTOR'))
    socket(ranged.inputs, 'From Min', 'VECTOR').default_value = (effect.in_low,) * 3
    socket(ranged.inputs, 'From Max', 'VECTOR').default_value = (max(effect.in_high, effect.in_low + 1e-3),) * 3
    socket(ranged.inputs, 'To Min', 'VECTOR').default_value = (0.0,) * 3
    socket(ranged.inputs, 'To Max', 'VECTOR').default_value = (1.0,) * 3
    curve = nodes.new('ShaderNodeGamma')
    links.new(socket(ranged.outputs, 'Vector', 'VECTOR'), curve.inputs['Color'])
    curve.inputs['Gamma'].default_value = 1.0 / effect.gamma
    output = nodes.new('ShaderNodeMapRange')
    output.data_type = 'FLOAT_VECTOR'
    output.clamp = effect.clamp
    links.new(curve.outputs['Color'], socket(output.inputs, 'Vector', 'VECTOR'))
    socket(output.inputs, 'From Min', 'VECTOR').default_value = (0.0,) * 3
    socket(output.inputs, 'From Max', 'VECTOR').default_value = (1.0,) * 3
    socket(output.inputs, 'To Min', 'VECTOR').default_value = (effect.out_low,) * 3
    socket(output.inputs, 'To Max', 'VECTOR').default_value = (effect.out_high,) * 3
    return mix_color(build, color, component_levels(build, socket(output.outputs, 'Vector', 'VECTOR'), effect), effect.opacity)


def combine_mask(build, value, other, blend, factor):
    split = build.nodes.new('ShaderNodeSeparateColor')
    build.links.new(mix_color(build, value, other, factor, MASK_MIXES.get(blend, blend)), split.inputs['Color'])
    return split.outputs['Red']


def fill_texture(build, effect):
    node = build.nodes.new('ShaderNodeTexImage')
    node.image = effect.texture
    if fill_projection(effect) == 'TRIPLANAR':
        node.projection = 'BOX'
        node.projection_blend = TRIPLANAR_BLEND
    build.links.new(fill_vector(build, effect), node.inputs['Vector'])
    return node.outputs['Color']


def fill_pattern(build, effect):
    texture, factor = pattern_node(build.nodes, effect.pattern, effect.uid + '.texture', (0, 0))
    build.links.new(fill_vector(build, effect), texture.inputs['Vector'])
    set_pattern_values(texture, effect.pattern, effect.scale, effect.detail)
    ranged = build.nodes.new('ShaderNodeMapRange')
    build.links.new(factor, ranged.inputs['Value'])
    ranged.inputs['From Min'].default_value, ranged.inputs['From Max'].default_value = contrast_range(effect.pattern, effect.contrast)
    return ranged.outputs['Result']


def fill_effect_value(build, effect):
    if effect.source == 'VALUE':
        return effect.value
    if effect.source == 'IMAGE' and effect.texture is not None:
        return gray(build, fill_texture(build, effect))
    if effect.source == 'PATTERN':
        return fill_pattern(build, effect)
    return None


def fill_content(build, effect, colored):
    if effect.source == 'IMAGE':
        if effect.texture is None:
            return None
        color = fill_texture(build, effect)
        return color if colored else gray(build, color)
    if effect.source == 'PATTERN':
        factor = fill_pattern(build, effect)
        return mix_color(build, rgba(effect.color_b), rgba(effect.color), factor) if colored else factor
    return rgba(effect.color) if colored else effect.value


def fill_projection(effect):
    if effect.projection != 'AUTO':
        return effect.projection
    return 'UV' if effect.source == 'IMAGE' else 'TRIPLANAR'


def fill_vector(build, effect):
    if fill_projection(effect) == 'UV':
        source = build.sampler.uv()
    else:
        source = build.nodes.new('ShaderNodeTexCoord').outputs['Object']
    mapping = build.nodes.new('ShaderNodeMapping')
    mapping.name = effect.uid + '.mapping'
    build.links.new(source, mapping.inputs['Vector'])
    mapping.inputs['Location'].default_value = (effect.offset_u, effect.offset_v, 0.0)
    mapping.inputs['Rotation'].default_value = (0.0, 0.0, math.radians(effect.angle))
    mapping.inputs['Scale'].default_value = (effect.tiling,) * 3
    return mapping.outputs['Vector']


def anchor_input(build, uid, channel):
    results = build.anchors.get(uid)
    if results is None:
        return None
    key = channel if channel in results else next(iter(results), None)
    return gray(build, results[key]) if key is not None else None


def anchor_value(build, effect):
    return anchor_input(build, effect.other, effect.channel)


def anchor_strength(build, effect):
    value = anchor_input(build, effect.anchor, effect.anchor_channel) if effect.anchor else None
    return None if value is None else mix_value(build, 1.0, value, effect.anchor_weight)


def anchor_detail(build, effect):
    value = anchor_input(build, effect.anchor, effect.anchor_channel) if effect.anchor else None
    if value is None:
        return None
    return math_node(build.nodes, build.links, 'MULTIPLY', math_node(build.nodes, build.links, 'SUBTRACT', value, .5), effect.anchor_weight * 2)


def anchored_sampling(build, effect, inner, chain):
    strength = anchor_strength(build, effect)
    if strength is None:
        return chain

    def sample(image, vector):
        base, result = inner(image, vector), chain(image, vector)
        return mix_color(build, base[0], result[0], strength), mix_value(build, base[1], result[1], strength)
    return sample


def mask_value(build, layer):
    if layer.uid in build.masks:
        return build.masks[layer.uid]
    build.masks[layer.uid] = 1.0
    nodes, links = build.nodes, build.links
    sample = build.sampler.sample
    value = 1.0
    if layer.mask:
        value = sample(layer.mask)[1]
    if layer.geo_mask and build.data is not None:
        attribute = nodes.new('ShaderNodeAttribute')
        attribute.attribute_type = 'GEOMETRY'
        attribute.attribute_name = geometry_attribute(build.data, layer)
        value = math_node(nodes, links, 'MULTIPLY', value, attribute.outputs['Fac'])
    for effect in layer.effects:
        if not effect.enabled or effect.target != 'MASK':
            continue
        if effect.kind == 'PAINT' and effect.image is not None:
            color, alpha = sample(effect.image)
            value = combine_mask(build, value, gray(build, color), effect.blend, math_node(nodes, links, 'MULTIPLY', alpha, effect.opacity))
        else:
            if effect.kind == 'LEVELS':
                other = levels_value(build, value, effect)
            elif positional(effect):
                value = filtered_mask(build, layer, effect, value)
                continue
            elif effect.kind == 'FILTER':
                other = filter_value(build, value, effect)
                strength = anchor_strength(build, effect) if other is not None else None
                if strength is not None:
                    other = mix_value(build, value, other, strength)
            elif effect.kind == 'FILL':
                other = fill_effect_value(build, effect)
            elif effect.kind == 'ID_COLOR':
                other = id_selection(build, effect, sample)
            elif effect.kind == 'GENERATOR':
                other = generator_mask(nodes, links, effect, generator_name(layer, effect), build, sample, anchor_detail(build, effect))
            elif effect.kind == 'COMPARE':
                target = build.layer_map.get(effect.other)
                other = mask_value(build, target) if target is not None and target.uid != layer.uid else None
            else:
                other = anchor_value(build, effect)
            if other is not None:
                value = combine_mask(build, value, other, effect.blend, effect.opacity)
    build.masks[layer.uid] = value
    return value


def layer_coverage(build, layer, x, stroke=None):
    nodes, links = build.nodes, build.links
    factor = nodes.new('ShaderNodeMath')
    factor.name = layer.uid + '.opacity'
    factor.operation = 'MULTIPLY'
    factor.location = (x - 150, -900)
    factor.inputs[0].default_value = 1.0
    coverage, source, weight = factor.outputs[0], None, None
    if layer.kind == 'PAINT' and layer.image:
        source, alpha = build.sampler.sample(layer.image)[0], coverage_sampling(build, layer, 'ALL')(layer.image)
        if stroke is not None:
            alpha, source, weight = stroke_over(build, stroke, alpha, source, x)
        links.new(alpha, factor.inputs[0])
    value = mask_value(build, layer)
    if not isinstance(value, float):
        coverage = math_node(nodes, links, 'MULTIPLY', coverage, value, x - 50, -1100)
    return coverage, source, weight


def projected(nodes, links, layer, coordinates, x):
    projector = nodes.new('ShaderNodeMapping')
    projector.name = layer.uid + '.projector'
    projector.vector_type = 'TEXTURE'
    projector.location = (x - 750, -400)
    links.new(coordinates.outputs['Object'], projector.inputs['Vector'])
    split = nodes.new('ShaderNodeSeparateXYZ')
    links.new(projector.outputs['Vector'], split.inputs['Vector'])
    px, py, pz = split.outputs['X'], split.outputs['Y'], split.outputs['Z']
    if layer.projection == 'PLANAR':
        u, v = px, py
        if layer.proj_bend > 0:
            radius = 1.0 / (layer.proj_bend * math.pi / 2)
            u = math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'ARCTAN2', px, math_node(nodes, links, 'ADD', pz, radius)), radius)
    else:
        u = math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'ARCTAN2', py, px), 1 / math.pi)
        v = pz
        if layer.projection == 'SPHERICAL':
            flat = math_node(nodes, links, 'SQRT', math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', px, px),
                                                              math_node(nodes, links, 'MULTIPLY', py, py)), 0.0)
            v = math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'ARCTAN2', pz, flat), 2 / math.pi)
    u = math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', u, .5), .5)
    v = math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', v, .5), .5)
    if layer.projection == 'PLANAR' and any(layer.proj_warp):
        u, v = corner_pin(nodes, links, u, v, layer.proj_warp)
    join = nodes.new('ShaderNodeCombineXYZ')
    links.new(u, join.inputs['X'])
    links.new(v, join.inputs['Y'])
    return join.outputs['Vector']


def corner_pin(nodes, links, u, v, warp):
    iu, iv = math_node(nodes, links, 'SUBTRACT', 1.0, u), math_node(nodes, links, 'SUBTRACT', 1.0, v)
    weights = (math_node(nodes, links, 'MULTIPLY', iu, iv), math_node(nodes, links, 'MULTIPLY', u, iv),
               math_node(nodes, links, 'MULTIPLY', u, v), math_node(nodes, links, 'MULTIPLY', iu, v))
    axes = []
    for axis in range(2):
        total = None
        for index, weight in enumerate(weights):
            corner = PIN_CORNERS[index][axis] + warp[index * 2 + axis]
            term = math_node(nodes, links, 'MULTIPLY', weight, float(corner))
            total = term if total is None else math_node(nodes, links, 'ADD', total, term)
        axes.append(total)
    return axes


def per_tile(nodes, links, vector):
    return vector_math(nodes, links, 'FRACTION', vector)


def layer_coordinates(nodes, links, layer, x):
    coordinates = nodes.new('ShaderNodeTexCoord')
    coordinates.location = (x - 900, -400)
    mapping = nodes.new('ShaderNodeMapping')
    mapping.name = layer.uid + '.mapping'
    mapping.location = (x - 450, -400)
    if layer.projection in PROJECTORS:
        source = projected(nodes, links, layer, coordinates, x)
    elif layer.projection == 'TRIPLANAR':
        source = coordinates.outputs['Object']
    else:
        source = per_tile(nodes, links, coordinates.outputs['UV']) if layer.tile_match else coordinates.outputs['UV']
    links.new(source, mapping.inputs['Vector'])
    return mapping.outputs['Vector']


def slot_content(build, layer, slot, vector, name, x, y):
    nodes, links = build.nodes, build.links
    if slot.source == 'IMAGE' and slot.image:
        if layer.kind == 'PAINT' or layer.projection != 'TRIPLANAR':
            return build.sampler.sample(slot.image, None if layer.kind == 'PAINT' else vector)[0]
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = slot.image
        texture.location = (x - 250, y - 120)
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


def content_effects_for(layer, key):
    return [effect for effect in layer.effects if effect.enabled and effect.target == 'CONTENT' and effect.kind in CONTENT_KINDS
            and effect.channel in {'ALL', key} and not (effect.kind == 'PAINT' and effect.image is None)]


def content_source(build, layer, effect, colored, generated):
    sample = build.sampler.sample
    if effect.kind == 'PAINT':
        color, alpha = sample(effect.image)
        return color if colored else gray(build, color), math_node(build.nodes, build.links, 'MULTIPLY', alpha, effect.opacity)
    if effect.kind == 'FILL':
        return fill_content(build, effect, colored), effect.opacity
    if effect.uid not in generated:
        generated[effect.uid] = generator_mask(build.nodes, build.links, effect, generator_name(layer, effect), build, sample, anchor_detail(build, effect))
    return generated[effect.uid], effect.opacity


def content_effect(build, layer, content, effect, key, colored, generated):
    if positional(effect):
        return filtered_content(build, layer, effect, key, content)
    if effect.kind == 'LEVELS':
        return levels_color(build, content, effect)
    if effect.kind == 'FILTER':
        result = filter_color(build, content, effect)
        strength = anchor_strength(build, effect)
        return result if strength is None else mix_color(build, content, result, strength)
    other, factor = content_source(build, layer, effect, colored, generated)
    if other is None:
        return content
    return mix_color(build, content, other, factor, MASK_MIXES.get(effect.blend, effect.blend))


def flip_green(nodes, links, color):
    split = nodes.new('ShaderNodeSeparateColor')
    links.new(color, split.inputs['Color'])
    join = nodes.new('ShaderNodeCombineColor')
    links.new(split.outputs[0], join.inputs[0])
    links.new(math_node(nodes, links, 'SUBTRACT', 1.0, split.outputs[1]), join.inputs[1])
    links.new(split.outputs[2], join.inputs[2])
    return join.outputs['Color']


def blend_normals(nodes, links, base, detail):
    unpacked = [vector_math(nodes, links, 'MULTIPLY_ADD', color, (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0)) for color in (base, detail)]
    parts = []
    for vector in unpacked:
        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(vector, split.inputs['Vector'])
        parts.append(split)
    join = nodes.new('ShaderNodeCombineXYZ')
    links.new(math_node(nodes, links, 'ADD', parts[0].outputs['X'], parts[1].outputs['X']), join.inputs['X'])
    links.new(math_node(nodes, links, 'ADD', parts[0].outputs['Y'], parts[1].outputs['Y']), join.inputs['Y'])
    links.new(math_node(nodes, links, 'MULTIPLY', parts[0].outputs['Z'], parts[1].outputs['Z']), join.inputs['Z'])
    normalized = vector_math(nodes, links, 'NORMALIZE', join.outputs['Vector'])
    return vector_math(nodes, links, 'MULTIPLY_ADD', normalized, (.5, .5, .5), (.5, .5, .5))


def combine_baked(build, results):
    nodes, links = build.nodes, build.links
    baked = build.maps.get('normal')
    if 'normal' in results and baked is not None:
        color, _ = build.sampler.sample(baked, None, (-800, -1500))
        if build.shading['normal_format'] == 'DIRECTX':
            color = flip_green(nodes, links, color)
        results['normal'] = blend_normals(nodes, links, color, results['normal'])
    if 'ambient_occlusion' in results:
        occlusion = results['ambient_occlusion']
        ambient = build.maps.get('ao')
        if ambient is not None:
            mix = nodes.new('ShaderNodeMix')
            mix.data_type = 'RGBA'
            mix.blend_type = 'MULTIPLY'
            socket(mix.inputs, 'Factor', 'VALUE').default_value = 1.0
            links.new(occlusion, socket(mix.inputs, 'A', 'RGBA'))
            links.new(build.sampler.sample(ambient, None, (-800, -1700))[0], socket(mix.inputs, 'B', 'RGBA'))
            occlusion = results['ambient_occlusion'] = socket(mix.outputs, 'Result', 'RGBA')
        if 'base_color' in results:
            shade = nodes.new('ShaderNodeMix')
            shade.data_type = 'RGBA'
            shade.blend_type = 'MULTIPLY'
            socket(shade.inputs, 'Factor', 'VALUE').default_value = 1.0
            links.new(results['base_color'], socket(shade.inputs, 'A', 'RGBA'))
            links.new(occlusion, socket(shade.inputs, 'B', 'RGBA'))
            build.shaded = socket(shade.outputs, 'Result', 'RGBA')


def surface_normal(build, results, x):
    nodes, links = build.nodes, build.links
    normal = None
    if 'normal' in results:
        node = nodes.new('ShaderNodeNormalMap')
        node.name = 'shader.normal_map'
        node.uv_map = build.sampler.uv_map
        node.space = build.shading['normal_space']
        node.location = (x, -600)
        color = results['normal']
        if build.shading['normal_format'] == 'DIRECTX':
            color = flip_green(nodes, links, color)
        links.new(color, node.inputs['Color'])
        normal = node.outputs['Normal']
    if 'height' in results:
        bump = nodes.new('ShaderNodeBump')
        bump.name = 'shader.bump'
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


def blended(slot):
    return slot.enabled and slot.blend != 'DISABLE'


def per_component(build, below, above, formula):
    nodes, links = build.nodes, build.links
    parts = []
    for color in (below, above):
        split = nodes.new('ShaderNodeSeparateColor')
        links.new(color, split.inputs['Color'])
        parts.append(split.outputs)

    def op(operation, first, second):
        return math_node(nodes, links, operation, first, second)
    join = nodes.new('ShaderNodeCombineColor')
    for index in range(3):
        links.new(formula(op, parts[0][index], parts[1][index]), join.inputs[index])
    return join.outputs['Color']


def chosen(op, low, high, above):
    return op('ADD', low, op('MULTIPLY', op('GREATER_THAN', above, .5), op('SUBTRACT', high, low)))


BLEND_FORMULAS = {
    'INVERSE_DIVIDE': lambda op, a, b: op('DIVIDE', b, op('MAXIMUM', a, 1e-4)),
    'INVERSE_SUBTRACT': lambda op, a, b: op('SUBTRACT', b, a),
    'SIGNED_ADD': lambda op, a, b: op('ADD', a, op('SUBTRACT', op('MULTIPLY', b, 2.0), 1.0)),
    'LINEAR_BURN': lambda op, a, b: op('SUBTRACT', op('ADD', a, b), 1.0),
    'HARD_LIGHT': lambda op, a, b: chosen(op, op('MULTIPLY', op('MULTIPLY', a, b), 2.0),
                                          op('SUBTRACT', 1.0, op('MULTIPLY', op('MULTIPLY', op('SUBTRACT', 1.0, a), op('SUBTRACT', 1.0, b)), 2.0)), b),
    'VIVID_LIGHT': lambda op, a, b: chosen(op, op('SUBTRACT', 1.0, op('DIVIDE', op('SUBTRACT', 1.0, a), op('MAXIMUM', op('MULTIPLY', b, 2.0), 1e-4))),
                                           op('DIVIDE', a, op('MAXIMUM', op('SUBTRACT', 2.0, op('MULTIPLY', b, 2.0)), 1e-4)), b),
    'PIN_LIGHT': lambda op, a, b: chosen(op, op('MINIMUM', a, op('MULTIPLY', b, 2.0)), op('MAXIMUM', a, op('SUBTRACT', op('MULTIPLY', b, 2.0), 1.0)), b),
}


def combine_normals(nodes, links, base, detail):
    unpacked = [vector_math(nodes, links, 'MULTIPLY_ADD', color, (2.0, 2.0, 2.0), (-1.0, -1.0, -1.0)) for color in (base, detail)]
    summed = vector_math(nodes, links, 'ADD', unpacked[0], vector_math(nodes, links, 'MULTIPLY', unpacked[1], (1.0, 1.0, 0.0)))
    normalized = vector_math(nodes, links, 'NORMALIZE', summed)
    return vector_math(nodes, links, 'MULTIPLY_ADD', normalized, (.5, .5, .5), (.5, .5, .5))


def custom_blend(build, mode, below, above):
    if mode == 'REPLACE':
        return above
    if mode == 'NORMAL_DETAIL':
        return blend_normals(build.nodes, build.links, below, above)
    if mode == 'NORMAL_INVERSE_DETAIL':
        return blend_normals(build.nodes, build.links, above, below)
    if mode == 'NORMAL_COMBINE':
        return combine_normals(build.nodes, build.links, below, above)
    return per_component(build, below, above, BLEND_FORMULAS[mode])


def compose_layer(build, channels, layer, results, x):
    nodes, links, stroke = build.nodes, build.links, build.stroke
    owner = stroke is not None and stroke[0] == layer.uid
    coverage, painted, weight = layer_coverage(build, layer, x, stroke[1] if owner else None)
    vector = layer_coordinates(nodes, links, layer, x) if uses_coordinates(layer) else None
    generated = {}
    for row, channel in enumerate(channels):
        slot = layer.slots[channel.key]
        if not blended(slot):
            continue
        name = f'{layer.uid}.{channel.key}'
        y = 300 - 250 * row
        reach = coverage
        if layer.kind == 'PAINT' and channel.key != 'base_color' and slot.source == 'IMAGE' and slot.image is not None:
            reach = math_node(nodes, links, 'MULTIPLY', coverage, coverage_sampling(build, layer, channel.key)(slot.image), x - 150, y - 60)
        factor = math_node(nodes, links, 'MULTIPLY', reach, 1.0, x - 100, y - 60, name + '.opacity')
        native = slot.blend in MIX_NODE_BLENDS
        node = channel_mix(nodes, links, name, results[channel.key], factor, slot.blend if native else 'MIX', x, y)
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
        effects = content_effects_for(layer, channel.key)
        if content is None and (effects or not native):
            constant = nodes.new('ShaderNodeRGB')
            constant.name = name + '.const'
            content = constant.outputs[0]
        for effect in effects:
            content = content_effect(build, layer, content, effect, channel.key, channel.width == 3, generated)
        if not native:
            content = custom_blend(build, slot.blend, results[channel.key], content)
        if content is not None:
            links.new(content, socket(node.inputs, 'B', 'RGBA'))
        results[channel.key] = socket(node.outputs, 'Result', 'RGBA')
    build.anchors[layer.uid] = dict(results)
    return coverage


def union(build, coverages):
    alpha = 0.0
    for coverage in coverages:
        alpha = math_node(build.nodes, build.links, 'SUBTRACT', math_node(build.nodes, build.links, 'ADD', alpha, coverage),
                          math_node(build.nodes, build.links, 'MULTIPLY', alpha, coverage))
    return alpha


def compose(build, channels, layers, parent, results, column, collector=None):
    for layer in children(layers, parent):
        if not layer.visible:
            continue
        x = 300 * column[0]
        column[0] += 1
        if layer.kind != 'FOLDER':
            coverage = compose_layer(build, channels, layer, results, x)
            if collector is not None:
                collector.append(coverage)
            continue
        below = dict(results)
        modes = {channel.key: folder_mode(layer, channel.key) for channel in channels}
        isolated = {key for key, mode in modes.items() if mode != 'PASSTHROUGH'}
        start = {channel.key: constant_color(build, channel) if channel.key in isolated else results[channel.key] for channel in channels}
        coverages = []
        inner = compose(build, channels, layers, layer.uid, dict(start), column, coverages)
        coverage, _, _ = layer_coverage(build, layer, 300 * column[0])
        grouped = math_node(build.nodes, build.links, 'MULTIPLY', coverage, union(build, coverages)) if isolated else coverage
        if collector is not None:
            collector.append(grouped)
        for row, channel in enumerate(channels):
            if inner[channel.key] is not start[channel.key]:
                merged = channel.key in isolated
                node = channel_mix(build.nodes, build.links, f'{layer.uid}.{channel.key}', below[channel.key], grouped if merged else coverage,
                                   modes[channel.key] if merged else 'MIX', 300 * column[0], 300 - 250 * row)
                build.links.new(inner[channel.key], socket(node.inputs, 'B', 'RGBA'))
                results[channel.key] = socket(node.outputs, 'Result', 'RGBA')
        build.anchors[layer.uid] = dict(results)
        column[0] += 1
    return results


class Rooted:
    def __init__(self, layer):
        self.layer = layer

    def __getattr__(self, name):
        return getattr(self.layer, name)

    @property
    def parent(self):
        return ''

    @property
    def visible(self):
        return True


def isolated_tree(data, tree, roots, key, mask_uid=''):
    build = set_build(data, tree, raw=True)
    tree.nodes.clear()
    build.sampler.cache.clear()
    layers = resolved(data.layers)
    build.layer_map = {layer.uid: layer for layer in layers}
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    emission = tree.nodes.new('ShaderNodeEmission')
    tree.links.new(emission.outputs[0], output.inputs['Surface'])
    if mask_uid:
        layer = build.layer_map[mask_uid]
        value = mask_value(build, layer)
        write_generators(tree.nodes, layer)
    else:
        channels = set_channels(data)
        chosen = {root.uid for root in roots}
        subset = [Rooted(layer) if layer.uid in chosen else layer for layer in layers if layer.uid in chosen or ancestor_in(layers, layer, chosen)]
        coverages = []
        results = compose(build, channels, subset, '',
                          {channel.key: constant_color(build, channel) for channel in channels}, [0], coverages)
        value = union(build, coverages) if key == 'ALPHA' else results[key]
        write_values(tree.nodes, channels, subset)
    link_or_set(build, emission.inputs['Color'], value)


def stack_layers(data, raw):
    layers = resolved(data.layers) if data.visible else []
    kept = None if raw else isolated_uids(data)
    if kept is None:
        return layers
    return [Rooted(layer) if layer.uid == data.isolate else layer for layer in layers if layer.uid in kept]


def ancestor_in(layers, layer, chosen):
    by_uid = {item.uid: item for item in layers}
    parent = by_uid.get(layer.parent)
    while parent is not None:
        if parent.uid in chosen:
            return True
        parent = by_uid.get(parent.parent)
    return False


def constant_color(build, channel):
    node = build.nodes.new('ShaderNodeRGB')
    node.outputs[0].default_value = rgba(channel.default)
    return node.outputs[0]


def build_tree(build, channels, layers, solo=None, raw=False):
    nodes, links = build.nodes, build.links
    nodes.clear()
    build.sampler.cache.clear()
    build.layer_map = {layer.uid: layer for layer in layers}
    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    results = {}
    for row, channel in enumerate(channels):
        node = nodes.new('ShaderNodeRGB')
        node.outputs[0].default_value = rgba(channel.default)
        node.location = (-400, 300 - 250 * row)
        results[channel.key] = node.outputs[0]
    column = [0]
    shader.name = 'shader.bsdf'
    results = compose(build, channels, layers, '', results, column)
    build.shaded = None
    combine_baked(build, results)
    if not raw and not solo and build.data is not None and build.data.quick_mask is not None and 'base_color' in results:
        stencil = build.sampler.sample(build.data.quick_mask)[1]
        results['base_color'] = mix_color(build, results['base_color'], QUICK_TINT, math_node(nodes, links, 'MULTIPLY', stencil, QUICK_SHOW))
    end = 300 * column[0]
    output.location, shader.location = (end + 600, 0), (end + 300, 0)
    for key, name in SHADER_INPUTS.items():
        if key in results:
            links.new(build.shaded if key == 'base_color' and build.shaded is not None else results[key], shader.inputs[name])
    normal = surface_normal(build, results, end)
    if normal is not None:
        links.new(normal, shader.inputs['Normal'])
    surface = shader.outputs[0]
    if solo:
        surface = solo_shader(nodes, links, solo, results[solo.key], end + 300, raw)
    elif build.shading['shader'] == 'UNLIT' and 'base_color' in results:
        unlit = nodes.new('ShaderNodeEmission')
        unlit.location = (end + 300, 400)
        links.new(build.shaded if build.shaded is not None else results['base_color'], unlit.inputs['Color'])
        surface = unlit.outputs[0]
    links.new(surface, output.inputs['Surface'])
    return output


def write_values(nodes, channels, layers, brush=None):
    if brush is not None and 'stroke.opacity' in nodes:
        nodes['stroke.opacity'].inputs[1].default_value = brush[0]
    for layer in shown_layers(layers):
        nodes[layer.uid + '.opacity'].inputs[1].default_value = layer.opacity
        write_generators(nodes, layer)
        if layer.kind == 'FOLDER':
            continue
        if uses_coordinates(layer):
            nodes[layer.uid + '.mapping'].inputs['Scale'].default_value = (layer.tiling,) * 3
            projector = nodes.get(layer.uid + '.projector')
            if projector is not None:
                projector.inputs['Location'].default_value = tuple(layer.proj_offset)
                projector.inputs['Rotation'].default_value = tuple(layer.proj_rotation)
                projector.inputs['Scale'].default_value = (layer.proj_size,) * 3
        for channel in channels:
            slot = layer.slots[channel.key]
            if not blended(slot):
                continue
            name = f'{layer.uid}.{channel.key}'
            nodes[name + '.opacity'].inputs[1].default_value = slot.opacity
            if slot.blend == 'REPLACE':
                nodes[name + '.opacity'].inputs[0].default_value = layer.opacity
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
            if name + '.const' in nodes:
                nodes[name + '.const'].outputs[0].default_value = rgba(slot_value(slot))


def rna_values(item):
    parts = []
    for prop in item.bl_rna.properties:
        if prop.identifier == 'rna_type':
            continue
        value = getattr(item, prop.identifier)
        if prop.type == 'COLLECTION':
            parts.extend(rna_values(entry) for entry in value)
        elif prop.type == 'POINTER':
            parts.append('' if value is None else value.name_full if hasattr(value, 'name_full') else rna_values(value))
        elif getattr(prop, 'is_array', False):
            parts.append(','.join(str(entry) for entry in value))
        else:
            parts.append(str(value))
    return '/'.join(parts)


def has_positional(data):
    return any(positional(effect) for layer in resolved(data.layers) for effect in layer.effects)


def below_stamp(data):
    project = data.id_data.devil_painter
    layers = '|'.join(rna_values(layer) for item in project.sets for layer in item.layers)
    channels = ','.join(channel.key for channel in set_channels(data))
    maps = ','.join(item.image.name_full for item in data.maps if item.image is not None)
    tiles = ','.join(str(number) for number in numbers(data))
    return f'{revision()};{data.visible};{data.resolution};{project.uv_map};{channels};{maps};{tiles};{layers}'


def below_build(data):
    tree = data.material.node_tree
    build = set_build(data, tree, raw=True)
    output = build_tree(build, set_channels(data), stack_layers(data, True), None, True)
    update_values(data, raw=True)
    emission = tree.nodes.new('ShaderNodeEmission')
    tree.links.new(emission.outputs[0], output.inputs['Surface'])
    return build, emission


def emit_below(build, emission, name):
    target = emission.inputs['Color']
    for link in list(target.links):
        build.links.remove(link)
    link_or_set(build, target, build.below[name])


def stroke_link(data):
    if not data.stroke_owner or data.stroke is None:
        return None
    return data.stroke_owner, data.stroke, tuple(slot.name for slot in data.brush_slots if slot.enabled)


def brush_values(data):
    shown = data.brush_opacity if data.stroke_tool in PREVIEW_TOOLS else 0.0
    return shown, {slot.name: slot_value(slot) for slot in data.brush_slots}


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


def viewed_mask(data):
    uid = data.solo.removeprefix('mask:') if data.solo.startswith('mask:') else None
    return next((layer for layer in resolved(data.layers) if layer.uid == uid), None)


def show_mask(build, output, layer):
    gamma = build.nodes.new('ShaderNodeGamma')
    gamma.inputs['Gamma'].default_value = DISPLAY_GAMMA
    link_or_set(build, gamma.inputs['Color'], mask_value(build, layer))
    emission = build.nodes.new('ShaderNodeEmission')
    build.links.new(gamma.outputs['Color'], emission.inputs['Color'])
    build.links.new(emission.outputs[0], output.inputs['Surface'])


def viewed_map(data):
    item = data.maps.get(data.solo.removeprefix('map:')) if data.solo.startswith('map:') else None
    return item.image if item is not None else None


def set_build(data, tree, raw=False):
    project = data.id_data.devil_painter
    sampler = Sampler(tree.nodes, tree.links, numbers(data), lambda image, number: tile_variant(data, image, number), project.uv_map)
    maps = {item.name: item.image for item in data.maps if item.image is not None}
    shading = dict(shader=data.shader, normal_format=project.normal_format, normal_space=project.normal_space)
    return Build(tree.nodes, tree.links, sampler, None if raw else stroke_link(data), maps, False, 1.0, active_tile(data), shading, data, data.resolution)


def rebuild(data, solo=None, raw=False):
    material = data.material
    build = set_build(data, material.node_tree, raw)
    channels = set_channels(data)
    output = build_tree(build, channels, stack_layers(data, raw), solo or solo_channel(data), raw)
    if not raw and solo is None and data.bake_paint:
        show_map(build, output, data.cage_map if data.bake_paint == 'CAGE' else data.skew_map)
    elif not raw and solo is None and viewed_map(data) is not None:
        show_map(build, output, viewed_map(data))
    elif not raw and solo is None and viewed_mask(data) is not None:
        show_mask(build, output, viewed_mask(data))
    material[SIGNATURE_KEY] = '' if raw else signature(data)


def update_values(data, raw=False):
    nodes = data.material.node_tree.nodes
    if not data.visible:
        return
    write_values(nodes, set_channels(data), stack_layers(data, raw), brush_values(data))
    if 'shader.normal_map' in nodes:
        nodes['shader.normal_map'].inputs['Strength'].default_value = data.normal_strength
    if 'shader.bump' in nodes:
        nodes['shader.bump'].inputs['Strength'].default_value = data.bump_strength
    if 'shader.bsdf' in nodes:
        nodes['shader.bsdf'].inputs['Emission Strength'].default_value = data.emission_strength
    obj = data.id_data
    project = obj.devil_painter
    for layer in shown_layers(stack_layers(data, raw)):
        mapping = nodes.get(layer.uid + '.mapping')
        if mapping is not None and layer.projection == 'TRIPLANAR' and project.use_physical:
            mapping.inputs['Scale'].default_value = tuple(layer.tiling * axis / project.physical_size for axis in obj.scale)


def sync(data):
    if data.material.get(SIGNATURE_KEY) != signature(data):
        rebuild(data)
    update_values(data)
    material = data.material
    method = data.transparency
    if method == 'AUTO':
        method = 'BLENDED' if any(channel.key == 'opacity' for channel in set_channels(data)) else 'DITHERED'
    if material.surface_render_method != method:
        material.surface_render_method = method
    if material.use_transparency_overlap != data.transparency_overlap:
        material.use_transparency_overlap = data.transparency_overlap


def assign_image_colorspace(image, channel):
    if image.colorspace_settings.is_data == channel.srgb:
        image.colorspace_settings.name = 'sRGB' if channel.srgb else 'Non-Color'
