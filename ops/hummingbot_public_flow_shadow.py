"""XRAY source bridge: Hummingbot-method taker-flow diagnostics ONLY.

Independent implementation inspired by Hummingbot v2.17.0 BinanceSpotCandles.
Not the Hummingbot engine. NO external API calls, orders, notifications, live
AL authority, new paid services, WSS, or changes to source bridge payloads.
"""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SCHEMA = "XRAY_HUMMINGBOT_METHOD_FLOW_SHADOW_V1"
BRIDGE_SCHEMA = "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1"
FRAMES = {"1h": (3_600_000, 100), "4h": (14_400_000, 70), "1d": (86_400_000, 60)}
WINDOW_HOURS = 20
MAX_GZIP_BYTES = 8 * 1024 * 1024
MAX_RAW_BYTES = 24 * 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class SourceHold(ValueError):
    """Unsafe or unverifiable source evidence; never claim shadow PASS."""


def _finite_nonnegative(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise SourceHold("INVALID_NONNEGATIVE_NUMBER")
    return float(value)


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise SourceHold("BAD_EVIDENCE_SHA")
    return value


def _validate_frame(bars: object, period: int, count: int, expected_close: int) -> list[dict]:
    if not isinstance(bars, list) or len(bars) != count:
        raise SourceHold("BAD_FRAME_HISTORY_COUNT")
    prev_close = None
    for row in bars:
        if not isinstance(row, dict) or set(row) != {
            "open_ms", "close_ms", "o", "h", "l", "c", "base_volume",
            "quote_volume", "trades", "taker_quote",
        }:
            raise SourceHold("BAD_FRAME_SCHEMA")
        op, cl = row["open_ms"], row["close_ms"]
        if type(op) is not int or type(cl) is not int or op % period != 0 or cl != op + period - 1:
            raise SourceHold("BAD_FRAME_ALIGNMENT")
        if prev_close is not None and cl - prev_close != period:
            raise SourceHold("FRAME_GAP_OR_DUPLICATE")
        if cl > expected_close:
            raise SourceHold("FUTURE_OR_FORMING_FRAME")
        prev_close = cl
        opening = _finite_nonnegative(row["o"])
        high = _finite_nonnegative(row["h"])
        low = _finite_nonnegative(row["l"])
        close = _finite_nonnegative(row["c"])
        base_volume = _finite_nonnegative(row["base_volume"])
        quote = _finite_nonnegative(row["quote_volume"])
        taker = _finite_nonnegative(row["taker_quote"])
        if low <= 0 or low > min(opening, close) or high < max(opening, close, low):
            raise SourceHold("INVALID_CANDLE_GEOMETRY")
        if taker > quote + max(1e-9, abs(quote) * 1e-12):
            raise SourceHold("TAKER_EXCEEDS_QUOTE")
        if type(row["trades"]) is not int or row["trades"] < 0:
            raise SourceHold("BAD_TRADE_COUNT")
        if base_volume == 0 and (quote != 0 or taker != 0 or row["trades"] != 0):
            raise SourceHold("INCONSISTENT_ZERO_VOLUME")
    if prev_close != expected_close:
        raise SourceHold("STALE_FRAME")
    return bars


def _validate_document(document: object) -> tuple[dict, int, int]:
    if not isinstance(document, dict):
        raise SourceHold("BAD_BRIDGE_TYPE")
    if document.get("schema") != BRIDGE_SCHEMA or document.get("transport_profile") != "FULL_QUALITY_READY_V2":
        raise SourceHold("BAD_BRIDGE_PROFILE")
    if document.get("source") != "BINANCE_PUBLIC_SPOT_REST":
        raise SourceHold("UNSUPPORTED_SOURCE")
    if document.get("disposition") != "PUBLIC_DATA_ONLY_PRIVATE_STRATEGY_NOT_EVALUATED":
        raise SourceHold("UNEXPECTED_SOURCE_DISPOSITION")
    if any(type(document.get(k)) is not int or document[k] != 0 for k in
           ("orders_sent", "notifications_sent", "private_strategy_evaluated")):
        raise SourceHold("SOURCE_EXECUTION_VIOLATION")
    if document.get("live_al_claim") is not False:
        raise SourceHold("UNAUTHORIZED_AL_CLAIM")
    for k in ("source_receipt_sha256", "scope_digest_sha256"):
        _require_digest(document.get(k))
    identity = document.get("identity_universe")
    ready = document.get("transport_ready_count")
    deferred_count = document.get("transport_deferred_count")
    markets = document.get("markets")
    deferred = document.get("deferred_symbols")
    if any(type(k) is not int for k in (identity, ready, deferred_count)):
        raise SourceHold("INVALID_SCOPE_COUNTER")
    if not (401 <= identity <= 564) or not isinstance(markets, dict) or not isinstance(deferred, dict):
        raise SourceHold("BAD_SOURCE_SCOPE")
    if ready != len(markets) or deferred_count != len(deferred) or identity != ready + deferred_count:
        raise SourceHold("SOURCE_SCOPE_NOT_RECONCILED")
    if set(markets).intersection(deferred):
        raise SourceHold("DUPLICATE_READY_DEFERRED_SYMBOL")
    end = document.get("utc_closed_epoch_1h_ms")
    origin = document.get("source_start_server_ms")
    if type(end) is not int or type(origin) is not int:
        raise SourceHold("BAD_SOURCE_CLOCK")
    if end != (origin // FRAMES["1h"][0]) * FRAMES["1h"][0] - 1:
        raise SourceHold("BRIDGE_CLOCK_EPOCH_MISMATCH")
    if not (0 <= origin - (end + 1) < FRAMES["1h"][0]):
        raise SourceHold("BRIDGE_CLOCK_OUT_OF_RANGE")
    return markets, identity, end


def summarize(document: object, *, bridge_file_sha256: str) -> dict:
    """Aggregate closed 1H taker flow; 0 trading and 0 candidate authority."""
    markets, identity, end = _validate_document(document)
    _require_digest(bridge_file_sha256)
    counts: Counter[str] = Counter()
    net_delta_quote = 0.0
    total_quote = 0.0
    for symbol, info in markets.items():
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{1,60}USDT", symbol):
            raise SourceHold("BAD_SYMBOL")
        if not isinstance(info, dict) or set(info) != {"frames", "liquidity_snapshot"}:
            raise SourceHold("BAD_MARKET_OBJECT")
        frames = info["frames"]
        if not isinstance(frames, dict) or set(frames) != set(FRAMES):
            raise SourceHold("MISSING_FRAMES")
        for frame, (period, count) in FRAMES.items():
            expected = ((end + 1) // period) * period - 1
            _validate_frame(frames[frame], period, count, expected)
        liquidity = info["liquidity_snapshot"]
        if not isinstance(liquidity, dict) or liquidity.get("ticker_within_120s") is not True:
            raise SourceHold("MISSING_FRESH_LIQUIDITY")
        _finite_nonnegative(liquidity.get("rolling_24h_quote_usdt"))
        _finite_nonnegative(liquidity.get("spread_bp"))
        recent = frames["1h"][-WINDOW_HOURS:]
        quote_sum = sum(float(bar["quote_volume"]) for bar in recent)
        taker_sum = sum(float(bar["taker_quote"]) for bar in recent)
        if not math.isfinite(quote_sum) or not math.isfinite(taker_sum):
            raise SourceHold("NONFINITE_AGGREGATION")
        if quote_sum == 0:
            counts["UNKNOWN_ZERO_QUOTE"] += 1
            continue
        delta = 2 * taker_sum - quote_sum
        ratio = delta / quote_sum
        if not math.isfinite(ratio) or abs(ratio) > 1.0 + 1e-9:
            raise SourceHold("OUT_OF_RANGE_TAKER_IMBALANCE")
        if ratio > 0.02:
            counts["TAKER_BUY_DOMINANT"] += 1
        elif ratio < -0.02:
            counts["TAKER_SELL_DOMINANT"] += 1
        else:
            counts["NEAR_BALANCED"] += 1
        net_delta_quote += delta
        total_quote += quote_sum
    if sum(counts.values()) != len(markets):
        raise SourceHold("FLOW_COVERAGE_MISMATCH")
    if not math.isfinite(net_delta_quote) or not math.isfinite(total_quote):
        raise SourceHold("NONFINITE_SUMMARY")
    if document["transport_deferred_count"] + len(markets) != identity:
        raise SourceHold("UNACCOUNTED_SCOPE")
    return {
        "schema": SCHEMA,
        "method_reference": "HUMMINGBOT_V2_17_0_BINANCE_CANDLES_REIMPLEMENTED_NO_DEPENDENCY",
        "source_receipt_sha256": document["source_receipt_sha256"],
        "scope_digest_sha256": document["scope_digest_sha256"],
        "bridge_file_sha256": bridge_file_sha256,
        "epoch_closed_1h_ms": end,
        "identity_symbols": identity,
        "ready_symbols": len(markets),
        "deferred_symbols": document["transport_deferred_count"],
        "taker_flow_20h_counts": dict(sorted(counts.items())),
        "taker_flow_20h_net_quote_usdt": round(net_delta_quote, 2),
        "taker_flow_20h_total_quote_usdt": round(total_quote, 2),
        "flow_metric": "SUM_LAST_20_CLOSED_1H_OF_2X_TAKER_BUY_QUOTE_MINUS_TOTAL_QUOTE",
        "complete_bar_validation": True,
        "research_only": True,
        "orders_permitted": False,
        "notifications_permitted": False,
        "full_final_start": False,
        "al_authority": False,
        "hummingbot_runtime_started": False,
        "network_requests": 0,
    }


def _reject_duplicate_pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceHold("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def read_gzip(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise SourceHold("BAD_BRIDGE_FILE")
    size = path.stat().st_size
    if not (0 < size <= MAX_GZIP_BYTES):
        raise SourceHold("BAD_GZIP_SIZE")
    compressed = path.read_bytes()
    digest = hashlib.sha256(compressed).hexdigest()
    with gzip.open(path, "rb") as stream:
        raw = stream.read(MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES:
        raise SourceHold("DECOMPRESSION_LIMIT")
    document = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(SourceHold("NONFINITE_JSON_CONSTANT")))
    return summarize(document, bridge_file_sha256=digest)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("USAGE: python3 -m ops.hummingbot_public_flow_shadow <existing_bridge.json.gz>", file=sys.stderr)
        return 2
    try:
        print(json.dumps(read_gzip(Path(argv[1])), sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
        print("HUMMINGBOT_PUBLIC_FLOW_SHADOW_HOLD_NO_AL_AUTHORITY", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
