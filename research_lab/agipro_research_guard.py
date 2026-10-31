"""Independent AGIPro-inspired XRAY CRYPTO research guards (method only).

Standard library, no network, API credentials, trade execution or promotion.
This is NOT a port of agiprolabs or a replacement for existing PIT/P30 gates.
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence, Mapping

HOUR_MS = 3_600_000
MAX_RECORDS = 10_000
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}\Z")


class ResearchGuardError(ValueError):
    """Invalid research provenance, timeline, bar or inference."""


def _ms(v: object) -> bool:
    return type(v) is int and v >= 0


def _finite(v: object) -> bool:
    if type(v) not in (float, int):
        return False
    try:
        return math.isfinite(v)
    except (OverflowError, ValueError):
        return False


def _rows(rows: object) -> Sequence[Mapping]:
    if type(rows) not in (list, tuple) or not 1 <= len(rows) <= MAX_RECORDS:
        raise ResearchGuardError("EMPTY_OR_OVERSIZE_ROWS")
    return rows


def validate_attribution(rows: Sequence[Mapping], *, asof_ms: int) -> dict:
    """Prohibit using a signal formed on bar-close to earn that same bar's return.

    Requires a *fully closed subsequent bar* for a conservative 1H return,
    following an observed entry quote strictly after decision timestamp.
    """
    fields = {"symbol", "decision_ms", "last_closed_end_ms",
              "feature_available_ms", "entry_observed_ms", "return_open_ms",
              "return_close_ms", "label_available_ms"}
    if not _ms(asof_ms):
        raise ResearchGuardError("BAD_ASOF")
    last = None
    for rec in _rows(rows):
        if type(rec) is not dict or set(rec) != fields:
            raise ResearchGuardError("UNREVIEWED_ATTRIBUTION_SCHEMA")
        sym = rec["symbol"]
        if type(sym) is not str or not _SYMBOL.fullmatch(sym):
            raise ResearchGuardError("INVALID_SYMBOL")
        if any(not _ms(rec[k]) for k in fields - {"symbol"}):
            raise ResearchGuardError("INVALID_TIMESTAMP")
        d = rec["decision_ms"]
        key = (d, sym)
        if last is not None and key <= last:
            raise ResearchGuardError("DUPLICATE_OR_UNSORTED_DECISION")
        last = key
        if d % HOUR_MS or rec["last_closed_end_ms"] != d - 1:
            raise ResearchGuardError("OPEN_OR_STALE_DECISION_BAR")
        if rec["feature_available_ms"] > d:
            raise ResearchGuardError("FUTURE_FEATURE")
        entry = rec["entry_observed_ms"]
        if entry <= d:
            raise ResearchGuardError("NO_POST_DECISION_ENTRY")
        full_next = (entry // HOUR_MS + 1) * HOUR_MS
        op = rec["return_open_ms"]
        if op < full_next or op % HOUR_MS:
            raise ResearchGuardError("SAME_BAR_RETURN_LEAK")
        if rec["return_close_ms"] != op + HOUR_MS - 1:
            raise ResearchGuardError("INVALID_RETURN_HORIZON")
        if not rec["return_close_ms"] < rec["label_available_ms"] <= asof_ms:
            raise ResearchGuardError("UNMATURED_OUTCOME")
    return {"validated_records": len(rows), "same_bar_attribution_allowed": False,
            "promotion_allowed": False, "orders_sent": 0}


def purged_temporal_split(rows: Sequence[Mapping], *, train_end_ms: int,
                          test_start_ms: int, embargo_ms: int) -> dict:
    """Train labels must be available and embargo-aged BEFORE first test epoch.

    Cutoffs are fixed externally. Entire UTC epochs stay in one time partition.
    This is a conservative one-split research diagnostic, not CPCV or OOS proof.
    """
    if (not all(_ms(v) for v in (train_end_ms, test_start_ms, embargo_ms))
            or train_end_ms >= test_start_ms or embargo_ms < HOUR_MS
            or train_end_ms % HOUR_MS or test_start_ms % HOUR_MS):
        raise ResearchGuardError("BAD_SPLIT_POLICY")
    fields = {"symbol", "decision_ms", "feature_available_ms", "label_available_ms"}
    last = None
    train, test, purged, gap = [], [], [], []
    for rec in _rows(rows):
        if type(rec) is not dict or set(rec) != fields:
            raise ResearchGuardError("UNREVIEWED_SPLIT_SCHEMA")
        sym = rec["symbol"]
        if type(sym) is not str or not _SYMBOL.fullmatch(sym):
            raise ResearchGuardError("INVALID_SYMBOL")
        if any(not _ms(rec[k]) for k in fields - {"symbol"}):
            raise ResearchGuardError("INVALID_TIMESTAMP")
        d = rec["decision_ms"]
        key = (d, sym)
        if last is not None and key <= last:
            raise ResearchGuardError("DUPLICATE_OR_UNSORTED_DECISION")
        last = key
        if (d % HOUR_MS or rec["feature_available_ms"] > d
                or rec["label_available_ms"] <= d):
            raise ResearchGuardError("TEMPORAL_LEAK_OR_UNALIGNED_EPOCH")
        if d <= train_end_ms:
            target = train if rec["label_available_ms"] + embargo_ms <= test_start_ms else purged
        elif d >= test_start_ms:
            target = test
        else:
            target = gap
        target.append(key)
    if not train or not test:
        raise ResearchGuardError("MISSING_INDEPENDENT_TRAIN_OR_TEST")
    return {"train": train, "test": test, "purged": purged,
            "between_cutoffs": gap, "embargo_ms": embargo_ms,
            "promotion_allowed": False, "orders_sent": 0}


def validate_unimputed_ohlcv(bars: Sequence[Mapping], *, period_ms: int = HOUR_MS) -> dict:
    """No forward-filled, interpolated, missing, duplicated or open OHLCV bars."""
    if not _ms(period_ms) or period_ms < 60_000:
        raise ResearchGuardError("BAD_PERIOD")
    fields = {"open_ms", "observed_ms", "open", "high", "low", "close",
              "volume", "is_synthetic"}
    previous = None
    for bar in _rows(bars):
        if type(bar) is not dict or set(bar) != fields:
            raise ResearchGuardError("UNREVIEWED_BAR_SCHEMA")
        op = bar["open_ms"]
        observed = bar["observed_ms"]
        if not _ms(op) or not _ms(observed) or op % period_ms:
            raise ResearchGuardError("BAD_BAR_TIME")
        if previous is not None and op != previous + period_ms:
            raise ResearchGuardError("OHLCV_GAP_OR_DUPLICATE")
        previous = op
        if observed < op + period_ms:
            raise ResearchGuardError("UNFINISHED_BAR")
        if bar["is_synthetic"] is not False:
            raise ResearchGuardError("SYNTHETIC_OR_IMPUTED_BAR")
        if any(not _finite(bar[k]) for k in ("open", "high", "low", "close", "volume")):
            raise ResearchGuardError("NONFINITE_OHLCV")
        o, h, l, c, v = (bar[k] for k in ("open", "high", "low", "close", "volume"))
        if min(o, h, l, c) <= 0 or v <= 0 or not l <= min(o, c) <= max(o, c) <= h:
            raise ResearchGuardError("INVALID_OHLCV_OR_ZERO_VOLUME")
    return {"closed_unimputed_bars": len(bars), "imputed": 0,
            "promotion_allowed": False, "orders_sent": 0}


def holm_research_gate(pvalues: Sequence[float], *, declared_trials: int,
                       alpha: float = 0.05) -> dict:
    """Multiple-comparison diagnostic; significance is NOT trade admission.

    No inference about effective independent trials or genuine market labels.
    """
    if (type(declared_trials) is not int or declared_trials < 2
            or type(pvalues) not in (tuple, list)
            or len(pvalues) != declared_trials or len(pvalues) > MAX_RECORDS):
        raise ResearchGuardError("UNDECLARED_OR_UNCOUNTED_TRIALS")
    if not _finite(alpha) or not 0 < alpha < 1:
        raise ResearchGuardError("BAD_ALPHA")
    if any(not _finite(p) or not 0 <= p <= 1 for p in pvalues):
        raise ResearchGuardError("BAD_PVALUE")
    accepted = [False] * len(pvalues)
    for rank, (idx, p) in enumerate(sorted(enumerate(pvalues), key=lambda x: x[1])):
        if p > alpha / (declared_trials - rank):
            break
        accepted[idx] = True
    return {"holm_rejections": accepted, "declared_trials": declared_trials,
            "statistical_provenance_verified": False,
            "promotion_allowed": False, "orders_sent": 0}


def positive_gain_concentration(pnls: Sequence[float], *, top_n: int = 2) -> dict:
    """Detect reliance on one or two outsized winners (not an alpha claim)."""
    if (type(pnls) not in (tuple, list) or not 3 <= len(pnls) <= MAX_RECORDS
            or type(top_n) is not int or not 1 <= top_n < len(pnls)
            or any(not _finite(x) for x in pnls)):
        raise ResearchGuardError("BAD_CONCENTRATION_SAMPLE")
    positives = sorted((x for x in pnls if x > 0), reverse=True)
    total = sum(positives)
    if not math.isfinite(total) or total <= 0:
        raise ResearchGuardError("NO_POSITIVE_GAINS_OR_OVERFLOW")
    ratio = sum(positives[:top_n]) / total
    if not math.isfinite(ratio):
        raise ResearchGuardError("UNSTABLE_CONCENTRATION")
    net_pnl = sum(pnls)
    if not math.isfinite(net_pnl):
        raise ResearchGuardError("UNSTABLE_NET_PNL")
    return {"top_n": top_n, "share_of_positive_gains": ratio,
            "net_pnl": net_pnl, "portfolio_return_verified": False,
            "promotion_allowed": False, "orders_sent": 0}
