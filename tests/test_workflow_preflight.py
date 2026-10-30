"""Execute the deployed workflow's exact guard against isolated real git repos."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class WorkflowPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root/'remote.git'
        self.work = self.root/'work'
        self.run_git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.run_git(self.root, 'clone', str(self.remote), str(self.work))
        self.run_git(self.work, 'config', 'user.name', 'Source QA fixture')
        self.run_git(self.work, 'config', 'user.email', 'fixture@example.invalid')
        self.run_git(self.work, 'commit', '--allow-empty', '-m', 'fixture initial')
        self.run_git(self.work, 'push', '-u', 'origin', 'main')
        text = (Path(__file__).resolve().parents[1]/'.github/workflows/hourly-519-public-source.yml').read_text()
        section = text.split('# BEGIN_SOURCE_PREFLIGHT\n', 1)[1].split('# END_SOURCE_PREFLIGHT', 1)[0]
        self.script = 'set -euo pipefail\n' + '\n'.join(line[10:] if line.startswith('          ') else line for line in section.splitlines())
        self.bin = self.root/'bin'
        self.bin.mkdir()
        date = self.bin/'date'
        date.write_text('#!/bin/sh\nprintf "2026/10/30/20261030T1800Z\\n"\n')
        date.chmod(0o755)

    @staticmethod
    def run_git(cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True)

    def guard(self):
        env = dict(os.environ, GITHUB_REF_NAME='main', MODE='519', PATH=str(self.bin)+os.pathsep+os.environ['PATH'])
        return subprocess.run(['bash', '-c', self.script], cwd=self.work, env=env, capture_output=True, text=True, timeout=10)

    def test_current_head_without_receipt_allows_scan(self):
        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SOURCE_PREFLIGHT_ALLOW_SCAN', result.stdout)

    def test_duplicate_epoch_blocks_before_scan_and_preserves_bytes(self):
        receipt = self.work/'receipts/2026/10/30/20261030T1800Z-n519.json.gz'
        receipt.parent.mkdir(parents=True)
        receipt.write_bytes(b'fixture immutable bytes')
        result = self.guard()
        self.assertEqual(result.returncode, 2)
        self.assertIn('DUPLICATE_EPOCH_NO_SCAN', result.stdout)
        self.assertNotIn('SOURCE_PREFLIGHT_ALLOW_SCAN', result.stdout)
        self.assertEqual(receipt.read_bytes(), b'fixture immutable bytes')

    def test_stale_trigger_head_blocks_before_scan(self):
        self.run_git(self.work, 'commit', '--allow-empty', '-m', 'remote advanced')
        self.run_git(self.work, 'push', 'origin', 'main')
        self.run_git(self.work, 'reset', '--hard', 'HEAD~1')
        result = self.guard()
        self.assertEqual(result.returncode, 2)
        self.assertIn('STALE_WORKFLOW_HEAD_NO_SCAN', result.stdout)
        self.assertNotIn('SOURCE_PREFLIGHT_ALLOW_SCAN', result.stdout)


if __name__ == '__main__':
    unittest.main()
