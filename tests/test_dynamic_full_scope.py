"""Local scope-boundary tests against the actual scanner and publishers."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bridge_519 import BridgeCollector, atomic_gzip
from ops.bridge_reason_summary import summarize
from ops import source_preflight
import publish_bridge
import publish_receipt
import research_519 as source
from test_bridge_integration import RichProvider


def write_receipt(report, root):
    path = root / 'source.json'
    source.atomic_json(path, report)
    return path


def prepare(receipt, root, mode='519'):
    return publish_receipt.prepare(
        receipt, root, owner_repo='gokaydonmez39-jpg/xray-519-source-qa',
        run_id='1', run_attempt='1', mode=mode,
    )


class DynamicFullScopeTests(unittest.TestCase):
    def run_full(self, count):
        provider = RichProvider(count)
        sink = BridgeCollector(full_scope=True)
        # The fake is considered HTTP only inside this test to exercise the
        # envelope validator. No live request, remote publication, or AL proof.
        with patch.object(source, 'HttpProvider', RichProvider):
            report = source.scan(provider, max_markets=519, bridge_sink=sink)
        self.assertEqual(report['markets_selected'], count)
        self.assertEqual(report['technical_frames_requested'], 3 * count)
        self.assertEqual(provider.requests, 6 + 3 * count)
        self.assertLessEqual(provider.requests, source.MAX_REQUESTS)
        self.assertTrue(report['complete_identity_scope'])
        self.assertTrue(report['scope_stable'])
        self.assertEqual(summarize(sink.document)['identity_symbols'], count)
        self.assertEqual(sink.document['deferred_symbols'], {})
        self.assertEqual(report['orders_sent'], 0)
        self.assertEqual(report['notifications_sent'], 0)
        self.assertFalse(report['native_wss_running'])
        return report, sink.document

    def test_full_401_518_and_519_keep_the_real_inventory(self):
        for count in (401, 518, 519):
            with self.subTest(count=count):
                report, _ = self.run_full(count)
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    relative, _ = prepare(write_receipt(report, root), root)
                    self.assertTrue(relative.name.endswith(f'-n{count}.json.gz'))

    def test_first_oversized_520_produces_exact_bound_receipt_and_bridge(self):
        report, bridge = self.run_full(520)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_path = write_receipt(report, root)
            bridge_path = root / 'input-bridge.json.gz'
            atomic_gzip(bridge_path, bridge)
            receipt_rel, _ = prepare(source_path, root)
            bridge_rel, _ = publish_bridge.prepare(bridge_path, source_path, root)
            self.assertEqual(bridge_rel, str(receipt_rel).replace('receipts/', 'bridges/', 1))
            self.assertTrue(receipt_rel.name.endswith('-n520.json.gz'))
            receipt_doc = json.loads(gzip.decompress((root / receipt_rel).read_bytes()))
            bridge_doc = json.loads(gzip.decompress((root / bridge_rel).read_bytes()))
            self.assertEqual(receipt_doc['source_receipt_sha256'], bridge_doc['source_receipt_sha256'])
            self.assertEqual(set(bridge_doc['markets']), {r['symbol'] for r in receipt_doc['results']})
            paths = {str(receipt_rel), bridge_rel}
            stamp = receipt_rel.name.split('-')[0]
            with patch.object(source_preflight, '_git_blob', side_effect=lambda _ref, _tree, path, _limit: (root / path).read_bytes()):
                self.assertTrue(source_preflight._pair('fixture', paths, '520', stamp))
            with self.assertRaisesRegex(publish_receipt.ReceiptError, 'DUPLICATE_RECEIPT_REFUSED'):
                prepare(source_path, root)

    def test_upper_564_fits_existing_request_limit(self):
        report, _ = self.run_full(564)
        self.assertEqual(report['requests'], 1698)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            relative, _ = prepare(write_receipt(report, root), root)
            self.assertTrue(relative.name.endswith('-n564.json.gz'))

    def test_400_and_565_are_denied_before_candles_in_full_mode(self):
        for count in (400, 565):
            with self.subTest(count=count):
                provider = RichProvider(count)
                with self.assertRaisesRegex(source.FatalSourceError, 'FULL_SCOPE_OUTSIDE_ACCEPTED_RANGE'):
                    source.scan(provider, max_markets=519, bridge_sink=BridgeCollector(full_scope=True))
                self.assertEqual([path for path, _ in provider.calls], ['/api/v3/time', '/api/v3/exchangeInfo'])

    def test_250_and_400_pilots_remain_explicitly_partial(self):
        for count in (250, 400):
            with self.subTest(count=count):
                with patch.object(source, 'HttpProvider', RichProvider):
                    report = source.scan(RichProvider(520), max_markets=count)
                self.assertEqual(report['markets_selected'], count)
                self.assertFalse(report['complete_identity_scope'])
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    relative, _ = prepare(write_receipt(report, root), root, str(count))
                    self.assertTrue(relative.name.endswith(f'-n{count}.json.gz'))

    def test_truncated_519_of_520_can_never_publish_as_full(self):
        with patch.object(source, 'HttpProvider', RichProvider):
            report = source.scan(RichProvider(520), max_markets=519)
        self.assertEqual(report['markets_selected'], 519)
        self.assertFalse(report['complete_identity_scope'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(publish_receipt.ReceiptError, 'SOURCE_EVIDENCE_GATE_FAILED'):
                prepare(write_receipt(report, root), root)
            self.assertFalse((root / 'receipts').exists())
