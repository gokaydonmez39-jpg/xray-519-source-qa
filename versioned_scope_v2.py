"""Offline supplemental gate, NOT production integration or release authority.

Trusted controller must call existing read_pair/verify_origin on the same pinned
commit, then supply independently acquired start/end exchangeInfo observations
from that epoch. Fixture/caller assertions alone do not establish live provenance.
Never fetches, writes, trades, dispatches, or authorizes release.
"""
from datetime import datetime, timezone, timedelta
import gzip, hashlib, io, json, re

MIN_SCOPE, MAX_SCOPE = 401, 564
SHA = re.compile(r'[0-9a-f]{64}\Z')
STAMP = re.compile(r'[0-9]{8}T[0-9]{2}00Z\Z')
ORIGINS = {'github_native_schedule', 'cloudflare_cron_trace_exact_run'}
class Hold(ValueError): pass

def require(condition, reason):
    if not condition: raise Hold(reason)

def canonical(obj):
    try: return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc: raise Hold('INVALID_CANONICAL') from exc

def digest(raw): return hashlib.sha256(raw).hexdigest()

def epoch(stamp):
    require(isinstance(stamp,str) and STAMP.fullmatch(stamp), 'INVALID_EPOCH')
    try: d=datetime.strptime(stamp,'%Y%m%dT%H00Z').replace(tzinfo=timezone.utc)
    except ValueError as exc: raise Hold('INVALID_EPOCH') from exc
    require(d.strftime('%Y%m%dT%H00Z')==stamp,'INVALID_EPOCH')
    return d

def integer(v): return type(v) is int

def decode_document(raw, compressed_limit, decoded_limit):
    require(type(raw) is bytes and 0<len(raw)<=compressed_limit,'DOCUMENT_SIZE')
    def unique(items):
        out={}
        for k,v in items:
            require(k not in out,'DUPLICATE_JSON_KEY'); out[k]=v
        return out
    def reject(_): raise Hold('NONFINITE_JSON')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f: data=f.read(decoded_limit+1)
        require(len(data)<=decoded_limit,'DOCUMENT_DECODE_LIMIT')
        doc=json.loads(data.decode('utf-8'),object_pairs_hook=unique,parse_constant=reject)
    except (OSError, EOFError, UnicodeError, ValueError) as exc:
        if isinstance(exc,Hold): raise
        raise Hold('INVALID_DOCUMENT') from exc
    require(type(doc) is dict,'INVALID_DOCUMENT'); return doc

def decode_receipt(raw):
    return decode_document(raw,200000,2500000)

def identity(meta):
    require(type(meta) is dict and type(meta.get('symbols')) is list,'EXCHANGEINFO_INVALID')
    rows=[]; seen=set()
    for row in meta['symbols']:
        require(type(row) is dict,'EXCHANGEINFO_ROW_INVALID')
        if row.get('status')!='TRADING' or row.get('isSpotTradingAllowed') is not True or row.get('quoteAsset')!='USDT': continue
        s,b=row.get('symbol'),row.get('baseAsset')
        require(type(s) is str and type(b) is str and bool(b) and s==b+'USDT' and len(s)<=64 and all(ord(c)>=33 and c not in '/\\?#&=' for c in s),'IDENTITY_INVALID')
        require(s not in seen,'IDENTITY_DUPLICATE'); seen.add(s)
        rows.append({'symbol':s,'baseAsset':b,'quoteAsset':'USDT'})
    require(MIN_SCOPE<=len(rows)<=MAX_SCOPE,'SCOPE_OUTSIDE_REVIEWED_BOUND')
    rows.sort(key=lambda r:r['symbol'].encode('utf-8'))
    return seen,digest(canonical(rows))

def verify_epoch(*, pair, origin, receipt_bytes, bridge_bytes, start_metadata, end_metadata, observed_start_ms, observed_end_ms):
    """Supplement actual read_pair + verify_origin; never replace their checks.
    Observation times must be trusted exchange-server timestamps acquired by
    independent collector, bracketing the scan, not timestamps reconstructed later.
    """
    require(type(pair) is dict and isinstance(origin,str) and origin in ORIGINS,'ORIGIN_OR_PAIR_UNVERIFIED')
    stamp=pair.get('stamp'); h=int(epoch(stamp).timestamp()*1000)
    require(type(bridge_bytes) is bytes and 0<len(bridge_bytes)<=8388608,'BRIDGE_SIZE')
    require(type(receipt_bytes) is bytes and digest(receipt_bytes)==pair.get('receipt_sha256') and digest(bridge_bytes)==pair.get('bridge_sha256'),'PAIR_BYTES_CHANGED')
    r=decode_receipt(receipt_bytes)
    n=pair.get('scope_count'); require(integer(n) and MIN_SCOPE<=n<=MAX_SCOPE,'SCOPE_OUTSIDE_REVIEWED_BOUND')
    require(integer(pair.get('run_id')) and pair['run_id']>0 and integer(pair.get('run_attempt')) and pair['run_attempt']>0,'RUN_INVALID')
    a,da=identity(start_metadata); b,db=identity(end_metadata)
    require(a==b and da==db,'IDENTITY_CHANGED_DURING_SCAN')
    require(len(a)==n and da==pair.get('scope_digest_sha256')==r.get('scope_digest_sha256'),'IDENTITY_DIGEST_MISMATCH')
    require(pair.get('scope_version')==f'{n}:{da}','SCOPE_VERSION_MISMATCH')
    begin,finish=r.get('start_server_ms'),r.get('end_server_ms')
    require(all(integer(v) for v in (observed_start_ms,begin,finish,observed_end_ms)) and h<=observed_start_ms<=begin<=finish<=observed_end_ms<=h+900000 and begin>=h+6000,'IDENTITY_OBSERVATION_OUTSIDE_EPOCH')
    require(r.get('utc_closed_epoch_1h_ms')==h-1,'RECEIPT_EPOCH_MISMATCH')
    require(all(integer(r.get(k)) and r[k]==n for k in ('identity_universe','markets_selected','technical_scanned')),'SCOPE_ACCOUNTING_INVALID')
    rows=r.get('results'); require(type(rows) is list and len(rows)==n,'RECEIPT_ROWS_INVALID')
    seen=set(); counts={'PASS':0,'WARMUP':0,'FAIL':0}
    for row in rows:
        require(type(row) is dict and type(row.get('symbol')) is str,'RECEIPT_ROW_INVALID')
        s=row['symbol']; q=row.get('technical_data_quality')
        require(s in a and s not in seen and row.get('identity')=='SPOT_USDT_TRADING','RECEIPT_IDENTITY_MISMATCH')
        require(row.get('research_only') is True and row.get('buy_candidate') is False and all(integer(row.get(k)) and row[k]==0 for k in ('orders_sent','notifications_sent')),'UNAUTHORIZED_ROW')
        require(type(q) is str and q in counts,'QUALITY_INVALID'); seen.add(s); counts[q]+=1
    require(seen==a and counts['FAIL']==0,'IDENTITY_OR_QUALITY_HOLD')
    for q,k in [('PASS','technical_pass'),('WARMUP','technical_warmup'),('FAIL','technical_failed')]:
        require(integer(r.get(k)) and integer(pair.get(k)) and r[k]==pair[k]==counts[q],'QUALITY_ACCOUNTING_MISMATCH')
    require(all(integer(r.get(k)) and r[k]==0 for k in ('orders_sent','notifications_sent','private_strategy_evaluated')) and r.get('live_al_claim') is False,'UNAUTHORIZED_RECEIPT')
    return {'stamp':stamp,'scope_count':n,'scope_version':f'{n}:{da}','run_id':pair['run_id'],'origin':origin,'receipt_sha256':pair['receipt_sha256'],'bridge_sha256':pair['bridge_sha256'],'technical_warmup':counts['WARMUP'],'status':'OFFLINE_EPOCH_ELIGIBLE_NOT_RELEASE','full_final_start':False}

def evaluate_window(records,end_stamp):
    """Only observations returned by trusted integration of verify_epoch count.
    This pure function is not proof of provenance or permission to start.
    """
    end=epoch(end_stamp); expected=[(end-timedelta(hours=i)).strftime('%Y%m%dT%H00Z') for i in range(47,-1,-1)]
    require(type(records) is list and len(records)<=10000,'INVALID_LEDGER')
    buckets={k:[] for k in expected}; runs={}; hashes={}
    for r in records:
        require(type(r) is dict,'INVALID_RECORD'); stamp=r.get('stamp'); epoch(stamp)
        if stamp not in buckets: continue
        buckets[stamp].append(r)
        rid=r.get('run_id'); require(integer(rid) and rid>0,'RUN_INVALID'); runs[rid]=runs.get(rid,0)+1
        for k in ('receipt_sha256','bridge_sha256'):
            v=r.get(k); require(type(v) is str and SHA.fullmatch(v),'INVALID_HASH'); key=(k,v); hashes[key]=hashes.get(key,0)+1
    errors={}; passed=0
    for stamp,group in buckets.items():
        if len(group)!=1: errors[stamp]='MISSING_OR_DUPLICATE_EPOCH'; continue
        r=group[0]; n=r.get('scope_count'); version=r.get('scope_version'); origin=r.get('origin')
        if r.get('status')!='OFFLINE_EPOCH_ELIGIBLE_NOT_RELEASE' or r.get('full_final_start') is not False or type(origin) is not str or origin not in ORIGINS or not integer(n) or not MIN_SCOPE<=n<=MAX_SCOPE or not isinstance(version,str) or not version.startswith(f'{n}:') or not SHA.fullmatch(version.split(':',1)[1]): errors[stamp]='INVALID_EPOCH_RECORD'; continue
        if runs[r['run_id']]!=1 or any(hashes[(k,r[k])]!=1 for k in ('receipt_sha256','bridge_sha256')): errors[stamp]='REUSED_RUN_OR_BYTES'; continue
        passed+=1
    return {'schema':'XRAY_VERSIONED_SCOPE_ACCEPTANCE_V2_OFFLINE_CANDIDATE','eligible_hours':passed,'required_hours':48,'offline_window_complete':passed==48,'diagnostics':errors,'live_evidence_independently_collected':False,'private_p30_verified':False,'full_final_start':False,'alert_release':False,'orders_permitted':False}


def verify_pinned_epoch(root, stamp, *, run_lookup, cloudflare_proof, start_metadata, end_metadata, observed_start_ms, observed_end_ms):
    """Integration seam for the EXISTING trusted read-only controller only.
    root must be an immutable/pinned checkout; observation acquisition and
    authentic Cloudflare mapping are controller responsibilities. No fallback.
    """
    from pathlib import Path
    from ops.versioned_scope_acceptance import read_pair, verify_origin, EvidenceHold
    d=epoch(stamp); folder=d.strftime('%Y/%m/%d'); root=Path(root)
    require(type(cloudflare_proof) is dict,'INVALID_PROVENANCE_MAP')
    try:
        pair=read_pair(root,stamp)
        run=run_lookup(pair['run_id'])
        require(type(run) is dict and type(run.get('created_at')) is str,'RUN_METADATA_INVALID')
        try: created=datetime.fromisoformat(run['created_at'].replace('Z','+00:00'))
        except ValueError as exc: raise Hold('RUN_METADATA_INVALID') from exc
        require(created.tzinfo is not None and created.utcoffset() is not None,'RUN_TIMEZONE_MISSING')
        origin=verify_origin(pair,run,cloudflare_proof.get(stamp))
        filename=f"{stamp}-n{pair['scope_count']}.json.gz"
        def read(kind,limit):
            p=root/kind/folder/filename
            require(not p.is_symlink() and p.is_file(),'PAIR_MISSING_OR_UNSAFE')
            with p.open('rb') as f: raw=f.read(limit+1)
            require(0<len(raw)<=limit,'PAIR_SIZE'); return raw
        receipt_raw=read('receipts',200000); bridge_raw=read('bridges',8388608)
        bridge=decode_document(bridge_raw,8388608,24*1024*1024)
        require(bridge.get('transport_profile')=='FULL_QUALITY_READY_V2','V2_FULL_QUALITY_PROFILE_REQUIRED')
        require(all(integer(bridge.get(k)) and bridge[k]==0 for k in ('orders_sent','notifications_sent','private_strategy_evaluated')) and bridge.get('live_al_claim') is False,'UNAUTHORIZED_BRIDGE')
        return verify_epoch(pair=pair,origin=origin,receipt_bytes=receipt_raw,bridge_bytes=bridge_raw,start_metadata=start_metadata,end_metadata=end_metadata,observed_start_ms=observed_start_ms,observed_end_ms=observed_end_ms)
    except Hold: raise
    except (EvidenceHold,OSError,TypeError,ValueError,KeyError,AttributeError,OverflowError) as exc: raise Hold('EXISTING_TRUSTED_GATE_HOLD') from exc
