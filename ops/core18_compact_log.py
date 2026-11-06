"""Bounded, non-trading CORE18 input log from a completed public source receipt.

This does not evaluate the private strategy, authorize an AL, write Sheets or
create new external calls. A reader must independently verify the complete
GitHub workflow, persisted source/bridge readback and source provenance.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math

CORE18 = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
    "NEARUSDT", "SUIUSDT", "UNIUSDT", "BCHUSDT", "XLMUSDT", "HBARUSDT",
)
FIELDS = (
    "last_closed_price", "ema20_4h", "ema20_4h_previous",
    "last_closed_price_4h", "last10_low_1h", "prev20_high_1h",
    "quote_rvol20_1h", "rsi14_wilder_1h",
)
HOUR_MS = 3_600_000
FOUR_HOUR_MS = 4 * HOUR_MS


def build(report: dict, raw_source: bytes) -> dict:
    """Return one fail-closed public input projection; never emit candidates."""
    safe = {
        "schema": "XRAY_PUBLIC_CORE18_CLOSED_BAR_INPUTS_V1",
        "research_only": True,
        "orders_sent": 0,
        "notifications_sent": 0,
        "full_final_start": False,
        "source_sha256": hashlib.sha256(raw_source).hexdigest(),
    }

    def hold(reason: str) -> dict:
        return {**safe, "status": "HOLD", "reason": reason, "records": []}

    try:
        if not isinstance(report, dict) or not isinstance(raw_source, bytes):
            return hold("SOURCE_INPUT_NOT_STRUCTURED")
        canonical = json.dumps(
            report, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if canonical != raw_source:
            return hold("SOURCE_RAW_BYTES_NOT_CANONICAL")
        if (report.get("source_qa_success") is not True or
                report.get("scope_stable") is not True or
                report.get("epoch_stable") is not True or
                report.get("complete_identity_scope") is not True or
                report.get("orders_sent") != 0 or
                report.get("notifications_sent") != 0):
            return hold("SOURCE_RECEIPT_NOT_SAFE")
        universe = report.get("identity_universe")
        if (type(universe) is not int or universe < 401 or universe > 564 or
                report.get("markets_selected") != universe or
                not isinstance(report.get("results"), list) or
                len(report["results"]) != universe):
            return hold("DYNAMIC_SOURCE_IDENTITY_INCOMPLETE")
        stamp = report.get("utc_closed_epoch_1h_ms")
        start = report.get("start_server_ms")
        if (type(stamp) is not int or type(start) is not int or
                stamp != start // HOUR_MS * HOUR_MS - 1):
            return hold("SOURCE_EPOCH_NOT_VERIFIED")
        expected_4h = start // FOUR_HOUR_MS * FOUR_HOUR_MS - 1
        source_rows = {}
        for row in report["results"]:
            if not isinstance(row, dict) or not isinstance(row.get("symbol"), str):
                return hold("MALFORMED_SOURCE_ROW")
            if row["symbol"] in source_rows:
                return hold("DUPLICATE_SOURCE_ROW")
            source_rows[row["symbol"]] = row
        records = []
        for symbol in CORE18:
            row = source_rows.get(symbol)
            if not row or row.get("technical_data_quality") != "PASS":
                return hold("CORE18_SOURCE_FRAME_NOT_READY")
            if row.get("frame_quality") != {"1h": "PASS", "4h": "PASS", "1d": "PASS"}:
                return hold("CORE18_FRAME_QUALITY_INCOMPLETE")
            technical = row.get("technical")
            snapshot = row.get("liquidity_snapshot")
            if not isinstance(technical, dict) or not isinstance(snapshot, dict):
                return hold("CORE18_SOURCE_INPUT_MISSING")
            if snapshot.get("ticker_within_120s") is not True:
                return hold("CORE18_TICKER_NOT_FRESH")
            if technical.get("asof_closed_utc_ms") != {
                "1h": stamp, "4h": expected_4h,
                "1d": start // (24 * HOUR_MS) * 24 * HOUR_MS - 1
            }:
                return hold("CORE18_BAR_ASOF_MISMATCH")
            values = {}
            for field in FIELDS:
                value = technical.get(field)
                if (type(value) not in (int, float) or
                        not math.isfinite(value) or
                        (field not in ("quote_rvol20_1h", "rsi14_wilder_1h")
                         and value <= 0)):
                    return hold("CORE18_INDICATOR_INVALID")
                values[field] = value
            quote = snapshot.get("rolling_24h_quote_usdt")
            spread = snapshot.get("spread_bp")
            if (type(quote) not in (int, float) or
                    type(spread) not in (int, float) or
                    not math.isfinite(quote) or not math.isfinite(spread) or
                    quote < 0 or spread < 0):
                return hold("CORE18_LIQUIDITY_INVALID")
            latest = values["ema20_4h"]
            prev = values["ema20_4h_previous"]
            close_4h = values["last_closed_price_4h"]
            expected = (19 / 21) * prev + (2 / 21) * close_4h
            if abs(latest - expected) > max(1e-9, abs(expected) * 1e-12):
                return hold("CORE18_EMA_RECURRENCE_MISMATCH")
            if values["last10_low_1h"] > values["last_closed_price"]:
                return hold("CORE18_STOP_WINDOW_CONTRADICTION")
            records.append({
                "symbol": symbol, **values, "rolling_24h_quote_usdt": quote,
                "spread_bp": spread
            })
        if len(records) != len(CORE18):
            return hold("CORE18_CARDINALITY_MISMATCH")
        epoch = datetime.fromtimestamp((stamp + 1) / 1000, timezone.utc)
        return {
            **safe, "status": "PASS_18OF18_SOURCE_INPUTS_ONLY",
            "epoch_utc": epoch.isoformat().replace("+00:00", "Z"),
            "source_universe": universe,
            "scope_digest_sha256": report.get("scope_digest_sha256"),
            "record_count": len(records),
            "records": records,
        }
    except (OverflowError, UnicodeError, ValueError, TypeError, KeyError):
        return hold("CORE18_SOURCE_PROJECTION_EXCEPTION")
