import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import commit_msg, dev, gate, gate_state, workspace

DEAD_PID = 2 ** 22 + 1


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=workspace.prepare_scratch())
        self.root = Path(self.temporary.name).resolve()
        self.scratch = self.root / 'scratch'
        self.settings = patch.multiple(workspace, ROOT=self.root, SCRATCH=self.scratch, DIST=self.root / 'dist')
        self.settings.start()
        self.printed = []
        self.silenced = patch('builtins.print', side_effect=lambda *values, **options: self.printed.append(' '.join(map(str, values))))
        self.silenced.start()

    def tearDown(self):
        self.silenced.stop()
        self.settings.stop()
        self.temporary.cleanup()

    def status(self, **fields):
        workspace.prepare_scratch()
        gate_state.write_status(**dict(dict(run='r1', command='--tier auto', started_at=0, console=None), **fields))


class TierTests(unittest.TestCase):
    def test_untracked_files_never_change_the_tier(self):
        with patch.object(gate, 'git', side_effect=lambda *arguments: 'README.md\n' if arguments[0] == 'diff' else 'devil_painter/assets/icons/local/a.png\n'), \
                patch.object(gate, 'merge_base', return_value='base'):
            self.assertEqual(gate.changed_files(), ['README.md'])
            self.assertEqual(gate.untracked_files(), ['devil_painter/assets/icons/local/a.png'])
            self.assertEqual(gate.select_tier(gate.changed_files())[0], 'light')


class ExportCountTests(unittest.TestCase):
    def test_every_journey_declares_its_expected_export_count_and_zero_reason(self):
        self.assertEqual(set(gate.EXPECTED_EXPORTS), set(dev.JOURNEYS))
        golden = gate.read_golden()
        self.assertEqual(gate.export_count_differences(golden), [])
        for journey, (count, reason) in gate.EXPECTED_EXPORTS.items():
            if count == 0:
                self.assertTrue(reason.strip() and '\n' not in reason, journey)

    def test_export_count_differences_flags_mismatches_missing_and_unexplained_zero(self):
        declared = {'a.py': (2, ''), 'b.py': (0, 'no exports'), 'c.py': (0, ''), 'missing_run.py': (1, '')}
        actual = {'a.py': [['x.png', '0' * 64]], 'b.py': [], 'c.py': [], 'undeclared.py': []}
        differences = gate.export_count_differences(actual, declared)
        self.assertEqual(differences, [
            'a.py: expected 2 exports, got 1',
            'c.py: declared 0 exports without a reason',
            'missing_run.py: declared journey did not run',
            'undeclared.py: missing expected export count declaration',
        ])


class LockTests(GateTestCase):
    def test_second_gate_is_refused_while_the_first_is_alive(self):
        gate_state.acquire_lock('first')
        with patch.object(gate_state.os, 'getpid', return_value=DEAD_PID):
            with self.assertRaisesRegex(gate_state.GateBusy, 'already running in this worktree'):
                gate_state.acquire_lock('second')
        gate_state.release_lock()
        self.assertFalse(gate_state.lock_path().exists())

    def test_stale_lock_of_a_dead_process_is_taken_over(self):
        workspace.prepare_scratch()
        gate_state.lock_path().write_text(json.dumps(dict(pid=DEAD_PID, run='old')), encoding='utf-8')
        gate_state.acquire_lock('new')
        self.assertEqual(json.loads(gate_state.lock_path().read_text(encoding='utf-8'))['run'], 'new')
        gate_state.release_lock()

    def test_runner_refuses_a_second_gate_with_a_clear_message(self):
        gate_state.acquire_lock('first')
        try:
            with patch.object(gate_state.os, 'getpid', return_value=DEAD_PID):
                self.assertEqual(dev.main(['--quick']), 1)
        finally:
            gate_state.release_lock()
        self.assertTrue(any('already running in this worktree' in line for line in self.printed))


class WaitTests(GateTestCase):
    def test_wait_reports_the_verdict_with_exit_codes(self):
        for state, code in (('passed', 0), ('failed', 1)):
            self.status(pid=DEAD_PID, state=state, summary=f'GATE RESULT: {state.upper()}', failures=[])
            self.assertEqual(dev.main(['--wait']), code)
        self.assertIn('GATE RESULT: FAILED', self.printed)

    def test_wait_returns_two_while_the_gate_still_runs(self):
        self.status(pid=os.getpid(), state='running')
        with patch.object(dev, 'WAIT_LIMIT', 0):
            self.assertEqual(dev.main(['--wait']), 2)

    def test_wait_reports_a_dead_gate_with_its_logs(self):
        workspace.prepare_scratch()
        console = self.scratch / 'gate-console.log'
        console.write_text('step one\nlast words\n', encoding='utf-8')
        self.status(pid=DEAD_PID, state='running', console='scratch/gate-console.log', folder='scratch/run-r1')
        self.assertEqual(dev.main(['--wait']), 1)
        self.assertEqual(gate_state.read_status()['state'], 'dead')
        self.assertTrue(any('is dead' in line for line in self.printed))
        self.assertIn('    | last words', self.printed)
        self.assertIn('Its logs remain in scratch/run-r1/logs.', self.printed)

    def test_wait_without_a_recorded_run_fails(self):
        self.assertEqual(dev.main(['--wait']), 1)


class DetachTests(GateTestCase):
    def test_detach_starts_the_gate_and_records_its_pid(self):
        class Started:
            pid = 4321

        with patch.object(dev.subprocess, 'Popen', return_value=Started()) as popen:
            self.assertEqual(dev.main(['--detach', '--tier', 'auto']), 0)
        spawned = popen.call_args.args[0]
        self.assertEqual(spawned[-2:], ['--tier', 'auto'])
        self.assertNotIn('--detach', spawned)
        self.assertIn('-u', spawned)
        status = gate_state.read_status()
        self.assertEqual((status['state'], status['pid'], status['console']), ('starting', 4321, 'scratch/gate-console.log'))

    def test_detach_refuses_while_a_gate_runs(self):
        gate_state.acquire_lock('first')
        try:
            with patch.object(dev.subprocess, 'Popen') as popen:
                self.assertEqual(dev.main(['--detach', '--tier', 'auto']), 1)
            popen.assert_not_called()
        finally:
            gate_state.release_lock()


class ResultTests(GateTestCase):
    def record(self, **fields):
        return dict(dict(verdict='passed', tier='standard', tree='a' * 40, zip_sha256=gate_state.sha256(self.archive), journeys=30, journeys_passed=30,
                         exports=12, differences=0, steps=40, steps_passed=40, seconds=961.4, finished='2026-11-20 12:00 UTC'), **fields)

    def setUp(self):
        super().setUp()
        self.archive = self.root / 'dist' / 'devil_painter.zip'
        self.archive.parent.mkdir()
        self.archive.write_bytes(b'zip')
        self.result = patch.object(gate_state, 'result_path', return_value=self.root / 'result.json')
        self.result.start()

    def tearDown(self):
        self.result.stop()
        super().tearDown()

    def test_saved_pass_matches_only_the_same_tree_archive_and_a_tier_at_least_as_strong(self):
        gate_state.save_result(self.record())
        self.assertIsNotNone(gate_state.saved_pass('a' * 40, 'light', self.archive))
        self.assertIsNotNone(gate_state.saved_pass('a' * 40, 'standard', self.archive))
        self.assertIsNone(gate_state.saved_pass('a' * 40, 'full', self.archive))
        self.assertIsNone(gate_state.saved_pass('b' * 40, 'standard', self.archive))
        self.archive.write_bytes(b'rebuilt')
        self.assertIsNone(gate_state.saved_pass('a' * 40, 'standard', self.archive))

    def test_summary_is_one_pasteable_line(self):
        line = gate_state.summary_line(self.record())
        self.assertEqual(line.splitlines(), [line])
        for part in ('GATE RESULT: PASSED', 'tier STANDARD', 'tree aaaaaaaaaaaa', 'journeys 30/30', 'golden 12 exports, 0 differences', '16m 01s'):
            self.assertIn(part, line)


class RepositoryFingerprintTests(unittest.TestCase):
    def test_fingerprint_follows_uncommitted_and_untracked_changes(self):
        with tempfile.TemporaryDirectory(dir=workspace.prepare_scratch()) as folder:
            root = Path(folder).resolve()

            def git(*arguments):
                subprocess.run(['git', *arguments], cwd=root, capture_output=True, check=True)

            git('init', '-q')
            git('config', 'user.name', 'fixture')
            git('config', 'user.email', 'fixture' + '@' + 'users.noreply.github.com')
            (root / 'tracked.txt').write_text('one', encoding='utf-8')
            git('add', 'tracked.txt')
            git('commit', '-q', '-m', 'fixture')
            with patch.object(workspace, 'ROOT', root):
                clean = gate_state.tree_fingerprint()
                self.assertEqual(clean, gate_state.tree_fingerprint())
                (root / 'new.txt').write_text('two', encoding='utf-8')
                untracked = gate_state.tree_fingerprint()
                (root / 'tracked.txt').write_text('changed', encoding='utf-8')
                edited = gate_state.tree_fingerprint()
            self.assertEqual(len({clean, untracked, edited}), 3)
            self.assertEqual(subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True).stdout.split(), ['M', 'tracked.txt', '??', 'new.txt'])


class BlenderPathTests(unittest.TestCase):
    def test_blender_variable_wins_and_old_versions_are_rejected_with_a_clear_message(self):
        with tempfile.NamedTemporaryFile(dir=workspace.prepare_scratch(), suffix='.exe', delete=False) as handle:
            executable = Path(handle.name)
        try:
            with patch.dict(os.environ, BLENDER=str(executable)):
                self.assertEqual(dev.blender_candidates(), [executable])
                with patch.object(dev, 'blender_version', return_value=(5, 3)):
                    self.assertEqual(dev.find_blender(), str(executable))
                with patch.object(dev, 'blender_version', return_value=(4, 2)):
                    with self.assertRaisesRegex(dev.BlenderMissing, r'is Blender 4\.2.*Set the BLENDER environment variable'):
                        dev.find_blender()
            with patch.dict(os.environ, BLENDER=str(executable) + '.missing'):
                with self.assertRaisesRegex(dev.BlenderMissing, 'does not exist'):
                    dev.find_blender()
        finally:
            executable.unlink()

    def test_version_is_read_from_blender_itself(self):
        self.assertIsNone(dev.blender_version(Path(sys.executable)))
        real_run = subprocess.run
        command = [sys.executable, '-c', 'print("Blender 5.2.1 LTS")']
        with patch.object(dev.subprocess, 'run', side_effect=lambda arguments, **options: real_run(command, **options)):
            self.assertEqual(dev.blender_version(Path('blender')), (5, 2))


class CommitMessageTests(unittest.TestCase):
    def test_co_author_trailers_are_removed(self):
        message = 'feat(gate): stream output\n\nBody line.\n\nCo-Authored-By: Someone <someone' + '@' + 'example.org>\nco-authored-by: Other <x>\n'
        self.assertEqual(commit_msg.strip_co_authors(message), 'feat(gate): stream output\n\nBody line.\n')

    def test_messages_without_trailers_are_untouched(self):
        for message in ('fix: one line', 'fix: body\n\nmentions co-authored work\n\n', 'docs: x\n\nSigned-off-by: Someone <s>\n'):
            self.assertEqual(commit_msg.strip_co_authors(message), message)

    def test_hook_rewrites_the_message_file(self):
        with tempfile.TemporaryDirectory(dir=workspace.prepare_scratch()) as folder:
            message = Path(folder) / 'COMMIT_EDITMSG'
            message.write_text('fix: x\n\nCo-Authored-By: A <b>\n', encoding='utf-8')
            with patch('sys.stderr'):
                self.assertEqual(commit_msg.main(str(message)), 0)
            self.assertEqual(message.read_text(encoding='utf-8'), 'fix: x\n')

    def test_hook_script_calls_the_python_rewriter(self):
        hook = Path(__file__).resolve().parents[1] / 'tools' / 'hooks' / 'commit-msg'
        self.assertEqual(hook.read_bytes(), b'#!/bin/sh\nexec python -B tools/commit_msg.py "$1"\n')
