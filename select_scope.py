#!/usr/bin/env python3
"""Autonomous fail-closed public research pilot progression 250 -> 400 -> 519.

Proof comes from create-only repository receipts, not from environment guesses.
No public trading decisions or private strategy input.
"""
from __future__ import annotations
import gzip
import json
from pathlib import Path


class StageError(ValueError):
    pass


def valid_receipt(path: Path) -> int | None:
    if path.is_symlink() or path.suffix != '.gz' or path.stat().st_size > 200_000:
        return None
    try:
        with gzip.open(path,'rb') as f:
            data=json.loads(f.read(2_500_000))
        source=data['public_runner']
        if (source['repository'] != 'gokaydonmez39-jpg/xray-519-source-qa' or
            not source['run_id'].isdecimal() or
            data.get('source') != 'BINANCE_PUBLIC_SPOT_REST' or
            data.get('http_provider_used') is not True or
            data.get('source_qa_success') is not True or
            data.get('scope_stable') is not True or
            data.get('epoch_stable') is not True or
            data.get('technical_failed') != 0 or
            data.get('orders_sent') != 0 or
            data.get('notifications_sent') != 0 or
            data.get('private_strategy_evaluated') != 0):
            return None
        size=data['markets_selected']
        if size not in (250,400,519) or data.get('technical_scanned') != size:
            return None
        return size
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return None


def next_size(root: Path) -> int:
    receipt_dir=root/'receipts'
    confirmed=set()
    if receipt_dir.exists():
        for path in receipt_dir.glob('*/*/*/*.json.gz'):
            size=valid_receipt(path)
            if size is not None:
                confirmed.add(size)
    return 519 if 400 in confirmed else 400 if 250 in confirmed else 250


if __name__=='__main__':
    print(next_size(Path('.')))
