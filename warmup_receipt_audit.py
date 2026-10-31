"""Public immutable 519-source receipt diagnostics; offline, aggregate-only.
No network, new source scan, keys, symbol disclosure, AL, or change to receipts.
"""
from collections import Counter
import gzip
import json
from pathlib import Path

MAX_COMPRESSED=200_000
MAX_JSON=2_500_000
FRAMES=frozenset(("1h","4h","1d"))
CATEGORIES=frozenset(("PASS","WARMUP","FAIL"))

class ReceiptInvalid(ValueError):
    pass

def _unique_pairs(pairs):
    obj={}
    for key,value in pairs:
        if key in obj:
            raise ReceiptInvalid("DUPLICATE_JSON_KEY")
        obj[key]=value
    return obj

def _reject_constant(_):
    raise ReceiptInvalid("NONFINITE_JSON")

def load_receipt(path):
    path=Path(path)
    if not str(path).endswith("-n519.json.gz") or "/receipts/" not in ("/"+path.as_posix()):
        raise ReceiptInvalid("INVALID_RECEIPT_PATH")
    if path.is_symlink() or not path.is_file():
        raise ReceiptInvalid("NOT_REGULAR_RECEIPT")
    if path.stat().st_size>MAX_COMPRESSED:
        raise ReceiptInvalid("COMPRESSED_SIZE_LIMIT")
    try:
        with gzip.open(path,"rb") as f:
            data=f.read(MAX_JSON+1)
        if len(data)>MAX_JSON:
            raise ReceiptInvalid("DECOMPRESSED_SIZE_LIMIT")
        doc=json.loads(data.decode("utf-8"),object_pairs_hook=_unique_pairs,
                       parse_constant=_reject_constant)
    except (OSError,UnicodeError,ValueError) as e:
        if isinstance(e,ReceiptInvalid):raise
        raise ReceiptInvalid("INVALID_COMPRESSED_JSON") from e
    if not isinstance(doc,dict) or doc.get("schema")!="XRAY_519_SOURCE_TECH_RESEARCH_V1":
        raise ReceiptInvalid("SCHEMA_MISMATCH")
    return doc

def summarize(doc):
    if not isinstance(doc,dict):
        raise ReceiptInvalid("NOT_AN_OBJECT")
    if doc.get("schema")!="XRAY_519_SOURCE_TECH_RESEARCH_V1":
        raise ReceiptInvalid("SCHEMA_MISMATCH")
    rows=doc.get("results")
    if not isinstance(rows,list) or len(rows)!=519 or any(type(x) is not dict for x in rows):
        raise ReceiptInvalid("ROWS_519_NOT_PRESENT")
    if any(type(doc.get(k)) is not int or doc[k]<0 for k in (
        "identity_universe","markets_selected","technical_scanned",
        "technical_pass","technical_warmup","technical_failed")):
        raise ReceiptInvalid("INVALID_COUNTER_TYPE")
    if (doc["identity_universe"],doc["markets_selected"],doc["technical_scanned"])!=(519,519,519):
        raise ReceiptInvalid("SCOPE_NOT_519")
    if doc.get("orders_sent")!=0 or doc.get("notifications_sent")!=0 or doc.get("private_strategy_evaluated")!=0:
        raise ReceiptInvalid("NONZERO_TRADING_AUTHORITY")
    symbols=set()
    counts=Counter()
    reasons=Counter()
    frames=Counter()
    for x in rows:
        symbol=x.get("symbol")
        if not isinstance(symbol,str) or not symbol or symbol in symbols:
            raise ReceiptInvalid("DUPLICATE_OR_BAD_SYMBOL")
        symbols.add(symbol)
        quality=x.get("technical_data_quality")
        if quality not in CATEGORIES:
            raise ReceiptInvalid("UNKNOWN_TECHNICAL_STATE")
        details=x.get("frame_quality")
        if not isinstance(details,dict) or set(details)!=FRAMES:
            raise ReceiptInvalid("MISSING_FRAME_QUALITY")
        if any(not isinstance(v,str) or not (v=="PASS" or v.startswith("WARMUP_") or v.startswith("FAIL_")) for v in details.values()):
            raise ReceiptInvalid("BAD_FRAME_STATE")
        failures=any(v.startswith("FAIL_") for v in details.values())
        warmups=any(v.startswith("WARMUP_") for v in details.values())
        if quality=="PASS" and (failures or warmups):
            raise ReceiptInvalid("FALSE_PASS_WITH_BAD_FRAME")
        if quality=="WARMUP" and (failures or not warmups) and not str(x.get("reason","")).startswith(("EMA_","RSI_")):
            raise ReceiptInvalid("WARMUP_FRAME_INCONSISTENT")
        if quality=="FAIL" and not failures and not str(x.get("reason","")).startswith("NONFINITE_INDICATOR"):
            raise ReceiptInvalid("FAIL_FRAME_INCONSISTENT")
        if quality in ("WARMUP","FAIL"):
            reason=x.get("reason")
            if not isinstance(reason,str) or not reason or len(reason)>160:
                raise ReceiptInvalid("MISSING_PROBLEM_REASON")
            reasons[quality+":"+reason]+=1
        for frame,value in details.items():
            if value!="PASS":
                frames[frame+":"+value]+=1
        counts[quality]+=1
    if any(counts[k]!=doc["technical_"+("pass" if k=="PASS" else "warmup" if k=="WARMUP" else "failed")] for k in CATEGORIES):
        raise ReceiptInvalid("HEADER_ROWS_DISAGREE")
    if sum(counts.values())!=519:
        raise ReceiptInvalid("ACCOUNTING_MISMATCH")
    return {
        "schema":"XRAY_PUBLIC_519_WARMUP_AUDIT_V1",
        "source_receipt_epoch_ms":doc.get("utc_closed_epoch_1h_ms"),
        "technical_pass":counts["PASS"],"technical_warmup":counts["WARMUP"],
        "technical_failed":counts["FAIL"],
        "reason_distribution":dict(sorted(reasons.items())),
        "frame_issue_distribution":dict(sorted(frames.items())),
        "source_contract_only":True,
        "private_al_verified":False,
        "full_519_technical_quality":counts["PASS"]==519,
        "source_scan_or_market_requests":0,
        "symbol_details_disclosed":0
    }

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--receipt",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(summarize(load_receipt(a.receipt)),sort_keys=True))
if __name__=="__main__":
    main()
