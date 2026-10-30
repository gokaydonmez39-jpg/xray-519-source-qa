#!/usr/bin/env python3
"""Audit two public, persisted 519-bar receipts after remote Git readback.

Only judges source QA coverage; it never declares an AL, strategy or WSS system live.
"""
from __future__ import annotations
import gzip
import json
from pathlib import Path
from verify_epoch_pair import validate_pair


def audit(root: Path) -> tuple[bool,str,list[str]]:
    receipts=[]
    for path in (root/'receipts').glob('*/*/*/*-n519.json.gz'):
        try:
            if path.is_symlink() or path.stat().st_size>200_000:
                continue
            with gzip.open(path,'rb') as f:
                receipt=json.loads(f.read(2_500_000))
            if receipt.get('markets_selected')!=519:
                continue
            provenance=receipt.get('public_runner',{})
            if (provenance.get('repository')!='gokaydonmez39-jpg/xray-519-source-qa' or
                not str(provenance.get('run_id','')).isdecimal()):
                continue
            receipts.append(receipt)
        except (OSError,ValueError,KeyError,TypeError,UnicodeError):
            continue
    receipts.sort(key=lambda r:r.get('utc_closed_epoch_1h_ms',0))
    if len(receipts)<2:
        return False,'NEED_TWO_DISTINCT_519_HOURLY_RECEIPTS',[]
    a,b=receipts[-2:]
    if a['public_runner']['run_id']==b['public_runner']['run_id']:
        return False,'SAME_GITHUB_RUN_NOT_INDEPENDENT',[]
    success,problems=validate_pair(a,b)
    return success,'TWO_EPOCH_519_SOURCE_QUALITY_PASS' if success else 'TWO_EPOCH_HOLD',problems


if __name__=='__main__':
    import sys
    result,status,problems=audit(Path('.'))
    print(json.dumps({'result':status,'source_qa_verified':result,
                      'private_AL_verified':False,'continuous_wss_verified':False,
                      'iPhone_delivery_verified':False,'issues':problems}))
    # First hour is normal; do not fail the source job solely for lacking two periods.
    sys.exit(0)
