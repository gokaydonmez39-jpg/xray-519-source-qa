"""Positive and hostile AGIPro-inspired research method-only checks."""
from __future__ import annotations

import copy
import math
import unittest

from research_lab.agipro_research_guard import (
    HOUR_MS as H, ResearchGuardError, validate_attribution,
    purged_temporal_split, validate_unimputed_ohlcv,
    holm_research_gate, positive_gain_concentration,
)
T = 1_800_000_000_000


def attribution(i=0, sym="BTCUSDT"):
    d = T + i * H
    return {"symbol": sym, "decision_ms": d,
            "last_closed_end_ms": d - 1, "feature_available_ms": d,
            "entry_observed_ms": d + 5_000,
            "return_open_ms": d + H, "return_close_ms": d + 2*H - 1,
            "label_available_ms": d + 2*H}


def splitrow(i, sym="BTCUSDT", delay=H):
    d = T + i*H
    return {"symbol": sym, "decision_ms": d,
            "feature_available_ms": d - 1, "label_available_ms": d + delay}


def bar(i=0):
    op = T + i*H
    return {"open_ms": op, "observed_ms": op+H, "open": 100.0,
            "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 250.0, "is_synthetic": False}


class TestAttribution(unittest.TestCase):
    def test_positive_next_closed_hour_and_no_promotion(self):
        result = validate_attribution([attribution(0), attribution(1)], asof_ms=T+4*H)
        self.assertEqual(result["validated_records"], 2)
        self.assertFalse(result["promotion_allowed"])
        self.assertEqual(result["orders_sent"], 0)

    def test_reject_same_bar_return_from_closing_signal(self):
        r = attribution(); r["return_open_ms"] = T
        r["return_close_ms"] = T + H-1
        with self.assertRaisesRegex(ResearchGuardError, "SAME_BAR_RETURN_LEAK"):
            validate_attribution([r], asof_ms=T+4*H)

    def test_reject_bar_overlapping_observed_entry(self):
        r = attribution(); r["entry_observed_ms"] = T+H+1
        with self.assertRaisesRegex(ResearchGuardError, "SAME_BAR_RETURN_LEAK"):
            validate_attribution([r], asof_ms=T+4*H)

    def test_reject_future_feature_and_predecision_entry(self):
        for k, v, msg in [("feature_available_ms",T+1,"FUTURE_FEATURE"),
                          ("entry_observed_ms",T,"NO_POST_DECISION_ENTRY")]:
            r = attribution(); r[k]=v
            with self.subTest(k=k), self.assertRaisesRegex(ResearchGuardError,msg):
                validate_attribution([r], asof_ms=T+4*H)

    def test_reject_stale_bar_and_immature_labels(self):
        r=attribution(); r["last_closed_end_ms"]=T-H-1
        with self.assertRaisesRegex(ResearchGuardError,"OPEN_OR_STALE"):
            validate_attribution([r], asof_ms=T+4*H)
        with self.assertRaisesRegex(ResearchGuardError,"UNMATURED"):
            validate_attribution([attribution()], asof_ms=T+H)

    def test_reject_duplicate_unsorted_and_bool_timestamp(self):
        with self.assertRaisesRegex(ResearchGuardError,"DUPLICATE"):
            validate_attribution([attribution(), attribution()], asof_ms=T+4*H)
        with self.assertRaisesRegex(ResearchGuardError,"DUPLICATE"):
            validate_attribution([attribution(1), attribution(0)], asof_ms=T+4*H)
        r=attribution();r["decision_ms"]=True
        with self.assertRaisesRegex(ResearchGuardError,"INVALID_TIMESTAMP"):
            validate_attribution([r], asof_ms=T+4*H)


class TestPurging(unittest.TestCase):
    def test_true_purge_and_embargo_ages_labels(self):
        rows=[splitrow(i) for i in range(9)]
        result=purged_temporal_split(rows,train_end_ms=T+4*H,
                                     test_start_ms=T+6*H,embargo_ms=2*H)
        self.assertEqual([i[0] for i in result["train"]], [T+i*H for i in range(4)])
        self.assertEqual(result["purged"], [(T+4*H,"BTCUSDT")])
        self.assertEqual(len(result["between_cutoffs"]),1)
        self.assertEqual(len(result["test"]),3)
        self.assertFalse(result["promotion_allowed"])

    def test_reject_missing_train_test_or_too_small_embargo(self):
        rows=[splitrow(i) for i in range(6)]
        with self.assertRaisesRegex(ResearchGuardError,"BAD_SPLIT_POLICY"):
            purged_temporal_split(rows,train_end_ms=T+2*H,test_start_ms=T+4*H,embargo_ms=0)
        with self.assertRaisesRegex(ResearchGuardError,"MISSING_INDEPENDENT"):
            purged_temporal_split(rows,train_end_ms=T,test_start_ms=T+4*H,embargo_ms=4*H)

    def test_do_not_split_same_epoch_across_symbols(self):
        rows=[splitrow(0,"BTCUSDT"),splitrow(0,"ETHUSDT"),
              splitrow(1,"BTCUSDT"),splitrow(1,"ETHUSDT"),
              splitrow(5,"BTCUSDT"),splitrow(5,"ETHUSDT")]
        out=purged_temporal_split(rows,train_end_ms=T+H,
                                  test_start_ms=T+5*H,embargo_ms=H)
        self.assertEqual(len(out["train"]),4)
        self.assertEqual(len(out["test"]),2)
        self.assertEqual({x[0] for x in out["test"]},{T+5*H})

    def test_reject_future_features_or_unsorted(self):
        rows=[splitrow(i) for i in range(8)]
        rows[1]["feature_available_ms"]=rows[1]["decision_ms"]+1
        with self.assertRaisesRegex(ResearchGuardError,"TEMPORAL_LEAK"):
            purged_temporal_split(rows,train_end_ms=T+3*H,test_start_ms=T+5*H,embargo_ms=H)
        rows=[splitrow(1),splitrow(0),splitrow(6)]
        with self.assertRaisesRegex(ResearchGuardError,"DUPLICATE_OR_UNSORTED"):
            purged_temporal_split(rows,train_end_ms=T+2*H,test_start_ms=T+5*H,embargo_ms=H)


class TestBars(unittest.TestCase):
    def test_valid_three_contiguous_unimputed_closed_bars(self):
        out=validate_unimputed_ohlcv([bar(i) for i in range(3)])
        self.assertEqual(out["closed_unimputed_bars"],3)
        self.assertEqual(out["imputed"],0)

    def test_missing_or_duplicate_bar_is_rejected_not_forward_filled(self):
        for xs in [[bar(0),bar(2)],[bar(0),bar(0)]]:
            with self.assertRaisesRegex(ResearchGuardError,"GAP_OR_DUPLICATE"):
                validate_unimputed_ohlcv(xs)

    def test_synthetic_and_unclosed_are_rejected(self):
        r=bar();r["is_synthetic"]=True
        with self.assertRaisesRegex(ResearchGuardError,"SYNTHETIC"):
            validate_unimputed_ohlcv([r])
        r=bar();r["observed_ms"]=T+H-1
        with self.assertRaisesRegex(ResearchGuardError,"UNFINISHED"):
            validate_unimputed_ohlcv([r])

    def test_bad_ohlc_zero_volume_and_nan_rejected(self):
        for key,v in [("high",98),("volume",0),("close",math.nan)]:
            r=bar();r[key]=v
            with self.subTest(key=key),self.assertRaises(ResearchGuardError):
                validate_unimputed_ohlcv([r])


class TestStatistics(unittest.TestCase):
    def test_holm_rejections_and_no_promotion(self):
        r=holm_research_gate([0.01,0.03,0.04],declared_trials=3)
        self.assertEqual(r["holm_rejections"],[True,False,False])
        self.assertFalse(r["promotion_allowed"])

    def test_reject_missing_trial_count_and_invalid_p(self):
        with self.assertRaisesRegex(ResearchGuardError,"UNDECLARED"):
            holm_research_gate([0.01,0.02],declared_trials=3)
        with self.assertRaisesRegex(ResearchGuardError,"BAD_PVALUE"):
            holm_research_gate([math.nan,0.02],declared_trials=2)

    def test_concentrated_winners_not_a_verified_portfolio_return(self):
        r=positive_gain_concentration([100.,1.,1.,-50.],top_n=1)
        self.assertAlmostEqual(r["share_of_positive_gains"],100/102)
        self.assertEqual(r["net_pnl"],52.)
        self.assertFalse(r["portfolio_return_verified"])
        self.assertFalse(r["promotion_allowed"])

    def test_reject_no_winners_and_nonfinite(self):
        with self.assertRaisesRegex(ResearchGuardError,"NO_POSITIVE"):
            positive_gain_concentration([-1.,0.,-2.])
        with self.assertRaisesRegex(ResearchGuardError,"BAD_CONCENTRATION"):
            positive_gain_concentration([1.,math.inf,3.])
        with self.assertRaisesRegex(ResearchGuardError,"BAD_CONCENTRATION"):
            positive_gain_concentration([1.,10**1000,3.])
        with self.assertRaisesRegex(ResearchGuardError,"UNSTABLE_NET_PNL"):
            positive_gain_concentration([1e308,-1e308,-1e308,-1e308])


if __name__ == "__main__":
    unittest.main()
