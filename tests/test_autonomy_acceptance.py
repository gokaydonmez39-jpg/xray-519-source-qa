"""Adversarial tests for the offline XRAY-519 admission gate.

All records below are invented fixtures; none is a real source PASS or signal.
"""
import copy
from datetime import datetime, timedelta, timezone
import unittest

from ops.autonomy_acceptance import (
    AdmissionError, evaluate_candidate, evaluate_public_window,
)

END = datetime(2026, 11, 3, 11, tzinfo=timezone.utc)


def stamp(dt):
    return dt.strftime("%Y%m%dT%H00Z")


def source(hour, run_id):
    return {
        "kind": "SOURCE", "stamp": stamp(hour), "run_id": run_id,
        "receipt_runner_id": str(run_id),
        "event": "workflow_dispatch", "trigger_provenance": "cloudflare_cron_trace_exact_run",
        "trigger_independently_verified": True,
        "conclusion": "success", "source_qa_success": True,
        "scanned": 519, "pass": 489, "warmup": 30, "failed": 0,
        "status_accounting_ok": True, "orders_sent": 0,
        "notifications_sent": 0, "private_strategy_evaluated": 0,
        "live_al_claim": False,
        "pair_bytes_independently_verified": True,
        "pair_canonical_independently_verified": True,
        "receipt_sha256": "a" * 64, "bridge_sha256": "b" * 64,
    }


def full():
    return [source(END - timedelta(hours=47-i), 10000+i)
            for i in range(48)]


class PublicGateTests(unittest.TestCase):
    def assess(self, records):
        return evaluate_public_window(records, end_stamp=stamp(END))

    def test_48_good_synthetic_hours_are_conditional_not_real_final(self):
        x = self.assess(full())
        self.assertEqual(x["counted_valid_hours"], 48)
        self.assertTrue(x["conditional_public_gate_pass"])
        self.assertFalse(x["live_evidence_independently_collected"])
        self.assertFalse(x["full_final_start"])

    def test_47_hours_hold_and_missing_epoch_is_exact(self):
        rows = full()
        dropped = rows.pop(8)["stamp"]
        x = self.assess(rows)
        self.assertFalse(x["conditional_public_gate_pass"])
        self.assertEqual(x["failed_epochs"][dropped], ["MISSING_SOURCE"])

    def test_noop_only_never_qualifies_as_source(self):
        rows = [{"kind": "NOOP", "stamp": stamp(END), "run_id": 55}]
        x = self.assess(rows)
        self.assertEqual(x["counted_valid_hours"], 0)
        self.assertEqual(x["ignored_noop_records"], 1)

    def test_legitimate_noop_alongside_source_is_ignored(self):
        rows = full()
        rows.append({"kind": "NOOP", "stamp": stamp(END), "run_id": 99999})
        x = self.assess(rows)
        self.assertTrue(x["conditional_public_gate_pass"])
        self.assertEqual(x["ignored_noop_records"], 1)

    def test_second_source_claim_on_same_epoch_is_invalid(self):
        rows = full()
        rows.append(source(END, 223344))
        x = self.assess(rows)
        self.assertEqual(x["failed_epochs"][stamp(END)], ["MULTIPLE_SOURCE_CLAIMS"])

    def test_reusing_run_id_across_hours_never_counts_twice(self):
        rows = full()
        rows[-1]["run_id"] = rows[0]["run_id"]
        rows[-1]["receipt_runner_id"] = str(rows[-1]["run_id"])
        x = self.assess(rows)
        self.assertIn("RUN_ID_REUSED_ACROSS_EPOCHS",
                      x["failed_epochs"][stamp(END)])

    def test_older_historic_48_does_not_rescue_recent_gap(self):
        rows = [source(END-timedelta(hours=48+i), 20000+i)
                for i in range(48)]
        x = self.assess(rows)
        self.assertEqual(x["counted_valid_hours"], 0)

    def test_later_future_epoch_does_not_backfill(self):
        rows = full()[:-1] + [source(END+timedelta(hours=1), 2000)]
        self.assertFalse(self.assess(rows)["conditional_public_gate_pass"])

    def test_legacy_unattested_cloudflare_labels_never_pass(self):
        for old_label in ("cloudflare_primary", "cloudflare_backup", "github_source_kick"):
            with self.subTest(label=old_label):
                rows = full()
                rows[0]["trigger_provenance"] = old_label
                result = self.assess(rows)
                self.assertIn("TRIGGER_PROVENANCE_UNVERIFIED",
                              result["failed_epochs"][rows[0]["stamp"]])

    def test_missing_trigger_provenance_blocks_successful_workflow_dispatch(self):
        rows = full()
        rows[0]["trigger_independently_verified"] = False
        x = self.assess(rows)
        self.assertIn("TRIGGER_PROVENANCE_UNVERIFIED",
                      x["failed_epochs"][rows[0]["stamp"]])

    def test_wrong_schedule_event_provenance_pair_rejected(self):
        rows = full()
        rows[0]["event"] = "schedule"
        x = self.assess(rows)
        self.assertFalse(x["conditional_public_gate_pass"])

    def test_true_native_schedule_accepted_only_with_evidence(self):
        rows = full()
        rows[0]["event"] = "schedule"
        rows[0]["trigger_provenance"] = "github_native_schedule"
        self.assertTrue(self.assess(rows)["conditional_public_gate_pass"])

    def test_warmup_is_allowed_but_never_519_full_quality(self):
        rows = full()
        rows[0]["pass"] = 519
        rows[0]["warmup"] = 0
        self.assertTrue(self.assess(rows)["conditional_public_gate_pass"])
        rows[0]["failed"] = 1
        self.assertFalse(self.assess(rows)["conditional_public_gate_pass"])

    def test_fail_1_invalid_even_when_workflow_says_success(self):
        rows = full()
        rows[0]["failed"] = 1
        rows[0]["pass"] = 488
        x = self.assess(rows)
        self.assertIn("519_ACCOUNTING_INVALID",
                      x["failed_epochs"][rows[0]["stamp"]])

    def test_missing_canonical_pair_blocks(self):
        rows = full()
        rows[3]["pair_canonical_independently_verified"] = None
        x = self.assess(rows)
        self.assertIn("PAIR_UNVERIFIED", x["failed_epochs"][rows[3]["stamp"]])

    def test_shas_must_be_literal_lower_hex_64(self):
        rows = full()
        rows[1]["receipt_sha256"] = "not_a_sha"
        x = self.assess(rows)
        self.assertIn("PAIR_UNVERIFIED", x["failed_epochs"][rows[1]["stamp"]])

    def test_order_or_notification_claim_hard_blocks(self):
        for field in ("orders_sent", "notifications_sent", "private_strategy_evaluated"):
            with self.subTest(field=field):
                rows = full()
                rows[6][field] = 1
                x = self.assess(rows)
                self.assertFalse(x["conditional_public_gate_pass"])
                self.assertIn("UNAUTHORIZED_" + field.upper(),
                              x["failed_epochs"][rows[6]["stamp"]])

    def test_boolean_integer_is_not_accepted_as_accounting(self):
        rows = full()
        rows[0]["scanned"] = True
        self.assertFalse(self.assess(rows)["conditional_public_gate_pass"])

    def test_unrecognized_record_fails_closed(self):
        rows = full()
        rows.append({"kind": "FAKE_PASS", "stamp": stamp(END)})
        with self.assertRaisesRegex(AdmissionError, "UNKNOWN_EVENT_KIND"):
            self.assess(rows)

    def test_invalid_utc_stamp_fails_closed(self):
        for malformed in ("20261101T2500Z", "20260230T0200Z",
                          "20261101T0201Z", "20261101T0200+03", None):
            with self.subTest(malformed=malformed):
                with self.assertRaises(AdmissionError):
                    evaluate_public_window(full(), end_stamp=malformed)


class CandidateTests(unittest.TestCase):
    def common(self, kind="research_method"):
        return {
            "kind": kind, "license_verified": True,
            "offline_deterministic_tests_pass": True,
            "point_in_time_test_pass": True,
            "no_execution_permissions": True,
            "zero_extra_cost_verified": True,
            "data_origin_audited": True,
            "rollback_defined": True,
            "independent_security_review_pass": True,
        }

    def test_safe_research_method_is_only_shadow_eligible(self):
        x = evaluate_candidate(self.common())
        self.assertEqual(x["decision"], "RESEARCH_SHADOW_ELIGIBLE")
        self.assertFalse(x["automatic_merge"])
        self.assertFalse(x["automatic_production_promotion"])
        self.assertFalse(x["live_trading_permitted"])

    def test_unknown_license_and_security_fail_closed(self):
        x = self.common()
        x["license_verified"] = False
        x["independent_security_review_pass"] = False
        y = evaluate_candidate(x)
        self.assertEqual(y["decision"], "HOLD_RESEARCH")
        self.assertEqual(len(y["reasons"]), 2)

    def test_model_requires_all_science_not_only_backtest_win(self):
        x = self.common("signal_model")
        x["oos_beats_baseline_after_cost"] = True
        y = evaluate_candidate(x)
        self.assertEqual(y["decision"], "HOLD_RESEARCH")
        self.assertIn("INSUFFICIENT_OOS_SAMPLE", y["reasons"])

    def test_model_sample_count_threshold(self):
        x = self.common("signal_model")
        x.update({k: True for k in (
            "purged_walk_forward_pass", "oos_beats_baseline_after_cost",
            "slippage_spread_liquidity_included", "multi_regime_robustness",
            "survivorship_and_churn_audited", "paper_shadow_complete",
        )})
        x.update(observations=199, distinct_epochs=100)
        self.assertEqual(evaluate_candidate(x)["decision"], "HOLD_RESEARCH")
        x["observations"] = 200
        self.assertEqual(evaluate_candidate(x)["decision"], "RESEARCH_SHADOW_ELIGIBLE")

    def test_model_true_is_synthetic_only_no_live_alpha(self):
        x = self.common("signal_model")
        x.update({k: True for k in (
            "purged_walk_forward_pass", "oos_beats_baseline_after_cost",
            "slippage_spread_liquidity_included", "multi_regime_robustness",
            "survivorship_and_churn_audited", "paper_shadow_complete",
        )})
        x.update(observations=200, distinct_epochs=100)
        y = evaluate_candidate(x)
        self.assertFalse(y["real_alpha_verified"])
        self.assertFalse(y["automatic_code_change"])

    def test_invalid_candidate_kind_is_not_promoted(self):
        with self.assertRaises(AdmissionError):
            evaluate_candidate({"kind": "trade_executor"})


if __name__ == "__main__":
    unittest.main()
