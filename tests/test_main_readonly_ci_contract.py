"""Offline check that push/main research CI cannot dispatch Binance source job."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
MAIN_CI=ROOT/".github/workflows/xray-519-main-offline-research.yml"
SOURCE_CI=ROOT/".github/workflows/hourly-519-public-source.yml"

class MainReadOnlyCIContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main=MAIN_CI.read_text()
        cls.source=SOURCE_CI.read_text()

    def test_push_main_is_explicit_and_no_schedule(self):
        self.assertIn("  push:\n    branches: [main]",self.main)
        self.assertNotIn("  schedule:",self.main)
        self.assertNotIn("  workflow_dispatch:",self.main)

    def test_main_workflow_requires_public_research_repo(self):
        self.assertIn("github.event.repository.private == false",self.main)
        self.assertIn("github.repository == 'gokaydonmez39-jpg/xray-519-source-qa'",self.main)
        self.assertIn("  contents: read",self.main)

    def test_no_scheduled_receipt_push_triggers_ci(self):
        self.assertNotIn("- 'receipts/**'",self.main)
        self.assertNotIn("- 'bridges/**'",self.main)
        self.assertIn("- 'tests/**'",self.main)
        self.assertIn("- 'warmup_receipt_audit.py'",self.main)

    def test_ci_has_no_external_dispatch_or_deployment(self):
        for forbidden in ("secrets.","workflow_dispatch:","wrangler deploy",
                          "git push ", "github-script", "curl ", "wget "):
            self.assertNotIn(forbidden,self.main)

    def test_ci_calls_only_python_unittests_and_explicit_contract(self):
        self.assertIn("python3 -m unittest discover -s tests -q",self.main)
        self.assertIn("python3 -O -m unittest discover -s tests -q",self.main)
        self.assertIn("MAIN_OFFLINE_RESEARCH_GATE_PASS_NO_MARKET_CALLS",self.main)
        self.assertIn("persist-credentials: false",self.main)

    def test_existing_source_schedule_unmodified_contract(self):
        self.assertIn("cron: '4 * * * *'",self.source)
        self.assertIn("Read-only Binance scan, immutable receipt and independent readback",self.source)

    def test_no_market_data_fetch_from_offline_workflow(self):
        self.assertNotIn("research_519.py --max-markets",self.main)
        self.assertNotIn("publish_git.py --base",self.main)
        self.assertNotIn("python3 publish_git.py",self.main)
        self.assertNotIn("GH_TOKEN:",self.main)

if __name__=="__main__":
    unittest.main()
