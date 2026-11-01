"""XRAY-519 trusted public-source evidence reader (read-only).

Operates over a checked-out public main repository and authenticated,
read-only GitHub workflow-run metadata. It never dispatches, trades, changes
credentials, mutates git history, or approves FULL FINAL START.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ops.autonomy_acceptance import evaluate_public_window
from ops.source_preflight import _json_gzip, _canonical, PreflightBlocked
from warmup_receipt_audit import summarize, ReceiptInvalid

REPO = "gokaydonmez39-jpg/xray-519-source-qa"
WORKFLOW_ID = 402070622
WORKFLOW_NAME = "XRAY 519 public Spot closed-bar research"
MAX_RECEIPT = 200_000
MAX_BRIDGE = 8_388_608
MAX_RUN_JSON = 256_000
MAX_RUN_DURATION_MIN = 30
STAMP = re.compile(r"^[0-9]{8}T[0-9]{2}00Z$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")


class EvidenceError(ValueError):
    pass


def _epoch_dt(stamp):
    if not isinstance(stamp, str) or STAMP.fullmatch(stamp) is None:
        raise EvidenceError("INVALID_STAMP")
    try:
        d = datetime.strptime(stamp, "%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise EvidenceError("INVALID_STAMP") from exc
    if d.strftime("%Y%m%dT%H00Z") != stamp:
        raise EvidenceError("INVALID_STAMP")
    return d


def _regular_bytes(root, rel, maximum):
    target = root / rel
    if target.is_symlink() or not target.is_file():
        raise EvidenceError("MISSING_OR_UNSAFE_PAIR")
    if target.stat().st_size <= 0 or target.stat().st_size > maximum:
        raise EvidenceError("PAIR_SIZE_INVALID")
    return target.read_bytes()


def _parse(raw, limit):
    try:
        return _json_gzip(raw, limit)
    except (PreflightBlocked, TypeError, ValueError) as exc:
        raise EvidenceError("INVALID_GZIP_JSON") from exc


def read_pair(root, stamp):
    """Compute SHA from raw compressed bytes; validate canonical cross-hash."""
    epoch = _epoch_dt(stamp)
    folder = epoch.strftime("%Y/%m/%d")
    receipt_rel = f"receipts/{folder}/{stamp}-n519.json.gz"
    bridge_rel = f"bridges/{folder}/{stamp}-n519.json.gz"
    root = Path(root)
    receipt_bytes = _regular_bytes(root, receipt_rel, MAX_RECEIPT)
    bridge_bytes = _regular_bytes(root, bridge_rel, MAX_BRIDGE)
    receipt = _parse(receipt_bytes, 2_500_000)
    bridge = _parse(bridge_bytes, 24 * 1024 * 1024)
    try:
        audit = summarize(receipt)
    except ReceiptInvalid as exc:
        raise EvidenceError("SOURCE_SUMMARY_INVALID") from exc
    if (type(receipt.get("utc_closed_epoch_1h_ms")) is not int or
            receipt["utc_closed_epoch_1h_ms"] != int(epoch.timestamp() * 1000) - 1 or
            receipt.get("source_qa_success") is not True or
            receipt.get("scope_stable") is not True or
            receipt.get("epoch_stable") is not True or
            receipt.get("complete_identity_scope") is not True or
            receipt.get("status_accounting_ok") is not True or
            receipt.get("http_provider_used") is not True or
            receipt.get("run_kind") != "RESEARCH_ONLY_NO_AL" or
            receipt.get("live_al_claim") is not False or
            audit["technical_failed"] != 0):
        raise EvidenceError("RECEIPT_SOURCE_NOT_VERIFIED")
    runner = receipt.get("public_runner")
    if (not isinstance(runner, dict) or runner.get("repository") != REPO or
            not isinstance(runner.get("run_id"), str) or
            not RUN_ID.fullmatch(runner["run_id"]) or
            not isinstance(runner.get("run_attempt"), str) or
            not RUN_ID.fullmatch(runner["run_attempt"])):
        raise EvidenceError("INVALID_RUNNER_ID")
    unwrapped = {k: v for k, v in receipt.items()
                 if k not in ("public_runner", "source_receipt_sha256")}
    digest = hashlib.sha256(_canonical(unwrapped)).hexdigest()
    if (receipt.get("source_receipt_sha256") != digest or
            bridge.get("schema") != "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1" or
            bridge.get("source_receipt_sha256") != digest or
            bridge.get("source_receipt_key") != receipt.get("receipt_key") or
            any(bridge.get(k) != receipt.get(k) for k in (
                "scope_digest_sha256", "utc_closed_epoch_1h_ms", "identity_universe"))):
        raise EvidenceError("CANONICAL_PAIR_HASH_MISMATCH")
    deferred = bridge.get("deferred_symbols")
    if (type(bridge.get("raw_prefilter_symbols")) is not int or
            type(bridge.get("exported_symbols")) is not int or
            not isinstance(deferred, dict) or
            bridge["raw_prefilter_symbols"] != bridge["exported_symbols"] + len(deferred) or
            bridge.get("orders_sent") != 0 or
            bridge.get("notifications_sent") != 0 or
            bridge.get("private_strategy_evaluated") != 0 or
            bridge.get("live_al_claim") is not False):
        raise EvidenceError("UNSAFE_BRIDGE")
    return {
        "stamp": stamp, "run_id": int(runner["run_id"]),
        "run_attempt": int(runner["run_attempt"]),
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "bridge_sha256": hashlib.sha256(bridge_bytes).hexdigest(),
        "pass": audit["technical_pass"], "warmup": audit["technical_warmup"],
        "failed": audit["technical_failed"], "scanned": receipt["technical_scanned"],
        "receipt_runner_id": runner["run_id"],
        "status_accounting_ok": receipt["status_accounting_ok"],
        "source_qa_success": receipt["source_qa_success"],
        "orders_sent": receipt["orders_sent"],
        "notifications_sent": receipt["notifications_sent"],
        "private_strategy_evaluated": receipt["private_strategy_evaluated"],
        "live_al_claim": receipt["live_al_claim"],
    }


def fetch_github_run(run_id, token):
    """Read only one allowlisted public Actions endpoint; never log the token."""
    if type(run_id) is not int or run_id <= 0:
        raise EvidenceError("INVALID_RUN_ID")
    if not isinstance(token, str) or not token:
        raise EvidenceError("MISSING_READ_TOKEN")
    req = Request(
        f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": "Bearer " + token,
            "User-Agent": "XRAY519-READONLY-EVIDENCE/1",
        },
    )
    try:
        with urlopen(req, timeout=7) as response:
            if response.status != 200:
                raise EvidenceError("GITHUB_RUN_HTTP_UNAVAILABLE")
            raw = response.read(MAX_RUN_JSON + 1)
        if len(raw) > MAX_RUN_JSON:
            raise EvidenceError("GITHUB_RUN_SIZE_LIMIT")
        result = json.loads(raw)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("GITHUB_RUN_READ_FAILED") from exc
    if not isinstance(result, dict):
        raise EvidenceError("GITHUB_RUN_INVALID_JSON")
    return result


def verify_run(pair, run, cloudflare_run_id=None):
    """Verify source-run metadata independently; Cloudflare origin remains HOLD."""
    stamp = pair["stamp"]
    epoch = _epoch_dt(stamp)
    if (not isinstance(run, dict) or run.get("id") != pair["run_id"] or
            run.get("workflow_id") != WORKFLOW_ID or
            run.get("name") != WORKFLOW_NAME or
            run.get("run_attempt") != pair["run_attempt"] or
            run.get("head_branch") != "main" or
            (run.get("head_repository") or {}).get("full_name") != REPO or
            run.get("status") != "completed" or
            run.get("conclusion") != "success"):
        raise EvidenceError("GITHUB_RUN_PROVENANCE_MISMATCH")
    date = run.get("created_at")
    if not isinstance(date, str):
        raise EvidenceError("INVALID_GITHUB_RUN_TIME")
    try:
        created = datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("INVALID_GITHUB_RUN_TIME") from exc
    delta = (created - epoch).total_seconds()
    if created.tzinfo is None or delta < 0 or delta > MAX_RUN_DURATION_MIN * 60:
        raise EvidenceError("RUN_TIME_OUTSIDE_EPOCH")
    event = run.get("event")
    if event not in ("workflow_dispatch", "schedule", "push"):
        raise EvidenceError("UNEXPECTED_RUN_EVENT")
    # GitHub cannot distinguish a manual workflow_dispatch from Cloudflare
    # without independently authenticated Cloudflare log/attestation.
    cf_verified = (event == "workflow_dispatch" and
                   type(cloudflare_run_id) is int and
                   cloudflare_run_id == run["id"])
    trusted = event == "schedule" or cf_verified
    provenance = ("github_native_schedule" if event == "schedule" else
                  "cloudflare_cron_trace_exact_run" if cf_verified else
                  "unknown_external_origin")
    return {**pair, "kind": "SOURCE", "event": event,
            "trigger_provenance": provenance,
            "trigger_independently_verified": trusted,
            "conclusion": "success",
            "pair_bytes_independently_verified": True,
            "pair_canonical_independently_verified": True}


def _cloudflare_window_accepted(rows, counted_valid_hours):
    """Cloudflare log COMPLETE is a 48-epoch claim, not an ANY-event claim.

    Native GitHub-schedule origins can count toward the 48h source acceptance
    if independently verified, but cannot alone prove a Cloudflare event.
    Missing hours, source/hash failures and unknown provenance force HOLD.
    """
    if (not isinstance(rows, list) or len(rows) != 48 or
            type(counted_valid_hours) is not int or counted_valid_hours != 48):
        return False
    return (any(row.get("trigger_provenance") == "cloudflare_cron_trace_exact_run"
                for row in rows) and
            all(row.get("trigger_independently_verified") is True
                for row in rows))


def collect(root, end_stamp, run_lookup, cloudflare_proof=None):
    """Never promote a partial history: failures are reported as HOLD."""
    end = _epoch_dt(end_stamp)
    # Origin map must come from an independently authenticated Cloudflare
    # Workers Observability query, never user claims or a GitHub dispatch.
    if cloudflare_proof is None:
        cloudflare_proof = {}
    if not isinstance(cloudflare_proof, dict):
        raise EvidenceError("CLOUDFLARE_PROOF_INVALID")
    rows, diagnostics = [], {}
    cache = {}
    for i in range(48):
        stamp = (end - timedelta(hours=i)).strftime("%Y%m%dT%H00Z")
        try:
            pair = read_pair(root, stamp)
            rid = pair["run_id"]
            if rid not in cache:
                cache[rid] = run_lookup(rid)
            record = verify_run(pair, cache[rid], cloudflare_proof.get(stamp))
            rows.append(record)
            if not record["trigger_independently_verified"]:
                diagnostics[stamp] = ["CLOUDFLARE_OR_MANUAL_ORIGIN_UNVERIFIED"]
        except EvidenceError as exc:
            diagnostics[stamp] = [str(exc)]
    evaluation = evaluate_public_window(rows, end_stamp=end_stamp)
    return {
        "schema": "XRAY519_TRUSTED_PUBLIC_EVIDENCE_READBACK_V1",
        "mode": "READONLY_PUBLIC_AUDIT_NOT_FULL_FINAL",
        "end_stamp": end_stamp,
        "pair_and_run_verified_count": len(rows),
        "fully_qualified_source_hours": evaluation["counted_valid_hours"],
        "conditional_public_gate_pass": evaluation["conditional_public_gate_pass"],
        "diagnostics": dict(sorted(diagnostics.items())),
        "acceptance": evaluation,
        # A successful API lookup with one matched event is not proof that
        # every source epoch has trusted origin. Gate on per-epoch records.
        "cloudflare_origin_verified_hours":
            sum(1 for row in rows
                if row["trigger_provenance"] == "cloudflare_cron_trace_exact_run"),
        "cloudflare_log_verified":
            _cloudflare_window_accepted(rows, evaluation["counted_valid_hours"]),
        "private_p30_verified": False,
        "full_final_start": False,
    }


def main():
    """Local/Actions CLI. Prints aggregate status, no symbol list or secrets."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--end-stamp", required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    result = collect(args.root, args.end_stamp,
                     lambda rid: fetch_github_run(rid, token))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
