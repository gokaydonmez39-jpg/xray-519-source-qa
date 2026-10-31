"""Adversarial and positive research-only checks, no external model or market calls."""
import gzip
import hashlib
import json
import math
import unittest
from pathlib import Path
from research_lab.pit_audit import (
    GateError, validate_rows, temporal_folds,
    fit_train_normalizer, score_shadow_forecasts, prefix_causality,
)

HOUR = 3_600_000
T0 = 1_800_000_000_000

def row(i, symbol="BTCUSDT", prediction=None):
    decision = T0 + i * HOUR
    close = 100.0 + i * 0.2
    return {
        "symbol": symbol,
        "decision_ms": decision,
        "feature_available_ms": decision - 1,
        "last_closed_ms": decision - 1,
        "label_close_ms": decision + HOUR - 1,
        "label_available_ms": decision + HOUR,
        "model_fit_cutoff_ms": T0 - 2 * HOUR,
        "reference_close": close,
        "forecast_close": close if prediction is None else prediction,
        "realized_close": close + 0.1,
        "forecast_created_ms": decision,
        "feature_rsi": 50.0 + i / 20.0,
    }

class TestPITIntegrity(unittest.TestCase):
    def test_valid_strictly_ordered_closed_input(self):
        rows = [row(i) for i in range(15)]
        self.assertEqual(len(validate_rows(rows, asof_ms=T0 + 16*HOUR)), 15)

    def test_no_future_features_or_open_candle(self):
        for key, value in [
            ("feature_available_ms", T0+1),
            ("last_closed_ms", T0),
            ("forecast_created_ms", T0+1),
            ("model_fit_cutoff_ms", T0),
        ]:
            with self.subTest(key=key):
                bad = row(0)
                bad[key] = value
                with self.assertRaises(GateError):
                    validate_rows([bad], asof_ms=T0+HOUR)

    def test_no_future_realized_label_at_asof(self):
        with self.assertRaises(GateError):
            validate_rows([row(0)], asof_ms=T0+HOUR-1)

    def test_bad_rows_duplicates_and_bad_prices(self):
        r = row(0)
        with self.assertRaises(GateError):
            validate_rows([r,r], asof_ms=T0+HOUR)
        for key, val in [("forecast_close",math.nan),("reference_close",0),
                         ("realized_close",-1),("feature_rsi",math.inf)]:
            bad = row(0)
            bad[key] = val
            with self.subTest(key=key),self.assertRaises(GateError):
                validate_rows([bad], asof_ms=T0+HOUR)

    def test_temporal_embargo_excludes_overlapping_labels(self):
        rows = validate_rows([row(i) for i in range(12)], asof_ms=T0+14*HOUR)
        f = temporal_folds(rows, train_end_ms=T0+4*HOUR,
                           validation_end_ms=T0+8*HOUR,
                           embargo_ms=HOUR)
        self.assertEqual([x["decision_ms"] for x in f["train"]],
                         [T0+i*HOUR for i in (0,1,2)])
        self.assertEqual([x["decision_ms"] for x in f["validation"]],
                         [T0+i*HOUR for i in (5,6)])
        self.assertEqual(len(f["test"]),3)
        self.assertEqual(f["embargo_dropped"], 4)

    def test_normalizer_is_fit_only_on_train(self):
        a = row(0)
        b = row(1)
        fitted = fit_train_normalizer([a,b], "feature_rsi")
        self.assertEqual(fitted["n_train"],2)
        c=row(10)
        c["feature_rsi"]=10_000_000.0
        self.assertEqual(fit_train_normalizer([a,b],"feature_rsi"),fitted)
        self.assertNotEqual(fitted["mean"], c["feature_rsi"])

    def test_prefix_causality_detects_future_dependent_indicator(self):
        xs=[1.,2.,3.,4.,5.,6.]
        self.assertTrue(prefix_causality(xs,lambda data:[sum(data[:i+1]) for i in range(len(data))]))
        with self.assertRaises(GateError):
            prefix_causality(xs,lambda data:[max(data)]*len(data))

    def test_synthetic_external_model_never_promoted(self):
        rows=[row(i) for i in range(240)]
        result=score_shadow_forecasts(rows,asof_ms=T0+241*HOUR,
            source_sha256="a"*64,model_sha256="b"*64,synthetic_only=True,
            min_samples=200,min_distinct_epochs=200)
        self.assertTrue(result["sample_gate_pass"])
        self.assertFalse(result["promotion_allowed"])
        self.assertFalse(result["model_verified"])
        self.assertEqual(result["dataset_kind"],"SYNTHETIC_ONLY")
        self.assertGreaterEqual(result["mae_ratio"],0.0)

    def test_insufficient_history_cannot_claim_quality(self):
        result=score_shadow_forecasts([row(i) for i in range(12)],
            asof_ms=T0+13*HOUR,source_sha256="a"*64,model_sha256="b"*64,
            synthetic_only=True,min_samples=200,min_distinct_epochs=100)
        self.assertFalse(result["sample_gate_pass"])
        self.assertFalse(result["promotion_allowed"])

    def test_invalid_sha_and_false_model_origin_rejected(self):
        with self.assertRaises(GateError):
            score_shadow_forecasts([row(i) for i in range(3)],
                asof_ms=T0+5*HOUR,source_sha256="not-a-real-hash",
                model_sha256="b"*64,synthetic_only=False)

    def test_public_frozen_receipt_is_source_not_private_alpha(self):
        path = Path(__file__).resolve().parents[1] / "receipts/2026/10/31/20261031T2100Z-n519.json.gz"
        body = path.read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(),
            "5661cad86a35812c07d677a5972fb88e71d575ece1dbf3ac65ad6d1eacee1256")
        data=json.loads(gzip.decompress(body))
        self.assertEqual(data["markets_selected"],519)
        self.assertEqual((data["technical_pass"],data["technical_warmup"],data["technical_failed"]),(489,30,0))
        self.assertFalse(data["full_technical_quality"])
        self.assertEqual(data["private_strategy_evaluated"],0)
        self.assertEqual(data["orders_sent"],0)

if __name__ == "__main__":
    unittest.main()
