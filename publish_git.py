#!/usr/bin/env python3
"""Append only generated evidence onto a moving remote head, without force push.

Never rescan, rebase execution code, overwrite an epoch, or claim source/AL success.
Every retry checks unchanged execution inputs and reads back exact SHA256 bytes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

PATH_RE = re.compile(r'(receipts|bridges)/\d{4}/\d{2}/\d{2}/\d{8}T\d{2}00Z-n(250|400|519)\.json\.gz\Z')


class PublishBlocked(ValueError):
    pass


def git(*args, data=None, env=None, check=True):
    r = subprocess.run(['git', *args], input=data, capture_output=True, env=env, timeout=30)
    if check and r.returncode:
        # Do not echo git stderr: authenticated remotes may contain credentials.
        raise PublishBlocked('GIT_OPERATION_FAILED:' + args[0])
    return r


def output(*args):
    return git(*args).stdout.decode().strip()


def tree(ref):
    entries = {}
    for row in git('ls-tree', '-rz', ref).stdout.split(b'\0'):
        if row:
            meta, name = row.split(b'\t', 1)
            mode, kind, sha = meta.decode().split()
            entries[name.decode()] = (mode, kind, sha)
    return entries


def publish(base, branch, paths, attempts=3):
    if branch != 'main' or len(paths) not in (1, 2) or len(set(paths)) != len(paths):
        raise PublishBlocked('INVALID_PUBLISH_SCOPE')
    if any(not PATH_RE.fullmatch(p) for p in paths):
        raise PublishBlocked('INVALID_EVIDENCE_PATH')
    receipt = [p for p in paths if p.startswith('receipts/')]
    if len(receipt) != 1:
        raise PublishBlocked('MISSING_RECEIPT')
    if receipt[0].endswith('-n519.json.gz'):
        if set(paths) != {receipt[0], receipt[0].replace('receipts/', 'bridges/', 1)}:
            raise PublishBlocked('MISSING_MATCHING_BRIDGE')
    elif len(paths) != 1:
        raise PublishBlocked('UNEXPECTED_BRIDGE')
    if git('diff', '--quiet', 'HEAD', check=False).returncode:
        raise PublishBlocked('DIRTY_TRACKED_STATE')
    original = tree(base)
    generated = tree('HEAD')
    changes = {p for p in original.keys() | generated.keys() if original.get(p) != generated.get(p)}
    if changes != set(paths) or any(p in original for p in paths):
        raise PublishBlocked('LOCAL_COMMIT_NOT_CREATE_ONLY_EVIDENCE')
    blobs = {}
    for p in paths:
        if generated[p][:2] != ('100644', 'blob'):
            raise PublishBlocked('UNSAFE_EVIDENCE_MODE')
        content = git('show', 'HEAD:' + p).stdout
        if not content or len(content) > (200_000 if p.startswith('receipts/') else 8_388_608):
            raise PublishBlocked('EVIDENCE_SIZE_LIMIT')
        blobs[p] = (content, hashlib.sha256(content).hexdigest())
    # All executable source inputs, not just the scanner: newly added source also blocks.
    def execution_inputs(t):
        return {p: entry for p, entry in t.items()
                if p.endswith('.py') or p.startswith('.github/workflows/')}
    for attempt in range(attempts):
        git('fetch', '--no-tags', 'origin', 'refs/heads/main')
        remote = output('rev-parse', 'FETCH_HEAD')
        if git('merge-base', '--is-ancestor', base, remote, check=False).returncode:
            raise PublishBlocked('REMOTE_HISTORY_DIVERGED')
        latest = tree(remote)
        if execution_inputs(original) != execution_inputs(latest):
            raise PublishBlocked('SOURCE_CHANGED_DURING_SCAN')
        present = [p for p in paths if p in latest]
        if present:
            if len(present) != len(paths) or any(latest[p] != generated[p] for p in paths):
                raise PublishBlocked('EPOCH_PATH_ALREADY_EXISTS')
            committed = remote  # Lost push acknowledgement: exact pair already exists.
        else:
            # A private index builds a commit on remote HEAD; worktree/index stay untouched.
            with tempfile.TemporaryDirectory(prefix='xray-publish-') as tmp:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / 'index'))
                git('read-tree', remote, env=env)
                for p in paths:
                    git('update-index', '--add', '--cacheinfo', '100644', generated[p][2], p, env=env)
                new_tree = git('write-tree', env=env).stdout.decode().strip()
            committed = git('commit-tree', new_tree, '-p', remote,
                            data=b'research: append immutable source evidence [skip ci]\n').stdout.decode().strip()
            pushed = git('push', 'origin', committed + ':refs/heads/main', check=False)
            if pushed.returncode:
                continue  # Bounded retry rechecks source, pair collision, and ancestry.
        git('fetch', '--no-tags', 'origin', 'refs/heads/main')
        readback = output('rev-parse', 'FETCH_HEAD')
        if git('merge-base', '--is-ancestor', committed, readback, check=False).returncode:
            raise PublishBlocked('REMOTE_READBACK_HISTORY_DIVERGED')
        for p, (_, expected) in blobs.items():
            if tree(readback).get(p) != generated[p]:
                raise PublishBlocked('REMOTE_READBACK_MODE_OR_BLOB_MISMATCH')
            actual = hashlib.sha256(git('show', readback + ':' + p).stdout).hexdigest()
            if actual != expected:
                raise PublishBlocked('REMOTE_SHA256_MISMATCH')
            print(json.dumps({'event': 'EVIDENCE_REMOTE_READBACK_PASS', 'path': p,
                              'sha256': actual, 'remote_commit': readback}))
        print('PAIR_REMOTE_READBACK_PASS')
        return
    raise PublishBlocked('REMOTE_PUSH_RETRY_EXHAUSTED')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--branch', required=True)
    p.add_argument('paths', nargs='+')
    a = p.parse_args()
    try:
        publish(a.base, a.branch, a.paths)
        return 0
    except (PublishBlocked, OSError, ValueError, subprocess.TimeoutExpired):
        import sys
        exc = sys.exc_info()[1]
        code = str(exc) if isinstance(exc, PublishBlocked) else 'LOCAL_GIT_OR_IO_FAILURE'
        print('PUBLISH_FAIL_CLOSED ' + code)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
