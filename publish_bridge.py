"""Append-only public source bridge publisher. Uses no credentials or trade APIs."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path

from bridge_519 import BridgeError, MAX_GZIP_BYTES, SCHEMA, canonical_bytes


def prepare(bridge: Path, receipt: Path, root: Path) -> tuple[str, str]:
    if any(p.is_symlink() or not p.is_file() for p in (bridge, receipt)):
        raise BridgeError('MISSING_OR_SYMLINK_SOURCE')
    compressed=bridge.read_bytes()
    if not 0 < len(compressed) <= MAX_GZIP_BYTES:
        raise BridgeError('BRIDGE_FILE_TOO_LARGE')
    try:
        doc=json.loads(gzip.decompress(compressed))
        source=json.loads(receipt.read_bytes())
    except (OSError,ValueError,UnicodeError) as exc:
        raise BridgeError('UNREADABLE_BRIDGE_OR_RECEIPT') from exc
    if not isinstance(doc,dict) or doc.get('schema') != SCHEMA:
        raise BridgeError('INVALID_BRIDGE_SCHEMA')
    if not isinstance(source,dict) or source.get('source_qa_success') is not True:
        raise BridgeError('SOURCE_NOT_ACCEPTED')
    expected_hash=hashlib.sha256(canonical_bytes(source)).hexdigest()
    if doc.get('source_receipt_sha256') != expected_hash or doc.get('source_receipt_key') != source.get('receipt_key'):
        raise BridgeError('BRIDGE_RECEIPT_MISMATCH')
    for key in ('scope_digest_sha256','utc_closed_epoch_1h_ms','identity_universe'):
        if doc.get(key) != source.get(key):
            raise BridgeError('BRIDGE_PROVENANCE_MISMATCH')
    if doc.get('orders_sent') != 0 or doc.get('notifications_sent') != 0 or doc.get('live_al_claim') is not False:
        raise BridgeError('BRIDGE_UNSAFE')
    if doc.get('raw_prefilter_symbols') != doc.get('exported_symbols') + len(doc.get('deferred_symbols', {})):
        raise BridgeError('BRIDGE_COUNT_MISMATCH')
    epoch=source['utc_closed_epoch_1h_ms'] + 1
    dt=datetime.fromtimestamp(epoch/1000,timezone.utc)
    relative=f'bridges/{dt:%Y/%m/%d/%Y%m%dT%H00Z}-n{source["identity_universe"]}.json.gz'
    dest=root/relative
    if dest.exists() or dest.is_symlink():
        raise BridgeError('BRIDGE_EPOCH_ALREADY_PUBLISHED')
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_name(dest.name+'.tmp.'+str(os.getpid()))
    try:
        with temp.open('xb') as out:
            out.write(compressed);out.flush();os.fsync(out.fileno())
        try:
            os.link(temp,dest)
        except FileExistsError as exc:
            raise BridgeError('CONCURRENT_BRIDGE_PUBLISH') from exc
    finally:
        if temp.exists():temp.unlink()
    return relative, hashlib.sha256(compressed).hexdigest()


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--bridge',required=True,type=Path)
    p.add_argument('--receipt',required=True,type=Path)
    p.add_argument('--root',type=Path,default=Path('.'))
    args=p.parse_args(argv)
    try:
        relative,sha=prepare(args.bridge,args.receipt,args.root)
    except (BridgeError,OSError,TypeError,KeyError,OverflowError) as exc:
        p.exit(2,f'BRIDGE_PUBLISH_FAIL_CLOSED {exc}\n')
    print(relative)
    print(sha)
    return 0

if __name__=='__main__':raise SystemExit(main())
