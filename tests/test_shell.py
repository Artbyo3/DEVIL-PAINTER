import unittest
from devil_painter.canvas import Rect
from devil_painter.shell import MAX_COLUMN, MAX_PANEL, MIN_COLUMN, MIN_PANEL, fit_heights, reorder, resize_panel, zones


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.top and b.y < a.top


class PanelHeightTests(unittest.TestCase):
    def test_panels_keep_the_height_the_user_set_when_they_fit(self):
        self.assertEqual(fit_heights([100.0, 50.0], 400.0, 48.0), [100.0, 50.0])

    def test_a_short_column_shrinks_panels_toward_their_minimum_without_overflow(self):
        fitted = fit_heights([300.0, 300.0], 400.0, 48.0)
        self.assertAlmostEqual(sum(fitted), 400.0)
        self.assertTrue(all(height >= 48.0 for height in fitted))

    def test_even_minimum_panels_never_overflow_a_tiny_column(self):
        self.assertLessEqual(sum(fit_heights([48.0, 48.0, 48.0], 100.0, 48.0)), 100.0 + 1e-6)

    def test_growing_a_panel_takes_room_from_the_panels_below_only_when_the_column_is_full(self):
        heights = dict(SETS=90.0, LAYERS=200.0, MAPS=100.0)
        keys = ['SETS', 'LAYERS', 'MAPS']
        roomy = resize_panel(keys, heights, 'LAYERS', 260.0, 1000.0)
        self.assertEqual((roomy['LAYERS'], roomy['MAPS']), (260.0, 100.0))
        full = resize_panel(keys, heights, 'LAYERS', 360.0, 500.0)
        self.assertEqual(full['LAYERS'], 360.0)
        self.assertEqual(full['MAPS'], 50.0)
        self.assertLessEqual(sum(full.values()), 500.0)

    def test_panel_heights_stay_within_safe_limits(self):
        keys = ['SETS', 'LAYERS']
        heights = dict(SETS=90.0, LAYERS=200.0)
        self.assertEqual(resize_panel(keys, heights, 'LAYERS', -50.0, 1000.0)['LAYERS'], MIN_PANEL)
        self.assertEqual(resize_panel(keys, heights, 'LAYERS', 99999.0, 99999.0)['LAYERS'], MAX_PANEL)

    def test_a_dragged_panel_lands_above_or_below_its_target(self):
        order = ['SETS', 'LAYERS', 'PROPERTIES', 'MAPS']
        self.assertEqual(reorder(order, 'MAPS', 'SETS', False), ['MAPS', 'SETS', 'LAYERS', 'PROPERTIES'])
        self.assertEqual(reorder(order, 'SETS', 'PROPERTIES', True), ['LAYERS', 'PROPERTIES', 'SETS', 'MAPS'])


class ZoneTests(unittest.TestCase):
    def test_zones_never_overlap_at_common_viewport_sizes(self):
        for width, height in ((800, 600), (1280, 720), (1920, 1080), (3840, 2160)):
            for scale, shelf_open in ((1.0, True), (2.0, True), (1.0, False)):
                area = zones(Rect(0, 0, width, height), scale, 330, shelf_open)
                parts = (area.bar, area.strip, area.dock, area.stage, area.shelf, area.column)
                for index, first in enumerate(parts):
                    for second in parts[index + 1:]:
                        self.assertFalse(overlaps(first, second), (width, height, scale, first, second))

    def test_column_width_is_clamped(self):
        bounds = Rect(0, 0, 3000, 1000)
        self.assertEqual(zones(bounds, 1.0, 10).column.w, MIN_COLUMN)
        self.assertEqual(zones(bounds, 1.0, 9000).column.w, MAX_COLUMN)

    def test_shelf_sits_under_the_stage_and_collapses_to_its_header(self):
        open_zones = zones(Rect(0, 0, 1600, 900), 1.0, 330, True)
        closed_zones = zones(Rect(0, 0, 1600, 900), 1.0, 330, False)
        self.assertLess(open_zones.shelf.top, open_zones.stage.y)
        self.assertEqual(open_zones.shelf.x, open_zones.stage.x)
        self.assertGreater(closed_zones.stage.h, open_zones.stage.h)

    def test_column_never_takes_more_than_half_the_viewport(self):
        self.assertLessEqual(zones(Rect(0, 0, 500, 600), 1.0, 480).column.w, 250)


if __name__ == '__main__':
    unittest.main()
