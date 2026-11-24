import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from tools import build, dev, workspace

MANIFEST = '''id = "devil_painter"
version = "0.0.1"

[build]
paths_exclude_pattern = [".*", "__pycache__/", "tests/", "*.blend[1-9]", "*.md", "!README.md", "assets/icons/*.png"]
'''


def git(root, *arguments):
    subprocess.run(['git', *arguments], cwd=root, capture_output=True, check=True)


def write(path, text='x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class BuildTests(unittest.TestCase):
    def build_fixture(self, folder):
        root = Path(folder)
        git(root, 'init', '-q')
        for name in ('README.md', 'LICENSE', 'SPEC.md'):
            write(root / name)
        package = root / 'devil_painter'
        write(package / 'blender_manifest.toml', MANIFEST)
        for name in ('__init__.py', 'assets/icons/README.md', 'assets/icons/brush.png', 'assets/icons/set/brush.png', 'notes.md', 'scene.blend1', '.hidden', 'tests/case.py'):
            write(package / name)
        git(root, 'add', '-f', '.')
        for name in ('untracked.py', 'desktop.ini', 'assets/icons/set/untracked.png'):
            write(package / name)
        archive = root / 'dist' / 'devil_painter-0.0.1.zip'
        with patch.object(build, 'root', root), patch.object(build, 'extension_archive', return_value=archive), patch('builtins.print'):
            build.build_extension(scanned=True)
        with ZipFile(archive) as packaged:
            return sorted(packaged.namelist())

    def test_only_tracked_files_minus_manifest_excludes_are_packaged(self):
        with tempfile.TemporaryDirectory(dir=workspace.prepare_scratch()) as folder:
            names = self.build_fixture(folder)
        self.assertEqual(names, ['LICENSE', 'README.md', 'SPEC.md', '__init__.py', 'assets/icons/README.md', 'assets/icons/set/brush.png', 'blender_manifest.toml'])

    def test_standalone_build_runs_the_source_scans(self):
        with patch.object(build, 'check_source_rules', side_effect=ValueError('comment')), self.assertRaises(ValueError):
            build.build_extension(scanned=False)

    def test_text_files_normalize_crlf_to_lf_while_binary_files_stay_verbatim(self):
        with tempfile.TemporaryDirectory(dir=workspace.prepare_scratch()) as folder:
            root = Path(folder)
            git(root, 'init', '-q')
            for name in ('README.md', 'LICENSE', 'SPEC.md'):
                (root / name).write_bytes(b'line1\r\nline2\r\n')
            package = root / 'devil_painter'
            (package / 'assets' / 'icons' / 'set').mkdir(parents=True, exist_ok=True)
            (package / 'blender_manifest.toml').write_bytes(MANIFEST.replace('\n', '\r\n').encode('utf-8'))
            (package / '__init__.py').write_bytes(b'x = 1\r\ny = 2\r\n')
            png_bytes = b'\x89PNG\r\n\x1a\nfake\r\ndata'
            (package / 'assets' / 'icons' / 'set' / 'brush.png').write_bytes(png_bytes)
            git(root, 'add', '-f', '.')
            archive = root / 'dist' / 'devil_painter-0.0.1.zip'
            with patch.object(build, 'root', root), patch.object(build, 'extension_archive', return_value=archive), patch('builtins.print'):
                build.build_extension(scanned=True)
            with ZipFile(archive) as packaged:
                for name in ('__init__.py', 'blender_manifest.toml', 'README.md', 'LICENSE', 'SPEC.md'):
                    self.assertNotIn(b'\r\n', packaged.read(name), name)
                self.assertEqual(packaged.read('assets/icons/set/brush.png'), png_bytes)


class InstallTests(unittest.TestCase):
    def test_install_replaces_the_old_copy_with_exactly_the_zip(self):
        with tempfile.TemporaryDirectory(dir=workspace.prepare_scratch()) as folder:
            root = Path(folder)
            archive = root / 'package.zip'
            with ZipFile(archive, 'w') as packaged:
                packaged.writestr('__init__.py', 'new')
                packaged.writestr('assets/icon.png', 'png')
            target = root / 'extensions' / 'user_default' / 'devil_painter'
            write(target / '__init__.py', 'old')
            write(target / 'removed_module.py')
            write(target / 'desktop.ini')
            write(target / '__pycache__' / 'stale.pyc')
            self.assertEqual(dev.install_package(archive, target), [])
            present = sorted(path.relative_to(target).as_posix() for path in target.rglob('*') if path.is_file())
            self.assertEqual(present, ['__init__.py', 'assets/icon.png'])
            self.assertEqual((target / '__init__.py').read_text(encoding='utf-8'), 'new')
            self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ['devil_painter'])


class PackageOnceTests(unittest.TestCase):
    def test_gate_packages_without_rescanning_and_smoke_needs_the_validated_zip(self):
        run = dev.Run('test', workspace.prepare_scratch(workspace.scratch_root() / 'run-build-test'))
        commands = []

        def record(run, name, *arguments, **options):
            commands.append(arguments)
            return run.record(name, True)

        try:
            with patch('builtins.print'):
                dev.do_smoke(run)
                self.assertEqual([outcome.detail for outcome in run.failures()], ['no zip from this run passed validation'])
                run.record(dev.SCAN_STEP, True)
                with patch.object(dev, 'python_step', side_effect=record), patch.object(dev, 'step', side_effect=record), \
                        patch.object(dev, 'blender', return_value='blender'), patch.object(dev.gate_state, 'sha256', return_value='a' * 64):
                    self.assertTrue(dev.do_package(run))
                    dev.do_smoke(run)
        finally:
            workspace.clean_scratch(run.folder)
        self.assertEqual(commands[0], ('tools/build.py', '--scanned'))
        self.assertEqual(commands[-1][0][-3:], ['--', str(dev.extension_archive()), 'a' * 64])
