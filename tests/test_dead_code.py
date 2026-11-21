import tempfile
import unittest
from pathlib import Path
from tools.check_dead_code import DRAW_FILES, find_dead_code, find_draw_integrity_violations, find_missing_imports

RECT = 'from dataclasses import dataclass\n\n\n@dataclass(frozen=True)\nclass Rect:\n    x: float\n    w: float\n\n    @property\n    def top(self):\n        return self.x\n'


def fixture(folder, files):
    root = Path(folder)
    for directory in ('devil_painter', 'tools', 'tests'):
        (root / directory).mkdir()
    for name in DRAW_FILES:
        (root / name).write_text('', encoding='utf-8')
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    return root


class DrawIntegrityTests(unittest.TestCase):
    def test_invalid_attributes_on_painter_types_are_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = fixture(folder, {
                'devil_painter/canvas.py': RECT,
                'devil_painter/minimal.py': 'from .canvas import Rect\n\n\nclass Flow:\n    def line(self):\n        return Rect(0, 1)\n\n    def size(self):\n        return self.width\n',
                'devil_painter/draw.py': 'from .canvas import Rect\nfrom .minimal import Flow\n\n\ndef paint(flow: Flow):\n    box = Rect(0, 1)\n    line = flow.line()\n    pick = box if flow else Rect(1, 0)\n    return box.top + box.right + line.w + line.bottom + pick.depth\n',
            })
            self.assertEqual(find_draw_integrity_violations(root), [
                "devil_painter/draw.py:9: invalid attribute 'bottom' on Rect",
                "devil_painter/draw.py:9: invalid attribute 'depth' on Rect",
                "devil_painter/draw.py:9: invalid attribute 'right' on Rect",
                "devil_painter/minimal.py:9: invalid attribute 'width' on Flow",
            ])

    def test_rebound_and_open_types_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = fixture(folder, {
                'devil_painter/canvas.py': RECT + '\n\nclass Panel(dict):\n    pass\n',
                'devil_painter/draw.py': 'from .canvas import Panel, Rect\n\n\ndef paint(other):\n    box = Rect(0, 1)\n    box = other\n    return box.right + Panel().anything\n',
            })
            self.assertEqual(find_draw_integrity_violations(root), [])

    def test_a_missing_draw_file_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = fixture(folder, {})
            (root / 'devil_painter' / 'shell.py').unlink()
            with self.assertRaises(FileNotFoundError) as raised:
                find_draw_integrity_violations(root)
            self.assertIn('devil_painter/shell.py', str(raised.exception))


class DeadCodeTests(unittest.TestCase):
    def test_definitions_need_a_resolved_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = fixture(folder, {
                'devil_painter/a.py': 'SCRIPT = "a.serve(1)"\n\n\ndef allowed():\n    return allowed\n\n\ndef used():\n    return 1\n\n\ndef tested():\n    return 2\n\n\ndef serve(value):\n    return value\n\n\nprint(SCRIPT)\n',
                'devil_painter/b.py': 'from .a import used\n\n\ndef caller():\n    allowed = used()\n    return allowed\n\n\nVALUE = caller()\n',
                'devil_painter/nested/deep.py': 'def hidden():\n    return 3\n',
                'tools/helper.py': 'import json\nfrom devil_painter import b\n\nprint(b.VALUE)\n',
                'tests/test_a.py': 'from devil_painter.a import tested\n\nprint(tested())\n',
            })
            self.assertEqual(find_dead_code(root), [
                'tools/helper.py:1: unused import json',
                'devil_painter/a.py:4: unused function allowed',
                'devil_painter/nested/deep.py:1: unused function hidden',
            ])

    def test_missing_import_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = fixture(folder, {
                'devil_painter/ui_system.py': 'ACCENT = (0, 0, 0, 1)\n',
                'devil_painter/draw.py': 'from .ui_system import ACCENT, RADIUS_WINDOW\nX = (ACCENT, RADIUS_WINDOW)\n',
                'tools/runner.py': 'from tools import gone\nfrom devil_painter import ui_system\nprint(gone, ui_system.MISSING)\n',
            })
            self.assertEqual(find_missing_imports(root), [
                'devil_painter/draw.py:1: missing import RADIUS_WINDOW from devil_painter.ui_system',
                'tools/runner.py:1: missing import gone from tools',
                'tools/runner.py:3: missing attribute MISSING on module devil_painter.ui_system',
            ])

    def test_a_missing_scanned_folder_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = fixture(folder, {})
            for name in DRAW_FILES:
                (root / name).unlink()
            (root / 'tools').rmdir()
            with self.assertRaises(FileNotFoundError) as raised:
                find_dead_code(root)
            self.assertIn('tools/', str(raised.exception))
