import json
import os
import sys
from pathlib import Path
from contextlib import nullcontext
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import dev, workspace


class ScratchWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=workspace.prepare_scratch())
        self.root = Path(self.temporary.name).resolve()
        self.scratch = self.root / 'scratch'
        self.settings = patch.multiple(workspace, ROOT=self.root, SCRATCH=self.scratch, DIST=self.root / 'dist')
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temporary.cleanup()

    def linked_directory(self, path, target):
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError:
            path.mkdir()
            original = workspace.is_link
            return patch.object(workspace, 'is_link', side_effect=lambda candidate: candidate == path or original(candidate))
        return nullcontext()

    def test_clean_is_idempotent_when_missing(self):
        self.assertEqual(workspace.clean_scratch(), 0)
        self.assertFalse(self.scratch.exists())

    def test_cleanup_removes_nested_artifacts_but_preserves_deliverables_and_source(self):
        workspace.prepare_scratch()
        nested = self.scratch / 'reports'
        nested.mkdir()
        (nested / 'test.blend').write_bytes(b'demo')
        (self.scratch / 'screenshot.png').write_bytes(b'image')
        source = self.root / 'source.py'
        source.write_text('important = True', encoding='utf-8')
        archive = self.root / 'dist' / 'extension.zip'
        archive.parent.mkdir()
        archive.write_bytes(b'installable')
        self.assertEqual(workspace.clean_scratch(), 2)
        self.assertFalse(self.scratch.exists())
        self.assertTrue(source.exists())
        self.assertEqual(archive.read_bytes(), b'installable')

    def test_cleanup_refuses_a_different_target(self):
        source = self.root / 'source'
        source.mkdir()
        with patch.object(workspace, 'SCRATCH', source):
            with self.assertRaises(ValueError):
                workspace.clean_scratch()
        self.assertTrue(source.is_dir())

    def test_cleanup_refuses_a_file_as_scratch(self):
        self.scratch.write_text('not disposable', encoding='utf-8')
        with self.assertRaises(ValueError):
            workspace.clean_scratch()
        self.assertEqual(self.scratch.read_text(encoding='utf-8'), 'not disposable')

    def test_cleanup_refuses_nested_links_before_deleting_anything(self):
        workspace.prepare_scratch()
        artifact = self.scratch / 'report.json'
        artifact.write_text('{}', encoding='utf-8')
        outside = self.root / 'source'
        outside.mkdir()
        protected = outside / 'important.py'
        protected.write_text('important = True', encoding='utf-8')
        with self.linked_directory(self.scratch / 'linked', outside):
            with self.assertRaises(ValueError):
                workspace.clean_scratch()
        self.assertTrue(protected.exists())
        self.assertTrue(artifact.exists())

    def test_cleanup_refuses_linked_scratch_root(self):
        outside = self.root / 'source'
        outside.mkdir()
        protected = outside / 'important.py'
        protected.write_text('important = True', encoding='utf-8')
        with self.linked_directory(self.scratch, outside):
            with self.assertRaises(ValueError):
                workspace.clean_scratch()
        self.assertTrue(protected.exists())

    def test_run_scratch_is_a_folder_inside_scratch_run(self):
        journey = self.scratch / 'run-1' / 'j' / '01'
        journey.mkdir(parents=True)
        with patch.object(workspace, 'SCRATCH', journey):
            self.assertEqual(workspace.prepare_scratch(), journey)
        environment = workspace.child_environment(journey)
        self.assertEqual(Path(environment[workspace.SCRATCH_VARIABLE]), journey)
        self.assertEqual(Path(environment['BLENDER_USER_CONFIG']), journey / 'blender-config')
        self.assertEqual(Path(environment['TEMP']), journey / 'blender-temp')
        self.assertEqual(environment['PYTHONUNBUFFERED'], '1')

    def test_run_scratch_refuses_escapes_and_links(self):
        (self.scratch / 'run-1').mkdir(parents=True)
        outside = self.root / 'source'
        outside.mkdir()
        for escape in (self.scratch / 'j', self.scratch / 'run-1' / '..' / '..' / 'source', outside / 'run-1'):
            with patch.object(workspace, 'SCRATCH', escape):
                with self.assertRaises(ValueError):
                    workspace.prepare_scratch()
        with self.linked_directory(self.scratch / 'run-1' / 'linked', outside):
            with patch.object(workspace, 'SCRATCH', self.scratch / 'run-1' / 'linked' / '01'):
                with self.assertRaises(ValueError):
                    workspace.prepare_scratch()
        self.assertEqual(list(outside.iterdir()), [])

    def test_windows_reparse_attribute_is_detected_without_symlink_privileges(self):
        with patch.object(Path, 'is_symlink', return_value=False), patch.object(Path, 'lstat', return_value=SimpleNamespace(st_file_attributes=0x400)):
            self.assertTrue(workspace.is_link(self.root / 'junction'))

    def test_archive_location_uses_manifest_version_and_is_not_scratch(self):
        source = self.root / 'devil_painter'
        source.mkdir()
        (source / 'blender_manifest.toml').write_text('id = "extension"\nversion = "1.2.3"\n', encoding='utf-8')
        self.assertEqual(workspace.extension_archive(), self.root / 'dist' / 'extension-1.2.3.zip')

    def test_developer_scripts_do_not_write_to_legacy_build_directory(self):
        project_root = Path(__file__).resolve().parents[1]
        for directory in ('tests', 'tools'):
            for source in (project_root / directory).glob('*.py'):
                text = source.read_text(encoding='utf-8')
                self.assertNotRegex(text, r"ROOT\s*/\s*['\"]build['\"]", str(source.relative_to(project_root)))

    def test_cleanup_reports_locked_files_without_removing_the_directory(self):
        workspace.prepare_scratch()
        artifact = self.scratch / 'preview.log'
        artifact.write_text('preview', encoding='utf-8')
        with patch.object(Path, 'unlink', side_effect=PermissionError('locked')):
            with self.assertRaisesRegex(OSError, 'close its owner'):
                workspace.clean_scratch()
        self.assertTrue(artifact.exists())

    def run_folders(self):
        return sorted(path.name for path in self.scratch.glob('run-*'))

    def passing(self, name='step'):
        return lambda run: run.record(name, True)

    def test_successful_runner_removes_only_its_own_run_folder(self):
        workspace.prepare_scratch()
        other = self.scratch / 'report.json'
        other.write_text('{}', encoding='utf-8')
        with patch.object(dev, 'do_quick_tests', side_effect=self.passing()), patch('builtins.print'):
            self.assertEqual(dev.main(['--quick']), 0)
        self.assertEqual(self.run_folders(), [])
        self.assertTrue(other.exists())
        self.assertFalse((self.scratch / 'gate.lock').exists())
        self.assertEqual(json.loads((self.scratch / 'gate-status.json').read_text(encoding='utf-8'))['state'], 'passed')

    def test_failed_runner_preserves_diagnostics_and_runs_every_group(self):
        ran = []

        def failing(run):
            ran.append('first')
            run.record('first', False, detail='exit code 1')

        def later(run):
            ran.append('later')
            run.record('later', True)

        later_groups = [patch.object(dev, name, side_effect=later) for name in ('do_package', 'do_smoke', 'do_install', 'do_archive_public')]
        for active in later_groups:
            active.start()
        try:
            with patch.object(dev, 'do_quick_tests', side_effect=failing), patch.object(dev, 'blender', return_value='blender'), patch('builtins.print'):
                self.assertEqual(dev.main(['--quick', '--build']), 1)
        finally:
            for active in later_groups:
                active.stop()
        self.assertEqual(ran, ['first', 'later', 'later', 'later', 'later'])
        self.assertEqual(len(self.run_folders()), 1)
        status = json.loads((self.scratch / 'gate-status.json').read_text(encoding='utf-8'))
        self.assertEqual((status['state'], [failure['name'] for failure in status['failures']]), ('failed', ['first']))

    def test_keep_scratch_retains_successful_run_artifacts(self):
        with patch.object(dev, 'do_quick_tests', side_effect=self.passing()), patch('builtins.print'):
            self.assertEqual(dev.main(['--quick', '--keep-scratch']), 0)
        self.assertEqual(len(self.run_folders()), 1)

    def test_explicit_clean_does_not_run_tests_or_build(self):
        workspace.prepare_scratch()
        with patch.object(dev, 'do_quick_tests') as tests, patch.object(dev, 'do_package') as build, patch('builtins.print'):
            self.assertEqual(dev.main(['--clean']), 0)
        tests.assert_not_called()
        build.assert_not_called()
        self.assertFalse(self.scratch.exists())

    def test_clean_refuses_while_a_gate_holds_the_lock(self):
        workspace.prepare_scratch()
        (self.scratch / 'gate.lock').write_text(json.dumps(dict(pid=os.getpid(), run='live')), encoding='utf-8')
        with patch('builtins.print'):
            self.assertEqual(dev.main(['--clean']), 1)
        self.assertTrue((self.scratch / 'gate.lock').exists())

    def test_runner_reports_cleanup_failure_and_retains_diagnostics(self):
        with patch.object(dev, 'do_quick_tests', side_effect=self.passing()), patch.object(dev, 'clean_scratch', side_effect=PermissionError('locked')), patch('builtins.print'):
            self.assertEqual(dev.main(['--quick']), 1)
        self.assertEqual(len(self.run_folders()), 1)

    def test_every_journey_runs_after_a_failure(self):
        started = []

        def journey(name, run):
            started.append(name)
            return [], name != 'gui_project.py'

        run = dev.Run('test', workspace.prepare_scratch(self.scratch / 'run-test'))
        with patch.object(dev, 'run_journey', side_effect=journey), patch.object(dev, 'journey_limits', return_value=dict(journeys=1)), patch('builtins.print'):
            hashes, failed = dev.run_journeys(run)
        self.assertEqual(failed, ['gui_project.py'])
        self.assertEqual(sorted(started), sorted(dev.JOURNEYS))
        self.assertEqual(list(hashes), list(dev.JOURNEYS))
        self.assertEqual((run.journeys, run.journeys_passed), (len(dev.JOURNEYS), len(dev.JOURNEYS) - 1))

    def test_golden_compare_runs_even_when_a_journey_failed(self):
        run = dev.Run('test', workspace.prepare_scratch(self.scratch / 'run-test'))
        exports = {'blender_api.py': [['a.png', '0' * 64]]}
        with patch.object(dev, 'run_journeys', return_value=(exports, ['gui_editor.py'])), \
                patch.object(dev.gate, 'read_golden', return_value=exports), patch('builtins.print'):
            self.assertTrue(dev.do_journeys(run, 'compare'))
        self.assertEqual([outcome.name for outcome in run.outcomes], ['Golden compare'])

    def test_journey_timeout_kills_the_process_and_keeps_the_partial_log(self):
        run = dev.Run('test', workspace.prepare_scratch(self.scratch / 'run-test'))
        run.logs.mkdir()
        command = [sys.executable, '-c', 'import time; print("partial", flush=True); time.sleep(60)']
        with patch('builtins.print'):
            passed = dev.step(run, 'Journey 99 hung.py', command, workspace.child_environment(run.folder), timeout=3, echo=False, failure_record=run.folder / 'hung.failures')
        self.assertFalse(passed)
        self.assertIn('timed out', run.outcomes[0].detail)
        self.assertIn('partial', run.outcomes[0].log.read_text(encoding='utf-8'))

    def test_journey_fails_when_the_editor_recorded_a_failure_despite_exit_zero(self):
        run = dev.Run('test', workspace.prepare_scratch(self.scratch / 'run-test'))
        run.logs.mkdir()
        record = run.folder / 'probe.failures'
        cases = (
            ("open(r'{0}', 'w').write('KeyError: probe\\n')", False, "the editor recorded 1 failure(s), first: KeyError: probe"),
            ("print('no record opened')", False, 'the journey never opened its editor failure record'),
            ("open(r'{0}', 'w').write('')", True, ''),
        )
        for script, expected, detail in cases:
            with self.subTest(script=script):
                record.unlink(missing_ok=True)
                with patch('builtins.print'):
                    passed = dev.step(run, 'Journey 98 probe.py', [sys.executable, '-c', script.format(record)], workspace.child_environment(run.folder),
                                      timeout=30, echo=False, failure_record=record)
                self.assertEqual((passed, run.outcomes[-1].detail), (expected, detail))

    def test_full_gate_saves_its_result_and_skips_an_unchanged_tree(self):
        archive = self.root / 'dist' / 'devil_painter-0.4.0.zip'
        calls = []

        def group(name):
            def record(run, *arguments):
                calls.append(name)
                if name == 'package':
                    archive.parent.mkdir(exist_ok=True)
                    archive.write_bytes(b'installable')
                run.record(name, True)
            return record

        saved = {}
        patches = [patch.object(dev, 'do_' + name, side_effect=group(name)) for name in ('public', 'quick_tests', 'package', 'smoke', 'journeys', 'install', 'archive_public')]
        patches += [patch.object(dev, 'blender', return_value='blender'), patch.object(dev, 'extension_archive', return_value=archive),
                    patch.object(dev.gate_state, 'tree_fingerprint', return_value='f' * 40),
                    patch.object(dev.gate_state, 'save_result', side_effect=saved.update),
                    patch.object(dev.gate_state, 'result_path', return_value=self.root / 'result.json'), patch('builtins.print')]
        for active in patches:
            active.start()
        try:
            self.assertEqual(dev.main(['--test', '--build']), 0)
            self.assertEqual(calls, ['public', 'quick_tests', 'package', 'smoke', 'journeys', 'install', 'archive_public'])
            self.assertEqual((saved['verdict'], saved['tier'], saved['tree']), ('passed', 'full', 'f' * 40))
            (self.root / 'result.json').write_text(json.dumps(saved), encoding='utf-8')
            calls.clear()
            self.assertEqual(dev.main(['--tier', 'standard']), 0)
            self.assertEqual(calls, [])
            status = json.loads((self.scratch / 'gate-status.json').read_text(encoding='utf-8'))
            self.assertTrue(status['saved'])
            self.assertIn('GATE RESULT: PASSED | tier FULL', status['summary'])
            self.assertEqual(dev.main(['--tier', 'full', '--rerun']), 0)
            self.assertEqual(len(calls), 7)
        finally:
            for active in patches:
                active.stop()
