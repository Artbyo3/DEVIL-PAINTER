from dataclasses import dataclass
from .signals import map_signal

GENERATOR_FIELDS = ('generator', 'gen_level', 'gen_contrast', 'gen_noise', 'gen_scale', 'gen_invert')


@dataclass(frozen=True)
class Generator:
    key: str
    label: str
    map_key: str
    channel: int
    offset: float
    gain: float


GENERATORS = (Generator('EDGE_WEAR', 'Edge wear', 'curvature', 0, -.5, 2.0), Generator('CAVITY', 'Cavity', 'curvature', 0, -.5, -2.0),
              Generator('DIRT', 'Dirt', 'ao', 0, -1.0, -1.0), Generator('GRADIENT', 'Ground gradient', 'position', 2, -1.0, -1.0),
              Generator('THICKNESS', 'Thickness', 'thickness', 0, 0.0, 1.0))
GENERATOR = {item.key: item for item in GENERATORS}
SMART_MASKS = (
    dict(name='Edge wear', generator='EDGE_WEAR', gen_level=.2, gen_contrast=.6, gen_noise=.35, gen_scale=30.0, gen_invert=False),
    dict(name='Soft edges', generator='EDGE_WEAR', gen_level=.1, gen_contrast=.2, gen_noise=0.0, gen_scale=10.0, gen_invert=False),
    dict(name='Dirt', generator='DIRT', gen_level=.3, gen_contrast=.5, gen_noise=.25, gen_scale=20.0, gen_invert=False),
    dict(name='Grime', generator='DIRT', gen_level=.15, gen_contrast=.75, gen_noise=.5, gen_scale=8.0, gen_invert=False),
    dict(name='Cavity', generator='CAVITY', gen_level=.15, gen_contrast=.6, gen_noise=.2, gen_scale=25.0, gen_invert=False),
    dict(name='Ground dust', generator='GRADIENT', gen_level=.65, gen_contrast=.45, gen_noise=.3, gen_scale=6.0, gen_invert=False),
    dict(name='Clean faces', generator='EDGE_WEAR', gen_level=.2, gen_contrast=.6, gen_noise=.2, gen_scale=30.0, gen_invert=True),
    dict(name='Thin areas', generator='THICKNESS', gen_level=.5, gen_contrast=.5, gen_noise=0.0, gen_scale=10.0, gen_invert=False),
)


def operate(nodes, links, operation, first, second, name=''):
    node = nodes.new('ShaderNodeMath')
    node.operation = operation
    if name:
        node.name = name
    for index, value in enumerate((first, second)):
        if isinstance(value, float):
            node.inputs[index].default_value = value
        else:
            links.new(value, node.inputs[index])
    return node.outputs[0]


def generator_mask(nodes, links, layer, maps, live, size):
    generator = GENERATOR[layer.generator]
    if live:
        source = map_signal(nodes, links, generator.map_key, size)
    else:
        image = maps.get(generator.map_key)
        if image is None:
            return None
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = image
        source = texture.outputs['Color']
    split = nodes.new('ShaderNodeSeparateColor')
    links.new(source, split.inputs['Color'])
    signal = operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'ADD', split.outputs[generator.channel], generator.offset), generator.gain)
    coordinates = nodes.new('ShaderNodeTexCoord')
    noise = nodes.new('ShaderNodeTexNoise')
    noise.name = layer.uid + '.gen.noise'
    noise.inputs['Detail'].default_value = 8.0
    links.new(coordinates.outputs['Object'], noise.inputs['Vector'])
    breakup = operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'SUBTRACT', noise.outputs['Fac'], .5), 1.0, layer.uid + '.gen.amount')
    ranged = nodes.new('ShaderNodeMapRange')
    ranged.name = layer.uid + '.gen.range'
    links.new(operate(nodes, links, 'ADD', signal, breakup), ranged.inputs['Value'])
    return ranged.outputs['Result']


def write_generator(nodes, layer):
    ranged = nodes[layer.uid + '.gen.range']
    width = (1 - layer.gen_contrast) * .5 + .01
    ranged.inputs['From Min'].default_value = layer.gen_level - width
    ranged.inputs['From Max'].default_value = layer.gen_level + width
    ranged.inputs['To Min'].default_value = 1.0 if layer.gen_invert else 0.0
    ranged.inputs['To Max'].default_value = 0.0 if layer.gen_invert else 1.0
    nodes[layer.uid + '.gen.noise'].inputs['Scale'].default_value = layer.gen_scale
    nodes[layer.uid + '.gen.amount'].inputs[1].default_value = layer.gen_noise * 2
