"""Real archived Nov-06 source pair: read-only regression, NOT live/current acceptance.

The files were created and SHA-read back by the official public workflow.
Tests never re-run the scanner, write historical epochs or authorize alerts.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import unittest

from ops.evidence_ref_pair_audit import PairRejected, audit_pair

ROOT = Path(__file__).resolve().parent.parent
RECEIPT = "receipts/2026/11/06/20261106T1300Z-n518.json.gz"
BRIDGE = "bridges/2026/11/06/20261106T1300Z-n518.json.gz"


class ArchivedRealPublicEvidenceAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.public_receipt = (ROOT / RECEIPT).read_bytes()
        cls.public_bridge = (ROOT / BRIDGE).read_bytes()

    def test_real_archived_source_pair_local_sha_and_scope(self):
        result = audit_pair(self.public_receipt, self.public_bridge,
                            RECEIPT, BRIDGE)
        self.assertEqual(result["status"],
                         "PAIR_LOCAL_SOURCE_AND_SCOPE_SHA_PASS_NOT_REMOTE")
        self.assertEqual(result["identity_symbols"], 518)
        self.assertEqual(result["ready"] + result["deferred"], 518)
        self.assertEqual(result["orders_sent"], 0)
        self.assertEqual(result["notifications_sent"], 0)
        self.assertFalse(result["full_final_start"])
        self.assertEqual(len(result["source_sha256"]), 64)

    def test_real_archived_source_digest_tampering_is_refused(self):
        receipt = json.loads(gzip.decompress(self.public_receipt))
        receipt["source_receipt_sha256"] = "0" * 64
        tampered = gzip.compress(json.dumps(
            receipt, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode(), mtime=0)
        with self.assertRaisesRegex(PairRejected,
                                    "SOURCE_RECEIPT_BRIDGE_SHA_MISMATCH"):
            audit_pair(tampered, self.public_bridge, RECEIPT, BRIDGE)

    def test_real_archived_bridge_profile_tampering_is_refused(self):
        bridge = json.loads(gzip.decompress(self.public_bridge))
        bridge["transport_profile"] = "PREFILTER_V1"
        tampered = gzip.compress(json.dumps(
            bridge, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode(), mtime=0)
        with self.assertRaisesRegex(PairRejected,
                                    "BRIDGE_SOURCE_OR_SAFETY_MISMATCH"):
            audit_pair(self.public_receipt, tampered, RECEIPT, BRIDGE)

    def test_real_archived_no_historical_relabel(self):
        with self.assertRaisesRegex(PairRejected,
                                    "PAIR_FILENAME_EPOCH_NOT_SAME_SOURCE"):
            audit_pair(self.public_receipt, self.public_bridge,
                       RECEIPT.replace("20261106T1300Z", "20261106T1200Z"),
                       BRIDGE)


if __name__ == "__main__":
    unittest.main()
