"""Synthetic only: structurally linked receipt+bridge fixtures, NOT Binance data."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json


def fixture_pair():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    epoch_ms = int(now.timestamp() * 1000)
    n = 518
    names = [f"XR{i:04d}USDT" for i in range(n)]
    rows = [{
        "symbol": sym,
        "identity": "SPOT_USDT_TRADING",
        "technical_data_quality": "PASS",
        "buy_candidate": False,
        "orders_sent": 0,
        "notifications_sent": 0,
    } for sym in names]
    source = {
        "schema": "XRAY_519_SOURCE_TECH_RESEARCH_V1",
        "source": "BINANCE_PUBLIC_SPOT_REST",
        "run_kind": "RESEARCH_ONLY_NO_AL",
        "http_provider_used": True,
        "source_qa_success": True,
        "scope_stable": True,
        "epoch_stable": True,
        "complete_identity_scope": True,
        "technical_failed": 0,
        "technical_pass": n,
        "technical_warmup": 0,
        "identity_universe": n,
        "markets_selected": n,
        "technical_scanned": n,
        "technical_frames_requested": 3 * n,
        "orders_sent": 0,
        "notifications_sent": 0,
        "private_strategy_evaluated": 0,
        "live_al_claim": False,
        "scope_digest_sha256": "a" * 64,
        "receipt_key": "OFFLINE_FIXTURE_NOT_LIVE",
        "utc_closed_epoch_1h_ms": epoch_ms - 1,
        "start_server_ms": epoch_ms + 60_000,
        "end_server_ms": epoch_ms + 300_000,
        "results": rows,
    }
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    published = {
        **source,
        "source_receipt_sha256": digest,
        "public_runner": {
            "repository": "gokaydonmez39-jpg/xray-519-source-qa",
            "runner_type": "GITHUB_HOSTED_STANDARD_PUBLIC",
            "run_id": "42223913661",
            "run_attempt": "1",
        },
    }
    bridge = {
        "schema": "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1",
        "source": "BINANCE_PUBLIC_SPOT_REST",
        "source_receipt_sha256": digest,
        "source_receipt_key": source["receipt_key"],
        "scope_digest_sha256": source["scope_digest_sha256"],
        "identity_universe": n,
        "utc_closed_epoch_1h_ms": epoch_ms - 1,
        "source_start_server_ms": source["start_server_ms"],
        "source_end_server_ms": source["end_server_ms"],
        "transport_profile": "FULL_QUALITY_READY_V2",
        "markets": {sym: {} for sym in names},
        "deferred_symbols": {},
        "exported_symbols": n,
        "transport_ready_count": n,
        "transport_deferred_count": 0,
        "orders_sent": 0,
        "notifications_sent": 0,
        "private_strategy_evaluated": 0,
        "live_al_claim": False,
    }
    stamp = now.strftime("%Y/%m/%d/%Y%m%dT%H00Z-n518.json.gz")
    return (
        ("receipts/" + stamp, "bridges/" + stamp),
        gzip.compress(json.dumps(published, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode(), mtime=0),
        gzip.compress(json.dumps(bridge, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode(), mtime=0),
        published, bridge
    )
