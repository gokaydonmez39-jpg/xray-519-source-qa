"""In-repository bridge checks; exercise the actual existing source scanner."""
import copy
import gzip
import tempfile
import unittest
from pathlib import Path
import research_519 as research
from bridge_519 import BridgeCollector, BridgeError, COUNTS, atomic_gzip, canonical_bytes
from publish_bridge import prepare
from test_source import Provider


class RichProvider(Provider):
    def __init__(self, count=2, injection=None):
        super().__init__(count,injection)
        self.ids[0]['symbol']='BTCUSDT'
        self.ids[0]['baseAsset']='BTC'
        if count > 1:
            self.ids[1]['symbol']='ARBUSDT'
            self.ids[1]['baseAsset']='ARB'

    def get(self,path,params=None):
        result=super().get(path,params)
        if path=='/api/v3/ticker/24hr':
            for r in result:
                r['quoteVolume']='22000000'
        return result


class LiveScannerBridgeTests(unittest.TestCase):
    def test_three_calls_per_market_preserved_and_complete_series(self):
        p=RichProvider(2);sink=BridgeCollector()
        receipt=research.scan(p,bridge_sink=sink)
        self.assertEqual(p.requests,6+3*2)
        self.assertEqual(receipt['technical_pass'],2)
        self.assertEqual(receipt['technical_failed'],0)
        self.assertEqual(receipt['private_strategy_evaluated'],0)
        self.assertEqual(sink.document['raw_prefilter_symbols'],2)
        self.assertEqual(sink.document['exported_symbols'],2)
        self.assertEqual(len(sink.document['markets']['ARBUSDT']['frames']['1h']),100)
        self.assertEqual(len(sink.document['markets']['ARBUSDT']['frames']['4h']),70)
        self.assertEqual(len(sink.document['markets']['ARBUSDT']['frames']['1d']),60)
        self.assertEqual(len(sink.document['btc_daily_60']),60)
        self.assertEqual([call[1]['limit'] for call in p.calls if call[0]=='/api/v3/klines'][:3],[100,70,60])

    def test_private_history_warmup_does_not_fake_success(self):
        def short(bars,params):
            if params['symbol']=='ARBUSDT' and params['interval']=='4h':
                return bars[-40:]
            return bars
        p=RichProvider(2,injection=short);sink=BridgeCollector()
        receipt=research.scan(p,bridge_sink=sink)
        self.assertTrue(receipt['source_qa_success'])
        self.assertEqual(receipt['technical_pass'],2)
        self.assertEqual(sink.document['exported_symbols'],1)
        self.assertIn('ARBUSDT',sink.document['deferred_symbols'])
        self.assertEqual(sink.document['private_strategy_evaluated'],0)

    def test_partial_inventory_fails_closed(self):
        p=RichProvider(2);sink=BridgeCollector()
        with self.assertRaises(BridgeError):research.scan(p,max_markets=1,bridge_sink=sink)

    def test_append_only_public_bridge_and_receipt_hash(self):
        p=RichProvider(2);sink=BridgeCollector()
        receipt=research.scan(p,bridge_sink=sink)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            rp=root/'source.json'
            rp.write_bytes(canonical_bytes(receipt))
            bp=root/'input.json.gz'
            atomic_gzip(bp,sink.document)
            name,digest=prepare(bp,rp,root)
            self.assertTrue((root/name).exists())
            self.assertEqual(len(digest),64)
            with self.assertRaisesRegex(BridgeError,'ALREADY_PUBLISHED'):
                prepare(bp,rp,root)
            document=copy.deepcopy(sink.document)
            document['source_receipt_sha256']='0'*64
            bad=root/'bad.json.gz'
            atomic_gzip(bad,document)
            with self.assertRaisesRegex(BridgeError,'BRIDGE_RECEIPT_MISMATCH'):
                prepare(bad,rp,root)


if __name__=='__main__':unittest.main()
