import tempfile
import unittest
from pathlib import Path
from tools import check_comments, workspace
from tools.check_comments import check_source


class NoCommentsTests(unittest.TestCase):
    def test_comments_are_rejected(self):
        for source in ('# note\n', 'value = 1 # note\n'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_source(source)

    def test_docstrings_and_standalone_strings_are_rejected(self):
        for source in (
            '\"\"\"module note\"\"\"\n',
            "'''module note'''\n",
            'class Example:\n    "class note"\n    pass\n',
            'def example():\n    "function note"\n    return 1\n',
            'value = 1\n"standalone note"\n',
            'f"standalone {1}"\n',
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_source(source)

    def test_functional_strings_are_preserved(self):
        check_source('label = "# visible label"\nscript = """print(1)"""\ndef label_text():\n    return "label"\nprint(label)\n')

    def test_invalid_source_is_rejected(self):
        with self.assertRaises(SyntaxError):
            check_source('def broken(:\n')

    def test_comment_check_reports_every_bad_file(self):
        with tempfile.TemporaryDirectory(dir=workspace.prepare_scratch()) as folder:
            root = Path(folder)
            for directory in ('devil_painter', 'tests', 'tools'):
                (root / directory).mkdir()
            (root / 'devil_painter' / 'a.py').write_text('x = 1  # note\n', encoding='utf-8')
            (root / 'tools' / 'b.py').write_text('"doc"\n', encoding='utf-8')
            (root / 'tests' / 'c.py').write_text('y = 2\n', encoding='utf-8')
            with self.assertRaises(ValueError) as raised:
                check_comments.check_repository(root)
        self.assertIn('a.py:1: code comment', str(raised.exception))
        self.assertIn('b.py:1: docstring or standalone string', str(raised.exception))
