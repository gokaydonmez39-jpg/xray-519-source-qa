"""XRAY PUBLIC SPOT: independent, read-only versioned-scope evidence SHADOW.

This module NEVER grants legacy 519/48h acceptance, alerts, trades, or FULL FINAL.
The trusted controller must acquire Cloudflare trace -> exact GitHub run proof.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

REPO = "gokaydonmez39-jpg/xray-519-source-qa"
WORKFLOW_ID = 402070622
WORKFLOW_NAME = "XRAY 519 public Spot closed-bar research"
HOURS = 48
MIN_SCOPE, MAX_SCOPE = 401, 564
STAMP = re.compile(r"[0-9]{8}T[0-9]{2}00Z\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceHold(ValueError):
    """Invalid evidence fails closed and must never be promoted."""


def _epoch(stamp):
    if not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
        raise EvidenceHold("INVALID_EPOCH")
    try:
        dt = datetime.strptime(stamp, "%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise EvidenceHold("INVALID_EPOCH") from exc
    if dt.strftime("%Y%m%dT%H00Z") != stamp:
        raise EvidenceHold("INVALID_EPOCH")
    return dt


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EvidenceHold("INVALID_CANONICAL_JSON") from exc


def _document(path, max_compressed, max_decoded):
    if path.is_symlink() or not path.is_file():
        raise EvidenceHold("PAIR_MISSING_OR_UNSAFE")
    size = path.stat().st_size
    if not 0 < size <= max_compressed:
        raise EvidenceHold("PAIR_SIZE_INVALID")
    raw = path.read_bytes()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            uncompressed = stream.read(max_decoded + 1)
        if len(uncompressed) > max_decoded:
            raise EvidenceHold("PAIR_DECODE_LIMIT")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise EvidenceHold("DUPLICATE_JSON_KEY")
                result[key] = value
            return result
        def no_nan(_):
            raise EvidenceHold("NONFINITE_JSON")
        document = json.loads(uncompressed.decode("utf-8"),
                              object_pairs_hook=unique, parse_constant=no_nan)
    except (OSError, ValueError, UnicodeError, EOFError) as exc:
        if isinstance(exc, EvidenceHold):
            raise
        raise EvidenceHold("PAIR_INVALID_GZIP_OR_JSON") from exc
    if not isinstance(document, dict):
        raise EvidenceHold("PAIR_INVALID_OBJECT")
    return raw, document


def read_pair(root, stamp):
    """Inspect exactly one authenticated-scope archive for a single epoch."""
    epoch = _epoch(stamp)
    folder = epoch.strftime("%Y/%m/%d")
    root = Path(root)
    rdir, bdir = root / "receipts" / folder, root / "bridges" / folder
    pattern = re.compile(re.escape(stamp) + r"-n([0-9]+)\.json\.gz\Z")
    receipt_names = {p.name for p in rdir.iterdir() if pattern.fullmatch(p.name)} if rdir.is_dir() else set()
    bridge_names = {p.name for p in bdir.iterdir() if pattern.fullmatch(p.name)} if bdir.is_dir() else set()
    if not receipt_names and not bridge_names:
        raise EvidenceHold("MISSING_SOURCE")
    if receipt_names != bridge_names or len(receipt_names) != 1:
        raise EvidenceHold("CONFLICTING_OR_INCOMPLETE_SCOPE")
    filename = next(iter(receipt_names))
    n = int(pattern.fullmatch(filename).group(1))
    if not MIN_SCOPE <= n <= MAX_SCOPE or filename != f"{stamp}-n{n}.json.gz":
        raise EvidenceHold("SCOPE_NOT_FULL_OR_NONCANONICAL")
    receipt_bytes, receipt = _document(rdir / filename, 200_000, 2_500_000)
    bridge_bytes, bridge = _document(bdir / filename, 8_388_608, 24 * 1024 * 1024)
    rows = receipt.get("results")
    counters = [receipt.get(key) for key in ("technical_pass", "technical_warmup", "technical_failed")]
    if (receipt.get("schema") != "XRAY_519_SOURCE_TECH_RESEARCH_V1" or
        receipt.get("source") != "BINANCE_PUBLIC_SPOT_REST" or
        receipt.get("run_kind") != "RESEARCH_ONLY_NO_AL" or
        any(receipt.get(key) is not True for key in
            ("http_provider_used", "source_qa_success", "scope_stable",
             "epoch_stable", "complete_identity_scope", "status_accounting_ok")) or
        any(type(receipt.get(key)) is not int or receipt[key] != n for key in
            ("identity_universe", "markets_selected", "technical_scanned")) or
        type(receipt.get("technical_frames_requested")) is not int or
        receipt["technical_frames_requested"] != 3 * n or
        any(type(x) is not int or x < 0 for x in counters) or
        sum(counters) != n or counters[2] != 0 or
        receipt.get("full_technical_quality") is not (counters[0] == n) or
        receipt.get("live_source_acceptance") is not (counters[0] == n) or
        type(rows) is not list or len(rows) != n):
        raise EvidenceHold("FULL_SCOPE_ACCOUNTING_INVALID")
    symbols = set()
    qualities = {"PASS": 0, "WARMUP": 0, "FAIL": 0}
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceHold("INVALID_MARKET_ROW")
        symbol = row.get("symbol")
        if (not isinstance(symbol, str) or not symbol.endswith("USDT") or
            len(symbol) > 64 or any(ord(ch) < 33 or ch in '/\\?#&=' for ch in symbol) or
            symbol in symbols or row.get("identity") != "SPOT_USDT_TRADING" or
            row.get("research_only") is not True or row.get("buy_candidate") is not False or
            row.get("orders_sent") != 0 or row.get("notifications_sent") != 0 or
            row.get("technical_data_quality") not in qualities):
            raise EvidenceHold("INVALID_MARKET_ROW")
        symbols.add(symbol)
        qualities[row["technical_data_quality"]] += 1
    if [qualities["PASS"], qualities["WARMUP"], qualities["FAIL"]] != counters:
        raise EvidenceHold("MARKET_QUALITY_COUNTS_MISMATCH")
    close_ms = int(epoch.timestamp() * 1000) - 1
    digest = receipt.get("scope_digest_sha256")
    if (receipt.get("utc_closed_epoch_1h_ms") != close_ms or
        not isinstance(digest, str) or not SHA.fullmatch(digest) or
        receipt.get("receipt_key") != f"XRAY_519_SOURCE_TECH_RESEARCH_V1|{close_ms}|{digest}|{n}"):
        raise EvidenceHold("SCOPE_EPOCH_DIGEST_MISMATCH")
    for key in ("orders_sent", "notifications_sent", "private_strategy_evaluated"):
        if receipt.get(key) != 0 or bridge.get(key) != 0:
            raise EvidenceHold("EXECUTION_OR_ALERT_FORBIDDEN")
    if (receipt.get("live_al_claim") is not False or
        bridge.get("live_al_claim") is not False or
        receipt.get("native_wss_running") is not False or
        receipt.get("phone_delivery_ack") is not False):
        raise EvidenceHold("LIVE_OR_DEVICE_CLAIM_FORBIDDEN")
    runner = receipt.get("public_runner")
    if (not isinstance(runner, dict) or runner.get("repository") != REPO or
        any(not isinstance(runner.get(k), str) or not runner[k].isdecimal() or
            int(runner[k]) <= 0 for k in ("run_id", "run_attempt"))):
        raise EvidenceHold("INVALID_RUNNER_ID")
    original = {k: v for k, v in receipt.items()
                if k not in ("public_runner", "source_receipt_sha256")}
    source_sha = hashlib.sha256(_canonical(original)).hexdigest()
    if (receipt.get("source_receipt_sha256") != source_sha or
        bridge.get("schema") != "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1" or
        bridge.get("source_receipt_sha256") != source_sha or
        bridge.get("source_receipt_key") != receipt["receipt_key"] or
        any(bridge.get(k) != receipt[k] for k in
            ("scope_digest_sha256", "identity_universe", "utc_closed_epoch_1h_ms"))):
        raise EvidenceHold("CANONICAL_PAIR_HASH_MISMATCH")
    deferred = bridge.get("deferred_symbols")
    if (type(bridge.get("raw_prefilter_symbols")) is not int or
        type(bridge.get("exported_symbols")) is not int or
        not isinstance(deferred, dict) or
        bridge["raw_prefilter_symbols"] != bridge["exported_symbols"] + len(deferred)):
        raise EvidenceHold("BRIDGE_ACCOUNTING_INVALID")
    return {"stamp": stamp, "scope_count": n, "scope_digest_sha256": digest,
            "scope_version": f"{n}:{digest}", "run_id": int(runner["run_id"]),
            "run_attempt": int(runner["run_attempt"]), "technical_pass": counters[0],
            "technical_warmup": counters[1], "technical_failed": counters[2],
            "full_technical_quality": counters[0] == n,
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "bridge_sha256": hashlib.sha256(bridge_bytes).hexdigest()}


def verify_origin(pair, run, cloudflare_run_id=None):
    """Only exact trusted GitHub metadata or exact CF-to-run match counts."""
    try:
        started = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise EvidenceHold("INVALID_RUN_TIME") from exc
    diff = (started - _epoch(pair["stamp"])).total_seconds()
    if (not isinstance(run, dict) or run.get("id") != pair["run_id"] or
        run.get("workflow_id") != WORKFLOW_ID or run.get("name") != WORKFLOW_NAME or
        run.get("head_branch") != "main" or
        (run.get("head_repository") or {}).get("full_name") != REPO or
        run.get("run_attempt") != pair["run_attempt"] or
        run.get("status") != "completed" or run.get("conclusion") != "success" or
        started.tzinfo is None or not 0 <= diff <= 1800):
        raise EvidenceHold("RUN_METADATA_NOT_VERIFIED")
    event = run.get("event")
    if event == "schedule":
        return "github_native_schedule"
    if event == "workflow_dispatch" and type(cloudflare_run_id) is int and cloudflare_run_id == run["id"]:
        return "cloudflare_cron_trace_exact_run"
    return None


def collect_shadow(root, end_stamp, run_lookup, *, cloudflare_proof=None):
    """48h evidence observations ONLY. Never an authorizing production gate."""
    end = _epoch(end_stamp)
    if cloudflare_proof is None:
        cloudflare_proof = {}
    if not isinstance(cloudflare_proof, dict):
        raise EvidenceHold("INVALID_PROVENANCE_MAP")
    expected = [(end - timedelta(hours=i)).strftime("%Y%m%dT%H00Z") for i in range(HOURS - 1, -1, -1)]
    diagnostics, verified, origin_count, versions = {}, [], 0, []
    used_runs = set()
    for stamp in expected:
        try:
            pair = read_pair(root, stamp)
            if pair["run_id"] in used_runs:
                raise EvidenceHold("RUN_REUSED_IN_WINDOW")
            used_runs.add(pair["run_id"])
            event = verify_origin(pair, run_lookup(pair["run_id"]), cloudflare_proof.get(stamp))
            if event is None:
                diagnostics[stamp] = "ORIGIN_HOLD"
            else:
                origin_count += 1
            verified.append({"stamp": stamp, "scope_version": pair["scope_version"],
                             "origin": event, "technical_pass": pair["technical_pass"],
                             "technical_warmup": pair["technical_warmup"]})
            if not versions or versions[-1]["scope_version"] != pair["scope_version"]:
                versions.append({"from_stamp": stamp, "scope_version": pair["scope_version"]})
        except EvidenceHold as exc:
            diagnostics[stamp] = str(exc)
    return {"schema": "XRAY_PUBLIC_SCOPE_VERSION_SHADOW_V1",
            "status": "SHADOW_ONLY_NOT_RELEASE_AUTHORITY",
            "end_stamp": end_stamp, "required_distinct_utc_hours": HOURS,
            "paired_authenticated_hours": len(verified),
            "trusted_origin_hours": origin_count,
            "warmup_present_hours": sum(r["technical_warmup"] > 0 for r in verified),
            "scope_versions": versions, "diagnostics": diagnostics,
            "shadow_complete_48h": len(verified) == HOURS and origin_count == HOURS,
            "legacy_519_contract_unchanged": True,
            "full_final_start": False, "alert_release": False,
            "private_p30_verified": False, "wss_14d_verified": False,
            "paper_oos_60d_verified": False, "device_ack_verified": False}
