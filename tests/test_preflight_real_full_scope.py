"""Reproduce the real valid-n518 preflight failure. No network or source scan.

Real immutable 2026-11-06 14Z/15Z public archive bytes are read via the local
Git object database. A real historical receipt is test data, NOT a replay.
"""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import json
import os
from pathlib import Path
from unittest import TestCase, mock

from ops import source_preflight as p

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def repository_cwd():
    old = Path.cwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(old)


class RealFullTransportPreflightTests(TestCase):
    def pair(self, hour: str, mutate=None):
        stamp = "20261106T" + hour + "00Z"
        with repository_cwd():
            entries = p._tree("HEAD")
            if mutate is None:
                return p._pair("HEAD", entries, "518", stamp)
            original = p._json_gzip
            seen = 0
            def altered(blob, cap):
                nonlocal seen
                seen += 1
                result = original(blob, cap)
                if seen == 2:
                    result = dict(result)
                    mutate(result)
                return result
            with mock.patch.object(p, "_json_gzip", side_effect=altered):
                return p._pair("HEAD", entries, "518", stamp)

    def test_real_archived_14z_full_scope_is_authentic_pair(self):
        self.assertTrue(self.pair("14"))

    def test_real_archived_15z_full_scope_is_authentic_pair(self):
        self.assertTrue(self.pair("15"))

    def test_raw_prefilter_distinct_from_all_symbol_transport(self):
        with repository_cwd():
            tree = p._tree("HEAD")
            stamp = "20261106T1500Z-n518.json.gz"
            base = "2026/11/06/" + stamp
            receipt = p._json_gzip(
                p._git_blob("HEAD", tree, "receipts/" + base, p.MAX_RECEIPT),
                p.MAX_JSON,
            )
            bridge = p._json_gzip(
                p._git_blob("HEAD", tree, "bridges/" + base, p.MAX_BRIDGE),
                p.MAX_BRIDGE_RAW,
            )
            source_raw_prefilter = sum(
                row.get("raw_15m_15bp_prefilter") is True
                for row in receipt["results"]
            )
            self.assertEqual(bridge["raw_prefilter_symbols"],
                             source_raw_prefilter)
            self.assertEqual(
                bridge["exported_symbols"] + len(bridge["deferred_symbols"]),
                receipt["identity_universe"],
            )
            self.assertNotEqual(bridge["raw_prefilter_symbols"],
                                receipt["identity_universe"])

    def test_full_scope_wrong_ready_accounting_is_rejected(self):
        def corrupt(bridge):
            bridge["transport_ready_count"] = bridge["exported_symbols"] + 1
        with self.assertRaisesRegex(
            p.PreflightBlocked, "INVALID_PUBLISHED_EVIDENCE"
        ):
            self.pair("15", corrupt)

    def test_full_scope_wrong_prefilter_metric_is_rejected(self):
        def corrupt(bridge):
            bridge["raw_prefilter_symbols"] += 1
        with self.assertRaisesRegex(
            p.PreflightBlocked, "INVALID_PUBLISHED_EVIDENCE"
        ):
            self.pair("15", corrupt)

    def test_full_scope_grafted_symbol_is_rejected(self):
        def corrupt(bridge):
            keys = sorted(bridge["markets"])
            other = keys[0]
            bridge["markets"]["NOT_A_REAL_SPOT_USDT"] = bridge["markets"].pop(other)
        with self.assertRaisesRegex(
            p.PreflightBlocked, "INVALID_PUBLISHED_EVIDENCE"
        ):
            self.pair("15", corrupt)


if __name__ == "__main__":
    import unittest
    unittest.main()
