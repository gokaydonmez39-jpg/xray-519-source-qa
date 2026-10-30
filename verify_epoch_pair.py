#!/usr/bin/env python3
"""Check structural consistency of two immutable research receipts.

This is NOT source authentication: JSON is forgeable without independent
remote runner IDs and Binance/host logs. Never marks trading or WSS live.
"""
import argparse
import json
from pathlib import Path
import sys

from research_519 import HOUR, MAX_REQUESTS, MAX_SECONDS, SCHEMA


def validate_pair(a: dict, b: dict, *, allow_warmup: bool=False) -> tuple[bool, list[str]]:
    problems=[]
    for i,receipt in enumerate((a,b)):
        tag=str(i+1)
        if receipt.get('schema') != SCHEMA or receipt.get('run_kind') != 'RESEARCH_ONLY_NO_AL':
            problems.append(f'{tag}:WRONG_SCHEMA_OR_RUN_KIND')
        for required in ('source_qa_success','scope_stable','epoch_stable','status_accounting_ok',
                         'complete_identity_scope'):
            if receipt.get(required) is not True:
                problems.append(f'{tag}:{required.upper()}_FALSE')
        n=receipt.get('identity_universe')
        if type(n) is not int or n<1 or receipt.get('markets_selected')!=n or receipt.get('technical_scanned')!=n:
            problems.append(f'{tag}:IDENTITY_TECHNICAL_NOT_EQUAL')
        if type(n) is int and receipt.get('technical_frames_requested')!=3*n:
            problems.append(f'{tag}:FRAME_COUNT_WRONG')
        if type(n) is int and sum(receipt.get(k,0) for k in ('technical_pass','technical_warmup','technical_failed'))!=n:
            problems.append(f'{tag}:STATUS_SUM_WRONG')
        if receipt.get('technical_failed')!=0:
            problems.append(f'{tag}:FAILED_TECHNICAL')
        req=receipt.get('requests'); elapsed=receipt.get('duration_seconds')
        if type(req) is not int or not 1<=req<=MAX_REQUESTS:
            problems.append(f'{tag}:REQUEST_LIMIT_NOT_PROVED')
        if type(elapsed) not in (int,float) or not 0<=elapsed<=MAX_SECONDS:
            problems.append(f'{tag}:TIME_LIMIT_NOT_PROVED')
        for safety in ('orders_sent','notifications_sent','private_strategy_evaluated'):
            if receipt.get(safety)!=0:
                problems.append(f'{tag}:UNSAFE_{safety.upper()}')
        for safety in ('live_al_claim','native_wss_running','phone_delivery_ack'):
            if receipt.get(safety) is not False:
                problems.append(f'{tag}:UNSUPPORTED_{safety.upper()}')
        if receipt.get('http_provider_used') is not True or (
                not allow_warmup and receipt.get('live_source_acceptance') is not True):
            problems.append(f'{tag}:NOT_REAL_SOURCE_RECEIPT')
        if allow_warmup:
            if type(req) is int and req != 3*n+6:
                problems.append(f'{tag}:REQUEST_COUNT_NOT_FULL_SOURCE_SCAN')
            passed=receipt.get('technical_pass'); warmup=receipt.get('technical_warmup')
            if (type(passed) is not int or type(warmup) is not int or
                    passed<0 or warmup<0 or passed+warmup!=n):
                problems.append(f'{tag}:WARMUP_STATUS_ACCOUNTING_INVALID')
            rows=receipt.get('results')
            if isinstance(rows,list) and len(rows)==n:
                counts={'PASS':0,'WARMUP':0}; seen=set()
                for row in rows:
                    if not isinstance(row,dict):
                        problems.append(f'{tag}:INVALID_ROW'); continue
                    status=row.get('technical_data_quality')
                    if status not in counts:
                        problems.append(f'{tag}:INVALID_ROW_STATUS')
                    else:
                        counts[status]+=1
                    name=row.get('symbol')
                    if not isinstance(name,str) or not name or name in seen:
                        problems.append(f'{tag}:DUPLICATE_OR_INVALID_SYMBOL')
                    else:
                        seen.add(name)
                    frames=row.get('frame_quality')
                    if not isinstance(frames,dict) or set(frames)!={'1h','4h','1d'} or any(
                            not isinstance(v,str) or (v!='PASS' and not v.startswith('WARMUP_'))
                            for v in frames.values()):
                        problems.append(f'{tag}:INVALID_FRAME_QUALITY')
                    elif status=='PASS' and any(v!='PASS' for v in frames.values()):
                        problems.append(f'{tag}:PASS_WITH_WARMUP_FRAME')
                    elif status=='WARMUP' and all(v=='PASS' for v in frames.values()):
                        problems.append(f'{tag}:WARMUP_WITH_ALL_FRAMES_PASS')
                    if (row.get('orders_sent')!=0 or row.get('notifications_sent')!=0 or
                            row.get('buy_candidate') is not False):
                        problems.append(f'{tag}:UNSAFE_ROW')
                if counts!={'PASS':passed,'WARMUP':warmup}:
                    problems.append(f'{tag}:ROW_STATUS_COUNTS_WRONG')
        if len(receipt.get('results',[])) != n:
            problems.append(f'{tag}:MISSING_ROWS')
    epoch_a=a.get('utc_closed_epoch_1h_ms');epoch_b=b.get('utc_closed_epoch_1h_ms')
    if type(epoch_a) is not int or type(epoch_b) is not int or epoch_b-epoch_a!=HOUR:
        problems.append('NOT_CONSECUTIVE_DISTINCT_HOURS')
    if not isinstance(a.get('receipt_key'),str) or a.get('receipt_key')==b.get('receipt_key'):
        problems.append('DUPLICATE_OR_MISSING_RECEIPT_KEY')
    if allow_warmup:
        for i,r in enumerate((a,b),start=1):
            p=r.get('public_runner')
            if (not isinstance(p,dict) or p.get('repository')!='gokaydonmez39-jpg/xray-519-source-qa' or
                    not isinstance(p.get('run_id'),str) or not p['run_id'].isdecimal()):
                problems.append(f'{i}:UNTRUSTED_RUN_ID')
        if (isinstance(a.get('public_runner'),dict) and isinstance(b.get('public_runner'),dict) and
                a['public_runner'].get('run_id')==b['public_runner'].get('run_id')):
            problems.append('SAME_GITHUB_RUN_NOT_INDEPENDENT')
    if a.get('scope_digest_sha256')!=b.get('scope_digest_sha256'):
        problems.append('SCOPE_CHANGED_BETWEEN_HOURS')
    if a.get('identity_universe')!=b.get('identity_universe'):
        problems.append('MARKET_COUNT_CHANGED_BETWEEN_HOURS')
    return not problems,problems


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('first',type=Path); p.add_argument('second',type=Path)
    x=p.parse_args(argv)
    try:
        a=json.loads(x.first.read_text(encoding='utf-8'))
        b=json.loads(x.second.read_text(encoding='utf-8'))
        ok,problems=validate_pair(a,b)
    except (OSError, ValueError, TypeError) as e:
        print(json.dumps({'status':'HOLD','reason':type(e).__name__}))
        return 2
    print(json.dumps({'status':'LOCAL_RECEIPT_STRUCTURE_PASS' if ok else 'HOLD',
                      'not_remote_authentication':True,'issues':problems}))
    return 0 if ok else 2

if __name__=='__main__':
    sys.exit(main())
