import tempfile
import unittest
from pathlib import Path
from tools.check_dead_code import find_draw_integrity_violations, find_missing_imports


class DeadCodeTests(unittest.TestCase):
    def test_invalid_draw_attribute_and_key_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / 'devil_painter'
            pkg.mkdir()
            (pkg / 'canvas.py').write_text('class Rect:\n    x: float\n\n    @property\n    def top(self):\n        return self.x\n', encoding='utf-8')
            (pkg / 'draw.py').write_text(
                'h_edge = ed.design_hit_edge()\nx = h_edge.edge\npair = pair_for(doc, \"id\")\ny = pair[\"a\"]\n'
                'box = Rect(1)\nz = box.top + box.right\n',
                encoding='utf-8'
            )
            violations = find_draw_integrity_violations(Path(tmp))
            self.assertEqual(violations, [
                "draw.py:2: invalid attribute 'edge' on EdgeRef",
                "draw.py:4: invalid key 'a' on linked_pair",
                "draw.py:6: invalid attribute 'right' on Rect",
            ])

    def test_missing_import_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / 'devil_painter'
            pkg.mkdir()
            (pkg / 'ui_system.py').write_text('BG_BASE = (0, 0, 0, 1)\n', encoding='utf-8')
            (pkg / 'draw.py').write_text('from .ui_system import BG_BASE, RADIUS_WINDOW\nX = (BG_BASE, RADIUS_WINDOW)\n', encoding='utf-8')
            violations = find_missing_imports(Path(tmp))
            self.assertEqual(violations, ['draw.py:1: missing import RADIUS_WINDOW from ui_system'])
