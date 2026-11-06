"""Local bare-Git integration tests; never touch GitHub or Binance."""
from __future__ import annotations

import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ops.evidence_ref_publisher import (
    EVIDENCE_BRANCH, EvidenceBlocked, append_pair, path_contract
)
from ops.evidence_ref_pair_audit import PairRejected, audit_pair
from evidence_ref_fixture import fixture_pair


def run(*args):
    x = subprocess.run(["git", *map(str, args)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return x.stdout.decode("utf-8").strip()


class EvidenceRefShadowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = Path.cwd()
        base = Path(self.temp.name)
        self.remote = base / "origin.git"
        self.work = base / "work"
        run("init", "--bare", self.remote)
        run("init", "-b", "main", self.work)
        os.chdir(self.work)
        run("config", "user.name", "Local QA")
        run("config", "user.email", "qa@example.invalid")
        (self.work / "README.md").write_text("main code release\n")
        run("add", "README.md")
        run("commit", "-m", "initial verified code")
        run("remote", "add", "origin", self.remote)
        run("push", "-u", "origin", "main")
        self.origin = run("rev-parse", "HEAD")
        run("branch", EVIDENCE_BRANCH, self.origin)
        run("push", "origin", EVIDENCE_BRANCH)
        self.paths, receipt, bridge, self.synthetic_source, self.synthetic_bridge = fixture_pair()
        for name, data in zip(self.paths, (receipt, bridge)):
            f = self.work / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        run("add", *self.paths)
        run("commit", "-m", "local candidate pair, not main")
        self.local_head = run("rev-parse", "HEAD")

    def tearDown(self):
        os.chdir(self.old)
        self.temp.cleanup()

    def _remote_branch(self, branch):
        return run("--git-dir", self.remote, "rev-parse", "refs/heads/" + branch)

    def test_pair_published_only_to_evidence_ref(self):
        result = append_pair(code_base=self.origin, evidence_origin=self.origin,
                             paths=self.paths)
        self.assertEqual(result["status"],
                         "EVIDENCE_REF_PAIR_DURABLE_READBACK_ONLY")
        self.assertTrue(result["code_main_unchanged"])
        self.assertEqual(result["orders_sent"], 0)
        self.assertEqual(result["notifications_sent"], 0)
        self.assertFalse(result["full_final_start"])
        self.assertEqual(self._remote_branch("main"), self.origin)
        self.assertNotEqual(self._remote_branch(EVIDENCE_BRANCH), self.origin)
        for path in self.paths:
            blob = subprocess.run(
                ["git", "--git-dir", str(self.remote), "show",
                 "refs/heads/" + EVIDENCE_BRANCH + ":" + path],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            ).stdout
            self.assertEqual(blob, (self.work / path).read_bytes())

    def test_exact_pair_retry_is_idempotent(self):
        first = append_pair(code_base=self.origin, evidence_origin=self.origin,
                            paths=self.paths)
        second = append_pair(code_base=self.origin, evidence_origin=self.origin,
                             paths=self.paths)
        self.assertEqual(first["evidence_commit"], second["evidence_commit"])
        self.assertEqual(self._remote_branch("main"), self.origin)

    def test_mutated_existing_receipt_is_rejected(self):
        append_pair(code_base=self.origin, evidence_origin=self.origin,
                    paths=self.paths)
        original = gzip.decompress((self.work / self.paths[0]).read_bytes())
        (self.work / self.paths[0]).write_bytes(gzip.compress(original, mtime=42))
        run("add", self.paths[0])
        run("commit", "--amend", "--no-edit")
        with self.assertRaisesRegex(EvidenceBlocked, "IMMUTABLE_EPOCH_COLLISION"):
            append_pair(code_base=self.origin, evidence_origin=self.origin,
                        paths=self.paths)

    def test_code_main_change_during_scan_fails(self):
        # Move source main with a genuine new code commit, not the evidence ref.
        run("checkout", "-b", "code-update", self.origin)
        (self.work / "README.md").write_text("new reviewed code\n")
        run("add", "README.md")
        run("commit", "-m", "source code progressed")
        run("push", "origin", "HEAD:main")
        run("checkout", "--detach", self.local_head)
        with self.assertRaisesRegex(EvidenceBlocked,
                                    "CODE_MAIN_CHANGED_DURING_SCAN"):
            append_pair(code_base=self.origin, evidence_origin=self.origin,
                        paths=self.paths)

    def test_evidence_branch_code_tamper_fails(self):
        run("checkout", "-b", "evil-evidence", EVIDENCE_BRANCH)
        (self.work / "README.md").write_text("unauthorized evidence-code edit\n")
        run("add", "README.md")
        run("commit", "-m", "forbidden evidence code drift")
        run("push", "origin", "HEAD:" + EVIDENCE_BRANCH)
        run("checkout", "--detach", self.local_head)
        with self.assertRaisesRegex(EvidenceBlocked,
                                    "EVIDENCE_REF_NON_APPEND_CHANGE"):
            append_pair(code_base=self.origin, evidence_origin=self.origin,
                        paths=self.paths)

    def test_shadow_requires_exact_existing_source_main_pair(self):
        with self.assertRaisesRegex(EvidenceBlocked,
                                    "SHADOW_MAIN_NOT_EXACT_VERIFIED_PAIR"):
            append_pair(code_base=self.origin, evidence_origin=self.origin,
                        paths=self.paths, shadow_source_main=True)
        self.assertEqual(self._remote_branch(EVIDENCE_BRANCH), self.origin)

    def test_shadow_mirrors_only_published_source_pair(self):
        run("push", "origin", "HEAD:main")  # normal existing main publisher
        source_head = self._remote_branch("main")
        self.assertEqual(source_head, self.local_head)
        result = append_pair(code_base=self.origin,
                             evidence_origin=self.origin, paths=self.paths,
                             shadow_source_main=True)
        self.assertEqual(result["status"],
                         "SHADOW_EVIDENCE_REF_PAIR_DURABLE_READBACK_NO_LIVE_CONSUMER")
        self.assertTrue(result["source_main_exact_pair_verified"])
        self.assertFalse(result["code_main_unchanged"])
        self.assertEqual(result["orders_sent"], 0)
        self.assertEqual(self._remote_branch("main"), source_head)
        self.assertNotEqual(self._remote_branch(EVIDENCE_BRANCH), self.origin)

    def test_shadow_repeat_is_exact_idempotent(self):
        run("push", "origin", "HEAD:main")
        first = append_pair(code_base=self.origin, evidence_origin=self.origin,
                            paths=self.paths, shadow_source_main=True)
        second = append_pair(code_base=self.origin, evidence_origin=self.origin,
                             paths=self.paths, shadow_source_main=True)
        self.assertEqual(first["evidence_commit"], second["evidence_commit"])
        self.assertEqual(self._remote_branch("main"), self.local_head)

    def test_shadow_rejects_unexpected_main_source_code_change(self):
        (self.work / "README.md").write_text("unapproved new code\n")
        run("add", "README.md")
        run("commit", "--amend", "--no-edit")
        tampered_main = run("rev-parse", "HEAD")
        run("push", "origin", "HEAD:main")
        run("checkout", "--detach", self.local_head)
        with self.assertRaisesRegex(EvidenceBlocked,
                                    "SHADOW_MAIN_NOT_EXACT_VERIFIED_PAIR"):
            append_pair(code_base=self.origin, evidence_origin=self.origin,
                        paths=self.paths, shadow_source_main=True)
        self.assertEqual(self._remote_branch("main"), tampered_main)
        self.assertEqual(self._remote_branch(EVIDENCE_BRANCH), self.origin)

    def test_shadow_rejects_mismatched_main_published_pair(self):
        run("push", "origin", "HEAD:main")
        run("checkout", "-b", "tamper-main", self.local_head)
        path = self.work / self.paths[0]
        content = gzip.decompress(path.read_bytes())
        path.write_bytes(gzip.compress(content, mtime=42))
        run("add", self.paths[0])
        run("commit", "-m", "replace source compressed blob")
        run("push", "origin", "HEAD:main")
        run("checkout", "--detach", self.local_head)
        with self.assertRaisesRegex(EvidenceBlocked,
                                    "SHADOW_MAIN_NOT_EXACT_VERIFIED_PAIR"):
            append_pair(code_base=self.origin, evidence_origin=self.origin,
                        paths=self.paths, shadow_source_main=True)
        self.assertEqual(self._remote_branch(EVIDENCE_BRANCH), self.origin)

    def test_unsafe_paths_fail_before_network(self):
        with self.assertRaises(EvidenceBlocked):
            path_contract(("../secrets", self.paths[1]))
        with self.assertRaises(EvidenceBlocked):
            path_contract((self.paths[0], "bridges/2026/11/06/WRONG.json.gz"))
        with self.assertRaises(EvidenceBlocked):
            path_contract((self.paths[0], self.paths[0]))

    def test_code_ref_and_evidence_ref_are_never_conflated(self):
        # Readback only, not a release or branch protection change.
        self.assertEqual(self._remote_branch("main"), self.origin)
        self.assertEqual(self._remote_branch(EVIDENCE_BRANCH), self.origin)
        self.assertNotEqual(self.local_head, self.origin)


if __name__ == "__main__":
    unittest.main()
