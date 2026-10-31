"""Negative tests only; real GitHub CI imports the real research_519.py."""
import math
import unittest
import freqtrade_causality_shadow as a
import research_519 as r

def fixture():
    frames={};cutoffs={}
    for frame,period in r.PERIODS.items():
        count=r.COUNTS[frame]+10
        cutoff=(2_000_000_000_000//period)*period-1
        cutoffs[frame]=cutoff
        frames[frame]=[]
        for i in range(count):
            close=cutoff-(count-i-1)*period
            v=100.0+i*.01
            frames[frame].append({"close_ms":close,"o":v,"h":v+.2,"l":v-.2,
                                  "c":v+.05,"quote_volume":1000.0+i})
    return frames,cutoffs

class FreqtradeMethodNegative(unittest.TestCase):
    def setUp(self):
        self.data,self.cutoffs=fixture()
    def denied(self,msg):
        with self.assertRaisesRegex(ValueError,msg):a.gated_indicators(self.data,self.cutoffs)
    def test_real_source_indicator_with_guard(self):
        self.assertTrue(math.isfinite(a.gated_indicators(self.data,self.cutoffs)["ema50_1h"]))
    def test_1h_future_bar_denied(self):
        self.data["1h"][-1]["close_ms"]+=r.HOUR
        self.denied("FUTURE_OR_FORMING_CANDLE")
    def test_4h_future_bar_denied(self):
        self.data["4h"][-1]["close_ms"]+=r.PERIODS["4h"]
        self.denied("FUTURE_OR_FORMING_CANDLE")
    def test_daily_future_bar_denied(self):
        self.data["1d"][-1]["close_ms"]+=r.DAY
        self.denied("FUTURE_OR_FORMING_CANDLE")
    def test_gap_denied(self):
        self.data["1h"][-12]["close_ms"]-=r.HOUR
        self.denied("DUPLICATE_OR_GAPPED_CANDLE")
    def test_stale_frame_denied(self):
        for x in self.data["4h"]:x["close_ms"]-=r.PERIODS["4h"]
        self.denied("STALE_FINAL_CANDLE")
    def test_missing_warmup_denied(self):
        self.data["1h"]=self.data["1h"][-40:]
        self.denied("INSUFFICIENT_CLOSED_HISTORY")
    def test_missing_frame_denied(self):
        del self.data["4h"]
        self.denied("FRAME_SCOPE_MISMATCH")
    def test_bad_geometry_denied(self):
        self.data["1h"][-1]["h"]=0.0
        self.denied("BAD_CANDLE_GEOMETRY")
    def test_nan_denied(self):
        self.data["1d"][-1]["c"]=math.nan
        self.denied("NONFINITE_CANDLE")
    def test_flat_ema_stable(self):
        x=a.recursion_check([100.0]*110)
        self.assertTrue(x["startup_stable"]);self.assertEqual(x["max_delta"],0)
    def test_ema_startup_sensitive_detected(self):
        x=a.recursion_check([100.0]*40+[120.0]*70,tolerance=1e-7)
        self.assertFalse(x["startup_stable"])
    def test_invalid_tolerance_denied(self):
        with self.assertRaisesRegex(ValueError,"INVALID_STARTUP_SETTINGS"):
            a.recursion_check([100.0]*110,tolerance=-1)
    def test_nan_bool_denied(self):
        for v in (True,math.nan,math.inf):
            series=[100.0]*110;series[-1]=v
            with self.assertRaisesRegex(ValueError,"NONFINITE_INPUT"):
                a.recursion_check(series)
    def test_no_action_report(self):
        out=a.report()
        self.assertTrue(out["synthetic_only"])
        self.assertEqual((out["orders"],out["source_api_calls"],out["real_markets_scanned"]),(0,0,0))
        self.assertFalse(out["freqtrade_executed"])
        self.assertFalse(out["technical_519_quality_promoted"])
    def test_existing_source_allowlist_unchanged(self):
        self.assertEqual(set(r.ALLOWED_PATHS),{
            "/api/v3/time","/api/v3/exchangeInfo","/api/v3/ticker/24hr",
            "/api/v3/ticker/bookTicker","/api/v3/klines"})

if __name__=="__main__":unittest.main()
