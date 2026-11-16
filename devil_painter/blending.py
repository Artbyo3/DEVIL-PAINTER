import numpy

BLEND_MODES = (('MIX', 'Normal'), ('MULTIPLY', 'Multiply'), ('SCREEN', 'Screen'), ('OVERLAY', 'Overlay'), ('ADD', 'Add'))
BASE_COLOR = (0.8, 0.8, 0.8)
BASE_ROUGHNESS = 0.5
BASE_METALLIC = 0.0


def blend(mode, below, above, factor):
    if mode == 'MIX':
        return below + factor * (above - below)
    if mode == 'MULTIPLY':
        return below * (1 - factor + factor * above)
    if mode == 'SCREEN':
        return 1 - (1 - factor + factor * (1 - above)) * (1 - below)
    if mode == 'OVERLAY':
        dark = below * (1 - factor + 2 * factor * above)
        light = 1 - (1 - factor + 2 * factor * (1 - above)) * (1 - below)
        return numpy.where(below < .5, dark, light)
    if mode == 'ADD':
        return below + factor * above
    raise ValueError('Unknown blend mode: ' + mode)


def srgb_to_linear(values):
    return numpy.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4)


def linear_to_srgb(values):
    values = numpy.clip(values, 0, 1)
    return numpy.where(values <= .0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - .055)


def composite(size, layers):
    color = numpy.empty((size, size, 3), dtype=numpy.float32)
    color[:] = BASE_COLOR
    roughness = numpy.full((size, size, 1), BASE_ROUGHNESS, dtype=numpy.float32)
    metallic = numpy.full((size, size, 1), BASE_METALLIC, dtype=numpy.float32)
    for layer in layers:
        factor = numpy.full((size, size, 1), layer['opacity'], dtype=numpy.float32)
        if layer['coverage'] is not None:
            factor = factor * layer['coverage']
        if layer['mask'] is not None:
            factor = factor * layer['mask']
        if layer['use_color']:
            color = blend(layer['blend'], color, layer['color'], factor)
        if layer['use_roughness']:
            roughness = roughness + factor * (layer['roughness'] - roughness)
        if layer['use_metallic']:
            metallic = metallic + factor * (layer['metallic'] - metallic)
    return dict(base_color=numpy.clip(color, 0, 1), roughness=numpy.clip(roughness, 0, 1), metallic=numpy.clip(metallic, 0, 1))
