"""Offline, deterministic XRAY-519 autonomy admission gates.

No network, system clock, subprocess, filesystem mutation, secrets, broker,
strategy or private runner. Inputs are attestations, NOT trusted evidence until
an independent collector proves them from raw GitHub/Cloudflare artifacts.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import re

STAMP_RE = re.compile(r"^[0-9]{8}T[0-9]{2}00Z$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_EVENTS = {
    # Only the independently collected origins that the trusted evidence
    # collector actually emits. Legacy caller-supplied labels must never
    # bypass the exact Cloudflare trace -> GitHub run-id attestation.
    "github_native_schedule": "schedule",
    "cloudflare_cron_trace_exact_run": "workflow_dispatch",
}
REQUIRED_HOURS = 48
SOURCE_ONLY_STATUS = "SOURCE_ONLY_OFFLINE_ELIGIBILITY_NOT_LIVE_ACCEPTANCE"
CANDIDATE_SCHEMA = "XRAY519_CANDIDATE_RESEARCH_SHADOW_V1"


class AdmissionError(ValueError):
    """Invalid/untrusted ledger structure; never silently interpret as PASS."""


def _integer(value):
    return type(value) is int


def _hour(stamp):
    if not isinstance(stamp, str) or STAMP_RE.fullmatch(stamp) is None:
        raise AdmissionError("INVALID_EPOCH_STAMP")
    try:
        dt = datetime.strptime(stamp, "%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AdmissionError("INVALID_CALENDAR_EPOCH") from exc
    if dt.strftime("%Y%m%dT%H00Z") != stamp:
        raise AdmissionError("NONCANONICAL_EPOCH")
    return dt


def _stamp(dt):
    return dt.strftime("%Y%m%dT%H00Z")


def _source_failures(item):
    failures = []
    if not isinstance(item, dict):
        return ["INVALID_EVIDENCE_RECORD"]
    run = item.get("run_id")
    if not _integer(run) or run <= 0 or str(run) != str(item.get("receipt_runner_id")):
        failures.append("RUN_ID_PROVENANCE_MISMATCH")
    provenance = item.get("trigger_provenance")
    if (PROVENANCE_EVENTS.get(provenance) != item.get("event") or
            item.get("trigger_independently_verified") is not True):
        failures.append("TRIGGER_PROVENANCE_UNVERIFIED")
    if item.get("conclusion") != "success" or item.get("source_qa_success") is not True:
        failures.append("SOURCE_QA_NOT_PASSED")
    values = [item.get(k) for k in ("scanned", "pass", "warmup", "failed")]
    if (any(not _integer(x) or x < 0 for x in values) or
            values[0] != 519 or sum(values[1:]) != 519 or values[3] != 0 or
            item.get("status_accounting_ok") is not True):
        failures.append("519_ACCOUNTING_INVALID")
    for key in ("orders_sent", "notifications_sent", "private_strategy_evaluated"):
        if type(item.get(key)) is not int or item[key] != 0:
            failures.append("UNAUTHORIZED_" + key.upper())
    if item.get("live_al_claim") is not False:
        failures.append("LIVE_AL_NOT_FALSE")
    if (item.get("pair_bytes_independently_verified") is not True or
            item.get("pair_canonical_independently_verified") is not True or
            any(not isinstance(item.get(k), str) or
                SHA_RE.fullmatch(item[k]) is None
                for k in ("receipt_sha256", "bridge_sha256"))):
        failures.append("PAIR_UNVERIFIED")
    return failures


def evaluate_public_window(records, *, end_stamp):
    """Check exactly 48 UTC hours ending in end_stamp. Never declare live FINAL.

    SOURCE is countable if proven and uniquely backed by a run/receipt/bridge.
    NOOP is not a SOURCE. Caller-provided verified flags are *not* verified by
    this pure function; a trusted evidence-ingestion layer is mandatory.
    """
    end = _hour(end_stamp)
    if not isinstance(records, list) or len(records) > 10000:
        raise AdmissionError("INVALID_LEDGER_SIZE")
    start = end - timedelta(hours=REQUIRED_HOURS - 1)
    expected = [_stamp(start + timedelta(hours=i))
                for i in range(REQUIRED_HOURS)]
    buckets = defaultdict(list)
    ignored_noop = 0
    for item in records:
        if not isinstance(item, dict):
            raise AdmissionError("INVALID_EVIDENCE_RECORD")
        stamp = item.get("stamp")
        dt = _hour(stamp)
        if item.get("kind") == "NOOP":
            ignored_noop += 1
            continue
        if item.get("kind") != "SOURCE":
            raise AdmissionError("UNKNOWN_EVENT_KIND")
        if start <= dt <= end:
            buckets[stamp].append(item)
    invalid = {}
    used_runs = set()
    passed = 0
    for epoch in expected:
        group = buckets.get(epoch, [])
        if not group:
            invalid[epoch] = ["MISSING_SOURCE"]
            continue
        if len(group) != 1:
            invalid[epoch] = ["MULTIPLE_SOURCE_CLAIMS"]
            continue
        item = group[0]
        failures = _source_failures(item)
        rid = item.get("run_id")
        if _integer(rid) and rid in used_runs:
            failures.append("RUN_ID_REUSED_ACROSS_EPOCHS")
        if _integer(rid):
            used_runs.add(rid)
        if failures:
            invalid[epoch] = failures
        else:
            passed += 1
    return {
        "schema": "XRAY519_AUTONOMY_ACCEPTANCE_V1",
        "mode": SOURCE_ONLY_STATUS,
        "start_stamp": expected[0],
        "end_stamp": end_stamp,
        "required_distinct_hours": REQUIRED_HOURS,
        "counted_valid_hours": passed,
        "ignored_noop_records": ignored_noop,
        "failed_epochs": invalid,
        "conditional_public_gate_pass": passed == REQUIRED_HOURS,
        "live_evidence_independently_collected": False,
        "private_p30_verified": False,
        "wss_14d_verified": False,
        "paper_oos_60d_verified": False,
        "iphone_ack_verified": False,
        "full_final_start": False,
    }


def evaluate_candidate(candidate):
    """Research-shadow eligibility, NEVER source integration or auto promotion."""
    if not isinstance(candidate, dict):
        raise AdmissionError("INVALID_CANDIDATE")
    kind = candidate.get("kind")
    if kind not in ("research_method", "signal_model"):
        raise AdmissionError("INVALID_CANDIDATE_KIND")
    common = (
        "license_verified", "offline_deterministic_tests_pass",
        "point_in_time_test_pass", "no_execution_permissions",
        "zero_extra_cost_verified", "data_origin_audited",
        "rollback_defined", "independent_security_review_pass",
    )
    reasons = ["MISSING_" + k.upper() for k in common if candidate.get(k) is not True]
    if kind == "signal_model":
        for key in (
            "purged_walk_forward_pass", "oos_beats_baseline_after_cost",
            "slippage_spread_liquidity_included", "multi_regime_robustness",
            "survivorship_and_churn_audited", "paper_shadow_complete",
        ):
            if candidate.get(key) is not True:
                reasons.append("MISSING_" + key.upper())
        if (not _integer(candidate.get("observations")) or
                candidate["observations"] < 200 or
                not _integer(candidate.get("distinct_epochs")) or
                candidate["distinct_epochs"] < 100):
            reasons.append("INSUFFICIENT_OOS_SAMPLE")
    result = "RESEARCH_SHADOW_ELIGIBLE" if not reasons else "HOLD_RESEARCH"
    return {
        "schema": CANDIDATE_SCHEMA,
        "candidate_kind": kind,
        "decision": result,
        "reasons": reasons,
        "automatic_code_change": False,
        "automatic_merge": False,
        "automatic_production_promotion": False,
        "real_alpha_verified": False,
        "live_trading_permitted": False,
    }
