from dataclasses import dataclass
import numpy

BLEND_MODES = (('DISABLE', 'Disable'), ('REPLACE', 'Replace'), ('MIX', 'Normal'), ('MULTIPLY', 'Multiply'), ('DIVIDE', 'Divide'),
               ('INVERSE_DIVIDE', 'Inverse divide'), ('DARKEN', 'Darken'), ('LIGHTEN', 'Lighten'), ('ADD', 'Linear dodge (Add)'),
               ('SUBTRACT', 'Subtract'), ('INVERSE_SUBTRACT', 'Inverse subtract'), ('DIFFERENCE', 'Difference'), ('EXCLUSION', 'Exclusion'),
               ('SIGNED_ADD', 'Signed addition'), ('OVERLAY', 'Overlay'), ('SCREEN', 'Screen'), ('LINEAR_BURN', 'Linear burn'),
               ('BURN', 'Color burn'), ('DODGE', 'Color dodge'), ('SOFT_LIGHT', 'Soft light'), ('HARD_LIGHT', 'Hard light'),
               ('VIVID_LIGHT', 'Vivid light'), ('LINEAR_LIGHT', 'Linear light'), ('PIN_LIGHT', 'Pin light'), ('SATURATION', 'Saturation'),
               ('COLOR', 'Color'), ('VALUE', 'Value'), ('HUE', 'Hue'), ('NORMAL_COMBINE', 'Normal map combine'),
               ('NORMAL_DETAIL', 'Normal map detail'), ('NORMAL_INVERSE_DETAIL', 'Normal map inverse detail'))
STORED_BLENDS = ('MIX', 'DARKEN', 'MULTIPLY', 'BURN', 'LIGHTEN', 'SCREEN', 'DODGE', 'ADD', 'OVERLAY', 'SOFT_LIGHT', 'LINEAR_LIGHT', 'DIFFERENCE',
                 'EXCLUSION', 'SUBTRACT', 'DIVIDE', 'HUE', 'SATURATION', 'COLOR', 'VALUE', 'NORMAL_DETAIL', 'DISABLE', 'REPLACE', 'INVERSE_DIVIDE',
                 'INVERSE_SUBTRACT', 'SIGNED_ADD', 'LINEAR_BURN', 'HARD_LIGHT', 'VIVID_LIGHT', 'PIN_LIGHT', 'NORMAL_COMBINE', 'NORMAL_INVERSE_DETAIL')
MIX_NODE_BLENDS = frozenset(STORED_BLENDS[:19])
NORMAL_DETAIL = 'NORMAL_DETAIL'
FOLDER_BLENDS = (('PASSTHROUGH', 'Passthrough'),) + tuple((key, dict(BLEND_MODES)[key]) for key in STORED_BLENDS[:19])
USER_CHANNELS = 8


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
            Channel('flow', 'Flow map', (0.5, 0.5, 0.0), False, 'FlowMap', False, False, False),
            *(Channel(f'user{number}', f'User {number}', (0.0,), False, f'User{number}', False, False, False) for number in range(1, USER_CHANNELS + 1)))
CHANNEL = {channel.key: channel for channel in CHANNELS}


def srgb_to_linear(values):
    return numpy.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4)


def linear_to_srgb(values):
    values = numpy.clip(values, 0, 1)
    return numpy.where(values <= .0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - .055)
