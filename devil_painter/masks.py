from dataclasses import dataclass
from .nodes import math_node, mesh_signal

GENERATOR_VALUES = ('gen_level', 'gen_contrast', 'gen_noise', 'gen_scale', 'gen_invert', 'gen_edges', 'gen_dirt', 'gen_top')
GENERATOR_FIELDS = ('generator',) + GENERATOR_VALUES
BUILDER_SLIDERS = (('GEN_EDGES', 'Edges', 'gen_edges'), ('GEN_DIRT', 'Dirt', 'gen_dirt'), ('GEN_TOP', 'Top', 'gen_top'))
STRETCH = {'NOISE': (1.0, 1.0, 1.0), 'SCRATCH': (1.0, 1.0, 30.0), 'STREAKS': (6.0, 6.0, .3), 'CELLS': (1.0, 1.0, 1.0)}


@dataclass(frozen=True)
class Term:
    map_key: str
    channel: int
    offset: float = 0.0
    gain: float = 1.0
    absolute: bool = False
    weight: str = ''


@dataclass(frozen=True)
class Generator:
    key: str
    label: str
    terms: tuple = ()
    breakup: str = 'NOISE'
    radial: bool = False
    flip: bool = False

    @property
    def maps(self):
        return tuple(dict.fromkeys(term.map_key for term in self.terms))


EDGES = Term('curvature', 0, -.5, 2.0)
DIRT = Term('ao', 0, -1.0, -1.0)
UP = Term('world_normal', 2, -.5, 2.0)
GENERATORS = (Generator('CURVATURE', 'Curvature', (Term('curvature', 0),)), Generator('EDGE_WEAR', 'Edge wear', (EDGES,)),
              Generator('METAL_EDGE_WEAR', 'Metal edge wear', (EDGES,), 'SCRATCH'),
              Generator('FIBERGLASS_EDGE_WEAR', 'Fiberglass edge wear', (EDGES,), 'CELLS'),
              Generator('CAVITY', 'Cavity', (Term('curvature', 0, -.5, -2.0),)), Generator('AO', 'Ambient occlusion', (Term('ao', 0),)),
              Generator('DIRT', 'Dirt', (DIRT,)), Generator('GRIME_STREAKS', 'Grime streaks', (DIRT,), 'STREAKS'),
              Generator('THICKNESS', 'Thickness', (Term('thickness', 0),)), Generator('GRADIENT', 'Ground gradient', (Term('position', 2, -1.0, -1.0),)),
              Generator('GRADIENT_X', '3D gradient X', (Term('position', 0),)), Generator('GRADIENT_Y', '3D gradient Y', (Term('position', 1),)),
              Generator('GRADIENT_Z', '3D gradient Z', (Term('position', 2),)), Generator('SPHERICAL', '3D spherical gradient', (Term('position', 0),), radial=True),
              Generator('TOP', 'Top surfaces', (UP,)), Generator('BOTTOM', 'Bottom surfaces', (Term('world_normal', 2, -.5, -2.0),)),
              Generator('SIDES', 'Side surfaces', (Term('world_normal', 2, -.5, 2.0, absolute=True),), flip=True),
              Generator('UV_BORDER', 'UV border distance', (Term('uv_border', 0),)), Generator('HEIGHT', 'Height', (Term('height', 0, -.5, 2.0),)),
              Generator('BUILDER', 'Mask builder', (Term('curvature', 0, -.5, 2.0, weight='gen_edges'), Term('ao', 0, -1.0, -1.0, weight='gen_dirt'),
                                                    Term('world_normal', 2, -.5, 2.0, weight='gen_top'))),
              Generator('NOISE', 'Noise'), Generator('SCRATCHES', 'Scratches', breakup='SCRATCH'))
GENERATOR = {item.key: item for item in GENERATORS}


def smart_mask(name, generator, level, contrast, noise, scale, invert=False, edges=.5, dirt=.5, top=0.0):
    return dict(name=name, generator=generator, gen_level=level, gen_contrast=contrast, gen_noise=noise, gen_scale=scale, gen_invert=invert,
                gen_edges=edges, gen_dirt=dirt, gen_top=top)


SMART_MASKS = (
    smart_mask('Edge wear', 'EDGE_WEAR', .2, .6, .35, 30.0), smart_mask('Soft edges', 'EDGE_WEAR', .1, .2, 0.0, 10.0),
    smart_mask('Dirt', 'DIRT', .3, .5, .25, 20.0), smart_mask('Grime', 'DIRT', .15, .75, .5, 8.0),
    smart_mask('Cavity', 'CAVITY', .15, .6, .2, 25.0), smart_mask('Ground dust', 'GRADIENT', .65, .45, .3, 6.0),
    smart_mask('Clean faces', 'EDGE_WEAR', .2, .6, .2, 30.0, True), smart_mask('Thin areas', 'THICKNESS', .5, .5, 0.0, 10.0),
    smart_mask('Chipped paint', 'FIBERGLASS_EDGE_WEAR', .25, .8, .45, 40.0), smart_mask('Scratched metal', 'METAL_EDGE_WEAR', .2, .7, .5, 25.0),
    smart_mask('Rain streaks', 'GRIME_STREAKS', .2, .6, .5, 12.0), smart_mask('Dusty tops', 'TOP', .6, .5, .3, 15.0),
    smart_mask('Weathered', 'BUILDER', .45, .55, .3, 20.0, edges=.6, dirt=.6, top=.3),
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


def pattern(nodes, links, name, kind):
    coordinates = nodes.new('ShaderNodeTexCoord')
    stretch = nodes.new('ShaderNodeVectorMath')
    stretch.operation = 'MULTIPLY'
    stretch.inputs[1].default_value = STRETCH[kind]
    links.new(coordinates.outputs['Object'], stretch.inputs[0])
    if kind == 'CELLS':
        texture = nodes.new('ShaderNodeTexVoronoi')
        output = texture.outputs['Distance']
    else:
        texture = nodes.new('ShaderNodeTexNoise')
        texture.inputs['Detail'].default_value = 8.0
        output = texture.outputs['Fac']
    texture.name = name + '.gen.noise'
    links.new(stretch.outputs['Vector'], texture.inputs['Vector'])
    return output


def term_signal(nodes, links, name, term, build, sample):
    value = operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'ADD', mesh_signal(build, term.map_key, term.channel, sample), term.offset), term.gain)
    if term.absolute:
        value = operate(nodes, links, 'ABSOLUTE', value, 0.0)
    if term.weight:
        value = operate(nodes, links, 'MULTIPLY', value, 0.0, f'{name}.gen.{term.weight}')
    return value


def radial_signal(nodes, links, build, sample):
    centered = nodes.new('ShaderNodeVectorMath')
    centered.operation = 'SUBTRACT'
    links.new(mesh_signal(build, 'position', None, sample), centered.inputs[0])
    centered.inputs[1].default_value = (.5, .5, .5)
    distance = nodes.new('ShaderNodeVectorMath')
    distance.operation = 'LENGTH'
    links.new(centered.outputs['Vector'], distance.inputs[0])
    return operate(nodes, links, 'MULTIPLY', distance.outputs['Value'], 2.0)


def generator_name(layer, effect):
    return f'{layer.uid}.{effect.uid}'


def generator_mask(nodes, links, effect, name, build, sample):
    generator = GENERATOR[effect.generator]
    if not build.live and any(key not in build.maps for key in generator.maps):
        return None
    texture = pattern(nodes, links, name, generator.breakup)
    if generator.radial:
        signal = radial_signal(nodes, links, build, sample)
    elif generator.terms:
        signal = term_signal(nodes, links, name, generator.terms[0], build, sample)
        for term in generator.terms[1:]:
            signal = operate(nodes, links, 'ADD', signal, term_signal(nodes, links, name, term, build, sample))
    else:
        signal = texture
    if generator.flip:
        signal = operate(nodes, links, 'SUBTRACT', 1.0, signal)
    breakup = operate(nodes, links, 'MULTIPLY', operate(nodes, links, 'SUBTRACT', texture, .5), 1.0, name + '.gen.amount')
    ranged = nodes.new('ShaderNodeMapRange')
    ranged.name = name + '.gen.range'
    links.new(operate(nodes, links, 'ADD', signal, breakup), ranged.inputs['Value'])
    return ranged.outputs['Result']


def id_selection(build, effect, sample):
    if not build.live and 'id' not in build.maps:
        return None
    signal = mesh_signal(build, 'id', None, sample)
    tolerance = max(effect.amount, .01)
    kept = None
    for color in id_colors(effect):
        distance = build.nodes.new('ShaderNodeVectorMath')
        distance.operation = 'DISTANCE'
        build.links.new(signal, distance.inputs[0])
        distance.inputs[1].default_value = tuple(color)
        ranged = build.nodes.new('ShaderNodeMapRange')
        build.links.new(distance.outputs['Value'], ranged.inputs['Value'])
        ranged.inputs['From Min'].default_value, ranged.inputs['From Max'].default_value = tolerance, tolerance * .5
        kept = ranged.outputs['Result'] if kept is None else math_node(build.nodes, build.links, 'MAXIMUM', kept, ranged.outputs['Result'])
    return kept


def id_colors(effect):
    return (effect.color, *(item.color for item in effect.id_colors))


def write_generator(nodes, effect, name):
    ranged = nodes[name + '.gen.range']
    width = (1 - effect.gen_contrast) * .5 + .01
    ranged.inputs['From Min'].default_value = effect.gen_level - width
    ranged.inputs['From Max'].default_value = effect.gen_level + width
    ranged.inputs['To Min'].default_value = 1.0 if effect.gen_invert else 0.0
    ranged.inputs['To Max'].default_value = 0.0 if effect.gen_invert else 1.0
    nodes[name + '.gen.noise'].inputs['Scale'].default_value = effect.gen_scale
    nodes[name + '.gen.amount'].inputs[1].default_value = effect.gen_noise * 2
    for _, _, field in BUILDER_SLIDERS:
        weight = nodes.get(f'{name}.gen.{field}')
        if weight is not None:
            weight.inputs[1].default_value = getattr(effect, field)


def write_generators(nodes, layer):
    for effect in layer.effects:
        name = generator_name(layer, effect)
        if effect.kind == 'GENERATOR' and name + '.gen.range' in nodes:
            write_generator(nodes, effect, name)
