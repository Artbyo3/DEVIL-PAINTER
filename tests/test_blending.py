import unittest
import numpy
from devil_painter.blending import BLEND_MODES, CHANNEL, CHANNELS, blend, composite, linear_to_srgb, srgb_to_linear


def layer(opacity=1.0, coverage=None, mask=None, **channels):
    values = channels or dict(base_color=((1.0, 0.0, 0.0), 'MIX'), roughness=((0.2,), 'MIX'), metallic=((1.0,), 'MIX'))
    return dict(opacity=opacity, coverage=coverage, mask=mask, channels=values)


class BlendTests(unittest.TestCase):
    def test_every_listed_mode_blends(self):
        below, above = numpy.array([.25, .75]), numpy.array([.5, .5])
        for mode, _ in BLEND_MODES:
            with self.subTest(mode=mode):
                self.assertTrue(numpy.allclose(blend(mode, below, above, 0.0), below))

    def test_full_factor_results(self):
        below, above = numpy.array([.25, .75]), numpy.array([.5, .5])
        self.assertTrue(numpy.allclose(blend('MIX', below, above, 1.0), above))
        self.assertTrue(numpy.allclose(blend('MULTIPLY', below, above, 1.0), below * above))
        self.assertTrue(numpy.allclose(blend('SCREEN', below, above, 1.0), 1 - (1 - below) * (1 - above)))
        self.assertTrue(numpy.allclose(blend('ADD', below, above, 1.0), below + above))
        self.assertTrue(numpy.allclose(blend('OVERLAY', below, above, 1.0), [2 * .25 * .5, 1 - 2 * .25 * .5]))

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            blend('NOPE', numpy.zeros(1), numpy.zeros(1), 1.0)

    def test_srgb_round_trip(self):
        values = numpy.linspace(0, 1, 11)
        self.assertTrue(numpy.allclose(linear_to_srgb(srgb_to_linear(values)), values, atol=1e-6))


class ChannelTests(unittest.TestCase):
    def test_registry_covers_the_standard_pbr_channels(self):
        self.assertEqual([channel.key for channel in CHANNELS],
                         ['base_color', 'roughness', 'metallic', 'normal', 'height', 'emission', 'opacity'])

    def test_color_channels_are_three_wide_and_values_one_wide(self):
        self.assertEqual({channel.key for channel in CHANNELS if channel.width == 3}, {'base_color', 'normal', 'emission'})

    def test_only_color_and_emission_are_srgb(self):
        self.assertEqual({channel.key for channel in CHANNELS if channel.srgb}, {'base_color', 'emission'})

    def test_flat_normal_is_the_default(self):
        self.assertEqual(CHANNEL['normal'].default, (0.5, 0.5, 1.0))


class CompositeTests(unittest.TestCase):
    def test_empty_stack_is_the_channel_defaults(self):
        result = composite(2, CHANNELS, [])
        for channel in CHANNELS:
            with self.subTest(channel=channel.key):
                self.assertEqual(result[channel.key].shape, (2, 2, channel.width))
                self.assertTrue(numpy.allclose(result[channel.key], channel.default))

    def test_fill_layer_covers_its_channels(self):
        result = composite(2, CHANNELS, [layer()])
        self.assertTrue(numpy.allclose(result['base_color'], (1, 0, 0)))
        self.assertTrue(numpy.allclose(result['roughness'], .2))
        self.assertTrue(numpy.allclose(result['metallic'], 1))
        self.assertTrue(numpy.allclose(result['normal'], CHANNEL['normal'].default))

    def test_coverage_mask_and_opacity_multiply(self):
        coverage = numpy.array([[[1.0], [0.0]], [[0.5], [1.0]]], dtype=numpy.float32)
        mask = numpy.array([[[1.0], [1.0]], [[1.0], [0.5]]], dtype=numpy.float32)
        result = composite(2, CHANNELS, [layer(coverage=coverage, mask=mask, opacity=.5, roughness=((.2,), 'MIX'))])
        base = CHANNEL['roughness'].default[0]
        self.assertTrue(numpy.allclose(result['roughness'], base + (coverage * mask * .5) * (.2 - base)))
        self.assertTrue(numpy.allclose(result['metallic'], CHANNEL['metallic'].default))

    def test_each_channel_blends_with_its_own_mode(self):
        result = composite(1, CHANNELS, [layer(height=((.25,), 'MIX')), layer(height=((.5,), 'MULTIPLY'), base_color=((0, 0, 1), 'MIX'))])
        self.assertTrue(numpy.allclose(result['height'], .125))
        self.assertTrue(numpy.allclose(result['base_color'], (0, 0, 1)))

    def test_channels_outside_the_set_are_ignored(self):
        result = composite(1, (CHANNEL['base_color'],), [layer(height=((1.0,), 'MIX'))])
        self.assertEqual(set(result), {'base_color'})

    def test_results_stay_in_range(self):
        result = composite(1, CHANNELS, [layer(emission=((.8, .8, .8), 'ADD')), layer(emission=((.8, .8, .8), 'ADD'))])
        self.assertTrue(numpy.allclose(result['emission'], 1.0))


if __name__ == '__main__':
    unittest.main()
