#!/usr/bin/env python3
"""Append only generated evidence onto a moving remote head, without force push.

Never rescan, rebase execution code, overwrite an epoch, or claim source/AL success.
Every retry checks unchanged execution inputs and reads back exact SHA256 bytes.
"""
from __future__ import annotations
import argparse
from contextvars import ContextVar
from datetime import datetime, timezone
import math
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import signal
import time

PATH_RE = re.compile(r'(receipts|bridges)/\d{4}/\d{2}/\d{2}/\d{8}T\d{2}00Z-n([1-9]\d{0,2})\.json\.gz\Z')


class PublishBlocked(ValueError):
    pass


class GitOperationTimeout(PublishBlocked):
    """Remote outcome may be ambiguous: always fetch and verify before another push."""


_GIT_TIMEOUT_SECONDS = 30.0
_PUBLISH_BUDGET_SECONDS = 150.0
_deadline = ContextVar('xray_publish_deadline', default=None)


def git(*args, data=None, env=None, check=True):
    remaining = _deadline.get()
    timeout = _GIT_TIMEOUT_SECONDS if remaining is None else min(_GIT_TIMEOUT_SECONDS, remaining - time.monotonic())
    if timeout <= 0:
        raise PublishBlocked('PUBLISH_DEADLINE_EXPIRED')
    operation = args[0]
    try:
        p = subprocess.Popen(['git', *args], stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    except OSError:
        raise PublishBlocked('GIT_START_FAILED:' + operation) from None
    try:
        stdout, stderr = p.communicate(input=data, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Killing only the immediate git process can leave git-remote-https or
        # an SSH child alive. Kill the process group, not the caller's session.
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            p.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            for stream in (p.stdin, p.stdout, p.stderr):
                if stream is not None:
                    stream.close()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                raise PublishBlocked('GIT_TIMEOUT_CLEANUP_UNCERTAIN:' + operation) from None
            # A child may have escaped the process group: do not retry blindly.
            raise PublishBlocked('GIT_TIMEOUT_CLEANUP_UNCERTAIN:' + operation) from None
        raise GitOperationTimeout('GIT_OPERATION_TIMEOUT:' + operation) from None
    r = subprocess.CompletedProcess(['git', *args], p.returncode, stdout, stderr)
    if check and r.returncode:
        # Do not echo git stderr: authenticated remotes may contain credentials.
        raise PublishBlocked('GIT_OPERATION_FAILED:' + operation)
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


def publish(base, branch, paths, attempts=3, *, budget_seconds=_PUBLISH_BUDGET_SECONDS):
    if (isinstance(budget_seconds, bool) or not isinstance(budget_seconds, (int, float))
            or not math.isfinite(budget_seconds) or not 0 < budget_seconds <= _PUBLISH_BUDGET_SECONDS):
        raise PublishBlocked('INVALID_PUBLISH_BUDGET')
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise PublishBlocked('INVALID_RETRY_BUDGET')
    deadline = time.monotonic() + budget_seconds
    parent = _deadline.get()
    token = _deadline.set(deadline if parent is None else min(deadline, parent))
    try:
        return _publish(base, branch, paths, attempts)
    finally:
        _deadline.reset(token)


def _retry_timeout(exc):
    # No remote URL, arguments, stdout, stderr or credentials in diagnostics.
    print('PUBLISH_RETRYABLE_TIMEOUT ' + str(exc), flush=True)


def _publish(base, branch, paths, attempts):
    if branch != 'main' or len(paths) not in (1, 2) or len(set(paths)) != len(paths):
        raise PublishBlocked('INVALID_PUBLISH_SCOPE')
    matches = [PATH_RE.fullmatch(p) for p in paths]
    if any(m is None for m in matches):
        raise PublishBlocked('INVALID_EVIDENCE_PATH')
    scopes = {int(m.group(2)) for m in matches}
    if len(scopes) != 1 or not all(n in (250, 400) or 401 <= n <= 564 for n in scopes):
        raise PublishBlocked('INVALID_EVIDENCE_SCOPE')
    scope = scopes.pop()
    receipt = [p for p in paths if p.startswith('receipts/')]
    if len(receipt) != 1:
        raise PublishBlocked('MISSING_RECEIPT')
    if scope >= 401:
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
        try:
            git('fetch', '--no-tags', 'origin', 'refs/heads/main')
        except GitOperationTimeout as exc:
            _retry_timeout(exc)
            continue
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
            # In the pinned partial checkout, unchanged blobs are promised by this
            # same remote. Default write-tree would fetch the entire old archive.
            # Every added blob was already read, hashed and size-checked above.
            # Keep the default existence check for non-promisor worktrees.
            promisor = git('config', '--bool', '--get', 'remote.origin.promisor', check=False)
            blob_filter = git('config', '--get', 'remote.origin.partialclonefilter', check=False)
            allow_promised = (promisor.returncode == blob_filter.returncode == 0
                              and promisor.stdout.strip() == b'true'
                              and blob_filter.stdout.strip() == b'blob:none')
            with tempfile.TemporaryDirectory(prefix='xray-publish-') as tmp:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / 'index'))
                git('read-tree', remote, env=env)
                for p in paths:
                    git('update-index', '--add', '--cacheinfo', '100644', generated[p][2], p, env=env)
                write_tree_args = ('--missing-ok',) if allow_promised else ()
                new_tree = git('write-tree', *write_tree_args, env=env).stdout.decode().strip()
            committed = git('commit-tree', new_tree, '-p', remote,
                            data=b'research: append immutable source evidence [skip ci]\n').stdout.decode().strip()
            try:
                pushed = git('push', 'origin', committed + ':refs/heads/main', check=False)
            except GitOperationTimeout as exc:
                # The server may have accepted the push before the timeout.
                # Next attempt rechecks ancestry, source inputs and exact pair.
                _retry_timeout(exc)
                continue
            if pushed.returncode:
                continue  # Bounded retry rechecks source, pair collision, and ancestry.
        try:
            git('fetch', '--no-tags', 'origin', 'refs/heads/main')
        except GitOperationTimeout as exc:
            _retry_timeout(exc)
            continue
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


def current_epoch_budget(paths, *, now=None):
    """For approved live workflow only; never reopen a previous natural epoch.

    End before the existing H+12 audit with a 30-second safety margin.
    The budget is computed once, then enforced using a monotonic clock.
    """
    receipts = [p for p in paths if p.startswith('receipts/')]
    if len(receipts) != 1 or PATH_RE.fullmatch(receipts[0]) is None:
        raise PublishBlocked('INVALID_LIVE_RECEIPT_PATH')
    path = receipts[0]
    try:
        stamp = Path(path).name.split('-n', 1)[0]
        epoch = datetime.strptime(stamp, '%Y%m%dT%H00Z').replace(tzinfo=timezone.utc)
    except ValueError:
        raise PublishBlocked('INVALID_LIVE_RECEIPT_EPOCH') from None
    if path.split('/')[1:4] != [epoch.strftime('%Y'), epoch.strftime('%m'), epoch.strftime('%d')]:
        raise PublishBlocked('LIVE_RECEIPT_PATH_EPOCH_MISMATCH')
    wall = time.time() if now is None else now
    if not isinstance(wall, (int, float)) or isinstance(wall, bool) or not math.isfinite(wall):
        raise PublishBlocked('INVALID_LIVE_CLOCK')
    age = wall - epoch.timestamp()
    if not 0 <= age < 690:
        raise PublishBlocked('OUTSIDE_CURRENT_LIVE_PUBLISH_WINDOW')
    # Reserve four seconds for bounded process cleanup in the worst case.
    budget = min(_PUBLISH_BUDGET_SECONDS, 686 - age)
    if budget <= 0:
        raise PublishBlocked('INSUFFICIENT_LIVE_PUBLISH_BUDGET')
    return budget


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--branch', required=True)
    p.add_argument('--require-current-epoch', action='store_true', help='Mandatory in approved live workflow; synthetic local tests only may omit.')
    p.add_argument('paths', nargs='+')
    a = p.parse_args()
    try:
        budget = current_epoch_budget(a.paths) if a.require_current_epoch else _PUBLISH_BUDGET_SECONDS
        publish(a.base, a.branch, a.paths, budget_seconds=budget)
        return 0
    except (PublishBlocked, OSError, ValueError, subprocess.TimeoutExpired):
        import sys
        exc = sys.exc_info()[1]
        code = str(exc) if isinstance(exc, PublishBlocked) else 'LOCAL_GIT_OR_IO_FAILURE'
        print('PUBLISH_FAIL_CLOSED ' + code)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
