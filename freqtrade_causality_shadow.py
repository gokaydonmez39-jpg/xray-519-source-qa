"""Independent Freqtrade-inspired read-only audit of XRAY public 519 indicators.
NOT the Freqtrade engine. No Binance request, AL, WSS, order, or private code.
"""
import math
import research_519 as research
REQUIRED=research.COUNTS.copy()
PERIODS=research.PERIODS.copy()

def gated_indicators(series,expected_closed):
    """Reject future/forming, stale, duplicate, gapped, or malformed input."""
    if set(series)!=set(REQUIRED) or set(expected_closed)!=set(REQUIRED):
        raise ValueError("FRAME_SCOPE_MISMATCH")
    for frame in REQUIRED:
        rows=series[frame]; expected=expected_closed[frame]; period=PERIODS[frame]
        if type(expected) is not int or expected<period:
            raise ValueError("BAD_CLOSED_EPOCH")
        if not isinstance(rows,list) or len(rows)<REQUIRED[frame]:
            raise ValueError("INSUFFICIENT_CLOSED_HISTORY")
        previous=None
        for item in rows:
            if not isinstance(item,dict) or type(item.get("close_ms")) is not int:
                raise ValueError("BAD_CANDLE")
            cl=item["close_ms"]
            if cl>expected:raise ValueError("FUTURE_OR_FORMING_CANDLE")
            if previous is not None and cl-previous!=period:
                raise ValueError("DUPLICATE_OR_GAPPED_CANDLE")
            previous=cl
            if cl%period != period-1:raise ValueError("MISALIGNED_CLOSE")
            for key in ("o","h","l","c","quote_volume"):
                v=item.get(key)
                if type(v) not in (float,int) or not math.isfinite(v):
                    raise ValueError("NONFINITE_CANDLE")
            if item["l"]<=0 or item["h"]<max(item["o"],item["c"],item["l"]) or item["l"]>min(item["o"],item["c"]):
                raise ValueError("BAD_CANDLE_GEOMETRY")
        if rows[-1]["close_ms"]!=expected:
            raise ValueError("STALE_FINAL_CANDLE")
    return research.indicators(series)

def recursion_check(values,lengths=(100,80,60),period=50,tolerance=1e-6):
    """Reveal EMA sensitivity to warmup length; diagnostic, not a trade veto."""
    if not isinstance(values,list) or any(type(v) not in (float,int) or not math.isfinite(v) for v in values):
        raise ValueError("NONFINITE_INPUT")
    if type(period) is not int or period<2 or len(values)<max(lengths):
        raise ValueError("INSUFFICIENT_EMA_HISTORY")
    if any(type(n) is not int or n<period for n in lengths) or type(tolerance) not in (float,int) or not math.isfinite(tolerance) or tolerance<0:
        raise ValueError("INVALID_STARTUP_SETTINGS")
    values_by_length=[research.ema(values[-n:],period) for n in lengths]
    delta=max(abs(x-values_by_length[0]) for x in values_by_length[1:])
    return {"baseline":values_by_length[0],"max_delta":delta,
            "startup_stable":delta<=tolerance,
            "no_al_authority":True,"freqtrade_engine_executed":False}

def report():
    r=recursion_check([100.0+i*.01 for i in range(100)])
    return {"schema":"XRAY_FREQTRADE_IDEA_SHADOW_V1",
            "synthetic_only":True,"orders":0,"real_markets_scanned":0,
            "source_api_calls":0,"freqtrade_executed":False,
            "recursive_synthetic_max_delta":r["max_delta"],
            "recursive_stable_under_tolerance":r["startup_stable"],
            "lookahead_claim":"STRUCTURAL_SNAPSHOT_GUARD_ONLY",
            "private_strategy_verified":False,"technical_519_quality_promoted":False,
            "no_al_authority":True}

if __name__=="__main__":
    import json
    print(json.dumps(report(),sort_keys=True))
