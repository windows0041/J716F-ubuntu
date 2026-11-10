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

    def stage_kernel_snapshot(self):
        name = 'kernel/linux-7.4-rc2'
        source = self.root / name / 'Makefile'
        source.parent.mkdir(parents=True)
        source.write_text('VERSION = 7\n')
        pins = {'kernel': {'commit': 'a' * 40}, 'patch_sha256': 'b' * 64,
                'config_sha256': 'c' * 64}
        docs = self.root / 'docs/mainline'
        docs.mkdir(parents=True)
        (docs / 'sources.json').write_text(json.dumps(pins))
        subprocess.run(['git', 'add', name, 'docs/mainline/sources.json'], cwd=self.root, check=True)
        root_tree = subprocess.check_output(['git', 'write-tree'], cwd=self.root).decode().strip()
        tree = subprocess.check_output(['git', 'rev-parse', root_tree + ':' + name], cwd=self.root).decode().strip()
        manifest = {'path': name, 'upstream_commit': pins['kernel']['commit'],
                    'patch_sha256': pins['patch_sha256'], 'config_sha256': pins['config_sha256'],
                    'every_exported_entry_matches_debugged_tree': True,
                    'generated_build_outputs_included': False, 'source_files': 1, 'git_tree_oid': tree}
        (docs / 'kernel-source-manifest.json').write_text(json.dumps(manifest))
        subprocess.run(['git', 'add', 'docs/mainline/kernel-source-manifest.json'], cwd=self.root, check=True)
        return source

    def test_verified_kernel_snapshot_is_accepted(self):
        self.stage_kernel_snapshot()
        code, report = self.audit(b'public metadata\n')
        self.assertEqual(code, 0)
        self.assertEqual(report['verified_kernel_snapshot_entries_staged'], 1)

    def test_changed_kernel_snapshot_is_rejected(self):
        source = self.stage_kernel_snapshot()
        source.write_text('changed source\n')
        subprocess.run(['git', 'add', 'kernel/linux-7.4-rc2/Makefile'], cwd=self.root, check=True)
        code, report = self.audit(b'public metadata\n')
        self.assertEqual(code, 1)
        self.assertIn('source tree mismatch', report['findings'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
