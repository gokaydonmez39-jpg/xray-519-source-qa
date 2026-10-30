#!/usr/bin/env python3
"""Package an independently generated Binance public REST QA receipt for public GitHub.

No orders, private configurations, push, authentication, or API keys.
The workflow, not this module, explicitly performs the remote push and readback.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

MAX_ARCHIVE_BYTES = 200_000
ALLOWED_LIMITS = (250, 400, 519)


class ReceiptError(ValueError):
    pass


def prepare(path: Path, dest_root: Path, *, owner_repo: str, run_id: str,
            run_attempt: str, mode: str) -> tuple[Path, str]:
    if owner_repo != 'gokaydonmez39-jpg/xray-519-source-qa':
        raise ReceiptError('WRONG_REPOSITORY')
    if not run_id.isdecimal() or not run_attempt.isdecimal() or not run_id or not run_attempt:
        raise ReceiptError('BAD_GITHUB_RUN_ID')
    if mode not in ('250','400','519'):
        raise ReceiptError('BAD_MODE')
    data = json.loads(path.read_text(encoding='utf-8'))
    checks = (
        data.get('schema') == 'XRAY_519_SOURCE_TECH_RESEARCH_V1',
        data.get('source') == 'BINANCE_PUBLIC_SPOT_REST',
        data.get('run_kind') == 'RESEARCH_ONLY_NO_AL',
        data.get('http_provider_used') is True,
        data.get('source_qa_success') is True,
        data.get('scope_stable') is True,
        data.get('epoch_stable') is True,
        data.get('status_accounting_ok') is True,
        data.get('orders_sent') == 0,
        data.get('notifications_sent') == 0,
        data.get('private_strategy_evaluated') == 0,
        data.get('live_al_claim') is False,
        data.get('native_wss_running') is False,
        data.get('phone_delivery_ack') is False,
        type(data.get('requests')) is int and 0 < data['requests'] <= 1700,
        type(data.get('duration_seconds')) in (int,float) and 0 <= data['duration_seconds'] <= 720,
        type(data.get('identity_universe')) is int and 0 < data['identity_universe'] <= 564,
        data.get('markets_selected') == min(data.get('identity_universe',0), int(mode)),
        data.get('technical_scanned') == data.get('markets_selected'),
        data.get('technical_frames_requested') == 3*data.get('markets_selected',-1),
        data.get('technical_pass',-1)+data.get('technical_warmup',-1)+data.get('technical_failed',-1) == data.get('markets_selected'),
        data.get('technical_failed') == 0,
        data.get('rank_ticker_missing_or_invalid') == 0,
        data.get('complete_identity_scope') is (data.get('identity_universe') <= int(mode)),
        isinstance(data.get('results'),list) and len(data['results']) == data['markets_selected'],
    )
    if not all(checks):
        raise ReceiptError('SOURCE_EVIDENCE_GATE_FAILED:'+','.join(str(i) for i,x in enumerate(checks) if not x))
    close_ms = data.get('utc_closed_epoch_1h_ms')
    if type(close_ms) is not int or close_ms <= 0 or (close_ms+1)%3600000:
        raise ReceiptError('INVALID_UTC_CLOSE')
    day = datetime.fromtimestamp((close_ms+1)/1000,timezone.utc)
    stamp=day.strftime('%Y%m%dT%H00Z')
    rel=Path('receipts')/day.strftime('%Y')/day.strftime('%m')/day.strftime('%d')/(stamp+'-n'+mode+'.json.gz')
    out=dest_root/rel
    if out.is_symlink() or out.exists():
        raise ReceiptError('DUPLICATE_RECEIPT_REFUSED')
    # Avoid accidentally publishing future private strategy payloads.
    public_keys={'schema','source','run_kind','http_provider_used','live_source_acceptance','start_server_ms','end_server_ms','utc_closed_epoch_1h_ms','identity_universe','markets_selected','rank_ticker_missing_or_invalid','technical_scanned','technical_frames_requested','technical_pass','technical_warmup','technical_failed','status_accounting_ok','scope_digest_sha256','receipt_key','scope_stable','epoch_stable','complete_identity_scope','full_technical_quality','source_qa_success','orders_sent','notifications_sent','private_strategy_evaluated','live_al_claim','native_wss_running','phone_delivery_ack','requests','duration_seconds','results'}
    if set(data) != public_keys:
        raise ReceiptError('UNKNOWN_TOP_LEVEL_FIELDS_STOP_PUBLICATION')
    public_result_keys={'symbol','identity','research_only','buy_candidate','orders_sent','notifications_sent','frame_quality','technical_data_quality','reason','technical','liquidity_snapshot','raw_15m_15bp_prefilter','liquidity_quality'}
    for row in data['results']:
        if not isinstance(row,dict) or not set(row).issubset(public_result_keys):
            raise ReceiptError('UNKNOWN_RESULT_FIELD_STOP_PUBLICATION')
        if row.get('orders_sent') != 0 or row.get('notifications_sent') != 0 or row.get('buy_candidate') is not False:
            raise ReceiptError('TRADE_CANDIDATE_FORBIDDEN')
    nested_schema = {
        'frame_quality': {'1h','4h','1d'},
        'technical': {'last_closed_price','ema20_1h','ema50_1h','ema20_4h','ema20_1d',
                      'rsi14_wilder_1h','prev20_high_1h','last_closed_quote_volume_1h',
                      'quote_rvol20_1h','asof_closed_utc_ms'},
        'liquidity_snapshot': {'rolling_24h_quote_usdt','spread_bp',
                               'ticker_within_120s','book_timestamp'},
    }
    for row in data['results']:
        for key, allowed_fields in nested_schema.items():
            if key in row:
                value=row[key]
                if not isinstance(value, dict) or not set(value).issubset(allowed_fields):
                    raise ReceiptError('UNKNOWN_NESTED_PUBLIC_FIELD')
                if key == 'technical':
                    asof=value.get('asof_closed_utc_ms')
                    if not isinstance(asof,dict) or set(asof) != {'1h','4h','1d'}:
                        raise ReceiptError('UNKNOWN_NESTED_PUBLIC_FIELD')
        for key in ('symbol','identity','reason','liquidity_quality'):
            if key in row and (not isinstance(row[key],str) or len(row[key])>180 or
                               any(ord(ch)<32 for ch in row[key])):
                raise ReceiptError('UNSAFE_PUBLIC_TEXT_FIELD')
    data['source_receipt_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    data['public_runner'] = {'repository':owner_repo, 'run_id':run_id,
                             'run_attempt':run_attempt, 'runner_type':'GITHUB_HOSTED_STANDARD_PUBLIC'}
    blob = json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    compressed=gzip.compress(blob,compresslevel=9,mtime=0)
    if len(compressed)>MAX_ARCHIVE_BYTES:
        raise ReceiptError('PUBLIC_RECEIPT_SIZE_EXCEEDED')
    out.parent.mkdir(parents=True,exist_ok=True)
    # Existing exact path is forbidden. A failed attempt must not overwrite evidence.
    with out.open('xb') as f:
        f.write(compressed)
        f.flush()
        os.fsync(f.fileno())
    return rel, hashlib.sha256(compressed).hexdigest()


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--mode',required=True)
    a=parser.parse_args()
    rel, sha=prepare(a.input,a.root,owner_repo=os.environ.get('GITHUB_REPOSITORY',''),
                     run_id=os.environ.get('GITHUB_RUN_ID',''),
                     run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT',''),mode=a.mode)
    # Passed to workflow as two independent lines; no untrusted path components.
    print(rel.as_posix())
    print(sha)

if __name__=='__main__':
    main()
