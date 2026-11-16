from dataclasses import dataclass
import numpy

BLEND_MODES = (('MIX', 'Normal'), ('MULTIPLY', 'Multiply'), ('SCREEN', 'Screen'), ('OVERLAY', 'Overlay'), ('ADD', 'Add'))


@dataclass(frozen=True)
class Channel:
    key: str
    label: str
    default: tuple
    srgb: bool
    suffix: str
    on_new_layers: bool
    on_new_sets: bool

    @property
    def width(self):
        return len(self.default)


CHANNELS = (Channel('base_color', 'Base Color', (0.8, 0.8, 0.8), True, 'BaseColor', True, True),
            Channel('roughness', 'Roughness', (0.5,), False, 'Roughness', True, True),
            Channel('metallic', 'Metallic', (0.0,), False, 'Metallic', True, True),
            Channel('normal', 'Normal', (0.5, 0.5, 1.0), False, 'Normal', False, True),
            Channel('height', 'Height', (0.5,), False, 'Height', False, True),
            Channel('emission', 'Emission', (0.0, 0.0, 0.0), True, 'Emission', False, False),
            Channel('opacity', 'Opacity', (1.0,), False, 'Opacity', False, False))
CHANNEL = {channel.key: channel for channel in CHANNELS}


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


def composite(size, channels, layers):
    result = {channel.key: numpy.full((size, size, channel.width), channel.default, dtype=numpy.float32) for channel in channels}
    for layer in layers:
        factor = numpy.full((size, size, 1), layer['opacity'], dtype=numpy.float32)
        for part in ('coverage', 'mask'):
            if layer[part] is not None:
                factor = factor * layer[part]
        for key, (value, mode) in layer['channels'].items():
            if key in result:
                result[key] = numpy.clip(blend(mode, result[key], numpy.asarray(value, dtype=numpy.float32), factor), 0, 1)
    return result
