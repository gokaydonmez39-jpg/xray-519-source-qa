"""Fail-closed source diagnostics: no release, order, or fallback semantics."""
import unittest

from research_519 import source_acceptance_diagnostics


class SourceAcceptanceDiagnosticsTests(unittest.TestCase):
    def _report(self):
        return {
            "source_qa_success": False,
            "scope_stable": True,
            "epoch_stable": True,
            "status_accounting_ok": True,
            "complete_identity_scope": True,
            "technical_failed": 2,
            "technical_warmup": 5,
            "technical_pass": 518,
            "identity_universe": 525,
            "markets_selected": 525,
            "start_server_ms": 1795183384155,
            "end_server_ms": 1795183661980,
            "secret_api_key": "NEVER_LOG_ME",
            "results": [
                {"symbol": "ZZZUSDT", "technical_data_quality": "FAIL",
                 "reason": "LAST_CLOSED_BAR_MISMATCH"},
                {"symbol": "AAAUSDT", "technical_data_quality": "FAIL",
                 "reason": "CLOSED_BAR_GAP"},
                {"symbol": "BTCUSDT", "technical_data_quality": "PASS",
                 "reason": "NEVER_COUNT_ME"},
            ],
        }

    def test_reveals_exact_failure_flags_and_reason_distribution(self):
        data = source_acceptance_diagnostics(self._report())
        self.assertEqual(data["event"], "SOURCE_ACCEPTANCE_FAIL_CLOSED_DIAGNOSTIC")
        self.assertFalse(data["source_qa_success"])
        self.assertTrue(data["scope_stable"])
        self.assertTrue(data["epoch_stable"])
        self.assertEqual(data["technical_failed"], 2)
        self.assertEqual(data["failure_reasons"], {
            "CLOSED_BAR_GAP": 1, "LAST_CLOSED_BAR_MISMATCH": 1})
        self.assertEqual(data["failed_symbols_sample"], ["AAAUSDT", "ZZZUSDT"])
        self.assertNotIn("secret_api_key", str(data))
        self.assertNotIn("NEVER_LOG_ME", str(data))

    def test_missing_or_malformed_field_never_claims_pass(self):
        report = self._report()
        report.pop("scope_stable")
        report["epoch_stable"] = "true"
        report["status_accounting_ok"] = 1
        result = source_acceptance_diagnostics(report)
        self.assertFalse(result["scope_stable"])
        self.assertFalse(result["epoch_stable"])
        self.assertFalse(result["status_accounting_ok"])
        self.assertFalse(result["source_qa_success"])

    def test_empty_failure_list_not_fabricated_and_no_side_effects(self):
        report = self._report()
        report["technical_failed"] = 0
        report["results"] = []
        original = dict(report)
        result = source_acceptance_diagnostics(report)
        self.assertEqual(result["failure_reasons"], {})
        self.assertEqual(result["failed_symbols_sample"], [])
        self.assertEqual(original, report)


if __name__ == "__main__":
    unittest.main()
