"""Read-only per-epoch deferred-reason summary of the public bridge.

Never prints symbol lists, candle data, secrets, trading decisions, or orders.
Runs on the same immutable gzip bridge already produced by source research.
"""
from __future__ import annotations

from collections import Counter
import gzip
import json
from pathlib import Path
import sys

MAX_GZIP_BYTES = 8 * 1024 * 1024
MAX_RAW_BYTES = 24 * 1024 * 1024
EXPECTED_PROFILE = "FULL_QUALITY_READY_V2"


def summarize(document: dict) -> dict:
    if not isinstance(document, dict) or document.get("transport_profile") != EXPECTED_PROFILE:
        raise ValueError("NOT_FULL_QUALITY_READY_V2")
    markets = document.get("markets")
    deferred = document.get("deferred_symbols")
    identity = document.get("identity_universe")
    ready = document.get("transport_ready_count")
    missing = document.get("transport_deferred_count")
    if not isinstance(markets, dict) or not isinstance(deferred, dict):
        raise ValueError("INVALID_BRIDGE_SCOPE")
    if any(type(n) is not int for n in (identity, ready, missing)):
        raise ValueError("INVALID_COUNTS")
    if not 401 <= identity <= 564 or ready != len(markets) or missing != len(deferred):
        raise ValueError("INCONSISTENT_COUNTS")
    if ready + missing != identity or set(markets).intersection(deferred):
        raise ValueError("UNRECONCILED_SCOPE")
    categories: Counter[str] = Counter()
    detail: Counter[str] = Counter()
    for reason in deferred.values():
        if isinstance(reason, str) and reason:
            categories[reason] += 1
        elif isinstance(reason, dict) and reason and all(
            isinstance(k, str) and k and isinstance(v, str) and v
            for k, v in reason.items()
        ):
            categories["FRAME_FETCH_INCOMPLETE"] += 1
            for timeframe, issue in reason.items():
                detail[timeframe + ":" + issue] += 1
        else:
            raise ValueError("INVALID_DEFERRED_REASON")
    if sum(categories.values()) != missing:
        raise ValueError("DEFERRED_REASON_SUM_INVALID")
    return {
        "event": "PUBLIC_FULL_BRIDGE_DEFERRED_REASON_SUMMARY_RESEARCH_ONLY",
        "identity_symbols": identity,
        "frames_ready": ready,
        "frames_deferred": missing,
        "reason_categories": dict(sorted(categories.items())),
        "frame_issue_details": dict(sorted(detail.items())),
        "orders_permitted": False,
        "notifications_permitted": False,
        "full_final_start": False,
    }


def read_gzip(path: Path) -> dict:
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_GZIP_BYTES:
        raise ValueError("GZIP_SIZE_INVALID")
    with gzip.open(path, "rb") as stream:
        raw = stream.read(MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("RAW_BRIDGE_OVERSIZED")
    document = json.loads(raw)
    return summarize(document)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("USAGE: bridge_reason_summary FILE.json.gz", file=sys.stderr)
        return 2
    try:
        result = read_gzip(Path(argv[1]))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("PUBLIC_DEFERRED_REASON_SUMMARY_HOLD", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
