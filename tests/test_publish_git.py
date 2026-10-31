"""Real bare-git race tests. No credentials, network or source requests."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'publish_git.py'


class GitPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.work = self.root / 'work'
        self.git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.git(self.root, 'clone', str(self.remote), str(self.work))
        self.git(self.work, 'config', 'user.name', 'fixture')
        self.git(self.work, 'config', 'user.email', 'fixture@example.invalid')
        (self.work / 'research_519.py').write_text('source v1')
        self.git(self.work, 'add', '.')
        self.git(self.work, 'commit', '-m', 'source')
        self.git(self.work, 'push', 'origin', 'main')
        self.base = self.git(self.work, 'rev-parse', 'HEAD').strip()
        self.path = 'receipts/2026/10/31/20261031T1300Z-n519.json.gz'
        self.bridge = self.path.replace('receipts/', 'bridges/')
        for p in (self.path, self.bridge):
            f = self.work / p
            f.parent.mkdir(parents=True)
            f.write_bytes(b'fixture:' + p.encode())
        self.git(self.work, 'add', self.path, self.bridge)
        self.git(self.work, 'commit', '-m', 'evidence')
        self.peer = self.root / 'peer'
        self.git(self.root, 'clone', str(self.remote), str(self.peer))
        self.git(self.peer, 'config', 'user.name', 'peer')
        self.git(self.peer, 'config', 'user.email', 'fixture@example.invalid')

    def git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def advance(self, path, content):
        f = self.peer / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content)
        self.git(self.peer, 'add', path)
        self.git(self.peer, 'commit', '-m', 'concurrent')
        self.git(self.peer, 'push', 'origin', 'main')

    def publish(self):
        return subprocess.run(['python3', str(MODULE), '--base', self.base,
                               '--branch', 'main', self.path, self.bridge],
                              cwd=self.work, capture_output=True, text=True, timeout=20)

    def test_original_workflow_push_reproduces_non_fast_forward(self):
        self.advance('ops/settings.json', b'concurrent merge')
        r = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=self.work,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('[rejected]', r.stderr)
        self.assertNotIn(self.path, self.git(self.remote, 'ls-tree', '-r', '--name-only', 'main'))

    def module(self):
        spec = importlib.util.spec_from_file_location('publish_git', MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_second_race_after_fetch_retries_and_preserves_new_commit(self):
        mod = self.module()
        original_git = mod.git
        pushes = []
        def racing_git(*args, **kwargs):
            if args[0] == 'push':
                pushes.append(args)
                if len(pushes) == 1:
                    self.advance('ops/second-race.json', b'preserved')
            return original_git(*args, **kwargs)
        previous = Path.cwd()
        try:
            os.chdir(self.work)
            with patch.object(mod, 'git', side_effect=racing_git):
                mod.publish(self.base, 'main', [self.path, self.bridge])
        finally:
            os.chdir(previous)
        self.assertEqual(len(pushes), 2)
        self.assertEqual(self.git(self.remote, 'show', 'main:ops/second-race.json'), 'preserved')
        self.assertTrue(all('--force' not in x for x in pushes))

    def test_retry_exhaustion_does_not_overwrite_remote(self):
        mod = self.module()
        original_git = mod.git
        pushes = []
        def racing_git(*args, **kwargs):
            if args[0] == 'push':
                pushes.append(args)
                self.advance('ops/race.json', str(len(pushes)).encode())
            return original_git(*args, **kwargs)
        previous = Path.cwd()
        try:
            os.chdir(self.work)
            with patch.object(mod, 'git', side_effect=racing_git):
                with self.assertRaisesRegex(mod.PublishBlocked, 'REMOTE_PUSH_RETRY_EXHAUSTED'):
                    mod.publish(self.base, 'main', [self.path, self.bridge])
        finally:
            os.chdir(previous)
        self.assertEqual(len(pushes), 3)
        self.assertNotIn(self.path, self.git(self.remote, 'ls-tree', '-r', '--name-only', 'main'))

    def test_pair_is_required(self):
        mod = self.module()
        with self.assertRaisesRegex(mod.PublishBlocked, 'MISSING_MATCHING_BRIDGE'):
            mod.publish(self.base, 'main', [self.path])

    def test_symlink_evidence_blocks(self):
        f = self.work / self.path
        f.unlink()
        f.symlink_to('external')
        self.git(self.work, 'add', self.path)
        self.git(self.work, 'commit', '--amend', '--no-edit')
        r = self.publish()
        self.assertEqual(r.returncode, 2)
        self.assertIn('UNSAFE_EVIDENCE_MODE', r.stdout)

    def test_unrelated_advance_preserved_and_pair_read_back(self):
        self.advance('ops/log-settings.json', b'new configuration')
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('PAIR_REMOTE_READBACK_PASS', r.stdout)
        self.assertEqual(self.git(self.remote, 'show', 'main:ops/log-settings.json').strip(), 'new configuration')
        for p in (self.path, self.bridge):
            self.assertEqual(self.git(self.remote, 'show', 'main:' + p).encode(), (self.work / p).read_bytes())

    def test_execution_source_change_blocks(self):
        self.advance('research_519.py', b'source v2')
        before = self.git(self.remote, 'rev-parse', 'main')
        r = self.publish()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('SOURCE_CHANGED_DURING_SCAN', r.stdout)
        self.assertEqual(self.git(self.remote, 'rev-parse', 'main'), before)

    def test_conflicting_epoch_blocks_without_overwrite(self):
        self.advance(self.path, b'other receipt')
        r = self.publish()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('EPOCH_PATH_ALREADY_EXISTS', r.stdout)
        self.assertEqual(self.git(self.remote, 'show', 'main:' + self.path), 'other receipt')

    def test_unrelated_staged_file_refused(self):
        (self.work / 'leak.txt').write_text('must not publish')
        self.git(self.work, 'add', 'leak.txt')
        r = self.publish()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('DIRTY_TRACKED_STATE', r.stdout)

    def test_no_race_and_repeat_are_idempotent(self):
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        before = self.git(self.remote, 'rev-parse', 'main')
        r = self.publish()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git(self.remote, 'rev-parse', 'main'), before)


if __name__ == '__main__':
    unittest.main()
