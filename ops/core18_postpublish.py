"""Fail-closed local receipt/bridge gate; invoked only AFTER Git remote readback.

No network, secrets, orders, alert or Sheets access. This module does not claim
that local evidence proves remote delivery: the calling workflow MUST complete
publish_git.py readback before invoking this gate.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
from pathlib import Path

from ops.core18_compact_log import CORE18, build

MAX_SOURCE = 2_500_000
MAX_RECEIPT_GZIP = 200_000
MAX_BRIDGE_GZIP = 8_388_608
MAX_BRIDGE_RAW = 25_165_824
REPOSITORY = "gokaydonmez39-jpg/xray-519-source-qa"


def _bounded_gzip(blob: bytes, limit: int) -> dict:
    with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as gz:
        data = gz.read(limit + 1)
    if len(data) > limit:
        raise ValueError("DECOMPRESSED_EVIDENCE_TOO_LARGE")
    value = json.loads(data)
    if type(value) is not dict:
        raise ValueError("EVIDENCE_NOT_JSON_OBJECT")
    return value


def _hold(reason: str) -> dict:
    return {
        "schema": "XRAY_PUBLIC_CORE18_CLOSED_BAR_INPUTS_V1",
        "status": "HOLD", "reason": reason,
        "records": [], "research_only": True,
        "orders_sent": 0, "notifications_sent": 0,
        "full_final_start": False
    }


def verify_pair_then_project(
    raw_source: bytes,
    published_gzip: bytes,
    bridge_gzip: bytes,
    *,
    runner_id: str,
    run_attempt: int,
) -> dict:
    """Verify local source, publication and transport SHA before projection.

    The separate workflow must have already performed independent remote
    Git readback of EXACT published gzip blobs. This function cannot infer
    remote attestation on its own and never grants trade/notification rights.
    """
    try:
        if (type(raw_source) is not bytes or len(raw_source) == 0
                or len(raw_source) > MAX_SOURCE
                or type(published_gzip) is not bytes or len(published_gzip) == 0
                or len(published_gzip) > MAX_RECEIPT_GZIP
                or type(bridge_gzip) is not bytes or len(bridge_gzip) == 0
                or len(bridge_gzip) > MAX_BRIDGE_GZIP):
            return _hold("EVIDENCE_INPUT_SIZE_OR_TYPE")
        if (type(runner_id) is not str
                or re.fullmatch(r"[1-9][0-9]{0,19}", runner_id) is None
                or type(run_attempt) is not int or not 1 <= run_attempt <= 100):
            return _hold("RUNNER_IDENTITY_INVALID")
        source = json.loads(raw_source)
        published = _bounded_gzip(published_gzip, MAX_SOURCE)
        bridge = _bounded_gzip(bridge_gzip, MAX_BRIDGE_RAW)
        if type(source) is not dict:
            return _hold("SOURCE_NOT_JSON_OBJECT")
        digest = hashlib.sha256(raw_source).hexdigest()
        if (published.get("source_receipt_sha256") != digest
                or bridge.get("source_receipt_sha256") != digest):
            return _hold("SOURCE_PUBLISHED_BRIDGE_SHA_MISMATCH")
        provenance = published.get("public_runner")
        if (type(provenance) is not dict
                or provenance.get("repository") != REPOSITORY
                or provenance.get("run_id") != runner_id
                or provenance.get("run_attempt") != str(run_attempt)
                or provenance.get("runner_type") != "GITHUB_HOSTED_STANDARD_PUBLIC"):
            return _hold("PUBLISH_RUNNER_PROVENANCE_MISMATCH")
        source_from_publication = {
            k: v for k, v in published.items()
            if k not in ("source_receipt_sha256", "public_runner")
        }
        if source_from_publication != source:
            return _hold("PUBLISHED_SOURCE_CONTENT_MISMATCH")
        for field in ("source_receipt_key", "scope_digest_sha256",
                      "identity_universe", "utc_closed_epoch_1h_ms"):
            other = "receipt_key" if field == "source_receipt_key" else field
            if bridge.get(field) != source.get(other):
                return _hold("BRIDGE_SOURCE_SCOPE_MISMATCH")
        if (bridge.get("schema") != "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1"
                or bridge.get("transport_profile") != "FULL_QUALITY_READY_V2"
                or bridge.get("orders_sent") != 0
                or bridge.get("notifications_sent") != 0
                or bridge.get("live_al_claim") is not False):
            return _hold("BRIDGE_PROFILE_OR_SAFETY_INVALID")
        selected, deferred = bridge.get("markets"), bridge.get("deferred_symbols")
        universe = source.get("identity_universe")
        if (type(selected) is not dict or type(deferred) is not dict
                or type(universe) is not int
                or bridge.get("exported_symbols") != len(selected)
                or bridge.get("transport_ready_count") != len(selected)
                or bridge.get("transport_deferred_count") != len(deferred)
                or len(selected) + len(deferred) != universe
                or set(selected) & set(deferred)
                or set(selected) | set(deferred) !=
                    {row.get("symbol") for row in source.get("results", [])
                     if isinstance(row, dict)}):
            return _hold("BRIDGE_IDENTITY_ACCOUNTING_INVALID")
        # A source PASS alone cannot certify a CORE18 symbol that the transport
        # explicitly DEFERRED. Require the same 18 symbols in the published
        # identity-accounted, source-ready bridge before returning any PASS.
        if not set(CORE18).issubset(selected):
            return _hold("CORE18_BRIDGE_DEFERRED")
        answer = build(source, raw_source)
        if answer.get("status") != "PASS_18OF18_SOURCE_INPUTS_ONLY":
            return answer  # Valid source, but no fabricated CORE18 PASS.
        answer["postpublish_pair_sha_verified"] = True
        answer["published_runner_id"] = runner_id
        answer["remote_readback_inferred"] = False
        return answer
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError,
            UnicodeError, ValueError, TypeError, OverflowError):
        return _hold("SOURCE_PAIR_PARSE_OR_GZIP_HOLD")


def _read_file(path: Path, cap: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise ValueError("INPUT_NOT_REGULAR_OR_TOO_LARGE")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post-remote-readback CORE18 source-only gate")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--runner-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    a = parser.parse_args(argv)
    try:
        result = verify_pair_then_project(
            _read_file(a.source, MAX_SOURCE),
            _read_file(a.receipt, MAX_RECEIPT_GZIP),
            _read_file(a.bridge, MAX_BRIDGE_GZIP),
            runner_id=a.runner_id, run_attempt=a.run_attempt,
        )
    except (OSError, ValueError):
        result = _hold("LOCAL_EVIDENCE_FILE_UNAVAILABLE")
    print("CORE18_PUBLIC_INPUTS_V1=" + json.dumps(
        result, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False))
    # Missing CORE18 quality can be healthy source HOLD, but a broken
    # publication/provenance match must fail the source workflow.
    if result["status"] == "PASS_18OF18_SOURCE_INPUTS_ONLY":
        return 0
    if result.get("reason", "").startswith((
        "CORE18_SOURCE_", "CORE18_BRIDGE_", "CORE18_FRAME_", "CORE18_TICKER_",
        "CORE18_BAR_", "CORE18_INDICATOR_", "CORE18_LIQUIDITY_",
        "CORE18_EMA_", "CORE18_STOP_", "CORE18_CARDINALITY_",
    )):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
