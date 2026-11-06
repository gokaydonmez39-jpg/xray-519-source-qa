"""No-network tests for bounded CORE18 source-log attestation."""
import copy
import hashlib
import json
import unittest

import research_519 as research
from ops.core18_compact_log import CORE18, build
from test_source import Provider


def sample():
    # Entirely synthetic fixtures; never labeled as live source acceptance.
    report = research.scan(Provider(18))
    if len(report["results"]) != 18:
        raise AssertionError("BAD_OFFLINE_FIXTURE")
    template = report["results"][0]
    names = list(CORE18) + [f"ZZZ{i:04d}USDT" for i in range(500)]
    report["results"] = []
    for symbol in names:
        row = copy.deepcopy(template)
        row["symbol"] = symbol
        report["results"].append(row)
    report.update(
        identity_universe=518, markets_selected=518,
        technical_scanned=518, technical_frames_requested=1554,
        technical_pass=518, technical_warmup=0, technical_failed=0,
        source_qa_success=True, complete_identity_scope=True,
        scope_stable=True, epoch_stable=True, orders_sent=0,
        notifications_sent=0,
    )
    return report


def raw(report):
    return json.dumps(
        report, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":")
    ).encode("utf-8")


class Core18CompactInputTests(unittest.TestCase):
    def test_exact_18_raw_source_rows_with_no_execution(self):
        d = sample()
        result = build(d, raw(d))
        self.assertEqual(result["status"], "PASS_18OF18_SOURCE_INPUTS_ONLY")
        self.assertEqual(result["record_count"], 18)
        self.assertEqual([r["symbol"] for r in result["records"]], list(CORE18))
        self.assertEqual(result["source_sha256"], hashlib.sha256(raw(d)).hexdigest())
        self.assertEqual(result["orders_sent"], 0)
        self.assertEqual(result["notifications_sent"], 0)
        self.assertFalse(result["full_final_start"])
        self.assertTrue(result["research_only"])
        self.assertNotIn("AL", result["status"])
        for r in result["records"]:
            self.assertGreater(r["ema20_4h_previous"], 0)
            self.assertLessEqual(r["last10_low_1h"], r["last_closed_price"])
            self.assertGreaterEqual(r["spread_bp"], 0)

    def test_raw_mutation_fails_closed(self):
        d = sample()
        self.assertEqual(build(d, raw(d) + b"x")["reason"],
                         "SOURCE_RAW_BYTES_NOT_CANONICAL")

    def test_wrong_raw_type_fails_closed(self):
        d = sample()
        self.assertEqual(build(d, None)["reason"], "SOURCE_RAW_BYTES_REQUIRED")

    def test_missing_core_symbol_fails_closed(self):
        d = sample()
        d["results"][0]["symbol"] = "ZZZ0500USDT"
        self.assertEqual(build(d, raw(d))["reason"], "CORE18_SOURCE_FRAME_NOT_READY")

    def test_stale_core_ticker_fails_closed(self):
        d = sample()
        d["results"][0]["liquidity_snapshot"]["ticker_within_120s"] = False
        self.assertEqual(build(d, raw(d))["reason"], "CORE18_TICKER_NOT_FRESH")

    def test_ema_ambiguity_fails_closed(self):
        d = sample()
        d["results"][0]["technical"]["ema20_4h"] += 1
        self.assertEqual(build(d, raw(d))["reason"], "CORE18_EMA_RECURRENCE_MISMATCH")

    def test_impossible_stop_window_fails_closed(self):
        d = sample()
        t = d["results"][0]["technical"]
        t["last10_low_1h"] = t["last_closed_price"] + 1
        self.assertEqual(build(d, raw(d))["reason"],
                         "CORE18_STOP_WINDOW_CONTRADICTION")

    def test_wrong_h1_epoch_fails_closed(self):
        d = sample()
        d["results"][0]["technical"]["asof_closed_utc_ms"]["1h"] += 3600000
        self.assertEqual(build(d, raw(d))["reason"], "CORE18_BAR_ASOF_MISMATCH")


if __name__ == "__main__":
    unittest.main()
