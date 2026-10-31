"""Real bare-Git no-network regression tests for native fallback idempotence."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ops import source_preflight as p

STAMP = "20261031T1800Z"


def canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def evidence(stamp=STAMP):
    from datetime import datetime, timezone
    dt = datetime.strptime(stamp, "%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    epoch = int(dt.timestamp() * 1000) - 1
    rows = [{"symbol": f"X{i:04}USDT", "technical_data_quality": "PASS",
             "frame_quality": {"1h": "PASS", "4h": "PASS", "1d": "PASS"}}
            for i in range(519)]
    receipt = {
        "schema": "XRAY_519_SOURCE_TECH_RESEARCH_V1",
        "source": "BINANCE_PUBLIC_SPOT_REST",
        "source_qa_success": True, "scope_stable": True, "epoch_stable": True,
        "complete_identity_scope": True, "status_accounting_ok": True,
        "identity_universe": 519, "markets_selected": 519, "technical_scanned": 519,
        "technical_pass": 519, "technical_warmup": 0, "technical_failed": 0,
        "orders_sent": 0, "notifications_sent": 0, "private_strategy_evaluated": 0,
        "live_al_claim": False, "utc_closed_epoch_1h_ms": epoch,
        "scope_digest_sha256": "a" * 64, "receipt_key": "FIXTURE|519",
        "public_runner": {"repository": "gokaydonmez39-jpg/xray-519-source-qa",
                          "run_id": "12345", "run_attempt": "1"},
        "results": rows,
    }
    bridge = {
        "schema": "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1",
        "source_receipt_sha256": hashlib.sha256(canon(receipt)).hexdigest(),
        "source_receipt_key": receipt["receipt_key"],
        "scope_digest_sha256": receipt["scope_digest_sha256"],
        "utc_closed_epoch_1h_ms": epoch, "identity_universe": 519,
        "raw_prefilter_symbols": 0, "exported_symbols": 0, "deferred_symbols": {},
        "orders_sent": 0, "notifications_sent": 0, "private_strategy_evaluated": 0,
        "live_al_claim": False
    }
    return gzip.compress(canon(receipt), mtime=0), gzip.compress(canon(bridge), mtime=0)


class SourcePreflightTests(unittest.TestCase):
    def git(self, where, *args):
        return subprocess.run(["git", *args], cwd=where, check=True,
                              capture_output=True, text=True).stdout.strip()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote, self.work, self.peer = root / "remote.git", root / "work", root / "peer"
        self.git(root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(root, "clone", str(self.remote), str(self.work))
        for loc in (self.work,):
            self.git(loc, "config", "user.name", "test")
            self.git(loc, "config", "user.email", "test@example.invalid")
        (self.work / "research_519.py").write_text("original source")
        (self.work / ".github/workflows").mkdir(parents=True)
        (self.work / ".github/workflows/hourly-519-public-source.yml").write_text("original workflow")
        self.git(self.work, "add", ".")
        self.git(self.work, "commit", "-m", "base")
        self.git(self.work, "push", "origin", "main")
        self.git(root, "clone", str(self.remote), str(self.peer))
        self.git(self.peer, "config", "user.name", "peer")
        self.git(self.peer, "config", "user.email", "peer@example.invalid")
        self.receipt = "receipts/2026/10/31/20261031T1800Z-n519.json.gz"
        self.bridge = self.receipt.replace("receipts/", "bridges/")

    def advance(self, files):
        for rel, data in files.items():
            f = self.peer / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        self.git(self.peer, "add", ".")
        self.git(self.peer, "commit", "-m", "advance")
        self.git(self.peer, "push", "origin", "main")
        self.git(self.work, "fetch", "origin", "main")

    def check(self, mode="519", stamp=STAMP):
        original = Path.cwd()
        try:
            os.chdir(self.work)
            return p.assess(mode, stamp, "HEAD", "origin/main")
        finally:
            os.chdir(original)

    def test_clean_head_allows_normal_scan(self):
        self.assertEqual(self.check(), p.ALLOW_SCAN)

    def test_published_pair_on_advanced_head_is_noop(self):
        a, b = evidence()
        self.advance({self.receipt: a, self.bridge: b})
        self.assertEqual(self.check(), p.ALREADY_PUBLISHED)
        self.assertNotIn(self.receipt, self.git(self.work, "ls-tree", "-r", "--name-only", "HEAD"))

    def test_advanced_head_without_pair_is_blocked(self):
        self.advance({"ops/release-note.txt": b"notes"})
        with self.assertRaisesRegex(p.PreflightBlocked, "STALE_HEAD_WITHOUT_VALID_EPOCH"):
            self.check()

    def test_source_modified_while_pair_published_is_blocked(self):
        a, b = evidence()
        self.advance({self.receipt: a, self.bridge: b, "research_519.py": b"changed source"})
        with self.assertRaisesRegex(p.PreflightBlocked, "SOURCE_CHANGED"):
            self.check()

    def test_only_receipt_published_is_blocked(self):
        a, _ = evidence()
        self.advance({self.receipt: a})
        with self.assertRaisesRegex(p.PreflightBlocked, "PAIR_INCOMPLETE"):
            self.check()

    def test_corrupted_bridge_blocks_noop(self):
        a, _ = evidence()
        self.advance({self.receipt: a, self.bridge: b"not gzip"})
        with self.assertRaisesRegex(p.PreflightBlocked, "INVALID_PUBLISHED_EVIDENCE"):
            self.check()

    def test_epoch_mismatch_blocks_noop(self):
        a, b = evidence("20261031T1700Z")
        self.advance({self.receipt: a, self.bridge: b})
        with self.assertRaisesRegex(p.PreflightBlocked, "EPOCH_MISMATCH"):
            self.check()

    def test_receipt_bridge_cross_hash_mismatch_blocks_noop(self):
        a, b = evidence()
        doc = json.loads(gzip.decompress(b))
        doc["source_receipt_sha256"] = "0" * 64
        self.advance({self.receipt: a, self.bridge: gzip.compress(canon(doc), mtime=0)})
        with self.assertRaisesRegex(p.PreflightBlocked, "PAIR_HASH_MISMATCH"):
            self.check()

    def test_non_519_stale_head_still_blocks(self):
        a, b = evidence()
        self.advance({self.receipt: a, self.bridge: b})
        with self.assertRaisesRegex(p.PreflightBlocked, "STALE_HEAD_NON_519"):
            self.check(mode="250")

    def test_non_519_clean_head_allows_scan(self):
        self.assertEqual(self.check(mode="250"), p.ALLOW_SCAN)

    def test_workflow_changed_while_pair_published_is_blocked(self):
        a, b = evidence()
        self.advance({self.receipt: a, self.bridge: b,
                      ".github/workflows/hourly-519-public-source.yml": b"different workflow"})
        with self.assertRaisesRegex(p.PreflightBlocked, "SOURCE_CHANGED"):
            self.check()

    def test_invalid_stamp_rejected(self):
        with self.assertRaisesRegex(p.PreflightBlocked, "INVALID_STAMP"):
            self.check(stamp="../../../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
