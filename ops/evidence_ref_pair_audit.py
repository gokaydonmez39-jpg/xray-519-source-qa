"""Bounded, source-backed checks before any evidence-ref write.

The exact pair must originate from the same genuine public source scan.
This module does not establish Git remote delivery and never authorizes AL.
"""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import re

REPO = "gokaydonmez39-jpg/xray-519-source-qa"
SOURCE_CAP = 2_500_000
BRIDGE_CAP = 24 * 1024 * 1024
RECEIPT_GZIP_CAP = 200_000
BRIDGE_GZIP_CAP = 8 * 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_SYMBOL = re.compile(r"[A-Z0-9]{2,60}USDT\Z")


class PairRejected(ValueError):
    pass


def reject(reason: str) -> None:
    raise PairRejected(reason)


def decompress_json(blob: bytes, *, compressed_cap: int, raw_cap: int) -> dict:
    if type(blob) is not bytes or not 0 < len(blob) <= compressed_cap:
        reject("COMPRESSED_SIZE_INVALID")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as stream:
            raw = stream.read(raw_cap + 1)
        if len(raw) > raw_cap:
            reject("DECOMPRESSED_EVIDENCE_LIMIT")
        doc = json.loads(raw.decode("utf-8", "strict"))
    except (OSError, EOFError, UnicodeError, ValueError, TypeError,
            json.JSONDecodeError) as exc:
        if isinstance(exc, PairRejected):
            raise
        reject("MALFORMED_COMPRESSED_EVIDENCE")
    if type(doc) is not dict:
        reject("COMPRESSED_JSON_NOT_OBJECT")
    return doc


def audit_pair(receipt_blob: bytes, bridge_blob: bytes,
               receipt_path: str, bridge_path: str) -> dict:
    """Local exact pair safety, clock, identity and cross-document SHA audit."""
    published = decompress_json(
        receipt_blob, compressed_cap=RECEIPT_GZIP_CAP, raw_cap=SOURCE_CAP)
    bridge = decompress_json(
        bridge_blob, compressed_cap=BRIDGE_GZIP_CAP, raw_cap=BRIDGE_CAP)
    raw_source = {k: v for k, v in published.items()
                  if k not in ("public_runner", "source_receipt_sha256")}
    try:
        canonical = json.dumps(raw_source, sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False,
                               allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        reject("NON_CANONICAL_SOURCE")
    if len(canonical) > SOURCE_CAP:
        reject("SOURCE_RAW_SIZE_INVALID")
    digest = hashlib.sha256(canonical).hexdigest()
    if (published.get("source_receipt_sha256") != digest or
            bridge.get("source_receipt_sha256") != digest):
        reject("SOURCE_RECEIPT_BRIDGE_SHA_MISMATCH")
    runner = published.get("public_runner")
    if (type(runner) is not dict
            or runner.get("repository") != REPO
            or runner.get("runner_type") != "GITHUB_HOSTED_STANDARD_PUBLIC"
            or type(runner.get("run_id")) is not str
            or not re.fullmatch(r"[1-9][0-9]{0,19}", runner["run_id"])
            or type(runner.get("run_attempt")) is not str
            or not re.fullmatch(r"[1-9][0-9]{0,2}", runner["run_attempt"])):
        reject("PUBLIC_RUNNER_PROVENANCE_MISSING")
    if (published.get("schema") != "XRAY_519_SOURCE_TECH_RESEARCH_V1"
            or published.get("source") != "BINANCE_PUBLIC_SPOT_REST"
            or published.get("run_kind") != "RESEARCH_ONLY_NO_AL"
            or published.get("http_provider_used") is not True
            or published.get("source_qa_success") is not True
            or published.get("scope_stable") is not True
            or published.get("epoch_stable") is not True
            or published.get("complete_identity_scope") is not True
            or published.get("technical_failed") != 0
            or published.get("live_al_claim") is not False
            or published.get("orders_sent") != 0
            or published.get("notifications_sent") != 0
            or published.get("private_strategy_evaluated") != 0):
        reject("SOURCE_SAFETY_OR_QUALITY_HOLD")
    n = published.get("identity_universe")
    source_rows = published.get("results")
    if (type(n) is not int or not 401 <= n <= 564
            or published.get("markets_selected") != n
            or published.get("technical_scanned") != n
            or published.get("technical_frames_requested") != 3 * n
            or type(source_rows) is not list or len(source_rows) != n
            or any(type(published.get(k)) is not int or
                   published[k] < 0 for k in (
                       "technical_pass", "technical_warmup", "technical_failed"))
            or sum(published[k] for k in (
                "technical_pass", "technical_warmup", "technical_failed")) != n):
        reject("SOURCE_DYNAMIC_SCOPE_INCOMPLETE")
    names = []
    for row in source_rows:
        if (type(row) is not dict or
                type(row.get("symbol")) is not str or
                not SAFE_SYMBOL.fullmatch(row["symbol"]) or
                row.get("buy_candidate") is not False or
                row.get("orders_sent") != 0 or
                row.get("notifications_sent") != 0):
            reject("SOURCE_UNSAFE_OR_INVALID_SYMBOL_ROW")
        names.append(row["symbol"])
    if len(set(names)) != n:
        reject("SOURCE_SYMBOL_DUPLICATE")
    stamp = published.get("utc_closed_epoch_1h_ms")
    start = published.get("start_server_ms")
    end = published.get("end_server_ms")
    if (type(stamp) is not int or type(start) is not int
            or type(end) is not int or
            (stamp + 1) % 3_600_000 != 0 or
            not stamp + 6_000 <= start <= end <= stamp + 1 + 900_000):
        reject("SOURCE_EPOCH_OR_FRESHNESS_INVALID")
    hour = datetime.fromtimestamp((stamp + 1) / 1000, timezone.utc)
    suffix = hour.strftime("%Y/%m/%d/%Y%m%dT%H00Z-n") + str(n) + ".json.gz"
    if (receipt_path != "receipts/" + suffix or
            bridge_path != "bridges/" + suffix):
        reject("PAIR_FILENAME_EPOCH_NOT_SAME_SOURCE")
    scope_hash = published.get("scope_digest_sha256")
    if (type(scope_hash) is not str or
            not HEX64.fullmatch(scope_hash) or
            bridge.get("scope_digest_sha256") != scope_hash):
        reject("SOURCE_SCOPE_SHA_MISMATCH")
    if (bridge.get("schema") != "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1"
            or bridge.get("source") != "BINANCE_PUBLIC_SPOT_REST"
            or bridge.get("identity_universe") != n
            or bridge.get("source_receipt_key") != published.get("receipt_key")
            or bridge.get("utc_closed_epoch_1h_ms") != stamp
            or bridge.get("source_start_server_ms") != start
            or bridge.get("source_end_server_ms") != end
            or bridge.get("transport_profile") != "FULL_QUALITY_READY_V2"
            or bridge.get("orders_sent") != 0
            or bridge.get("notifications_sent") != 0
            or bridge.get("private_strategy_evaluated") != 0
            or bridge.get("live_al_claim") is not False):
        reject("BRIDGE_SOURCE_OR_SAFETY_MISMATCH")
    ready, deferred = bridge.get("markets"), bridge.get("deferred_symbols")
    if (type(ready) is not dict or type(deferred) is not dict
            or set(ready) & set(deferred)
            or set(ready) | set(deferred) != set(names)
            or bridge.get("exported_symbols") != len(ready)
            or bridge.get("transport_ready_count") != len(ready)
            or bridge.get("transport_deferred_count") != len(deferred)
            or len(ready) + len(deferred) != n):
        reject("BRIDGE_FULL_IDENTITY_NOT_ACCOUNTED")
    if any(not isinstance(v, (str, dict)) or not v
           for v in deferred.values()):
        reject("BRIDGE_DEFERRED_REASON_MISSING")
    for sym in ready:
        row = source_rows[names.index(sym)]
        if row.get("technical_data_quality") != "PASS":
            reject("BRIDGE_UNREADY_SYMBOL_ASSERTED_PASS")
    return {
        "status": "PAIR_LOCAL_SOURCE_AND_SCOPE_SHA_PASS_NOT_REMOTE",
        "epoch_utc": hour.isoformat().replace("+00:00", "Z"),
        "identity_symbols": n,
        "ready": len(ready),
        "deferred": len(deferred),
        "source_sha256": digest,
        "receipt_gzip_sha256": hashlib.sha256(receipt_blob).hexdigest(),
        "bridge_gzip_sha256": hashlib.sha256(bridge_blob).hexdigest(),
        "orders_sent": 0, "notifications_sent": 0,
        "full_final_start": False,
    }
