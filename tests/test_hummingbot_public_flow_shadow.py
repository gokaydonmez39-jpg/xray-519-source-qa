"""Deterministic offline tests: Hummingbot-method public flow, NO_ORDER."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from ops.hummingbot_public_flow_shadow import FRAMES, SourceHold, main, read_gzip, summarize


class FlowShadowTests(unittest.TestCase):
    H = 1_794_074_399_999  # synthetic 2026-11-07 17:59:59.999Z

    def fixture(self, *, taker_fraction=0.75, zero=False, ready=1, deferred=400):
        epoch = self.H
        frames = {}
        for tf, (period, count) in FRAMES.items():
            expected = ((epoch + 1) // period) * period - 1
            frames[tf] = []
            for i in range(count):
                start = expected - (count - 1 - i) * period - period + 1
                q = 0.0 if zero else 100.0
                frames[tf].append({
                    "open_ms": start, "close_ms": start + period - 1,
                    "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.0,
                    "base_volume": 0.0 if zero else 10.0,
                    "quote_volume": q, "trades": 0 if zero else 10,
                    "taker_quote": q * taker_fraction,
                })
        markets = {
            f"ASSET{i}USDT": {
                "frames": copy.deepcopy(frames),
                "liquidity_snapshot": {
                    "ticker_within_120s": True,
                    "rolling_24h_quote_usdt": 35000.0,
                    "spread_bp": 1.1,
                },
            }
            for i in range(ready)
        }
        return {
            "schema": "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1",
            "transport_profile": "FULL_QUALITY_READY_V2",
            "source": "BINANCE_PUBLIC_SPOT_REST",
            "disposition": "PUBLIC_DATA_ONLY_PRIVATE_STRATEGY_NOT_EVALUATED",
            "orders_sent": 0, "notifications_sent": 0,
            "private_strategy_evaluated": 0, "live_al_claim": False,
            "source_receipt_sha256": "1" * 64,
            "scope_digest_sha256": "2" * 64,
            "identity_universe": ready + deferred,
            "transport_ready_count": ready,
            "transport_deferred_count": deferred,
            "deferred_symbols": {f"DEFER{i}USDT": "WARMUP" for i in range(deferred)},
            "markets": markets,
            "utc_closed_epoch_1h_ms": epoch,
            "source_start_server_ms": epoch + 1 + 300000,
        }

    def test_positive_flow_sign_and_no_execution(self):
        result = summarize(self.fixture(), bridge_file_sha256="3" * 64)
        self.assertEqual(result["taker_flow_20h_counts"], {"TAKER_BUY_DOMINANT": 1})
        self.assertEqual(result["taker_flow_20h_net_quote_usdt"], 1000.0)
        self.assertEqual(result["taker_flow_20h_total_quote_usdt"], 2000.0)
        self.assertEqual(result["source_receipt_sha256"], "1" * 64)
        for key in ("orders_permitted", "notifications_permitted", "full_final_start",
                    "al_authority", "hummingbot_runtime_started"):
            self.assertIs(result[key], False)
        self.assertEqual(result["network_requests"], 0)
        self.assertNotIn("ASSET0USDT", json.dumps(result))

    def test_negative_and_balanced_flow(self):
        negative = summarize(self.fixture(taker_fraction=0.2), bridge_file_sha256="3" * 64)
        neutral = summarize(self.fixture(taker_fraction=0.5), bridge_file_sha256="3" * 64)
        self.assertEqual(negative["taker_flow_20h_counts"], {"TAKER_SELL_DOMINANT": 1})
        self.assertEqual(negative["taker_flow_20h_net_quote_usdt"], -1200.0)
        self.assertEqual(neutral["taker_flow_20h_counts"], {"NEAR_BALANCED": 1})
        self.assertEqual(neutral["taker_flow_20h_net_quote_usdt"], 0)

    def test_zero_quote_unknown_not_false_signal(self):
        result = summarize(self.fixture(zero=True), bridge_file_sha256="3" * 64)
        self.assertEqual(result["taker_flow_20h_counts"], {"UNKNOWN_ZERO_QUOTE": 1})
        self.assertEqual(result["taker_flow_20h_net_quote_usdt"], 0)

    def test_dynamic_scope_and_cumulative_math(self):
        out = summarize(self.fixture(ready=2, deferred=399), bridge_file_sha256="3" * 64)
        self.assertEqual((out["identity_symbols"], out["ready_symbols"], out["deferred_symbols"]),
                         (401, 2, 399))
        self.assertEqual(out["taker_flow_20h_counts"]["TAKER_BUY_DOMINANT"], 2)

    def test_future_duplicate_or_missing_candles_are_hold(self):
        for change in ("future", "duplicate", "missing"):
            with self.subTest(change=change):
                doc = self.fixture()
                frames = doc["markets"]["ASSET0USDT"]["frames"]
                if change == "future":
                    frames["1h"][-1]["close_ms"] += 1
                elif change == "duplicate":
                    frames["1h"][-2] = copy.deepcopy(frames["1h"][-3])
                else:
                    frames["4h"].pop()
                with self.assertRaises(SourceHold):
                    summarize(doc, bridge_file_sha256="3" * 64)

    def test_invalid_taker_nan_negative_and_boolean_rejected(self):
        for key, value in (("quote_volume", -1.), ("taker_quote", 101.),
                           ("taker_quote", math.nan), ("quote_volume", True)):
            with self.subTest(key=key, value=value):
                doc = self.fixture()
                doc["markets"]["ASSET0USDT"]["frames"]["1h"][-1][key] = value
                with self.assertRaises(SourceHold):
                    summarize(doc, bridge_file_sha256="3" * 64)

    def test_invalid_source_provenance_or_execution_rejected(self):
        for key, value in (("orders_sent", 1), ("live_al_claim", True),
                           ("scope_digest_sha256", "bad"),
                           ("transport_profile", "SOURCE_ONLY"),
                           ("transport_deferred_count", 399)):
            with self.subTest(key=key):
                doc = self.fixture()
                doc[key] = value
                with self.assertRaises(SourceHold):
                    summarize(doc, bridge_file_sha256="3" * 64)

    def test_gzip_roundtrip_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public_bridge.json.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(json.dumps(self.fixture()).encode("utf-8"))
            result = read_gzip(path)
            self.assertEqual(result["bridge_file_sha256"],
                             hashlib.sha256(path.read_bytes()).hexdigest())

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(b'{"schema":"bad","schema":"duplicate"}')
            with self.assertRaises(SourceHold):
                read_gzip(path)

    def test_missing_bridge_fail_closed(self):
        self.assertEqual(main(["module", "/missing/no-public-bridge.gz"]), 2)


    def test_immutable_real_bridge_20261107_1800z(self):
        """Real source readback from already committed public blob; no Binance call."""
        root = Path(__file__).resolve().parents[1]
        path = root / "bridges/2026/11/07/20261107T1800Z-n518.json.gz"
        self.assertTrue(path.is_file(), "LIVE_BRIDGE_FIXTURE_MISSING")
        output = read_gzip(path)
        self.assertEqual(output["identity_symbols"], 518)
        self.assertEqual(output["ready_symbols"], 469)
        self.assertEqual(output["deferred_symbols"], 49)
        self.assertEqual(sum(output["taker_flow_20h_counts"].values()), 469)
        self.assertTrue(output["complete_bar_validation"])
        self.assertFalse(output["al_authority"])
        self.assertFalse(output["orders_permitted"])
        self.assertEqual(output["bridge_file_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
