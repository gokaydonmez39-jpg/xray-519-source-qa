"""XRAY-519 research-only validation gates for Qlib-style PIT and Kronos benchmarking.

No third-party package imported, no strategy/execution model, no network.
Inspired by documented research patterns; not the Qlib or Kronos engines.
Never grants AL, private model admission, or production promotion authority.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence

HOUR_MS = 3_600_000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}\Z")
_REQUIRED_TIME = (
    "decision_ms", "feature_available_ms", "last_closed_ms",
    "label_close_ms", "label_available_ms",
    "model_fit_cutoff_ms", "forecast_created_ms",
)
_REQUIRED_PRICE = ("reference_close", "forecast_close", "realized_close", "feature_rsi")


class GateError(ValueError):
    """No research evidence may be promoted after malformed or leaked data."""


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_rows(rows: Sequence[Mapping], *, asof_ms: int) -> list[dict]:
    """Validate one complete as-of snapshot and point-in-time provenance.

    Labels are allowed in offline scoring only after becoming available;
    prediction creation and all feature timestamps must precede decisions.
    """
    if not _integer(asof_ms) or not isinstance(rows, (tuple, list)) or not rows:
        raise GateError("INVALID_ASOF_OR_EMPTY_INPUT")
    validated: list[dict] = []
    seen: set[tuple[str, int]] = set()
    previous_key: tuple[int, str] | None = None
    for item in rows:
        if not isinstance(item, dict):
            raise GateError("BAD_ROW")
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise GateError("BAD_SYMBOL")
        if any(not _integer(item.get(k)) for k in _REQUIRED_TIME):
            raise GateError("INVALID_TIMESTAMP")
        if any(not _finite(item.get(k)) for k in _REQUIRED_PRICE):
            raise GateError("NONFINITE_FEATURE_OR_PRICE")
        if any(item[k] <= 0 for k in ("reference_close", "forecast_close", "realized_close")):
            raise GateError("NONPOSITIVE_PRICE")
        decision = item["decision_ms"]
        key = (symbol, decision)
        order = (decision, symbol)
        if key in seen or (previous_key is not None and order <= previous_key):
            raise GateError("DUPLICATE_OR_UNSORTED_EPOCH")
        seen.add(key)
        previous_key = order
        if decision % HOUR_MS:
            raise GateError("UNALIGNED_DECISION_EPOCH")
        if item["last_closed_ms"] != decision - 1:
            raise GateError("OPEN_OR_STALE_CANDLE")
        if item["feature_available_ms"] > decision or item["forecast_created_ms"] > decision:
            raise GateError("LOOKAHEAD_OR_REPAINT")
        if item["model_fit_cutoff_ms"] >= decision:
            raise GateError("MODEL_TRAINED_ON_FUTURE")
        if not (decision < item["label_close_ms"] <= item["label_available_ms"] <= asof_ms):
            raise GateError("FUTURE_OR_UNMATURED_LABEL")
        if item["label_close_ms"] != decision + HOUR_MS - 1:
            raise GateError("INVALID_HORIZON_ALIGNMENT")
        validated.append(dict(item))
    return validated


def temporal_folds(
    validated_rows: Sequence[Mapping], *,
    train_end_ms: int,
    validation_end_ms: int,
    embargo_ms: int,
) -> dict:
    """Qlib-style point-in-time ordered folds; embargo purges label overlaps.

    Never random-split correlated markets into training and testing;
    the same UTC decision epoch is assigned to exactly one fold.
    """
    if (not all(_integer(x) for x in (train_end_ms, validation_end_ms, embargo_ms))
            or train_end_ms >= validation_end_ms or embargo_ms < HOUR_MS):
        raise GateError("INVALID_TEMPORAL_CUTOFF_OR_EMBARGO")
    if not validated_rows:
        raise GateError("EMPTY_FOLDS")
    folds: dict[str, list] = {"train": [], "validation": [], "test": []}
    dropped = 0
    prior_key = None
    for row in validated_rows:
        d = row["decision_ms"]
        order = (d, row["symbol"])
        if prior_key is not None and order <= prior_key:
            raise GateError("UNSORTED_FOLDS")
        prior_key = order
        if d <= train_end_ms:
            if row["label_available_ms"] + embargo_ms > train_end_ms:
                dropped += 1
                continue
            folds["train"].append(dict(row))
        elif d <= validation_end_ms:
            if row["label_available_ms"] + embargo_ms > validation_end_ms:
                dropped += 1
                continue
            folds["validation"].append(dict(row))
        else:
            folds["test"].append(dict(row))
    if not all(folds.values()):
        raise GateError("MISSING_TRAIN_VALIDATION_OR_TEST")
    return {**folds, "embargo_dropped": dropped, "embargo_ms": embargo_ms,
            "no_random_symbol_split": True}


def fit_train_normalizer(train_rows: Sequence[Mapping], feature: str) -> dict:
    """Fit-only-on-training standardizer; never sees validation/test examples."""
    if not isinstance(feature, str) or not feature.startswith("feature_") or not train_rows:
        raise GateError("BAD_TRAIN_FEATURE")
    values = [r.get(feature) for r in train_rows]
    if not all(_finite(x) for x in values):
        raise GateError("NONFINITE_TRAIN_FEATURE")
    n = len(values)
    mu = sum(values) / n
    variance = sum((x - mu) ** 2 for x in values) / n
    if not math.isfinite(mu) or not math.isfinite(variance) or variance <= 0:
        raise GateError("ZERO_VARIANCE_OR_UNSTABLE_TRAIN_FIT")
    return {"feature": feature, "n_train": n, "mean": mu,
            "std": math.sqrt(variance), "training_only": True}


def prefix_causality(values: Sequence[float], compute: Callable) -> bool:
    """Check that later data cannot rewrite earlier indicator outputs.

    This complements, but does not replace, full strategy backtest lookahead
    analysis. Fails on even one historical-prefix mismatch.
    """
    if not isinstance(values, (tuple, list)) or len(values) < 2 or not all(_finite(x) for x in values):
        raise GateError("BAD_CAUSALITY_SERIES")
    if not callable(compute):
        raise GateError("BAD_CAUSALITY_FUNCTION")
    try:
        full = compute(list(values))
        if not isinstance(full, (tuple, list)) or len(full) != len(values):
            raise GateError("BAD_INDICATOR_SHAPE")
        for i in range(1, len(values) + 1):
            short = compute(list(values[:i]))
            if not isinstance(short, (tuple, list)) or len(short) != i:
                raise GateError("BAD_INDICATOR_SHAPE")
            a, b = full[i - 1], short[i - 1]
            if not _finite(a) or not _finite(b) or not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
                raise GateError("FUTURE_DEPENDENT_INDICATOR")
    except GateError:
        raise
    except (TypeError, ValueError, ArithmeticError, IndexError) as e:
        raise GateError("INDICATOR_EXECUTION_FAILED") from e
    return True


def score_shadow_forecasts(
    rows: Sequence[Mapping], *,
    asof_ms: int,
    source_sha256: str,
    model_sha256: str,
    synthetic_only: bool,
    min_samples: int = 200,
    min_distinct_epochs: int = 100,
) -> dict:
    """Compare a supplied candidate forecast with naive last-closed baseline.

    Does not run, verify or import Kronos. No AL promotion is possible here.
    """
    if (not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256)
            or not isinstance(model_sha256, str) or not _SHA256.fullmatch(model_sha256)):
        raise GateError("UNVERIFIED_SOURCE_OR_MODEL_DIGEST")
    if type(synthetic_only) is not bool:
        raise GateError("INVALID_DATASET_CLASS")
    if (type(min_samples) is not int or min_samples < 2
            or type(min_distinct_epochs) is not int or min_distinct_epochs < 2):
        raise GateError("INVALID_SAMPLE_POLICY")
    validated = validate_rows(rows, asof_ms=asof_ms)
    n = len(validated)
    unique_epochs = len({r["decision_ms"] for r in validated})
    model_mae = sum(abs(r["forecast_close"] - r["realized_close"]) for r in validated) / n
    baseline_mae = sum(abs(r["reference_close"] - r["realized_close"]) for r in validated) / n
    if not math.isfinite(model_mae) or not math.isfinite(baseline_mae):
        raise GateError("UNSTABLE_ERROR_METRIC")
    sample_gate = n >= min_samples and unique_epochs >= min_distinct_epochs
    return {
        "schema": "XRAY_RESEARCH_SHADOW_OOS_METHOD_V1",
        "dataset_kind": "SYNTHETIC_ONLY" if synthetic_only else "EXTERNAL_DATA_UNVERIFIED",
        "sample_count": n,
        "distinct_epoch_count": unique_epochs,
        "sample_gate_pass": sample_gate,
        "model_mae": model_mae,
        "naive_last_close_mae": baseline_mae,
        "mae_ratio": model_mae / baseline_mae if baseline_mae > 0 else None,
        "source_sha256": source_sha256,
        "model_sha256": model_sha256,
        "model_verified": False,
        "oos_verified": False,
        "cost_spread_slippage_verified": False,
        "promotion_allowed": False,
        "live_al_claim": False,
        "orders_sent": 0,
        "private_strategy_evaluated": 0,
    }
