import unittest
import numpy
from devil_painter.blending import BASE_COLOR, BASE_METALLIC, BASE_ROUGHNESS, BLEND_MODES, blend, composite, linear_to_srgb, srgb_to_linear


def layer(**values):
    defaults = dict(opacity=1.0, coverage=None, mask=None, blend='MIX', color=(1.0, 0.0, 0.0),
                    use_color=True, roughness=0.2, use_roughness=True, metallic=1.0, use_metallic=True)
    defaults.update(values)
    return defaults


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


class CompositeTests(unittest.TestCase):
    def test_empty_stack_is_the_base_material(self):
        result = composite(2, [])
        self.assertTrue(numpy.allclose(result['base_color'], BASE_COLOR))
        self.assertTrue(numpy.allclose(result['roughness'], BASE_ROUGHNESS))
        self.assertTrue(numpy.allclose(result['metallic'], BASE_METALLIC))

    def test_fill_layer_covers_every_channel(self):
        result = composite(2, [layer()])
        self.assertTrue(numpy.allclose(result['base_color'], (1, 0, 0)))
        self.assertTrue(numpy.allclose(result['roughness'], .2))
        self.assertTrue(numpy.allclose(result['metallic'], 1))

    def test_coverage_mask_and_opacity_multiply(self):
        coverage = numpy.array([[[1.0], [0.0]], [[0.5], [1.0]]], dtype=numpy.float32)
        mask = numpy.array([[[1.0], [1.0]], [[1.0], [0.5]]], dtype=numpy.float32)
        result = composite(2, [layer(coverage=coverage, mask=mask, opacity=.5, use_color=False, use_metallic=False)])
        expected = BASE_ROUGHNESS + (coverage * mask * .5) * (.2 - BASE_ROUGHNESS)
        self.assertTrue(numpy.allclose(result['roughness'], expected))
        self.assertTrue(numpy.allclose(result['metallic'], BASE_METALLIC))

    def test_disabled_channels_pass_through(self):
        result = composite(1, [layer(use_color=False, use_roughness=False, use_metallic=False)])
        self.assertTrue(numpy.allclose(result['base_color'], BASE_COLOR))
        self.assertTrue(numpy.allclose(result['roughness'], BASE_ROUGHNESS))

    def test_upper_layers_win(self):
        result = composite(1, [layer(color=(1, 0, 0)), layer(color=(0, 0, 1))])
        self.assertTrue(numpy.allclose(result['base_color'], (0, 0, 1)))


if __name__ == '__main__':
    unittest.main()
