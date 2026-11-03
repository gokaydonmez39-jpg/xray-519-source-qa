"""Opt-in, bounded DexPaprika read-only research and offline cost stress tests.

This module is deliberately disconnected from the XRAY source scan and P30.
No external MCP, paid account, wallet, API key, orders or notification runtime.
All external observations remain UNVERIFIED for trading or AL promotion.
"""
from __future__ import annotations

import http.client
import json
import math
import re
from collections.abc import Callable

HOST = "api.dexpaprika.com"
NETWORKS = frozenset({"ethereum", "bsc", "base", "arbitrum", "polygon"})
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
SYMBOL = re.compile(r"[A-Z0-9]{2,30}USDT\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_TOKENS = 10
MAX_RESPONSE_BYTES = 65_536


class ShadowBlocked(ValueError):
    """Fail closed on malformed, unproven, or unsafe research input."""


def _positive(value: object) -> float:
    if type(value) not in (int, float, str):
        raise ShadowBlocked("NONFINITE_METRIC")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ShadowBlocked("NONFINITE_METRIC") from exc
    if not math.isfinite(number) or number < 0:
        raise ShadowBlocked("NONFINITE_METRIC")
    return number


def validate_contract_manifest(rows: object, source_sha256: str) -> list[dict]:
    if not isinstance(source_sha256, str) or not SHA256.fullmatch(source_sha256):
        raise ShadowBlocked("UNVERIFIED_PUBLIC_SOURCE_SHA")
    if type(rows) is not list or not 1 <= len(rows) <= MAX_TOKENS:
        raise ShadowBlocked("INPUT_COUNT_EXCEEDS_TEN_OR_EMPTY")
    output = []
    symbols = set()
    pairs = set()
    for row in rows:
        if type(row) is not dict or set(row) != {"symbol", "network", "token_address"}:
            raise ShadowBlocked("UNREVIEWED_MAPPING_SCHEMA")
        symbol, network, address = (row[k] for k in ("symbol", "network", "token_address"))
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise ShadowBlocked("BAD_SPOT_SYMBOL")
        if not isinstance(network, str) or network not in NETWORKS:
            raise ShadowBlocked("UNAPPROVED_CHAIN")
        if not isinstance(address, str) or not ADDRESS.fullmatch(address):
            raise ShadowBlocked("BAD_CONTRACT_ADDRESS")
        address = address.lower()
        if symbol in symbols or (network, address) in pairs:
            raise ShadowBlocked("DUPLICATE_OR_AMBIGUOUS_MAPPING")
        symbols.add(symbol)
        pairs.add((network, address))
        output.append({"symbol": symbol, "network": network, "token_address": address})
    return output


def _keyless_get_token(network: str, address: str) -> dict:
    """Exactly one unauthenticated GET to a pinned host. No redirects or writes."""
    conn = http.client.HTTPSConnection(HOST, timeout=3)
    try:
        conn.request("GET", f"/networks/{network}/tokens/{address}",
                     headers={"Accept": "application/json", "User-Agent": "xray-shadow-research/1"})
        response = conn.getresponse()
        if response.status != 200:
            raise ShadowBlocked("PROVIDER_NON_200")
        plan = (response.getheader("x-api-plan") or "").lower()
        if plan not in {"", "keyless", "free"}:
            raise ShadowBlocked("PAID_PROVIDER_PLAN_REJECTED")
        if "json" not in (response.getheader("Content-Type") or "").lower():
            raise ShadowBlocked("PROVIDER_NON_JSON")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ShadowBlocked("PROVIDER_OVERSIZE_RESPONSE")
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ShadowBlocked("PROVIDER_BAD_JSON") from exc
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ShadowBlocked("PROVIDER_UNAVAILABLE") from exc
    finally:
        conn.close()


def dex_shadow(rows: object, *, source_sha256: str, allow_public_rest: bool = False,
               fetcher: Callable[[str, str], dict] | None = None) -> dict:
    """Explicit manual shadow; never auto-map symbols to chain contracts."""
    accepted = validate_contract_manifest(rows, source_sha256)
    if type(allow_public_rest) is not bool:
        raise ShadowBlocked("INVALID_NETWORK_AUTHORIZATION")
    if fetcher is not None and not callable(fetcher):
        raise ShadowBlocked("INVALID_FETCHER")
    if not allow_public_rest and fetcher is not None:
        raise ShadowBlocked("NETWORK_NOT_AUTHORIZED")
    result = []
    for row in accepted:
        evidence = {**row, "source_sha256": source_sha256,
                    "contract_mapping_authenticated": False,
                    "private_alpha_verified": False, "promotion_allowed": False}
        if not allow_public_rest:
            evidence["status"] = "PLAN_ONLY_NO_NETWORK"
        else:
            response = (fetcher or _keyless_get_token)(row["network"], row["token_address"])
            if type(response) is not dict or not isinstance(response.get("id"), str) or not isinstance(response.get("chain"), str):
                raise ShadowBlocked("TOKEN_IDENTITY_MISSING")
            if response["chain"] != row["network"] or response["id"].lower() != row["token_address"]:
                raise ShadowBlocked("TOKEN_CONTRACT_MISMATCH")
            summary = response.get("summary")
            if type(summary) is not dict or type(summary.get("24h")) is not dict:
                raise ShadowBlocked("TOKEN_METRICS_MISSING")
            evidence.update(status="EXTERNAL_RESEARCH_UNVERIFIED",
                            price_usd=_positive(summary.get("price_usd")),
                            liquidity_usd=_positive(summary.get("liquidity_usd")),
                            volume_usd_24h=_positive(summary["24h"].get("volume_usd")))
        result.append(evidence)
    return {"schema": "XRAY_DEXPAPRIKA_MANUAL_SHADOW_V1", "provider": HOST,
            "network_enabled": allow_public_rest, "requests_maximum": len(accepted),
            "data_for_trading_verified": False, "orders_sent": 0,
            "notifications_sent": 0, "private_strategy_evaluated": 0,
            "promotion_allowed": False, "records": result}


def cost_sensitivity_shadow(rows: object, *, commission_bps: tuple = (0, 10, 20),
                            slippage_bps: tuple = (0, 10, 20)) -> dict:
    """Offline per-trade *hypothetical* cost stress, not fills or portfolio P&L.

    Each cost scenario applies round-trip commission/slippage in basis points;
    a matched BTC reference receives the same assumed friction. No optimization.
    """
    if type(rows) is not list or not 1 <= len(rows) <= 10_000:
        raise ShadowBlocked("BAD_TRADE_COUNT")
    for axis in (commission_bps, slippage_bps):
        if type(axis) is not tuple or not 1 <= len(axis) <= 5:
            raise ShadowBlocked("BAD_COST_GRID")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 150 for v in axis):
            raise ShadowBlocked("INVALID_COST_BPS")
    expected = {"symbol", "entry_ms", "exit_ms", "feature_available_ms",
                "entry_ask", "exit_bid", "btc_entry_ask", "btc_exit_bid"}
    seen = set()
    validated = []
    for row in rows:
        if type(row) is not dict or set(row) != expected:
            raise ShadowBlocked("BAD_TRADE_SCHEMA")
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise ShadowBlocked("BAD_SPOT_SYMBOL")
        start, end, feature = (row[k] for k in ("entry_ms", "exit_ms", "feature_available_ms"))
        if any(type(v) is not int or v < 0 for v in (start, end, feature)) or not feature <= start < end:
            raise ShadowBlocked("LOOKAHEAD_OR_TIME_REVERSAL")
        key = (symbol, start)
        if key in seen:
            raise ShadowBlocked("DUPLICATE_TRADE")
        seen.add(key)
        prices = [row[k] for k in ("entry_ask", "exit_bid", "btc_entry_ask", "btc_exit_bid")]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in prices):
            raise ShadowBlocked("BAD_PRICE")
        validated.append((prices[1] / prices[0], prices[3] / prices[2]))
    outcomes = []
    for fee in commission_bps:
        for slip in slippage_bps:
            cost = (fee + slip) / 10_000.0
            model = [(a * (1 - cost / 2) / (1 + cost / 2) - 1) for a, _ in validated]
            benchmark = [(b * (1 - cost / 2) / (1 + cost / 2) - 1) for _, b in validated]
            outcomes.append({"commission_roundtrip_bps": fee, "slippage_roundtrip_bps": slip,
                             "mean_model_return": sum(model) / len(model),
                             "mean_btc_same_window_proxy_return": sum(benchmark) / len(benchmark),
                             "delta_vs_btc_proxy": (sum(model) - sum(benchmark)) / len(model)})
    return {"schema": "XRAY_COST_GRID_METHOD_ONLY_V1", "sample_count": len(validated),
            "scenarios": outcomes, "real_market_data_authenticated": False,
            "actual_fills_observed": False, "oos_verified": False,
            "survivorship_bias_ruled_out": False, "production_promoted": False,
            "orders_sent": 0, "notifications_sent": 0}
