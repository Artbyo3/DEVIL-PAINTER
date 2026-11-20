import unittest
import numpy
from devil_painter.blending import CHANNEL, CHANNELS, linear_to_srgb, srgb_to_linear
from devil_painter.procedural import PATTERN, PATTERNS


class ColorTests(unittest.TestCase):
    def test_srgb_round_trip(self):
        values = numpy.linspace(0, 1, 11)
        self.assertTrue(numpy.allclose(linear_to_srgb(srgb_to_linear(values)), values, atol=1e-6))


class ChannelTests(unittest.TestCase):
    def test_registry_covers_the_standard_pbr_channels(self):
        self.assertEqual([channel.key for channel in CHANNELS],
                         ['base_color', 'roughness', 'metallic', 'normal', 'height', 'emission', 'opacity', 'ambient_occlusion',
                          'flow', 'user1', 'user2', 'user3', 'user4', 'user5', 'user6', 'user7', 'user8'])

    def test_flow_and_user_channels_are_export_only(self):
        self.assertEqual({channel.key for channel in CHANNELS if not channel.in_shader}, {'flow', 'user1', 'user2', 'user3', 'user4', 'user5', 'user6', 'user7', 'user8'})

    def test_color_channels_are_three_wide_and_values_one_wide(self):
        self.assertEqual({channel.key for channel in CHANNELS if channel.width == 3}, {'base_color', 'normal', 'emission', 'flow'})

    def test_only_color_and_emission_are_srgb(self):
        self.assertEqual({channel.key for channel in CHANNELS if channel.srgb}, {'base_color', 'emission'})

    def test_flat_normal_is_the_default(self):
        self.assertEqual(CHANNEL['normal'].default, (0.5, 0.5, 1.0))


class PatternTests(unittest.TestCase):
    def test_pattern_keys_are_unique_and_indexed(self):
        self.assertEqual(len(PATTERN), len(PATTERNS))

    def test_every_pattern_names_a_blender_texture_node(self):
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern.key):
                self.assertTrue(pattern.node.startswith('ShaderNodeTex'))
                self.assertTrue(pattern.output)


if __name__ == '__main__':
    unittest.main()
