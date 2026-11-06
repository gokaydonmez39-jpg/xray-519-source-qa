"""Release contract: one safe opt-in for full-quality closed-bar source data.

No live Binance calls, GitHub writes, alerts or orders.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/hourly-519-public-source.yml"


class FullQualityWorkflowReleaseGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = FLOW.read_text(encoding="utf-8")

    def test_two_original_utc_crons_untouched(self):
        self.assertEqual(self.raw.count("cron: '4 * * * *'"), 1)
        self.assertEqual(self.raw.count("cron: '8 * * * *'"), 1)
        self.assertNotIn("cron: '1 * * * *'", self.raw)
        self.assertNotIn("cron: '2 * * * *'", self.raw)

    def test_live_519_market_path_is_full_quality_only(self):
        self.assertEqual(self.raw.count("--bridge-profile full-quality"), 1)
        self.assertRegex(self.raw,
            r'if \[ "\$MODE" = 519 \]; then\s*'
            r'python3 research_519\.py --max-markets "\$MODE"'
            r' --output "\$OUT" --bridge-output "\$BRIDGE"'
            r' --bridge-profile full-quality --pace 0\.15')
        self.assertIn(
            'python3 research_519.py --max-markets "$MODE" --output "$OUT" --pace 0.15',
            self.raw)

    def test_source_records_remain_immutable_and_mirror_verified(self):
        self.assertIn("python3 -m ops.source_preflight", self.raw)
        self.assertIn('SOURCE_ALREADY_PUBLISHED_NO_SCAN_NOT_NEW_SOURCE_PASS', self.raw)
        self.assertIn('git add -- "$FILE" "$BFILE"', self.raw)
        self.assertIn('python3 publish_git.py --base "$SCAN_BASE"', self.raw)
        self.assertIn('python3 verify_remote_pair.py', self.raw)
        self.assertIn("SOURCE_PREFLIGHT_BLOCKED", self.raw)

    def test_no_private_writer_or_orders_inside_source_job(self):
        for forbidden in ["api/v3/order", "submitOrder", "SUPABASE_SERVICE_ROLE_KEY",
                          "xray_write_private_research_epoch_v1", "--place-order"]:
            self.assertNotIn(forbidden, self.raw)


if __name__ == "__main__":
    unittest.main()
