"""Regression: public-source failover kick can trigger only the existing source-only job.

No private billing, trading, browser automation, credentials, or altered AL thresholds.
"""
from pathlib import Path
import unittest


class PublicSourceKickFallbackTests(unittest.TestCase):
    def test_hourly_schedule_and_auditable_kick_both_present(self):
        src=(Path(__file__).resolve().parents[1]/'.github/workflows/hourly-519-public-source.yml').read_text()
        self.assertIn("cron: '4 * * * *'",src)
        self.assertIn("      - 'ops/source-kicks/*.json'",src)
        self.assertIn('    branches: [main]',src)
        self.assertIn('  workflow_dispatch:',src)

    def test_source_kick_does_not_change_private_p30_or_strategy(self):
        src=(Path(__file__).resolve().parents[1]/'.github/workflows/hourly-519-public-source.yml').read_text()
        self.assertIn('if [ "$EVENT_NAME" = schedule ] || [ "$EVENT_NAME" = push ]; then',src)
        self.assertIn('MODE="$(python3 select_scope.py)"',src)
        self.assertIn('SOURCE_PREFLIGHT_ALLOW_SCAN',src)
        self.assertIn('python3 -m ops.source_preflight',src)
        helper=(Path(__file__).resolve().parents[1]/'ops/source_preflight.py').read_text()
        self.assertIn('DUPLICATE_EPOCH_NO_SCAN',helper)
        self.assertIn('SOURCE_ALREADY_PUBLISHED_AUTHENTIC_PAIR_NO_SCAN_NOT_NEW_SOURCE_PASS',helper)
        self.assertIn('Read-only Binance scan, immutable receipt and independent readback',src)

    def test_kick_cannot_create_automatic_trading(self):
        src=(Path(__file__).resolve().parents[1]/'.github/workflows/hourly-519-public-source.yml').read_text()
        self.assertNotIn('secrets.',src)
        self.assertNotIn('broker',src.lower())
        self.assertIn('python3 verify_remote_pair.py',src)


if __name__=='__main__':
    unittest.main()
