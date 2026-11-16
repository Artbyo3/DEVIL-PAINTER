import unittest
from devil_painter.canvas import Rect
from devil_painter.shell import MAX_COLUMN, MIN_COLUMN, distribute, zones


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.top and b.y < a.top


class DistributeTests(unittest.TestCase):
    def test_panels_that_fit_get_their_full_height(self):
        self.assertEqual(distribute([100.0, 50.0], 400.0, (.5, .5)), [100.0, 50.0])

    def test_space_a_small_panel_does_not_need_goes_to_the_other(self):
        self.assertEqual(distribute([500.0, 50.0], 400.0, (.5, .5)), [350.0, 50.0])

    def test_overflowing_panels_share_by_the_divider(self):
        self.assertEqual(distribute([500.0, 500.0], 400.0, (.75, .25)), [300.0, 100.0])

    def test_collapsed_panels_give_all_room_away(self):
        self.assertEqual(distribute([0.0, 900.0], 400.0, (.5, .5)), [0.0, 400.0])


class ZoneTests(unittest.TestCase):
    def test_zones_never_overlap_at_common_viewport_sizes(self):
        for width, height in ((800, 600), (1280, 720), (1920, 1080), (3840, 2160)):
            for scale in (1.0, 2.0):
                area = zones(Rect(0, 0, width, height), scale, 330)
                parts = (area.bar, area.strip, area.dock, area.stage, area.column)
                for index, first in enumerate(parts):
                    for second in parts[index + 1:]:
                        self.assertFalse(overlaps(first, second), (width, height, scale, first, second))

    def test_column_width_is_clamped(self):
        bounds = Rect(0, 0, 3000, 1000)
        self.assertEqual(zones(bounds, 1.0, 10).column.w, MIN_COLUMN)
        self.assertEqual(zones(bounds, 1.0, 9000).column.w, MAX_COLUMN)

    def test_column_never_takes_more_than_half_the_viewport(self):
        self.assertLessEqual(zones(Rect(0, 0, 500, 600), 1.0, 480).column.w, 250)


if __name__ == '__main__':
    unittest.main()
