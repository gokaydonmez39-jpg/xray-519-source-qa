"""Verify two independent public native cron opportunities and one fail-closed writer."""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/hourly-519-public-source.yml'

class TestNativeScheduleRedundancy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = WORKFLOW.read_text(encoding='utf-8')

    def test_primary_and_backup(self):
        section = self.src.split('  schedule:\n', 1)[1].split('\n  push:', 1)[0]
        crons = re.findall(r"^\s+- cron: '([^']+)'$", section, re.M)
        self.assertEqual(crons, ['4 * * * *', '8 * * * *'])
        self.assertEqual(len(crons), len(set(crons)))

    def test_one_serial_source_writer(self):
        self.assertIn('group: xray-public-source-main', self.src)
        self.assertIn('cancel-in-progress: false', self.src)
        self.assertEqual(self.src.count('  source-only:'), 1)
        self.assertIn('if [ "$EVENT_NAME" = schedule ] || [ "$EVENT_NAME" = push ]; then', self.src)

    def test_duplicate_authentication_and_fail_closed(self):
        self.assertIn('python3 -m ops.source_preflight --mode "$MODE" --stamp "$STAMP"', self.src)
        self.assertIn('SOURCE_ALREADY_PUBLISHED_NO_SCAN_NOT_NEW_SOURCE_PASS', self.src)
        self.assertIn('FAIL_CLOSED SOURCE_PREFLIGHT_BLOCKED', self.src)
        self.assertIn('python3 verify_remote_pair.py', self.src)

    def test_no_private_or_trading_side_effect(self):
        self.assertIn("github.event.repository.private == false", self.src)
        for forbidden in ['xray-crypto-godzilla-omega', 'api/v3/order', 'secrets.']:
            self.assertNotIn(forbidden, self.src)

if __name__ == '__main__':
    unittest.main()
