from .signals import map_signal


def socket(sockets, name, kind):
    return next(item for item in sockets if item.name == name and item.type == kind)


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


def link_or_set(build, target, value):
    if isinstance(value, (float, int)):
        target.default_value = float(value) if target.type == 'VALUE' else (float(value),) * 3 + (1.0,)
    elif isinstance(value, tuple):
        target.default_value = value
    else:
        build.links.new(value, target)


def mix_color(build, below, above, factor, mode='MIX'):
    node = build.nodes.new('ShaderNodeMix')
    node.data_type = 'RGBA'
    node.blend_type = mode
    node.clamp_result = True
    link_or_set(build, socket(node.inputs, 'Factor', 'VALUE'), factor)
    link_or_set(build, socket(node.inputs, 'A', 'RGBA'), below)
    link_or_set(build, socket(node.inputs, 'B', 'RGBA'), above)
    return socket(node.outputs, 'Result', 'RGBA')


def mix_value(build, below, above, factor):
    node = build.nodes.new('ShaderNodeMix')
    node.data_type = 'FLOAT'
    node.clamp_result = True
    link_or_set(build, socket(node.inputs, 'Factor', 'VALUE'), factor)
    link_or_set(build, socket(node.inputs, 'A', 'VALUE'), below)
    link_or_set(build, socket(node.inputs, 'B', 'VALUE'), above)
    return socket(node.outputs, 'Result', 'VALUE')


def gray(build, color):
    node = build.nodes.new('ShaderNodeRGBToBW')
    link_or_set(build, node.inputs['Color'], color)
    return node.outputs['Val']


def as_color(build, value):
    node = build.nodes.new('ShaderNodeCombineColor')
    for name in ('Red', 'Green', 'Blue'):
        link_or_set(build, node.inputs[name], value)
    return node.outputs['Color']


def vector_math(nodes, links, operation, *values):
    node = nodes.new('ShaderNodeVectorMath')
    node.operation = operation
    for index, value in enumerate(values):
        if isinstance(value, tuple):
            node.inputs[index].default_value = value
        else:
            links.new(value, node.inputs[index])
    return node.outputs['Vector']


def offset(build, vector, dx, dy):
    return vector_math(build.nodes, build.links, 'ADD', vector, (dx, dy, 0.0))


def averaged(build, samples):
    color, alpha = samples[0]
    for index, (next_color, next_alpha) in enumerate(samples[1:], 2):
        color = mix_color(build, color, next_color, 1.0 / index)
        alpha = mix_value(build, alpha, next_alpha, 1.0 / index)
    return color, alpha


def mesh_signal(build, key, channel=None):
    if build.live or key not in build.maps:
        source = map_signal(build.nodes, build.links, key, build.size)
    else:
        source = build.sampler.sample(build.maps[key])[0]
    if channel is None:
        return source
    split = build.nodes.new('ShaderNodeSeparateColor')
    build.links.new(source, split.inputs['Color'])
    return split.outputs[channel]
