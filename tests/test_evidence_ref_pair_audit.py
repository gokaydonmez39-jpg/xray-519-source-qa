"""Offline negative/positive provenance tests; all data is synthetic only."""
from __future__ import annotations

import gzip
import json
import unittest

from evidence_ref_fixture import fixture_pair
from ops.evidence_ref_pair_audit import PairRejected, audit_pair


def encoded(value):
    return gzip.compress(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode(), mtime=0
    )


class PublicPairAuditTests(unittest.TestCase):
    def setUp(self):
        self.paths, self.receipt, self.bridge, self.pub, self.br = fixture_pair()

    def check(self, receipt=None, bridge=None, paths=None):
        paths = paths if paths is not None else self.paths
        return audit_pair(
            receipt if receipt is not None else self.receipt,
            bridge if bridge is not None else self.bridge,
            paths[0], paths[1])

    def test_positive_pair_reconciles_all_518_symbols(self):
        result = self.check()
        self.assertEqual(result["status"],
                         "PAIR_LOCAL_SOURCE_AND_SCOPE_SHA_PASS_NOT_REMOTE")
        self.assertEqual(result["identity_symbols"], 518)
        self.assertEqual(result["ready"], 518)
        self.assertEqual(result["deferred"], 0)
        self.assertEqual(result["orders_sent"], 0)
        self.assertFalse(result["full_final_start"])

    def test_modified_source_sha_fails_before_remote(self):
        self.pub["source_receipt_sha256"] = "0" * 64
        with self.assertRaisesRegex(PairRejected,
                                    "SOURCE_RECEIPT_BRIDGE_SHA_MISMATCH"):
            self.check(receipt=encoded(self.pub))

    def test_modified_bridge_sha_fails_before_remote(self):
        self.br["source_receipt_sha256"] = "f" * 64
        with self.assertRaisesRegex(PairRejected,
                                    "SOURCE_RECEIPT_BRIDGE_SHA_MISMATCH"):
            self.check(bridge=encoded(self.br))

    def test_wrong_utc_hour_path_fails_before_remote(self):
        filename = self.paths[0].replace("1300Z", "1400Z")
        if filename == self.paths[0]:
            filename = self.paths[0].replace("00Z-n518", "01Z-n518")
        with self.assertRaisesRegex(PairRejected,
                                    "PAIR_FILENAME_EPOCH_NOT_SAME_SOURCE"):
            self.check(paths=(filename, self.paths[1]))

    def test_missing_bridge_symbol_fails_before_remote(self):
        self.br["markets"].pop("XR0000USDT")
        with self.assertRaisesRegex(PairRejected,
                                    "BRIDGE_FULL_IDENTITY_NOT_ACCOUNTED"):
            self.check(bridge=encoded(self.br))

    def test_unsafe_original_order_fails_before_remote(self):
        self.pub["orders_sent"] = 1
        with self.assertRaises(PairRejected):
            self.check(receipt=encoded(self.pub))

    def test_public_runner_mismatch_fails_before_remote(self):
        self.pub["public_runner"]["repository"] = "untrusted/example"
        with self.assertRaisesRegex(PairRejected,
                                    "PUBLIC_RUNNER_PROVENANCE_MISSING"):
            self.check(receipt=encoded(self.pub))

    def test_broken_compressed_stream_fails_before_remote(self):
        with self.assertRaisesRegex(PairRejected,
                                    "MALFORMED_COMPRESSED_EVIDENCE"):
            self.check(bridge=b"not-gzip")

    def test_public_bridge_scope_mismatch_fails(self):
        self.br["scope_digest_sha256"] = "0" * 64
        with self.assertRaisesRegex(PairRejected,
                                    "SOURCE_SCOPE_SHA_MISMATCH"):
            self.check(bridge=encoded(self.br))

    def test_deferred_reason_is_mandatory(self):
        self.br["deferred_symbols"]["XR0000USDT"] = ""
        self.br["markets"].pop("XR0000USDT")
        self.br["exported_symbols"] = 517
        self.br["transport_ready_count"] = 517
        self.br["transport_deferred_count"] = 1
        with self.assertRaisesRegex(PairRejected,
                                    "BRIDGE_DEFERRED_REASON_MISSING"):
            self.check(bridge=encoded(self.br))

    def test_deferred_scope_is_valid_when_accounted(self):
        self.br["deferred_symbols"]["XR0000USDT"] = "SOURCE_FRAME_NOT_PASS"
        self.br["markets"].pop("XR0000USDT")
        self.br["exported_symbols"] = 517
        self.br["transport_ready_count"] = 517
        self.br["transport_deferred_count"] = 1
        result = self.check(bridge=encoded(self.br))
        self.assertEqual(result["ready"], 517)
        self.assertEqual(result["deferred"], 1)


if __name__ == "__main__":
    unittest.main()
