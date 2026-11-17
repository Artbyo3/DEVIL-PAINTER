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
    in_shader: bool = True

    @property
    def width(self):
        return len(self.default)


CHANNELS = (Channel('base_color', 'Base Color', (0.8, 0.8, 0.8), True, 'BaseColor', True, True),
            Channel('roughness', 'Roughness', (0.5,), False, 'Roughness', True, True),
            Channel('metallic', 'Metallic', (0.0,), False, 'Metallic', True, True),
            Channel('normal', 'Normal', (0.5, 0.5, 1.0), False, 'Normal', False, True),
            Channel('height', 'Height', (0.5,), False, 'Height', False, True),
            Channel('emission', 'Emission', (0.0, 0.0, 0.0), True, 'Emission', False, False),
            Channel('opacity', 'Opacity', (1.0,), False, 'Opacity', False, False),
            Channel('ambient_occlusion', 'Ambient Occlusion', (1.0,), False, 'AmbientOcclusion', False, False),
            Channel('user1', 'User 1', (0.0,), False, 'User1', False, False, False),
            Channel('user2', 'User 2', (0.0,), False, 'User2', False, False, False),
            Channel('user3', 'User 3', (0.0,), False, 'User3', False, False, False),
            Channel('user4', 'User 4', (0.0,), False, 'User4', False, False, False))
CHANNEL = {channel.key: channel for channel in CHANNELS}


def srgb_to_linear(values):
    return numpy.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4)


def linear_to_srgb(values):
    values = numpy.clip(values, 0, 1)
    return numpy.where(values <= .0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - .055)
