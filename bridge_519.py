"""Public-only closed-mum transport for a separately operated private strategy.

No strategy thresholds, private credentials, orders, alerts, or AL classifications.
This produces provenance-bound public OHLCV inputs; it cannot authorize an AL.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path

COUNTS = {'1h': 100, '4h': 70, '1d': 60}
SCHEMA = 'XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1'
MAX_RAW_BYTES = 24 * 1024 * 1024
MAX_GZIP_BYTES = 8 * 1024 * 1024

class BridgeError(ValueError):
    pass


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _safe_symbol(symbol: str) -> bool:
    return (isinstance(symbol, str) and 3 <= len(symbol) <= 64 and
            symbol.endswith('USDT') and symbol.isupper() and
            all(ch not in '/\\\\?#&= \\t\\r\\n' and ord(ch) >= 33 for ch in symbol))


class BridgeCollector:
    """Memory-bounded source snapshot; private signal engine stays separate."""
    def __init__(self):
        self.frames: dict[str, dict[str, list[dict]]] = {}
        self.problems: dict[str, dict[str, str]] = {}
        self.document: dict | None = None

    def put(self, symbol: str, interval: str, candles: list[dict]) -> None:
        if not _safe_symbol(symbol) or interval not in COUNTS:
            raise BridgeError('INVALID_BRIDGE_IDENTITY')
        if not isinstance(candles, list) or len(candles) != COUNTS[interval]:
            raise BridgeError('BRIDGE_HISTORY_LENGTH_MISMATCH')
        for bar in candles:
            if not isinstance(bar, dict) or set(bar) != {
                    'open_ms', 'close_ms', 'o', 'h', 'l', 'c',
                    'base_volume', 'quote_volume', 'trades', 'taker_quote'}:
                raise BridgeError('BRIDGE_BAR_SCHEMA_MISMATCH')
            if any(type(bar[k]) not in (int, float) or not math.isfinite(bar[k])
                   for k in ('o','h','l','c','base_volume','quote_volume','taker_quote')):
                raise BridgeError('BRIDGE_NONFINITE_BAR')
        if interval in self.frames.get(symbol, {}):
            raise BridgeError('DUPLICATE_BRIDGE_FRAME')
        self.frames.setdefault(symbol, {})[interval] = candles

    def mark(self, symbol: str, interval: str, error: str) -> None:
        if not _safe_symbol(symbol) or interval not in COUNTS or not isinstance(error, str):
            raise BridgeError('INVALID_BRIDGE_STATUS')
        self.problems.setdefault(symbol, {})[interval] = error[:140]

    def finish(self, receipt: dict) -> dict:
        if self.document is not None:
            raise BridgeError('BRIDGE_ALREADY_FINALIZED')
        required = ('source_qa_success','scope_stable','epoch_stable','complete_identity_scope')
        if not isinstance(receipt, dict) or any(receipt.get(k) is not True for k in required):
            raise BridgeError('SOURCE_RECEIPT_NOT_ACCEPTED')
        if (receipt.get('orders_sent') != 0 or receipt.get('notifications_sent') != 0 or
            receipt.get('private_strategy_evaluated') != 0 or receipt.get('live_al_claim') is not False):
            raise BridgeError('UNSAFE_SOURCE_RECEIPT')
        if (type(receipt.get('markets_selected')) is not int or
                receipt['markets_selected'] != receipt.get('identity_universe') or
                type(receipt.get('utc_closed_epoch_1h_ms')) is not int):
            raise BridgeError('INCOMPLETE_SCOPE_OR_EPOCH')
        digest = receipt.get('scope_digest_sha256')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise BridgeError('SCOPE_DIGEST_INVALID')
        btc = self.frames.get('BTCUSDT', {}).get('1d')
        if btc is None or len(btc) != COUNTS['1d']:
            raise BridgeError('BTC_DAILY_CONTEXT_NOT_READY')
        results = receipt.get('results')
        if not isinstance(results, list) or len(results) != receipt['markets_selected']:
            raise BridgeError('SOURCE_RESULTS_INCOMPLETE')
        names = set()
        selected = {}
        deferred = {}
        for row in results:
            if not isinstance(row,dict) or not _safe_symbol(row.get('symbol')):
                raise BridgeError('INVALID_SOURCE_MARKET')
            sym = row['symbol']
            if sym in names:
                raise BridgeError('DUPLICATE_SOURCE_MARKET')
            names.add(sym)
            if row.get('raw_15m_15bp_prefilter') is not True:
                continue
            if row.get('technical_data_quality') != 'PASS':
                deferred[sym] = 'SOURCE_FRAME_NOT_PASS'
                continue
            frames = self.frames.get(sym, {})
            if set(frames) != set(COUNTS):
                deferred[sym] = dict(self.problems.get(sym, {})) or 'FULL_HISTORY_NOT_READY'
                continue
            market = row.get('liquidity_snapshot')
            if not isinstance(market, dict) or market.get('ticker_within_120s') is not True:
                deferred[sym] = 'STALE_OR_MISSING_TICKER'
                continue
            try:
                q = float(market['rolling_24h_quote_usdt'])
                spread = float(market['spread_bp'])
            except (ValueError,TypeError,KeyError) as exc:
                raise BridgeError('INVALID_PREFILTER_VALUES') from exc
            if (not math.isfinite(q) or q < 15_000_000 or not math.isfinite(spread)
                    or not 0 <= spread <= 15):
                raise BridgeError('PREFILTER_CLAIM_INVALID')
            for interval, expected in (('1h', 3_600_000), ('4h', 14_400_000), ('1d', 86_400_000)):
                end = (int(receipt['start_server_ms']) // expected) * expected - 1
                if frames[interval][-1]['close_ms'] != end:
                    raise BridgeError('FRAME_EPOCH_MISMATCH')
            selected[sym] = {'frames':frames,'liquidity_snapshot':market}
        if len(names) != receipt['markets_selected']:
            raise BridgeError('SOURCE_IDENTITY_COUNT_MISMATCH')
        self.document = {
            'schema':SCHEMA,'source':'BINANCE_PUBLIC_SPOT_REST',
            'disposition':'PUBLIC_DATA_ONLY_PRIVATE_STRATEGY_NOT_EVALUATED',
            'source_receipt_sha256':hashlib.sha256(canonical_bytes(receipt)).hexdigest(),
            'source_receipt_key':receipt['receipt_key'],
            'scope_digest_sha256':digest,
            'utc_closed_epoch_1h_ms':receipt['utc_closed_epoch_1h_ms'],
            'source_start_server_ms':receipt['start_server_ms'],
            'source_end_server_ms':receipt['end_server_ms'],
            'identity_universe':receipt['identity_universe'],
            'raw_prefilter_symbols':sum(row.get('raw_15m_15bp_prefilter') is True for row in results),
            'exported_symbols':len(selected),'deferred_symbols':deferred,
            'btc_daily_60':btc,
            'markets':selected,
            'orders_sent':0,'notifications_sent':0,'private_strategy_evaluated':0,
            'live_al_claim':False,
        }
        raw = canonical_bytes(self.document)
        if len(raw) > MAX_RAW_BYTES:
            self.document = None
            raise BridgeError('BRIDGE_RAW_SIZE_LIMIT')
        return self.document


def atomic_gzip(path: Path, document: dict) -> tuple[str, int]:
    if not isinstance(document, dict) or document.get('schema') != SCHEMA:
        raise BridgeError('UNVERIFIED_BRIDGE_DOCUMENT')
    raw = canonical_bytes(document)
    if len(raw) > MAX_RAW_BYTES:
        raise BridgeError('BRIDGE_RAW_SIZE_LIMIT')
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    if len(compressed) > MAX_GZIP_BYTES:
        raise BridgeError('BRIDGE_GZIP_SIZE_LIMIT')
    if path.is_symlink() or path.exists() or path.suffix != '.gz':
        raise BridgeError('EXISTING_OR_UNSAFE_BRIDGE_PATH')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp.'+str(os.getpid()))
    try:
        with tmp.open('xb') as f:
            f.write(compressed)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp,path)
        except FileExistsError as exc:
            raise BridgeError('CONCURRENT_BRIDGE_WRITE') from exc
    finally:
        if tmp.exists():
            tmp.unlink()
    return hashlib.sha256(compressed).hexdigest(), len(compressed)
