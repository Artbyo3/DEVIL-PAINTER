import unittest
from devil_painter.state import format_number, parse_number


class NumericFieldHelperTests(unittest.TestCase):
    def test_format_number_strips_trailing_zeros_and_negative_zero(self):
        self.assertEqual(format_number(0.5), '0.5')
        self.assertEqual(format_number(1.0), '1')
        self.assertEqual(format_number(-0.0), '0')
        self.assertEqual(format_number(0.125), '0.125')
        self.assertEqual(format_number(50.0, decimals=2), '50')
        self.assertEqual(format_number(12.5, decimals=2), '12.5')
        self.assertEqual(format_number(16.4, integer=True), '16')

    def test_parse_number_supports_blender_decimal_and_sign_forms(self):
        self.assertAlmostEqual(parse_number('.5', 0.0, 1.0), 0.5)
        self.assertAlmostEqual(parse_number('-.5', -5.0, 5.0), -0.5)
        self.assertAlmostEqual(parse_number('+1.25', -5.0, 5.0), 1.25)
        self.assertAlmostEqual(parse_number('1.', 0.0, 2.0), 1.0)
        self.assertAlmostEqual(parse_number('0.375', 0.0, 1.0), 0.375)

    def test_parse_number_scales_percentages_and_strips_units(self):
        self.assertAlmostEqual(parse_number('75', 0.0, 1.0, scale=100.0, units=('%',)), 0.75)
        self.assertAlmostEqual(parse_number('75%', 0.0, 1.0, scale=100.0, units=('%',)), 0.75)
        self.assertAlmostEqual(parse_number('0.5', 0.0, 1.0, scale=100.0, units=('%',)), 0.005)
        self.assertAlmostEqual(parse_number('45°', 0.0, 360.0, units=('°', 'deg')), 45.0)
        self.assertAlmostEqual(parse_number('90 deg', 0.0, 360.0, units=('°', 'deg')), 90.0)
        self.assertEqual(parse_number('128 px', 1, 500, integer=True, units=('px',)), 128)
        self.assertAlmostEqual(parse_number('2.5x', 0.125, 32.0, units=('x',)), 2.5)
        self.assertAlmostEqual(parse_number('0.25 m', 0.0, 0.5, units=('m',)), 0.25)
        self.assertAlmostEqual(parse_number('35 mm', 10.0, 150.0, units=('mm',)), 35.0)
        self.assertEqual(parse_number('10 min', 1, 30, integer=True, units=('min',)), 10)

    def test_parse_number_clamps_to_slider_bounds_and_rounds_integers(self):
        self.assertEqual(parse_number('999', 1, 500, integer=True), 500)
        self.assertEqual(parse_number('-5', 1, 500, integer=True), 1)
        self.assertEqual(parse_number('12.6', 1, 128, integer=True), 13)
        self.assertAlmostEqual(parse_number('150', 0.0, 1.0, scale=100.0, units=('%',)), 1.0)
        self.assertAlmostEqual(parse_number('-20', 0.0, 1.0, scale=100.0, units=('%',)), 0.0)
        self.assertAlmostEqual(parse_number('2.0', 0.0, 0.98), 0.98)

    def test_parse_number_rejects_empty_invalid_and_non_finite_text(self):
        for bad in ('', '   ', '%', 'abc', 'nan', 'inf', '-inf'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_number(bad, 0.0, 1.0, units=('%',))


if __name__ == '__main__':
    unittest.main()
