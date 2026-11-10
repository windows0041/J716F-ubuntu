#!/usr/bin/env python3
"""Exercise the publication audit against a temporary Git index."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).with_name('audit-staged.py')


class StagedAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='j716f-index-audit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / 'tools/project/audit-staged.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SOURCE, self.script)
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True)

    def audit(self, data, unstaged=None):
        path = self.root / 'review.txt'
        path.write_bytes(data)
        subprocess.run(['git', 'add', 'review.txt'], cwd=self.root, check=True)
        if unstaged is not None:
            path.write_bytes(unstaged)
        result = subprocess.run([sys.executable, str(self.script)], cwd=self.root,
                                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_only_index_content_is_reviewed(self):
        fake_key = b'-----BEGIN OPENSSH ' + b'PRIVATE KEY-----\nfixture\n'
        code, report = self.audit(b'ordinary public source\n', unstaged=fake_key)
        self.assertEqual(code, 0)
        self.assertEqual(report['files'], 1)

    def test_staged_private_key_is_rejected_without_printing_contents(self):
        fake_key = b'-----BEGIN OPENSSH ' + b'PRIVATE KEY-----\nfixture\n'
        code, report = self.audit(fake_key)
        self.assertEqual(code, 1)
        self.assertEqual(report['findings'][0]['reason'], 'private_key')
        self.assertNotIn('fixture', json.dumps(report))

    def test_device_uuid_is_rejected(self):
        fixture = b'01234567' + b'-89ab-cdef-0123-456789abcdef'
        code, report = self.audit(b'root_uuid=' + fixture + b'\n')
        self.assertEqual(code, 1)
        self.assertEqual(report['findings'][0]['reason'], 'potential_device_uuid')

    def test_public_upstream_bug_reference_is_allowed(self):
        fixture = b'01234567' + b'-89ab-cdef-0123-456789abcdef'
        code, report = self.audit(b'Closes: https://sashiko.dev/#/bug/linux-' + fixture + b'\n')
        self.assertEqual(code, 0)
        self.assertEqual(report['findings'], [])


if __name__ == '__main__':
    unittest.main()
