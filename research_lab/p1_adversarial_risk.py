"""XRAY CRYPTO P1: offline, synthetic-only research gates (method-only).

This module performs no I/O, network requests, installs, orders, wallet
operations, or promotion. It is NOT Freqtrade, AGIPro, or a private strategy.
Source receipt/bridge checks here assess submitted metadata, not authenticity.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

HOUR_MS = 3_600_000
MAX_ROWS = 2_000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"[A-Z0-9]{2,30}\Z")


class ResearchRejected(ValueError):
    """Fail-closed method-only research validation failure."""


def _int(value: object) -> bool:
    return type(value) is int and value >= 0


def _num(value: object) -> bool:
    if type(value) not in (float, int):
        return False
    try:
        return math.isfinite(value) and abs(value) <= 1e15
    except (OverflowError, ValueError):
        return False


def _schema(value: object, keys: set[str], tag: str) -> Mapping:
    if type(value) is not dict or set(value) != keys:
        raise ResearchRejected(f"{tag}_SCHEMA")
    return value


def _rows(value: object) -> Sequence[dict]:
    if type(value) not in (list, tuple) or not 1 <= len(value) <= MAX_ROWS:
        raise ResearchRejected("EMPTY_OR_UNBOUNDED_INPUT")
    return value


def historical_membership_guard(records: Sequence[Mapping], *, asof_ms: int) -> dict:
    """Only contemporaneously attested Binance SPOT/USDT eligibility counts.

    A present-day token list is not proof of historical membership. Records must
    carry a prior membership observation and a closed 1H data timestamp.
    """
    keys = {"symbol", "decision_ms", "membership_observed_ms",
            "last_closed_ms", "spot_usdt_at_asof", "delisted_effective_ms"}
    if not _int(asof_ms):
        raise ResearchRejected("BAD_ASOF")
    previous = None
    for value in _rows(records):
        record = _schema(value, keys, "MEMBERSHIP")
        symbol = record["symbol"]
        if type(symbol) is not str or not SYMBOL.fullmatch(symbol) or not symbol.endswith("USDT"):
            raise ResearchRejected("INVALID_SPOT_SYMBOL")
        if any(not _int(record[k]) for k in ("decision_ms", "membership_observed_ms", "last_closed_ms")):
            raise ResearchRejected("INVALID_MEMBERSHIP_TIMESTAMP")
        decision = record["decision_ms"]
        key = (decision, symbol)
        if previous is not None and key <= previous:
            raise ResearchRejected("DUPLICATE_OR_UNSORTED_MEMBERSHIP")
        previous = key
        if decision % HOUR_MS or record["last_closed_ms"] != decision - 1 or decision > asof_ms:
            raise ResearchRejected("OPEN_OR_FUTURE_MEMBERSHIP")
        if record["membership_observed_ms"] > decision:
            raise ResearchRejected("SURVIVORSHIP_OR_FUTURE_LISTING")
        if record["spot_usdt_at_asof"] is not True:
            raise ResearchRejected("NOT_SPOT_USDT_AT_DECISION")
        delisted = record["delisted_effective_ms"]
        if delisted is not None and (not _int(delisted) or delisted <= decision):
            raise ResearchRejected("DELISTED_AT_DECISION")
    return {"records": len(records), "point_in_time_claim": "INPUT_METADATA_ONLY",
            "history_authenticated": False, "promotion_allowed": False, "orders_sent": 0}


def cost_liquidity_stress(snapshot: Mapping, *,
                          roundtrip_commission_bps: float,
                          slippage_bps_per_side: Sequence[float] = (5, 15, 30),
                          impact_bps: Sequence[float] = (0, 10, 30),
                          max_quote_age_ms: int = 300_000,
                          min_depth_multiple: float = 10.0,
                          max_spread_bps: float = 30.0) -> dict:
    """Hypothetical CEX Spot quote friction, never fill or return evidence.

    Depth is conservatively compared with the smaller quoted bid/ask depth.
    Spread is counted once, commission is round-trip, slippage is per side,
    impact is total for the round trip. All values use bps except quote units.
    """
    keys = {"decision_ms", "quote_observed_ms", "bid", "ask",
            "bid_depth_usdt", "ask_depth_usdt", "order_notional_usdt",
            "hypothetical_gross_edge_bps"}
    row = _schema(snapshot, keys, "COST")
    if (not _int(row["decision_ms"]) or not _int(row["quote_observed_ms"])
            or not _int(max_quote_age_ms) or max_quote_age_ms == 0):
        raise ResearchRejected("INVALID_QUOTE_TIMESTAMP")
    age = row["decision_ms"] - row["quote_observed_ms"]
    if age < 0 or age > max_quote_age_ms:
        raise ResearchRejected("FUTURE_OR_STALE_QUOTE")
    numeric = [row[k] for k in ("bid", "ask", "bid_depth_usdt",
               "ask_depth_usdt", "order_notional_usdt", "hypothetical_gross_edge_bps")]
    if not all(_num(x) for x in numeric):
        raise ResearchRejected("INVALID_QUOTE_NUMERIC")
    if (row["bid"] < 1e-12 or row["ask"] <= row["bid"]
            or min(row["bid_depth_usdt"], row["ask_depth_usdt"], row["order_notional_usdt"]) <= 0):
        raise ResearchRejected("INVALID_SPREAD_OR_DEPTH")
    if abs(row["hypothetical_gross_edge_bps"]) > 10_000:
        raise ResearchRejected("UNBOUNDED_HYPOTHETICAL_EDGE")
    if (not all(_num(x) for x in (roundtrip_commission_bps, min_depth_multiple, max_spread_bps))
            or not (0 <= roundtrip_commission_bps <= 300)
            or not (1 <= min_depth_multiple <= 1000)
            or not (0 < max_spread_bps <= 1000)):
        raise ResearchRejected("INVALID_COST_POLICY")
    if (type(slippage_bps_per_side) not in (list, tuple)
            or type(impact_bps) not in (list, tuple)
            or not (1 <= len(slippage_bps_per_side) <= 8)
            or not (1 <= len(impact_bps) <= 8)
            or not all(_num(x) and 0 <= x <= 300 for x in (*slippage_bps_per_side, *impact_bps))):
        raise ResearchRejected("INVALID_STRESS_GRID")
    mid = (row["bid"] + row["ask"]) / 2
    spread = (row["ask"] - row["bid"]) / mid * 10_000
    depth_multiple = min(row["bid_depth_usdt"], row["ask_depth_usdt"]) / row["order_notional_usdt"]
    if not math.isfinite(spread) or not math.isfinite(depth_multiple):
        raise ResearchRejected("NUMERIC_OVERFLOW")
    if spread > max_spread_bps:
        raise ResearchRejected("SPREAD_EXCEEDS_POLICY")
    if depth_multiple < min_depth_multiple:
        raise ResearchRejected("LOW_LIQUIDITY_CAPACITY")
    scenarios = []
    for slip in slippage_bps_per_side:
        for impact in impact_bps:
            total = spread + roundtrip_commission_bps + 2 * slip + impact
            net = row["hypothetical_gross_edge_bps"] - total
            if not all(map(math.isfinite, (total, net))):
                raise ResearchRejected("NUMERIC_OVERFLOW")
            scenarios.append({"slippage_per_side_bps": slip, "impact_roundtrip_bps": impact,
                              "total_cost_bps": total, "hypothetical_net_edge_bps": net})
    return {"quote_age_ms": age, "observed_spread_bps": spread,
            "depth_multiple": depth_multiple, "scenario_count": len(scenarios),
            "scenarios": scenarios, "worst_hypothetical_net_bps": min(x["hypothetical_net_edge_bps"] for x in scenarios),
            "assumed_fill": False, "trade_approved": False,
            "historical_quotes_authenticated": False, "promotion_allowed": False, "orders_sent": 0}


def epoch_bridge_consistency(rows: Sequence[Mapping], *, expected_universe: int = 519) -> dict:
    """Reject missing/duplicate UTC epochs, changed scope and broken pair hashes.

    An epoch count is a STRUCTURAL diagnostic only. It must never grant the
    48-hour live acceptance or claim 519 real market requests occurred.
    """
    keys = {"epoch_ms", "universe_count", "scanned_count", "pass_count",
            "warmup_count", "failed_count", "scope_sha256", "receipt_sha256",
            "bridge_receipt_sha256"}
    if type(expected_universe) is not int or expected_universe != 519:
        raise ResearchRejected("UNIVERSE_CONTRACT_CHANGED")
    previous_epoch = None
    scope = None
    for raw in _rows(rows):
        value = _schema(raw, keys, "EPOCH")
        epoch = value["epoch_ms"]
        if not _int(epoch) or epoch % HOUR_MS:
            raise ResearchRejected("UNALIGNED_EPOCH")
        if previous_epoch is not None and epoch != previous_epoch + HOUR_MS:
            raise ResearchRejected("DUPLICATE_GAP_OR_REORDERED_EPOCH")
        previous_epoch = epoch
        for k in ("universe_count", "scanned_count", "pass_count", "warmup_count", "failed_count"):
            if not _int(value[k]):
                raise ResearchRejected("INVALID_EPOCH_COUNTS")
        if value["universe_count"] != 519 or value["scanned_count"] != 519:
            raise ResearchRejected("UNIVERSE_519_DRIFT")
        if sum(value[k] for k in ("pass_count", "warmup_count", "failed_count")) != 519:
            raise ResearchRejected("ACCOUNTING_MISMATCH")
        if value["failed_count"]:
            raise ResearchRejected("TECHNICAL_FAILURE_PRESENT")
        if any(type(value[k]) is not str or not SHA256.fullmatch(value[k]) for k in
               ("scope_sha256", "receipt_sha256", "bridge_receipt_sha256")):
            raise ResearchRejected("INVALID_SOURCE_DIGEST")
        if value["receipt_sha256"] != value["bridge_receipt_sha256"]:
            raise ResearchRejected("SOURCE_BRIDGE_HASH_DRIFT")
        if scope is None:
            scope = value["scope_sha256"]
        elif scope != value["scope_sha256"]:
            raise ResearchRejected("SOURCE_SCOPE_DRIFT_REVIEW_REQUIRED")
    return {"structurally_consecutive_epochs": len(rows), "universe_contract": 519,
            "real_epochs_authenticated": False, "cloudflare_cron_verified": False,
            "public_source_acceptance": False, "private_strategy_verified": False,
            "promotion_allowed": False, "orders_sent": 0}
