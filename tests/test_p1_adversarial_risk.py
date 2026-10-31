"""Standalone zero-network synthetic and negative contract tests."""
import copy
import math
import unittest

from research_lab.p1_adversarial_risk import (
    HOUR_MS as H, ResearchRejected, historical_membership_guard,
    cost_liquidity_stress, epoch_bridge_consistency,
)

T = 1_800_000_000_000


def membership(i=0, sym="BTCUSDT"):
    d = T + i * H
    return {"symbol": sym, "decision_ms": d,
            "membership_observed_ms": d - 60_000,
            "last_closed_ms": d - 1, "spot_usdt_at_asof": True,
            "delisted_effective_ms": None}


def quote():
    return {"decision_ms": T, "quote_observed_ms": T - 10_000,
            "bid": 99.99, "ask": 100.01,
            "bid_depth_usdt": 50_000, "ask_depth_usdt": 60_000,
            "order_notional_usdt": 1_000, "hypothetical_gross_edge_bps": 50.0}


def epoch(i):
    return {"epoch_ms": T + i * H, "universe_count": 519,
            "scanned_count": 519, "pass_count": 489,
            "warmup_count": 30, "failed_count": 0,
            "scope_sha256": "a" * 64,
            "receipt_sha256": "b" * 64, "bridge_receipt_sha256": "b" * 64}


class HistoricalUniverse(unittest.TestCase):
    def test_positive_and_no_claim(self):
        got = historical_membership_guard([membership(), membership(1)], asof_ms=T + H)
        self.assertEqual(got["records"], 2)
        self.assertFalse(got["history_authenticated"])
        self.assertFalse(got["promotion_allowed"])

    def test_future_membership_or_listing(self):
        row = membership(); row["membership_observed_ms"] = T + 1
        with self.assertRaisesRegex(ResearchRejected, "SURVIVORSHIP"):
            historical_membership_guard([row], asof_ms=T)

    def test_delisted_at_decision(self):
        row = membership(); row["delisted_effective_ms"] = T
        with self.assertRaisesRegex(ResearchRejected, "DELISTED"):
            historical_membership_guard([row], asof_ms=T)

    def test_not_spot_or_bad_symbol(self):
        for bad in (False, "YES", 1):
            row = membership(); row["spot_usdt_at_asof"] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(ResearchRejected, "NOT_SPOT"):
                historical_membership_guard([row], asof_ms=T)
        with self.assertRaisesRegex(ResearchRejected, "INVALID_SPOT_SYMBOL"):
            historical_membership_guard([membership(sym="BTCUSD")], asof_ms=T)

    def test_future_bar_and_duplicate_epoch_rejected(self):
        row = membership(); row["last_closed_ms"] = T + H - 1
        with self.assertRaisesRegex(ResearchRejected, "OPEN_OR_FUTURE"):
            historical_membership_guard([row], asof_ms=T)
        with self.assertRaisesRegex(ResearchRejected, "DUPLICATE"):
            historical_membership_guard([membership(), membership()], asof_ms=T)


class LiquidityAndFriction(unittest.TestCase):
    def test_positive_formula_and_worst_case(self):
        got = cost_liquidity_stress(quote(), roundtrip_commission_bps=20,
                                   slippage_bps_per_side=(5, 10), impact_bps=(0, 10))
        self.assertEqual(got["scenario_count"], 4)
        self.assertAlmostEqual(got["observed_spread_bps"], 2.0)
        self.assertAlmostEqual(got["worst_hypothetical_net_bps"], -2.0)
        self.assertFalse(got["trade_approved"])
        self.assertFalse(got["historical_quotes_authenticated"])

    def test_wider_spread_rejected(self):
        row = quote(); row["ask"] = 103
        with self.assertRaisesRegex(ResearchRejected, "SPREAD_EXCEEDS"):
            cost_liquidity_stress(row, roundtrip_commission_bps=20)

    def test_low_liquidity_rejected(self):
        row = quote(); row["bid_depth_usdt"] = 999
        with self.assertRaisesRegex(ResearchRejected, "LOW_LIQUIDITY"):
            cost_liquidity_stress(row, roundtrip_commission_bps=20)

    def test_future_and_stale_quote_rejected(self):
        for observed in (T + 1, T - 300_001):
            row = quote(); row["quote_observed_ms"] = observed
            with self.subTest(observed=observed), self.assertRaisesRegex(ResearchRejected, "FUTURE_OR_STALE"):
                cost_liquidity_stress(row, roundtrip_commission_bps=20)

    def test_impossible_hypothetical_edge_denied(self):
        row = quote(); row["hypothetical_gross_edge_bps"] = 10_001.0
        with self.assertRaisesRegex(ResearchRejected, "UNBOUNDED_HYPOTHETICAL_EDGE"):
            cost_liquidity_stress(row, roundtrip_commission_bps=20)

    def test_spread_commission_and_slippage_monotonicity(self):
        low = cost_liquidity_stress(quote(), roundtrip_commission_bps=10,
                                    slippage_bps_per_side=(1,), impact_bps=(0,))
        high = cost_liquidity_stress(quote(), roundtrip_commission_bps=50,
                                     slippage_bps_per_side=(15,), impact_bps=(30,))
        self.assertGreater(low["worst_hypothetical_net_bps"], high["worst_hypothetical_net_bps"])

    def test_bad_parameters_fail_closed(self):
        for bad in (True, math.nan, -1, 500):
            with self.subTest(bad=bad), self.assertRaisesRegex(ResearchRejected, "INVALID_COST_POLICY"):
                cost_liquidity_stress(quote(), roundtrip_commission_bps=bad)
        with self.assertRaisesRegex(ResearchRejected, "INVALID_STRESS_GRID"):
            cost_liquidity_stress(quote(), roundtrip_commission_bps=20, slippage_bps_per_side=(math.inf,))

    def test_oversized_numeric_rejected(self):
        row = quote(); row["bid_depth_usdt"] = 10**1000
        with self.assertRaisesRegex(ResearchRejected, "INVALID_QUOTE_NUMERIC"):
            cost_liquidity_stress(row, roundtrip_commission_bps=20)


class EpochEvidence(unittest.TestCase):
    def test_positive_accounting_not_real_success(self):
        got = epoch_bridge_consistency([epoch(0), epoch(1), epoch(2)])
        self.assertEqual(got["structurally_consecutive_epochs"], 3)
        self.assertFalse(got["real_epochs_authenticated"])
        self.assertFalse(got["public_source_acceptance"])

    def test_duplicate_gap_and_reversed_epoch(self):
        for arr in ([epoch(0), epoch(0)], [epoch(0), epoch(2)], [epoch(1), epoch(0)]):
            with self.subTest(arr=arr), self.assertRaisesRegex(ResearchRejected, "DUPLICATE_GAP"):
                epoch_bridge_consistency(arr)

    def test_pair_hash_drift_rejected(self):
        row = epoch(0); row["bridge_receipt_sha256"] = "c" * 64
        with self.assertRaisesRegex(ResearchRejected, "SOURCE_BRIDGE_HASH_DRIFT"):
            epoch_bridge_consistency([row])

    def test_scope_drift_rejected(self):
        arr = [epoch(0), epoch(1)]; arr[1]["scope_sha256"] = "c" * 64
        with self.assertRaisesRegex(ResearchRejected, "SOURCE_SCOPE_DRIFT"):
            epoch_bridge_consistency(arr)

    def test_universe_and_accounting_rejected(self):
        row = epoch(0); row["universe_count"] = 518
        with self.assertRaisesRegex(ResearchRejected, "UNIVERSE_519_DRIFT"):
            epoch_bridge_consistency([row])
        row = epoch(0); row["warmup_count"] = 31
        with self.assertRaisesRegex(ResearchRejected, "ACCOUNTING_MISMATCH"):
            epoch_bridge_consistency([row])

    def test_failure_fails_closed(self):
        row = epoch(0); row.update({"failed_count": 1, "pass_count": 488})
        with self.assertRaisesRegex(ResearchRejected, "TECHNICAL_FAILURE"):
            epoch_bridge_consistency([row])

    def test_wrong_hash_and_bool_denied(self):
        row = epoch(0); row["receipt_sha256"] = "bad"
        with self.assertRaisesRegex(ResearchRejected, "INVALID_SOURCE_DIGEST"):
            epoch_bridge_consistency([row])
        row = epoch(0); row["scanned_count"] = True
        with self.assertRaisesRegex(ResearchRejected, "INVALID_EPOCH_COUNTS"):
            epoch_bridge_consistency([row])

    def test_dont_allow_change_519_contract(self):
        with self.assertRaisesRegex(ResearchRejected, "UNIVERSE_CONTRACT_CHANGED"):
            epoch_bridge_consistency([epoch(0)], expected_universe=520)


if __name__ == "__main__":
    unittest.main()
