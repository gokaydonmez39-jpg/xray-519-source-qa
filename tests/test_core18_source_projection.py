"""Pure closed-bar CORE18 source projection tests; no secrets, alerts or orders."""
import unittest

import research_519 as source


def frame(count, period_ms, closes, lows=None):
    if len(closes) != count:
        raise AssertionError("INVALID_TEST_CANDLE_COUNT")
    if lows is None:
        lows = [c - 1.0 for c in closes]
    if len(lows) != count:
        raise AssertionError("INVALID_TEST_LOW_COUNT")
    return [
        {
            "close_ms": (i + 1) * period_ms - 1,
            "c": float(closes[i]),
            "h": float(closes[i]) + 1.0,
            "l": float(lows[i]),
            "quote_volume": 100_000.0,
        }
        for i in range(count)
    ]


def fixture(four_hour_closes):
    h1 = [100.0] * 100
    h1_lows = [5.0] * 90 + [90.0 + i for i in range(10)]
    return {
        "1h": frame(100, 3_600_000, h1, h1_lows),
        "4h": frame(70, 14_400_000, four_hour_closes),
        "1d": frame(60, 86_400_000, [100.0] * 60),
    }


class Core18SourceProjectionTests(unittest.TestCase):
    def test_ema_predecessor_uses_chronological_seed_and_closed_bars(self):
        bars = fixture([100.0] * 68 + [110.0, 110.0])
        info = source.indicators(bars)
        self.assertAlmostEqual(info["ema20_4h_previous"], 100.95238095238095, places=9)
        self.assertAlmostEqual(info["ema20_4h"], 101.8140589569161, places=9)
        self.assertGreater(info["ema20_4h"], info["ema20_4h_previous"])
        self.assertEqual(info["last_closed_price_4h"], 110.0)
        self.assertEqual(info["asof_closed_utc_ms"]["4h"], 70 * 14_400_000 - 1)

    def test_falling_ema_is_not_mislabeled_as_rising(self):
        bars = fixture([110.0] * 69 + [100.0])
        info = source.indicators(bars)
        self.assertLess(info["ema20_4h"], info["ema20_4h_previous"])

    def test_stop_window_excludes_older_lows_not_current_closed_bar(self):
        bars = fixture([100.0] * 70)
        info = source.indicators(bars)
        self.assertEqual(info["last10_low_1h"], 90.0)
        bars["1h"][-1]["l"] = 80.0
        info2 = source.indicators(bars)
        self.assertEqual(info2["last10_low_1h"], 80.0)
        self.assertEqual(info2["prev20_high_1h"], info["prev20_high_1h"])

    def test_existing_closed_bar_indicators_and_no_trade_interface_preserved(self):
        bars = fixture([100.0] * 70)
        info = source.indicators(bars)
        self.assertEqual(info["quote_rvol20_1h"], 1.0)
        self.assertEqual(info["rsi14_wilder_1h"], 50.0)
        self.assertEqual(info["last_closed_price"], 100.0)
        self.assertNotIn("buy_candidate", info)
        self.assertNotIn("orders_permitted", info)
        self.assertNotIn("send_alert", info)
        self.assertEqual(set(source.ALLOWED_PATHS), {
            "/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/24hr",
            "/api/v3/ticker/bookTicker", "/api/v3/klines"
        })


if __name__ == "__main__":
    unittest.main()
