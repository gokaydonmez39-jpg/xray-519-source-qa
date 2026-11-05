"""Opt-in full-quality transport tests; never grant AL, alerts, or orders."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bridge_519
import research_519 as research
from bridge_519 import BridgeCollector, BridgeError, atomic_gzip, canonical_bytes
from publish_bridge import prepare
from test_bridge_integration import RichProvider


class MixedLiquidityProvider(RichProvider):
    def get(self, path, params=None):
        rows = super().get(path, params)
        if path == '/api/v3/ticker/24hr':
            for row in rows:
                if row['symbol'] == 'ARBUSDT':
                    row['quoteVolume'] = '1000000'
        return rows


class FullSourceTransportTests(unittest.TestCase):
    def test_legacy_prefilter_is_unchanged(self):
        receipt = research.scan(MixedLiquidityProvider(2), bridge_sink=BridgeCollector())
        self.assertTrue(receipt['source_qa_success'])
        self.assertEqual(receipt['technical_pass'], 2)
        self.assertFalse(receipt['results'][1]['buy_candidate'])
        sink = BridgeCollector()
        research.scan(MixedLiquidityProvider(2), bridge_sink=sink)
        self.assertEqual(sink.document['raw_prefilter_symbols'], 1)
        self.assertEqual(sink.document['exported_symbols'], 1)
        self.assertNotIn('transport_profile', sink.document)

    def test_full_quality_profile_preserves_low_liquidity_for_private_classification(self):
        sink = BridgeCollector(full_scope=True)
        receipt = research.scan(MixedLiquidityProvider(2), bridge_sink=sink)
        doc = sink.document
        self.assertTrue(receipt['source_qa_success'])
        self.assertEqual(doc['transport_profile'], 'FULL_QUALITY_READY_V2')
        self.assertEqual(doc['raw_prefilter_symbols'], 1)
        self.assertEqual(doc['exported_symbols'], 2)
        self.assertEqual(doc['transport_ready_count'], 2)
        self.assertEqual(doc['transport_deferred_count'], 0)
        self.assertEqual(set(doc['markets']), {'BTCUSDT', 'ARBUSDT'})
        self.assertFalse(doc['live_al_claim'])
        self.assertEqual(doc['orders_sent'], 0)
        self.assertEqual(doc['notifications_sent'], 0)
        self.assertEqual(doc['private_strategy_evaluated'], 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rp = root / 'receipt.json'
            rp.write_bytes(canonical_bytes(receipt))
            bp = root / 'bridge.json.gz'
            atomic_gzip(bp, doc)
            published, digest = prepare(bp, rp, root)
            self.assertTrue((root / published).is_file())
            self.assertEqual(len(digest), 64)

    def test_warmup_full_history_is_deferred_not_silently_passed(self):
        def shorten(bars, params):
            if params['symbol'] == 'ARBUSDT' and params['interval'] == '4h':
                return bars[-40:]
            return bars
        class MixedShort(MixedLiquidityProvider):
            def __init__(self):
                super().__init__(2, injection=shorten)
        sink = BridgeCollector(full_scope=True)
        receipt = research.scan(MixedShort(), bridge_sink=sink)
        self.assertEqual(receipt['technical_pass'], 2)
        self.assertEqual(sink.document['raw_prefilter_symbols'], 1)
        self.assertEqual(sink.document['exported_symbols'], 1)
        self.assertEqual(sink.document['transport_deferred_count'], 1)
        self.assertIn('ARBUSDT', sink.document['deferred_symbols'])

    def test_oversize_full_transport_is_hold_not_partial(self):
        with patch.object(bridge_519, 'MAX_RAW_BYTES', 100):
            with self.assertRaisesRegex(BridgeError, 'BRIDGE_RAW_SIZE_LIMIT'):
                research.scan(MixedLiquidityProvider(2), bridge_sink=BridgeCollector(full_scope=True))

    def test_wrong_profile_is_rejected_before_collector(self):
        with self.assertRaisesRegex(BridgeError, 'INVALID_BRIDGE_PROFILE'):
            BridgeCollector(full_scope='true')


if __name__ == '__main__':
    unittest.main()
