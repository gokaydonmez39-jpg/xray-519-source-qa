"""Explicit final-start negative cases; fixtures are never live evidence."""
import copy
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import research_519 as src
from test_source import Provider


class FinalStartNegativeTests(unittest.TestCase):
    def test_http_418_and_429_stop_without_retry(self):
        for status in (418, 429):
            with self.subTest(status=status):
                provider = src.HttpProvider(pace=0)
                with patch.object(provider.opener, 'open', side_effect=HTTPError(
                    src.BASE_URL + '/api/v3/time', status, 'blocked', {}, None
                )) as request:
                    with self.assertRaisesRegex(src.FatalSourceError, f'HTTP_{status}_FAIL_CLOSED'):
                        provider.get('/api/v3/time')
                    self.assertEqual(request.call_count, 1)
                    self.assertEqual(provider.requests, 1)

    def test_outage_stops_without_retry(self):
        provider = src.HttpProvider(pace=0)
        with patch.object(provider.opener, 'open', side_effect=URLError('offline')) as request:
            with self.assertRaisesRegex(src.FatalSourceError, 'SOURCE_UNAVAILABLE_URLError'):
                provider.get('/api/v3/time')
            self.assertEqual(request.call_count, 1)

    def test_nonspot_nonusdt_and_inactive_excluded(self):
        valid = Provider(1).ids[0]
        rejected = []
        for key, value in (('isSpotTradingAllowed', False), ('quoteAsset', 'USDC'), ('status', 'BREAK')):
            row = copy.deepcopy(valid)
            row[key] = value
            rejected.append(row)
        scope, _ = src.instrument_scope({'symbols': [valid] + rejected})
        self.assertEqual(scope, [{'symbol': valid['symbol'], 'baseAsset': valid['baseAsset'], 'quoteAsset': 'USDT'}])
        with self.assertRaisesRegex(src.QualityError, 'NO_ACTIVE_SPOT_USDT'):
            src.instrument_scope({'symbols': rejected})

    def test_stale_closed_series_fails_all_three_frames(self):
        def stale(bars, params):
            period = src.PERIODS[params['interval']]
            for row in bars:
                row[0] -= period
                row[6] -= period
            return bars
        report = src.scan(Provider(1, stale))
        self.assertFalse(report['source_qa_success'])
        self.assertFalse(report['full_technical_quality'])
        self.assertEqual(report['technical_failed'], 1)
        self.assertTrue(all(value == 'FAIL_LAST_CLOSED_BAR_MISMATCH'
                            for value in report['results'][0]['frame_quality'].values()))
        self.assertNotIn('technical', report['results'][0])

    def test_stale_ticker_cannot_pass_liquidity_prefilter(self):
        class StaleTicker(Provider):
            def get(self, path, params=None):
                rows = super().get(path, params)
                if path == '/api/v3/ticker/24hr':
                    for row in rows:
                        row['closeTime'] -= 121_000
                return rows
        report = src.scan(StaleTicker(1))
        row = report['results'][0]
        self.assertFalse(row['liquidity_snapshot']['ticker_within_120s'])
        self.assertFalse(row['raw_15m_15bp_prefilter'])
        self.assertFalse(row['buy_candidate'])


if __name__ == '__main__':
    unittest.main()
