from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    key: str
    label: str
    node: str
    output: str
    settings: tuple = ()
    inputs: tuple = ()
    detail: tuple = ()
    span: tuple = (0.0, 1.0)


PATTERNS = (Pattern('NOISE', 'Noise', 'ShaderNodeTexNoise', 'Fac', detail=('Detail', 15.0)),
            Pattern('GRUNGE', 'Grunge', 'ShaderNodeTexNoise', 'Fac', inputs=(('Roughness', .75), ('Distortion', .6)), detail=('Detail', 15.0)),
            Pattern('CELLS', 'Cells', 'ShaderNodeTexVoronoi', 'Distance', detail=('Randomness', 1.0), span=(0.0, .9)),
            Pattern('CRACKS', 'Cracks', 'ShaderNodeTexVoronoi', 'Distance', settings=(('feature', 'DISTANCE_TO_EDGE'),), detail=('Randomness', 1.0),
                    span=(0.0, .25)),
            Pattern('WOOD', 'Wood', 'ShaderNodeTexWave', 'Fac', settings=(('wave_type', 'RINGS'),), inputs=(('Detail', 4.0),),
                    detail=('Distortion', 12.0)),
            Pattern('STRIPES', 'Stripes', 'ShaderNodeTexWave', 'Fac', settings=(('wave_type', 'BANDS'),), detail=('Distortion', 4.0)),
            Pattern('BRICKS', 'Bricks', 'ShaderNodeTexBrick', 'Fac', inputs=(('Color1', (1.0, 1.0, 1.0, 1.0)), ('Color2', (1.0, 1.0, 1.0, 1.0)),
                                                                             ('Mortar', (0.0, 0.0, 0.0, 1.0))), detail=('Mortar Size', .05)),
            Pattern('CHECKER', 'Checker', 'ShaderNodeTexChecker', 'Fac', inputs=(('Color1', (1.0, 1.0, 1.0, 1.0)), ('Color2', (0.0, 0.0, 0.0, 1.0)))))
PATTERN = {pattern.key: pattern for pattern in PATTERNS}


def pattern_node(nodes, key, name, location):
    pattern = PATTERN[key]
    node = nodes.new(pattern.node)
    node.name = name
    node.location = location
    for attribute, value in pattern.settings:
        setattr(node, attribute, value)
    for socket_name, value in pattern.inputs:
        node.inputs[socket_name].default_value = value
    return node, node.outputs[pattern.output]


def contrast_range(key, contrast):
    low, high = PATTERN[key].span
    margin = (high - low) * contrast / 2
    return low + margin, high - margin


def set_pattern_values(node, key, scale, detail):
    pattern = PATTERN[key]
    node.inputs['Scale'].default_value = scale
    if pattern.detail:
        socket_name, factor = pattern.detail
        node.inputs[socket_name].default_value = detail * factor
