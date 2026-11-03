"""Positive and adversarial offline tests for optional research adapters."""
import copy
import math
import unittest
from research_lab.external_sources_shadow import (
    ShadowBlocked, cost_sensitivity_shadow, dex_shadow,
    validate_contract_manifest,
)

SHA = "a" * 64
ADDR = "0x" + "1" * 40
RECORD = {"symbol": "TESTUSDT", "network": "ethereum", "token_address": ADDR}


def fetch(_chain, _address):
    return {"id": ADDR, "chain": "ethereum", "summary": {
        "price_usd": 1.5, "liquidity_usd": 25000,
        "24h": {"volume_usd": 37000}}}


def trade():
    return {"symbol": "ETHUSDT", "entry_ms": 1000, "exit_ms": 2000,
            "feature_available_ms": 999, "entry_ask": 100.0,
            "exit_bid": 105.0, "btc_entry_ask": 200.0, "btc_exit_bid": 210.0}


class TestDexShadow(unittest.TestCase):
    def test_offline_plan_never_calls_fetcher(self):
        out = dex_shadow([RECORD], source_sha256=SHA)
        self.assertEqual(out["records"][0]["status"], "PLAN_ONLY_NO_NETWORK")
        self.assertFalse(out["promotion_allowed"])
        self.assertEqual(out["orders_sent"], 0)

    def test_explicit_opt_in_fetch_with_injected_fake(self):
        out = dex_shadow([RECORD], source_sha256=SHA,
                         allow_public_rest=True, fetcher=fetch)
        self.assertEqual(out["records"][0]["price_usd"], 1.5)
        self.assertFalse(out["records"][0]["contract_mapping_authenticated"])
        self.assertFalse(out["promotion_allowed"])

    def test_fetch_without_authorization_rejected(self):
        with self.assertRaisesRegex(ShadowBlocked, "NETWORK_NOT_AUTHORIZED"):
            dex_shadow([RECORD], source_sha256=SHA, fetcher=fetch)

    def test_cannot_inject_path_or_pseudo_chain(self):
        for key, value in (("network", "ethereum/../../orders"),
                           ("token_address", "0x123/../../api/order"),
                           ("symbol", "TESTUSDT/ETHUSDT")):
            row = {**RECORD, key: value}
            with self.subTest(key=key), self.assertRaises(ShadowBlocked):
                validate_contract_manifest([row], SHA)

    def test_ambiguous_or_duplicate_mapping_fails(self):
        with self.assertRaisesRegex(ShadowBlocked, "DUPLICATE"):
            validate_contract_manifest([RECORD, RECORD], SHA)
        with self.assertRaises(ShadowBlocked):
            validate_contract_manifest([RECORD] * 11, SHA)

    def test_bad_sha_fails(self):
        with self.assertRaises(ShadowBlocked):
            dex_shadow([RECORD], source_sha256="not-a-real-sha")

    def test_wrong_address_or_network_is_rejected(self):
        for key, value in (("id", "0x" + "2" * 40), ("chain", "bsc")):
            bad = fetch("", "")
            bad[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ShadowBlocked, "MISMATCH"):
                dex_shadow([RECORD], source_sha256=SHA, allow_public_rest=True,
                           fetcher=lambda _a, _b: bad)

    def test_missing_and_nan_metrics_rejected(self):
        for metric in (math.nan, -1.0, None, True):
            bad = fetch("", "")
            bad["summary"]["liquidity_usd"] = metric
            with self.subTest(metric=metric), self.assertRaises(ShadowBlocked):
                dex_shadow([RECORD], source_sha256=SHA, allow_public_rest=True,
                           fetcher=lambda _a, _b: bad)


class TestOfflineCostStress(unittest.TestCase):
    def test_costs_reduce_returns_and_never_authorize_live(self):
        out = cost_sensitivity_shadow([trade()])
        scenarios = out["scenarios"]
        self.assertEqual(len(scenarios), 9)
        self.assertGreater(scenarios[0]["mean_model_return"], scenarios[-1]["mean_model_return"])
        self.assertEqual(out["orders_sent"], 0)
        self.assertFalse(out["oos_verified"])
        self.assertFalse(out["production_promoted"])

    def test_matched_btc_baseline_equals_same_price_path(self):
        out = cost_sensitivity_shadow([trade()])
        self.assertTrue(all(abs(v["delta_vs_btc_proxy"]) < 1e-12 for v in out["scenarios"]))

    def test_lookahead_and_duplicate_rejected(self):
        bad = {**trade(), "feature_available_ms": 1001}
        with self.assertRaisesRegex(ShadowBlocked, "LOOKAHEAD"):
            cost_sensitivity_shadow([bad])
        with self.assertRaisesRegex(ShadowBlocked, "DUPLICATE"):
            cost_sensitivity_shadow([trade(), copy.deepcopy(trade())])

    def test_nonfinite_cost_or_price_rejected(self):
        with self.assertRaisesRegex(ShadowBlocked, "INVALID_COST"):
            cost_sensitivity_shadow([trade()], commission_bps=(math.nan,))
        bad = {**trade(), "exit_bid": math.inf}
        with self.assertRaisesRegex(ShadowBlocked, "BAD_PRICE"):
            cost_sensitivity_shadow([bad])

    def test_cannot_inject_unreviewed_trades(self):
        bad = {**trade(), "side": "BUY"}
        with self.assertRaisesRegex(ShadowBlocked, "SCHEMA"):
            cost_sensitivity_shadow([bad])


if __name__ == "__main__":
    unittest.main()
