import math


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


def map_signal(nodes, links, key, size, ao_distance=.25, ao_spread=180.0, curvature='PER_PIXEL', thickness_range=.5):
    if key == 'ao':
        ao = node(nodes, 'ShaderNodeAmbientOcclusion', Distance=size * ao_distance).outputs['AO']
        if ao_spread >= 179.9:
            return ao
        cone = max(math.sin(math.radians(ao_spread * .5)) ** 2, 1e-4)
        return operate(nodes, links, 'MULTIPLY', ao, 1.0 / cone)
    if key == 'thickness':
        occlusion = nodes.new('ShaderNodeAmbientOcclusion')
        occlusion.inside = True
        occlusion.inputs['Distance'].default_value = size * thickness_range
        return operate(nodes, links, 'SUBTRACT', 1.0, occlusion.outputs['AO'])
    if key == 'curvature':
        geometry = nodes.new('ShaderNodeNewGeometry')
        if curvature == 'PER_VERTEX':
            ranged = nodes.new('ShaderNodeMapRange')
            ranged.inputs['From Min'].default_value = .375
            ranged.inputs['From Max'].default_value = .625
            links.new(geometry.outputs['Pointiness'], ranged.inputs['Value'])
            return ranged.outputs['Result']
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
    if key in {'height', 'uv_border'}:
        constant = nodes.new('ShaderNodeValue')
        constant.outputs[0].default_value = .5 if key == 'height' else 1.0
        return constant.outputs[0]
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
