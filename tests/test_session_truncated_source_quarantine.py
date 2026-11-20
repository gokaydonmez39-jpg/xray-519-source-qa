"""Corroborated non-24h session candles remain quarantined, never scored.

Uses deterministic synthetic public Spot fixtures; no trading or network.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import research_519 as r
from bridge_519 import BridgeCollector, BridgeError
from publish_receipt import ReceiptError, prepare
from test_source import NOW, Provider


class SourceSessionQuarantineTests(unittest.TestCase):
    def test_real_shape_truncated_candle_marker_requires_following_gap(self):
        epoch = 1795132800000
        cutoff = 1795208399999
        partial = [epoch, '10', '11', '9', '10', '100',
                   epoch + 1800000 - 1]
        after = [epoch + 14*r.HOUR, '10', '11', '9', '10', '100',
                 epoch + 15*r.HOUR - 1]
        self.assertEqual(
            r.session_truncated_markers([partial, after],
                                        period=r.HOUR, expected=cutoff),
            {(epoch, epoch + 1800000 - 1)})
        self.assertEqual(
            r.session_truncated_markers([partial, after],
                                        period=4*r.HOUR, expected=cutoff),
            {(epoch, epoch + 1800000 - 1)})
        self.assertEqual(
            r.session_truncated_markers([partial, after],
                                        period=16*r.HOUR, expected=cutoff),
            set())

    @staticmethod
    def _provider(affected):
        target_start = (NOW // r.DAY - 1) * r.DAY
        def inject(bars, params):
            if params['symbol'] not in affected or params['interval'] not in ('1h', '4h'):
                return bars
            period = r.PERIODS[params['interval']]
            idx = next(i for i, bar in enumerate(bars) if bar[0] == target_start)
            before = list(bars[0])
            before[0] -= period
            before[6] -= period
            bars[idx][6] = target_start + 1800000 - 1
            del bars[idx + 1]   # Retain a natural unfilled session gap.
            bars.insert(0, before) # An older historical sample, NOT a missing candle.
            return bars
        provider = Provider(401, inject)
        provider.ids[0]['symbol'] = 'BTCUSDT'
        provider.ids[0]['baseAsset'] = 'BTC'
        return provider

    def test_full_source_one_session_quarantined_but_not_scored(self):
        bridge = BridgeCollector(full_scope=True)
        report = r.scan(self._provider({'AAA0001USDT'}),
                        max_markets=519, bridge_sink=bridge)
        self.assertTrue(report['source_qa_success'], report)
        self.assertFalse(report['full_technical_quality'])
        self.assertFalse(report['live_source_acceptance'])
        self.assertEqual(report['identity_universe'], 401)
        self.assertEqual(report['session_quarantine_count'], 1)
        self.assertEqual(report['technical_failed'], 0)
        self.assertEqual(report['technical_warmup'], 1)
        self.assertEqual(report['technical_pass'], 400)
        row = next(x for x in report['results'] if x['symbol']=='AAA0001USDT')
        self.assertTrue(row['session_quarantined'])
        self.assertEqual(row['reason'], 'SESSION_TRUNCATED_CANDLE_REVIEW_NO_SIGNAL')
        self.assertFalse(row['buy_candidate'])
        self.assertNotIn('technical', row)
        self.assertEqual(bridge.document['transport_ready_count'], 400)
        self.assertEqual(bridge.document['transport_deferred_count'], 1)
        self.assertNotIn('AAA0001USDT', bridge.document['markets'])
        self.assertIn('AAA0001USDT', bridge.document['deferred_symbols'])
        self.assertEqual(report['orders_sent'], 0)
        self.assertEqual(report['notifications_sent'], 0)
        # Validate the *actual public receipt publisher*, not merely scan().
        # The synthetic provider flag is set to True only inside this test
        # fixture to exercise the source packaging contract without network.
        packed = dict(report, http_provider_used=True)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            source = root/'research.json'
            source.write_text(json.dumps(packed, allow_nan=False), encoding='utf-8')
            relative, digest = prepare(
                source, root, owner_repo='gokaydonmez39-jpg/xray-519-source-qa',
                run_id='199', run_attempt='1', mode='519')
            self.assertTrue((root/relative).is_file())
            self.assertEqual(len(digest), 64)
            tampered = dict(packed, session_quarantine_count=0)
            source.write_text(json.dumps(tampered, allow_nan=False), encoding='utf-8')
            with self.assertRaisesRegex(ReceiptError, 'SESSION_QUARANTINE_COUNT_MISMATCH'):
                prepare(source, root, owner_repo='gokaydonmez39-jpg/xray-519-source-qa',
                        run_id='199', run_attempt='1', mode='519')

    def test_more_than_two_session_anomalies_fail_closed(self):
        provider = self._provider({'AAA0001USDT','AAA0002USDT','AAA0003USDT'})
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(BridgeError, 'SOURCE_RECEIPT_NOT_ACCEPTED'):
                r.scan(provider, max_markets=519, bridge_sink=BridgeCollector(full_scope=True))

    def test_same_short_close_without_gap_is_not_enough(self):
        op = 1795132800000
        short = [op, 0,0,0,0,0,op+1800000-1]
        next_bar = [op+r.HOUR,0,0,0,0,0,op+2*r.HOUR-1]
        self.assertEqual(r.session_truncated_markers(
            [short,next_bar],period=r.HOUR,expected=op+4*r.HOUR),set())


if __name__ == '__main__':
    unittest.main()
