import unittest
from devil_painter.canvas import Rect
from devil_painter.shell import (HEADER, HEIGHTS, MAX_SIZE, MIN_PANEL, PANELS, SECTIONS, WIDTHS, arrange, clamp_strip, default_strips, fit_heights, place,
                                 resize_run)

BOUNDS = Rect(0, 0, 1600, 900)


def overlaps(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.top and b.y < a.top


def layout(strips, bounds=BOUNDS, collapsed=(), shelf_open=True):
    return arrange(bounds, 1.0, strips, dict(HEIGHTS), dict(WIDTHS), set(SECTIONS), set(collapsed), shelf_open)


def clean(found, bounds=BOUNDS):
    parts = list(found.rects.values()) + [found.stage]
    for index, first in enumerate(parts):
        if first.x < bounds.x - .5 or first.y < bounds.y - .5 or first.x + first.w > bounds.x + bounds.w + .5 or first.top > bounds.top + .5:
            return False
        if any(overlaps(first, second) for second in parts[index + 1:]):
            return False
    return True


class FitTests(unittest.TestCase):
    def test_sections_keep_the_size_the_user_set_when_they_fit(self):
        self.assertEqual(fit_heights([100.0, 50.0], 400.0, 48.0), [100.0, 50.0])

    def test_a_short_column_shrinks_sections_toward_their_minimum_without_overflow(self):
        fitted = fit_heights([300.0, 300.0], 400.0, 48.0)
        self.assertAlmostEqual(sum(fitted), 400.0)
        self.assertTrue(all(height >= 48.0 for height in fitted))

    def test_growing_a_section_takes_room_only_from_the_sections_after_it(self):
        lengths = dict(SETS=90.0, LAYERS=200.0, MAPS=100.0)
        grown = resize_run(['SETS', 'LAYERS', 'MAPS'], lengths, 'LAYERS', 360.0, 500.0)
        self.assertEqual((grown['SETS'], grown['LAYERS'], grown['MAPS']), (90.0, 360.0, 50.0))
        self.assertEqual(resize_run(['SETS', 'LAYERS'], lengths, 'LAYERS', -50.0, 1000.0)['LAYERS'], MIN_PANEL)
        self.assertEqual(resize_run(['SETS', 'LAYERS'], lengths, 'LAYERS', 99999.0, 99999.0)['LAYERS'], MAX_SIZE)


class ArrangementTests(unittest.TestCase):
    def test_the_default_layout_matches_the_workspace(self):
        found = layout(default_strips())
        self.assertTrue(clean(found))
        self.assertEqual(found.places['BAR'][0], 'TOP')
        self.assertEqual(found.places['DOCK'][0], 'LEFT')
        self.assertEqual(found.places['SHELF'][0], 'BOTTOM')
        self.assertTrue(all(found.places[key][0] == 'RIGHT' for key in PANELS))
        self.assertGreater(found.stage.w, 600)

    def test_every_section_fits_without_overlap_at_common_sizes(self):
        for width, height in ((800, 600), (1280, 720), (1920, 1080), (3840, 2160)):
            bounds = Rect(0, 0, width, height)
            self.assertTrue(clean(layout(default_strips(), bounds), bounds), (width, height))

    def test_a_panel_dropped_near_the_viewport_edge_starts_a_new_column(self):
        found = layout(default_strips())
        stage = found.stage
        strips = place(default_strips(), 'LAYERS', stage.x + 10, stage.y + stage.h / 2, found)
        self.assertEqual(strips['LEFT'][-1]['items'], ['LAYERS'])
        self.assertNotIn('LAYERS', strips['RIGHT'][0]['items'])
        self.assertTrue(clean(layout(strips)))

    def test_dropping_on_a_column_edge_splits_and_its_middle_joins(self):
        found = layout(default_strips())
        column = found.rects['LAYERS']
        split = place(default_strips(), 'MAPS', column.x + column.w - 5, column.y + column.h / 2, found)
        self.assertEqual(len(split['RIGHT']), 2)
        self.assertTrue(clean(layout(split)))
        joined = place(default_strips(), 'MAPS', column.x + column.w / 2, column.top - 5, found)
        self.assertEqual(len(joined['RIGHT']), 1)
        self.assertLess(joined['RIGHT'][0]['items'].index('MAPS'), joined['RIGHT'][0]['items'].index('PROPERTIES'))

    def test_toolbars_only_dock_in_rows_and_everything_else_can_leave_the_middle_empty(self):
        found = layout(default_strips())
        stage = found.stage
        bar = place(default_strips(), 'BAR', stage.x + 5, stage.y + 5, found)
        self.assertTrue(any('BAR' in strip['items'] for strip in bar['BOTTOM']))
        shelf = place(default_strips(), 'SHELF', stage.x + 10, stage.y + stage.h / 2, found)
        self.assertTrue(any('SHELF' in strip['items'] for strip in shelf['LEFT']))
        self.assertTrue(clean(layout(shelf)))

    def test_the_last_section_fills_its_column_and_collapsed_panels_keep_their_header(self):
        found = layout(default_strips(), collapsed={'PROPERTIES'})
        self.assertAlmostEqual(found.rects['PROPERTIES'].h, HEADER)
        self.assertAlmostEqual(found.rects['MAPS'].y, BOUNDS.y + 8, delta=1)

    def test_column_and_row_sizes_stay_within_safe_limits(self):
        self.assertEqual(clamp_strip('LEFT', 1, ['DOCK']), 40)
        self.assertEqual(clamp_strip('LEFT', 1, ['LAYERS']), 200)
        self.assertEqual(clamp_strip('RIGHT', 99999, ['LAYERS']), MAX_SIZE)
        self.assertEqual(clamp_strip('TOP', 500, ['BAR']), 96)


if __name__ == '__main__':
    unittest.main()
