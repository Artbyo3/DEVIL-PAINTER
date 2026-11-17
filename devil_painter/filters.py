import math
from dataclasses import dataclass
from .nodes import as_color, averaged, gray, link_or_set, math_node, mesh_signal, mix_color, mix_value, offset, vector_math

BLUR_TAPS = 8
WARP_REACH = .1
POSTERIZE_STEPS = 14
LIGHT_SLOPE = 1.0
RIPPLE_REACH = .02
SWIRL_TURNS = 2.0
SEPIA = (1.07, .74, .43, 1.0)
WARM = (1.0, .78, .55, 1.0)
COOL = (.6, .78, 1.0, 1.0)
RADIUS = ('radius', 'Radius', 32.0)
AMOUNT = ('amount', 'Amount', 1.0)
SCALE = ('scale', 'Scale', 50.0)
ANGLE = ('angle', 'Angle', 360.0)
GROUPS = ('Blur and sharpen', 'Distort', 'Edges', 'Adjust', 'Color', 'Surface finish', 'Lighting')


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    group: str
    sliders: tuple = ()
    colors: tuple = ()
    sampling: bool = False
    color_only: bool = False


def blur_like(key, label, group, *sliders, color_only=False):
    return Filter(key, label, group, sliders, sampling=True, color_only=color_only)


def surface(key, label):
    return Filter(key, label, 'Surface finish', (AMOUNT, SCALE), (('color', 'Color'),))


FILTERS = (
    blur_like('BLUR', 'Blur', 'Blur and sharpen', RADIUS),
    blur_like('DIRECTIONAL_BLUR', 'Directional blur', 'Blur and sharpen', RADIUS, ANGLE),
    blur_like('RADIAL_BLUR', 'Radial blur', 'Blur and sharpen', RADIUS),
    blur_like('SPIN_BLUR', 'Spin blur', 'Blur and sharpen', ANGLE),
    blur_like('SHARPEN', 'Sharpen', 'Blur and sharpen', RADIUS, AMOUNT),
    blur_like('GLOW', 'Glow', 'Blur and sharpen', RADIUS, AMOUNT),
    blur_like('WARP', 'Warp', 'Distort', AMOUNT, SCALE),
    blur_like('RIPPLE', 'Ripple', 'Distort', AMOUNT, SCALE),
    blur_like('SWIRL', 'Swirl', 'Distort', AMOUNT),
    blur_like('PIXELATE', 'Pixelate', 'Distort', RADIUS),
    blur_like('TILE', 'Tile', 'Distort', ('scale', 'Repeats', 50.0)),
    blur_like('OFFSET', 'Offset', 'Distort', AMOUNT, ANGLE),
    blur_like('ROTATE', 'Rotate', 'Distort', ANGLE),
    blur_like('MIRROR_X', 'Mirror horizontal', 'Distort'),
    blur_like('MIRROR_Y', 'Mirror vertical', 'Distort'),
    blur_like('KALEIDOSCOPE', 'Kaleidoscope', 'Distort'),
    blur_like('COLOR_FRINGE', 'Color fringe', 'Distort', RADIUS, color_only=True),
    blur_like('EDGE_DETECT', 'Edge detect', 'Edges', RADIUS, AMOUNT),
    blur_like('EMBOSS', 'Emboss', 'Edges', RADIUS, ANGLE),
    blur_like('DILATE', 'Dilate', 'Edges', RADIUS),
    blur_like('ERODE', 'Erode', 'Edges', RADIUS),
    blur_like('OUTLINE', 'Outline', 'Edges', RADIUS),
    blur_like('BEVEL', 'Bevel', 'Edges', RADIUS),
    Filter('INVERT', 'Invert', 'Adjust'),
    Filter('POSTERIZE', 'Posterize', 'Adjust', (('amount', 'Steps', 1.0),)),
    Filter('CONTRAST', 'Contrast', 'Adjust', (('amount', 'Contrast', 1.0),)),
    Filter('THRESHOLD', 'Threshold', 'Adjust', (('amount', 'Level', 1.0),)),
    Filter('SOFT_THRESHOLD', 'Soft threshold', 'Adjust', (('amount', 'Level', 1.0), ('contrast', 'Softness', .98))),
    Filter('BRIGHTNESS', 'Brightness', 'Adjust', (('brightness', 'Brightness', 2.0),)),
    Filter('GAMMA', 'Gamma', 'Adjust', (('gamma', 'Gamma', 4.0),)),
    Filter('EXPOSURE', 'Exposure', 'Adjust', (('amount', 'Exposure', 1.0),)),
    Filter('CLAMP', 'Clamp', 'Adjust', (('in_low', 'Low', 1.0), ('in_high', 'High', 1.0))),
    Filter('SOLARIZE', 'Solarize', 'Adjust', (('amount', 'Level', 1.0),)),
    Filter('BANDS', 'Bands', 'Adjust', (('scale', 'Bands', 50.0),)),
    Filter('FADE', 'Fade', 'Adjust', (AMOUNT,), (('color', 'Fade to'),)),
    Filter('GRAIN', 'Grain', 'Adjust', (AMOUNT, SCALE)),
    Filter('DITHER', 'Dither', 'Adjust', (SCALE,)),
    Filter('HALFTONE', 'Halftone', 'Adjust', (SCALE,)),
    Filter('HSV', 'Hue, saturation, value', 'Color', (('hue', 'Hue', 1.0), ('saturation', 'Saturation', 2.0), ('brightness', 'Value', 2.0)),
           color_only=True),
    Filter('TINT', 'Tint', 'Color', colors=(('color', 'Tint'),), color_only=True),
    Filter('GRADIENT_MAP', 'Gradient map', 'Color', colors=(('color_b', 'Dark'), ('color', 'Light')), color_only=True),
    Filter('DESATURATE', 'Desaturate', 'Color', (AMOUNT,), color_only=True),
    Filter('COLORIZE', 'Colorize', 'Color', colors=(('color', 'Color'),), color_only=True),
    Filter('SEPIA', 'Sepia', 'Color', color_only=True),
    Filter('TEMPERATURE', 'Temperature', 'Color', (('amount', 'Cool to warm', 1.0),), color_only=True),
    Filter('CHANNEL_SWAP', 'Swap red and blue', 'Color', color_only=True),
    Filter('REPLACE_COLOR', 'Replace color', 'Color', (('amount', 'Tolerance', 1.0),), (('color', 'From'), ('color_b', 'To')), color_only=True),
    Filter('COLOR_VARIATION', 'Color variation', 'Color', (AMOUNT, SCALE), color_only=True),
    Filter('VIBRANCE', 'Vibrance', 'Color', (AMOUNT,), color_only=True),
    surface('DUST', 'Dust'),
    surface('SCRATCHES', 'Scratches'),
    surface('RUST_SPOTS', 'Rust spots'),
    surface('GRUNGE', 'Grunge'),
    surface('CRACKS', 'Cracks'),
    surface('STAINS', 'Stains'),
    surface('FINGERPRINTS', 'Fingerprints'),
    surface('BRUSHED', 'Brushed metal'),
    surface('HAMMERED', 'Hammered'),
    surface('DRIPS', 'Drips'),
    surface('SPECKLE', 'Speckle'),
    surface('WATER_SPOTS', 'Water spots'),
    Filter('LIGHT', 'Directional light', 'Lighting', (ANGLE, AMOUNT), color_only=True),
    Filter('AO_SHADE', 'Occlusion shading', 'Lighting', (AMOUNT,)),
    Filter('EDGE_HIGHLIGHT', 'Edge highlight', 'Lighting', (AMOUNT,)),
    Filter('CAVITY_SHADE', 'Cavity darken', 'Lighting', (AMOUNT,)),
    Filter('TOP_LIGHT', 'Top light', 'Lighting', (AMOUNT,)),
    Filter('HEIGHT_GRADIENT', 'Height gradient', 'Lighting', (AMOUNT,)),
)
FILTER = {item.key: item for item in FILTERS}


def ring_offsets(step):
    return [(math.cos(index * math.tau / BLUR_TAPS) * step, math.sin(index * math.tau / BLUR_TAPS) * step) for index in range(BLUR_TAPS)]


def split_xyz(build, vector):
    node = build.nodes.new('ShaderNodeSeparateXYZ')
    build.links.new(vector, node.inputs['Vector'])
    return node.outputs['X'], node.outputs['Y']


def join_xyz(build, x, y):
    node = build.nodes.new('ShaderNodeCombineXYZ')
    link_or_set(build, node.inputs['X'], x)
    link_or_set(build, node.inputs['Y'], y)
    return node.outputs['Vector']


def local(build, value):
    return math_node(build.nodes, build.links, 'FRACT', value, 0.0)


def mirrored(build, value):
    nodes, links = build.nodes, build.links
    fraction = local(build, value)
    folded = math_node(nodes, links, 'SUBTRACT', .5, math_node(nodes, links, 'ABSOLUTE', math_node(nodes, links, 'SUBTRACT', fraction, .5), 0.0))
    return math_node(nodes, links, 'ADD', math_node(nodes, links, 'SUBTRACT', value, fraction), folded)


def around_center(build, vector, angle_of):
    nodes, links = build.nodes, build.links
    u, v = split_xyz(build, vector)
    cu, cv = math_node(nodes, links, 'SUBTRACT', local(build, u), .5), math_node(nodes, links, 'SUBTRACT', local(build, v), .5)
    angle = angle_of(math_node(nodes, links, 'SQRT', math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', cu, cu),
                                                              math_node(nodes, links, 'MULTIPLY', cv, cv)), 0.0))
    cosine, sine = math_node(nodes, links, 'COSINE', angle, 0.0), math_node(nodes, links, 'SINE', angle, 0.0)
    ru = math_node(nodes, links, 'SUBTRACT', math_node(nodes, links, 'MULTIPLY', cu, cosine), math_node(nodes, links, 'MULTIPLY', cv, sine))
    rv = math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', cu, sine), math_node(nodes, links, 'MULTIPLY', cv, cosine))
    base_u = math_node(nodes, links, 'SUBTRACT', u, cu)
    base_v = math_node(nodes, links, 'SUBTRACT', v, cv)
    return join_xyz(build, math_node(nodes, links, 'ADD', base_u, ru), math_node(nodes, links, 'ADD', base_v, rv))


def warp_vector(build, effect, vector):
    noise = build.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = effect.scale
    build.links.new(vector, noise.inputs['Vector'])
    centered = vector_math(build.nodes, build.links, 'SUBTRACT', noise.outputs['Color'], (.5, .5, .5))
    return vector_math(build.nodes, build.links, 'MULTIPLY_ADD', centered, (effect.amount * WARP_REACH,) * 3, vector)


def remap_vector(build, effect, vector):
    nodes, links = build.nodes, build.links
    key = effect.filter
    if key == 'WARP':
        return warp_vector(build, effect, vector)
    u, v = split_xyz(build, vector)
    if key == 'RIPPLE':
        wave = math_node(nodes, links, 'SINE', math_node(nodes, links, 'MULTIPLY', v, effect.scale * math.tau), 0.0)
        return join_xyz(build, math_node(nodes, links, 'ADD', u, math_node(nodes, links, 'MULTIPLY', wave, effect.amount * RIPPLE_REACH)), v)
    if key == 'PIXELATE':
        cell = max(effect.radius, 1.0) / max(build.resolution, 1)
        snap = [math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'ADD', math_node(nodes, links, 'FLOOR',
                math_node(nodes, links, 'DIVIDE', axis, cell), 0.0), .5), cell) for axis in (u, v)]
        return join_xyz(build, *snap)
    if key == 'TILE':
        repeats = max(round(effect.scale), 1)
        tiled = [math_node(nodes, links, 'ADD', math_node(nodes, links, 'SUBTRACT', axis, local(build, axis)),
                           local(build, math_node(nodes, links, 'MULTIPLY', axis, float(repeats)))) for axis in (u, v)]
        return join_xyz(build, *tiled)
    if key == 'OFFSET':
        direction = math.radians(effect.angle)
        return offset(build, vector, math.cos(direction) * effect.amount, math.sin(direction) * effect.amount)
    if key == 'ROTATE':
        return around_center(build, vector, lambda distance: -math.radians(effect.angle))
    if key == 'SWIRL':
        return around_center(build, vector, lambda distance: math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'SUBTRACT', .5, distance),
                                                                       effect.amount * SWIRL_TURNS * math.tau))
    mirror_u = key in {'MIRROR_X', 'KALEIDOSCOPE'}
    mirror_v = key in {'MIRROR_Y', 'KALEIDOSCOPE'}
    return join_xyz(build, mirrored(build, u) if mirror_u else u, mirrored(build, v) if mirror_v else v)


REMAPS = {'WARP', 'RIPPLE', 'PIXELATE', 'TILE', 'OFFSET', 'ROTATE', 'SWIRL', 'MIRROR_X', 'MIRROR_Y', 'KALEIDOSCOPE'}


def extreme(build, samples, mode, operation):
    color, alpha = samples[0]
    for next_color, next_alpha in samples[1:]:
        color = mix_color(build, color, next_color, 1.0, mode)
        alpha = math_node(build.nodes, build.links, operation, alpha, next_alpha)
    return color, alpha


def wrap_sampling(build, effect, inner):
    step = effect.radius / max(build.resolution, 1)
    key = effect.filter

    def ring(image, vector):
        return [inner(image, vector)] + [inner(image, offset(build, vector, dx, dy)) for dx, dy in ring_offsets(step)]

    def line(image, vector, direction):
        positions = [(index / (BLUR_TAPS // 2)) * step for index in range(-(BLUR_TAPS // 2), BLUR_TAPS // 2 + 1)]
        return [inner(image, offset(build, vector, math.cos(direction) * position, math.sin(direction) * position)) for position in positions]

    def radial(image, vector):
        u, v = split_xyz(build, vector)
        center = join_xyz(build, math_node(build.nodes, build.links, 'SUBTRACT', u, local(build, u)),
                          math_node(build.nodes, build.links, 'SUBTRACT', v, local(build, v)))
        center = vector_math(build.nodes, build.links, 'ADD', center, (.5, .5, 0.0))
        toward = vector_math(build.nodes, build.links, 'SUBTRACT', vector, center)
        reach = effect.radius / 64
        return [inner(image, vector_math(build.nodes, build.links, 'MULTIPLY_ADD', toward, (1 - reach * index / BLUR_TAPS,) * 3, center))
                for index in range(BLUR_TAPS + 1)]

    def spin(image, vector):
        return [inner(image, around_center(build, vector, lambda distance, index=index: math.radians(effect.angle) * (index / BLUR_TAPS - .5)))
                for index in range(BLUR_TAPS + 1)]

    def mixed(center, result):
        return mix_color(build, center[0], result[0], effect.opacity), mix_value(build, center[1], result[1], effect.opacity)

    def sample(image, vector):
        if key in REMAPS:
            return inner(image, remap_vector(build, effect, vector))
        center = inner(image, vector)
        if key == 'COLOR_FRINGE':
            red = inner(image, offset(build, vector, step, 0.0))[0]
            blue = inner(image, offset(build, vector, -step, 0.0))[0]
            channels = [build.nodes.new('ShaderNodeSeparateColor') for _ in range(3)]
            for node, source in zip(channels, (red, center[0], blue)):
                build.links.new(source, node.inputs['Color'])
            joined = build.nodes.new('ShaderNodeCombineColor')
            for index, node in enumerate(channels):
                build.links.new(node.outputs[index], joined.inputs[index])
            return mixed(center, (joined.outputs['Color'], center[1]))
        if key == 'EMBOSS':
            direction = math.radians(effect.angle)
            shifted = inner(image, offset(build, vector, math.cos(direction) * step, math.sin(direction) * step))
            relief = vector_math(build.nodes, build.links, 'ADD', vector_math(build.nodes, build.links, 'SUBTRACT', center[0], shifted[0]), (.5, .5, .5))
            value = math_node(build.nodes, build.links, 'ADD', math_node(build.nodes, build.links, 'SUBTRACT', center[1], shifted[1]), .5)
            return mixed(center, (relief, value))
        if key == 'DILATE':
            return mixed(center, extreme(build, ring(image, vector), 'LIGHTEN', 'MAXIMUM'))
        if key == 'ERODE':
            return mixed(center, extreme(build, ring(image, vector), 'DARKEN', 'MINIMUM'))
        if key == 'OUTLINE':
            taps = ring(image, vector)
            grown, shrunk = extreme(build, taps, 'LIGHTEN', 'MAXIMUM'), extreme(build, taps, 'DARKEN', 'MINIMUM')
            return mixed(center, (mix_color(build, grown[0], shrunk[0], 1.0, 'DIFFERENCE'),
                                  math_node(build.nodes, build.links, 'SUBTRACT', grown[1], shrunk[1])))
        if key == 'DIRECTIONAL_BLUR':
            blurred = averaged(build, line(image, vector, math.radians(effect.angle)))
        elif key == 'RADIAL_BLUR':
            blurred = averaged(build, radial(image, vector))
        elif key == 'SPIN_BLUR':
            blurred = averaged(build, spin(image, vector))
        else:
            blurred = averaged(build, ring(image, vector))
        if key == 'SHARPEN':
            detail = mix_color(build, center[0], blurred[0], 1.0, 'SUBTRACT')
            return mix_color(build, center[0], detail, effect.amount * 2, 'ADD'), center[1]
        if key == 'GLOW':
            return mixed(center, (mix_color(build, center[0], blurred[0], effect.amount, 'ADD'),
                                  math_node(build.nodes, build.links, 'ADD', center[1], math_node(build.nodes, build.links, 'MULTIPLY', blurred[1], effect.amount))))
        if key == 'EDGE_DETECT':
            gain = 1 + effect.amount * 8
            edges = vector_math(build.nodes, build.links, 'MULTIPLY', vector_math(build.nodes, build.links, 'ABSOLUTE',
                                vector_math(build.nodes, build.links, 'SUBTRACT', center[0], blurred[0])), (gain,) * 3)
            value = math_node(build.nodes, build.links, 'MULTIPLY', math_node(build.nodes, build.links, 'ABSOLUTE',
                              math_node(build.nodes, build.links, 'SUBTRACT', center[1], blurred[1]), 0.0), gain)
            return mixed(center, (edges, value))
        if key == 'BEVEL':
            return mixed(center, (blurred[0], math_node(build.nodes, build.links, 'MULTIPLY', blurred[1], 2.0)))
        return mixed(center, blurred)
    return sample


def noise_factor(build, effect, scale=None, stretch=(1.0, 1.0, 1.0), detail=8.0):
    coordinates = build.nodes.new('ShaderNodeTexCoord')
    noise = build.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = effect.scale if scale is None else scale
    noise.inputs['Detail'].default_value = detail
    build.links.new(vector_math(build.nodes, build.links, 'MULTIPLY', coordinates.outputs['Object'], stretch), noise.inputs['Vector'])
    return noise.outputs['Fac']


def voronoi(build, effect, feature='F1', output='Distance', stretch=(1.0, 1.0, 1.0)):
    coordinates = build.nodes.new('ShaderNodeTexCoord')
    cells = build.nodes.new('ShaderNodeTexVoronoi')
    cells.feature = feature
    cells.inputs['Scale'].default_value = effect.scale
    build.links.new(vector_math(build.nodes, build.links, 'MULTIPLY', coordinates.outputs['Object'], stretch), cells.inputs['Vector'])
    return cells.outputs[output]


def band(build, value, low, high):
    ranged = build.nodes.new('ShaderNodeMapRange')
    ranged.interpolation_type = 'SMOOTHSTEP'
    link_or_set(build, ranged.inputs['Value'], value)
    ranged.inputs['From Min'].default_value, ranged.inputs['From Max'].default_value = low, high
    return ranged.outputs['Result']


def inverted(build, value):
    return math_node(build.nodes, build.links, 'SUBTRACT', 1.0, value)


def surface_pattern(build, effect):
    key = effect.filter
    if key == 'DUST':
        return band(build, noise_factor(build, effect), .45, .7)
    if key == 'SCRATCHES':
        return band(build, inverted(build, voronoi(build, effect, 'DISTANCE_TO_EDGE', stretch=(1.0, 12.0, 1.0))), .93, .99)
    if key == 'RUST_SPOTS':
        return band(build, inverted(build, voronoi(build, effect)), .55, .8)
    if key == 'GRUNGE':
        return band(build, noise_factor(build, effect, detail=15.0), .4, .65)
    if key == 'CRACKS':
        return band(build, inverted(build, voronoi(build, effect, 'DISTANCE_TO_EDGE')), .95, .99)
    if key == 'STAINS':
        return band(build, noise_factor(build, effect, effect.scale * .25, detail=2.0), .5, .6)
    if key == 'FINGERPRINTS':
        wave = build.nodes.new('ShaderNodeTexWave')
        wave.wave_type = 'RINGS'
        wave.inputs['Scale'].default_value = effect.scale
        wave.inputs['Distortion'].default_value = 4.0
        coordinates = build.nodes.new('ShaderNodeTexCoord')
        build.links.new(coordinates.outputs['Object'], wave.inputs['Vector'])
        spots = band(build, noise_factor(build, effect, effect.scale * .1, detail=1.0), .5, .6)
        return math_node(build.nodes, build.links, 'MULTIPLY', band(build, wave.outputs['Fac'], .5, .9), spots)
    if key == 'BRUSHED':
        return noise_factor(build, effect, stretch=(1.0, 60.0, 60.0))
    if key == 'HAMMERED':
        return band(build, voronoi(build, effect, 'SMOOTH_F1'), .1, .6)
    if key == 'DRIPS':
        return band(build, noise_factor(build, effect, stretch=(6.0, 6.0, .3)), .55, .7)
    if key == 'SPECKLE':
        return band(build, noise_factor(build, effect, effect.scale * 20, detail=0.0), .68, .7)
    return band(build, inverted(build, voronoi(build, effect)), .8, .83)


def lighting_factor(build, effect):
    nodes, links = build.nodes, build.links
    key = effect.filter
    if key == 'LIGHT':
        geometry = nodes.new('ShaderNodeNewGeometry')
        direction = math.radians(effect.angle)
        dot = nodes.new('ShaderNodeVectorMath')
        dot.operation = 'DOT_PRODUCT'
        links.new(geometry.outputs['Normal'], dot.inputs[0])
        dot.inputs[1].default_value = (math.cos(direction) * LIGHT_SLOPE, math.sin(direction) * LIGHT_SLOPE, 1.0)
        return math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', dot.outputs['Value'], .5), .5)
    if key == 'AO_SHADE':
        return mesh_signal(build, 'ao', 0)
    if key == 'EDGE_HIGHLIGHT':
        return math_node(nodes, links, 'ADD', .5, math_node(nodes, links, 'MAXIMUM', math_node(nodes, links, 'SUBTRACT', mesh_signal(build, 'curvature', 0), .5), 0.0))
    if key == 'CAVITY_SHADE':
        return math_node(nodes, links, 'ADD', .5, math_node(nodes, links, 'MINIMUM', math_node(nodes, links, 'SUBTRACT', mesh_signal(build, 'curvature', 0), .5), 0.0))
    if key == 'TOP_LIGHT':
        return mesh_signal(build, 'world_normal', 2)
    return mesh_signal(build, 'position', 2)


def adjusted(build, color, effect):
    nodes, links = build.nodes, build.links
    key = effect.filter
    if key == 'INVERT':
        node = nodes.new('ShaderNodeInvert')
        links.new(color, node.inputs['Color'])
        return node.outputs['Color']
    if key == 'POSTERIZE':
        steps = 2.0 + round(effect.amount * POSTERIZE_STEPS)
        return vector_math(nodes, links, 'DIVIDE', vector_math(nodes, links, 'FLOOR', vector_math(nodes, links, 'MULTIPLY', color, (steps,) * 3)),
                           (steps - 1,) * 3)
    if key == 'CONTRAST':
        node = nodes.new('ShaderNodeBrightContrast')
        node.inputs['Contrast'].default_value = (effect.amount - .5) * 2
        links.new(color, node.inputs['Color'])
        return node.outputs['Color']
    if key in {'THRESHOLD', 'SOFT_THRESHOLD'}:
        softness = effect.contrast * .5 if key == 'SOFT_THRESHOLD' else 1e-3
        return as_color(build, band(build, gray(build, color), effect.amount - softness, effect.amount + softness))
    if key == 'BRIGHTNESS':
        return vector_math(nodes, links, 'MULTIPLY', color, (effect.brightness,) * 3)
    if key == 'GAMMA':
        node = nodes.new('ShaderNodeGamma')
        links.new(color, node.inputs['Color'])
        node.inputs['Gamma'].default_value = 1.0 / effect.gamma
        return node.outputs['Color']
    if key == 'EXPOSURE':
        return vector_math(nodes, links, 'MULTIPLY', color, (2 ** ((effect.amount - .5) * 4),) * 3)
    if key == 'CLAMP':
        low, high = effect.in_low, max(effect.in_high, effect.in_low)
        return vector_math(nodes, links, 'MINIMUM', vector_math(nodes, links, 'MAXIMUM', color, (low,) * 3), (high,) * 3)
    if key == 'SOLARIZE':
        flipped = nodes.new('ShaderNodeInvert')
        links.new(color, flipped.inputs['Color'])
        return mix_color(build, color, flipped.outputs['Color'], math_node(nodes, links, 'GREATER_THAN', gray(build, color), effect.amount))
    if key == 'BANDS':
        stripes = math_node(nodes, links, 'SINE', math_node(nodes, links, 'MULTIPLY', gray(build, color), effect.scale * math.tau), 0.0)
        return as_color(build, math_node(nodes, links, 'ADD', math_node(nodes, links, 'MULTIPLY', stripes, .5), .5))
    if key == 'FADE':
        return mix_color(build, color, (*effect.color, 1.0), effect.amount)
    if key == 'GRAIN':
        grain = math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'SUBTRACT', noise_factor(build, effect), .5), effect.amount * 2)
        return vector_math(nodes, links, 'ADD', color, as_color(build, grain))
    if key == 'DITHER':
        return as_color(build, math_node(nodes, links, 'GREATER_THAN', gray(build, color), noise_factor(build, effect, effect.scale * 20, detail=0.0)))
    if key == 'HALFTONE':
        dots = voronoi(build, effect)
        return as_color(build, math_node(nodes, links, 'LESS_THAN', dots, math_node(nodes, links, 'MULTIPLY', gray(build, color), .75)))
    return None


def colored(build, color, effect):
    nodes, links = build.nodes, build.links
    key = effect.filter
    if key == 'HSV':
        node = nodes.new('ShaderNodeHueSaturation')
        node.inputs['Hue'].default_value, node.inputs['Saturation'].default_value = effect.hue, effect.saturation
        node.inputs['Value'].default_value = effect.brightness
        links.new(color, node.inputs['Color'])
        return node.outputs['Color']
    if key == 'TINT':
        return mix_color(build, color, (*effect.color, 1.0), 1.0, 'MULTIPLY')
    if key == 'GRADIENT_MAP':
        return mix_color(build, (*effect.color_b, 1.0), (*effect.color, 1.0), gray(build, color))
    if key == 'DESATURATE':
        return mix_color(build, color, as_color(build, gray(build, color)), effect.amount)
    if key == 'COLORIZE':
        return mix_color(build, as_color(build, gray(build, color)), (*effect.color, 1.0), 1.0, 'MULTIPLY')
    if key == 'SEPIA':
        return mix_color(build, as_color(build, gray(build, color)), SEPIA, 1.0, 'MULTIPLY')
    if key == 'TEMPERATURE':
        warmth = abs(effect.amount - .5) * 2
        return mix_color(build, color, mix_color(build, color, WARM if effect.amount >= .5 else COOL, 1.0, 'MULTIPLY'), warmth)
    if key == 'CHANNEL_SWAP':
        split = nodes.new('ShaderNodeSeparateColor')
        links.new(color, split.inputs['Color'])
        joined = nodes.new('ShaderNodeCombineColor')
        for source, target in ((2, 0), (1, 1), (0, 2)):
            links.new(split.outputs[source], joined.inputs[target])
        return joined.outputs['Color']
    if key == 'REPLACE_COLOR':
        distance = nodes.new('ShaderNodeVectorMath')
        distance.operation = 'DISTANCE'
        links.new(color, distance.inputs[0])
        distance.inputs[1].default_value = tuple(effect.color)
        near = band(build, distance.outputs['Value'], effect.amount * .5 + .05, effect.amount * .5 + 1e-3)
        return mix_color(build, color, (*effect.color_b, 1.0), near)
    if key == 'COLOR_VARIATION':
        node = nodes.new('ShaderNodeHueSaturation')
        links.new(color, node.inputs['Color'])
        links.new(math_node(nodes, links, 'ADD', .5 - effect.amount * .1, math_node(nodes, links, 'MULTIPLY', noise_factor(build, effect), effect.amount * .2)),
                  node.inputs['Hue'])
        return node.outputs['Color']
    if key == 'VIBRANCE':
        node = nodes.new('ShaderNodeHueSaturation')
        node.inputs['Saturation'].default_value = 1 + effect.amount
        links.new(color, node.inputs['Color'])
        return node.outputs['Color']
    return None


def filter_color(build, color, effect):
    item = FILTER[effect.filter]
    if item.sampling:
        return color
    if item.group == 'Surface finish':
        result = mix_color(build, color, (*effect.color, 1.0), math_node(build.nodes, build.links, 'MULTIPLY', surface_pattern(build, effect), effect.amount))
    elif item.group == 'Lighting':
        shading = mix_color(build, (0.0, 0.0, 0.0, 1.0), (2.0, 2.0, 2.0, 1.0), lighting_factor(build, effect))
        result = mix_color(build, color, mix_color(build, color, shading, 1.0, 'MULTIPLY'), effect.amount)
    else:
        result = adjusted(build, color, effect) or colored(build, color, effect)
    if effect.filter == 'INVERT':
        result.node.inputs['Fac'].default_value = effect.opacity
        return result
    return mix_color(build, color, result, effect.opacity)


def filter_value(build, value, effect):
    item = FILTER[effect.filter]
    if item.sampling or item.color_only:
        return value
    nodes, links = build.nodes, build.links
    if item.group == 'Surface finish':
        result = math_node(nodes, links, 'MULTIPLY', value, inverted(build, math_node(nodes, links, 'MULTIPLY', surface_pattern(build, effect), effect.amount)))
    elif item.group == 'Lighting':
        result = math_node(nodes, links, 'MULTIPLY', value, mix_value(build, 1.0, math_node(nodes, links, 'MULTIPLY', lighting_factor(build, effect), 2.0),
                                                                      effect.amount))
    elif effect.filter == 'INVERT':
        result = math_node(nodes, links, 'SUBTRACT', 1.0, value)
    elif effect.filter == 'THRESHOLD':
        result = math_node(nodes, links, 'GREATER_THAN', value, effect.amount)
    elif effect.filter == 'GRAIN':
        result = math_node(nodes, links, 'ADD', value, math_node(nodes, links, 'MULTIPLY', math_node(nodes, links, 'SUBTRACT', noise_factor(build, effect), .5),
                                                                  effect.amount * 2))
    else:
        result = gray(build, adjusted(build, as_color(build, value), effect))
    return mix_value(build, value, result, effect.opacity)


def content_warp(effects):
    return next((effect for effect in effects if effect.enabled and effect.target == 'CONTENT' and effect.kind == 'FILTER'
                 and effect.filter == 'WARP'), None)

