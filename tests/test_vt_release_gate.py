import io
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
from tools import vt_release_gate as gate


def zipped(name, payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return buffer.getvalue()


class ReleaseScanGateTests(unittest.TestCase):
    def test_only_strict_release_tags_are_accepted(self):
        for tag in ('v0.2.0', 'v1.10.3', 'v0.0.0-scantest1', 'v2.0.0-rc.1'):
            self.assertTrue(gate.valid_tag(tag), tag)
        for tag in ('', '0.2.0', 'v0.2', 'v0.2.0;rm', 'v0.2.0\nx', '../v0.2.0', 'v0.2.0-', 'v0.2.0-a..b', 'v0.2.0 '):
            self.assertFalse(gate.valid_tag(tag), tag)

    def test_validate_tag_cli_uses_the_single_tag_pattern(self):
        for tag, expected in (('', 0), ('v0.5.0', 0), ('v1.2.3-rc.1', 0), ('0.5.0', 1), ('v0.5.0 ', 1)):
            with patch.dict(os.environ, {'RELEASE_TAG': tag}), patch('builtins.print'):
                self.assertEqual(gate.main(['--validate-tag']), expected, tag)

    def test_the_draft_must_carry_exactly_the_versioned_add_on_zip(self):
        self.assertEqual(gate.asset_name('v0.2.0'), 'devil_painter-0.2.0.zip')
        good = dict(assets=[dict(name='devil_painter-0.2.0.zip', size=1000)])
        self.assertEqual(gate.release_asset(good, 'v0.2.0')['name'], 'devil_painter-0.2.0.zip')
        for assets in ([], [dict(name='other.zip', size=10)], [dict(name='devil_painter-0.2.0.zip', size=10)] * 2,
                       [dict(name='devil_painter-0.2.0.zip', size=(32 << 20) + 1)], [dict(name='devil_painter-0.2.0.zip', size=0)]):
            with self.assertRaises(gate.GateError):
                gate.release_asset(dict(assets=assets), 'v0.2.0')

    def test_network_addresses_stay_inside_the_allowlists(self):
        gate.checked_url('https://api.github.com/repos/x/y', gate.GITHUB_HOSTS)
        gate.checked_url('https://objects.githubusercontent.com/a', gate.GITHUB_HOSTS, gate.ASSET_HOST_SUFFIX)
        gate.checked_url('https://www.virustotal.com/api/v3/files', gate.VT_HOSTS)
        for url, hosts, suffix in (('http://api.github.com/x', gate.GITHUB_HOSTS, ''), ('https://evil.example/x', gate.GITHUB_HOSTS, ''),
                                   ('https://user:pass' + chr(64) + 'api.github.com/x', gate.GITHUB_HOSTS, ''), ('https://api.github.com:8443/x', gate.GITHUB_HOSTS, ''),
                                   ('https://githubusercontent.com.evil.example/x', gate.GITHUB_HOSTS, gate.ASSET_HOST_SUFFIX),
                                   ('https://virustotal.com.evil.example/x', gate.VT_HOSTS, '')):
            with self.assertRaises(gate.GateError, msg=url):
                gate.checked_url(url, hosts, suffix)

    def test_step_outputs_refuse_newlines_and_unsafe_names(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'output'
            os.environ['GITHUB_OUTPUT'] = str(target)
            try:
                gate.set_output('clean', 'true')
                with self.assertRaises(gate.GateError):
                    gate.set_output('clean', 'true\npublished=true')
                with self.assertRaises(gate.GateError):
                    gate.set_output('bad name', 'x')
            finally:
                del os.environ['GITHUB_OUTPUT']
            self.assertEqual(target.read_text(encoding='utf-8'), 'clean=true\n')

    def test_simulate_flags_the_test_signature_inside_a_zip_and_passes_a_clean_one(self):
        self.assertTrue(gate.contains_test_signature(zipped('readme.txt', gate.TEST_SIGNATURE)))
        self.assertFalse(gate.contains_test_signature(zipped('readme.txt', b'clean add-on')))
        with tempfile.TemporaryDirectory() as folder:
            clean = Path(folder) / 'devil_painter-0.0.0.zip'
            clean.write_bytes(zipped('readme.txt', b'clean add-on'))
            self.assertTrue(gate.SimulatedVirusTotal().scan(clean, gate.sha256_of(clean)).clean)

    def test_any_detection_blocks_and_the_scan_record_is_appended_once(self):
        self.assertFalse(gate.Verdict('a' * 64, 0, 1, 50, 10).clean)
        self.assertFalse(gate.Verdict('a' * 64, 1, 0, 50, 10).clean)
        verdict = gate.Verdict('b' * 64, 0, 0, 60, 10)
        record = gate.scan_record('devil_painter-0.2.0.zip', verdict, '2026-11-18 00:00 UTC')
        once = gate.notes_with_record('Release notes.', record)
        self.assertEqual(gate.notes_with_record(once, record), once)
        self.assertIn('0 malicious, 0 suspicious', once)
        self.assertTrue(once.startswith('Release notes.'))

    def test_virustotal_results_count_only_malicious_and_suspicious_engines(self):
        verdict = gate.verdict_from('c' * 64, dict(malicious=0, suspicious=1, harmless=3, undetected=60),
                                    dict(A=dict(category='suspicious', result='Heur'), B=dict(category='undetected')), 'upload')
        self.assertEqual((verdict.suspicious, verdict.engines, verdict.clean), (1, ['A: Heur'], False))


if __name__ == '__main__':
    unittest.main()
