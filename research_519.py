#!/usr/bin/env python3
"""XRAY 519 public Binance Spot/USDT technical research only.

Never emits buy/sell decisions, orders, credentials, notifications or private indicators.
A completed source run does not certify a private strategy or phone delivery.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from bridge_519 import BridgeCollector, COUNTS as BRIDGE_COUNTS, atomic_gzip

HOUR = 3_600_000
DAY = 24 * HOUR
PERIODS = {"1h": HOUR, "4h": 4 * HOUR, "1d": DAY}
COUNTS = {"1h": 100, "4h": 40, "1d": 40}
SCHEMA = "XRAY_519_SOURCE_TECH_RESEARCH_V1"
MAX_REQUESTS = 1700
MAX_SECONDS = 720.0
BASE_URL = "https://data-api.binance.vision"
ALLOWED_PATHS = frozenset({"/api/v3/time", "/api/v3/exchangeInfo",
                            "/api/v3/ticker/24hr", "/api/v3/ticker/bookTicker",
                            "/api/v3/klines"})


class SourceError(RuntimeError):
    pass


class FatalSourceError(SourceError):
    pass


class QualityError(SourceError):
    pass


class Warmup(SourceError):
    pass


def finite_decimal(v: Any, *, nonnegative: bool = False) -> Decimal:
    if isinstance(v, (bool, type(None))):
        raise QualityError("INVALID_NUMERIC_TYPE")
    try:
        n = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise QualityError("INVALID_NUMBER") from None
    if not n.is_finite() or (nonnegative and n < 0):
        raise QualityError("NONFINITE_OR_NEGATIVE")
    return n


def parse_epoch(v: Any) -> int:
    if type(v) is not int or v < 1_500_000_000_000:
        raise QualityError("INVALID_EPOCH")
    return v


def instrument_scope(metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(metadata, dict) or not isinstance(metadata.get("symbols"), list):
        raise QualityError("MISSING_EXCHANGEINFO")
    selected = []
    seen = set()
    for row in metadata["symbols"]:
        if not isinstance(row, dict):
            raise QualityError("MALFORMED_INSTRUMENT")
        if row.get("status") != "TRADING" or row.get("isSpotTradingAllowed") is not True or row.get("quoteAsset") != "USDT":
            continue
        symbol = row.get("symbol")
        base = row.get("baseAsset")
        if not isinstance(symbol, str) or not isinstance(base, str) or not symbol.endswith("USDT") or not symbol or len(symbol) > 64:
            raise QualityError("BAD_EXACT_SYMBOL")
        if any(ord(ch) < 33 or ch in '/\\?#&=' for ch in symbol):
            raise QualityError("UNSAFE_EXACT_SYMBOL")
        if symbol in seen:
            raise QualityError("DUPLICATE_EXACT_SYMBOL")
        seen.add(symbol)
        selected.append({"symbol": symbol, "baseAsset": base, "quoteAsset": "USDT"})
    selected.sort(key=lambda r: r["symbol"].encode("utf-8"))
    if not selected:
        raise QualityError("NO_ACTIVE_SPOT_USDT")
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    return selected, digest


def closed_epoch(server_ms: int, period: int) -> int:
    return (parse_epoch(server_ms) // period) * period - 1


def parse_candles(raw: Any, *, period: int, expected: int, required: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise QualityError("NONLIST_KLINES")
    closed = []
    previous_open = None
    for r in raw:
        if not isinstance(r, list) or len(r) < 11:
            raise QualityError("MALFORMED_KLINE")
        op, cl = r[0], r[6]
        if type(op) is not int or type(cl) is not int:
            raise QualityError("NONINTEGER_KLINE_TIME")
        if previous_open is not None and op <= previous_open:
            raise QualityError("UNSORTED_OR_DUPLICATE_KLINE")
        previous_open = op
        if cl > expected:
            # Forming candles are never used in any indicator computation.
            continue
        if op % period or cl != op + period - 1:
            raise QualityError("INVALID_PERIOD_ALIGNMENT")
        o, h, l, c = (finite_decimal(r[k], nonnegative=True) for k in (1, 2, 3, 4))
        vol = finite_decimal(r[5], nonnegative=True)
        quote = finite_decimal(r[7], nonnegative=True)
        trades = r[8]
        if type(trades) is not int or trades < 0:
            raise QualityError("INVALID_TRADES")
        tb = finite_decimal(r[9], nonnegative=True)
        tq = finite_decimal(r[10], nonnegative=True)
        if min(o, c, l) <= 0 or h < max(o, c, l) or l > min(o, c, h):
            raise QualityError("INVALID_OHLC")
        if vol > 0 and quote == 0:
            raise QualityError("NONZERO_VOLUME_CONTRADICTION")
        if tb > vol or tq > quote:
            raise QualityError("TAKER_EXCEEDS_TOTAL")
        if vol == 0 and (quote != 0 or tb != 0 or tq != 0 or trades != 0 or len({o,h,l,c}) != 1):
            raise QualityError("ZERO_TRADE_CONTRADICTION")
        if vol > 0 and (quote == 0 or trades == 0):
            raise QualityError("NONZERO_VOLUME_CONTRADICTION")
        closed.append({"open_ms": op, "close_ms": cl, "o": float(o), "h": float(h),
                       "l": float(l), "c": float(c), "base_volume": float(vol),
                       "quote_volume": float(quote), "trades": trades, "taker_quote": float(tq)})
    if len(closed) < required:
        raise Warmup(f"CLOSED_HISTORY_{len(closed)}_OF_{required}")
    chosen = closed[-required:]
    if chosen[-1]["close_ms"] != expected:
        raise QualityError("LAST_CLOSED_BAR_MISMATCH")
    for a, b in zip(chosen, chosen[1:]):
        if b["open_ms"] - a["open_ms"] != period:
            raise QualityError("CLOSED_BAR_GAP")
    return chosen


def ema(values: list[float], n: int) -> float:
    if len(values) < n:
        raise Warmup("EMA_WARMUP")
    v = sum(values[:n]) / n
    k = 2 / (n + 1)
    for value in values[n:]:
        v = value * k + v * (1-k)
    return v


def wilder_rsi(values: list[float], n: int = 14) -> float:
    if len(values) < n + 1:
        raise Warmup("RSI_WARMUP")
    changes = [b-a for a,b in zip(values, values[1:])]
    gains = sum(max(x, 0) for x in changes[:n]) / n
    losses = sum(max(-x, 0) for x in changes[:n]) / n
    for x in changes[n:]:
        gains = (gains*(n-1)+max(x, 0)) / n
        losses = (losses*(n-1)+max(-x, 0)) / n
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0/(1.0 + gains/losses)


def indicators(series: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    h1 = series['1h']; h4 = series['4h']; d1 = series['1d']
    c1 = [r['c'] for r in h1]; c4 = [r['c'] for r in h4]; cd = [r['c'] for r in d1]
    prev = h1[-21:-1]
    avg_quote = sum(r['quote_volume'] for r in prev)/20
    q = h1[-1]['quote_volume']
    data = {
        "last_closed_price": c1[-1], "ema20_1h": ema(c1, 20),
        "ema50_1h": ema(c1, 50), "ema20_4h": ema(c4, 20),
        "ema20_1d": ema(cd, 20), "rsi14_wilder_1h": wilder_rsi(c1),
        "prev20_high_1h": max(r['h'] for r in prev),
        "last_closed_quote_volume_1h": q,
        "quote_rvol20_1h": q / avg_quote if avg_quote > 0 else None,
        "asof_closed_utc_ms": {k: v[-1]['close_ms'] for k,v in series.items()},
    }
    for k,v in data.items():
        if isinstance(v,float) and not math.isfinite(v):
            raise QualityError("NONFINITE_INDICATOR")
    return data


class HttpProvider:
    def __init__(self, *, pace: float = 0.15, max_requests: int = MAX_REQUESTS,
                 max_seconds: float = MAX_SECONDS, timeout: float = 8.0,
                 clock=time.monotonic, sleeper=time.sleep):
        if not (0 <= pace <= 2) or not (1 <= max_requests <= MAX_REQUESTS) or not (0 < max_seconds <= MAX_SECONDS):
            raise ValueError("BOUNDS_VIOLATION")
        self.pace, self.max_requests, self.max_seconds, self.timeout = pace, max_requests, max_seconds, timeout
        self.clock, self.sleeper = clock, sleeper
        self.started = clock()
        self.previous = None
        self.requests = 0
        proxies = urllib.request.getproxies()
        # Preserve the configured proxy route exactly. Direct standard runners
        # can reuse one verified TLS connection instead of reconnecting per GET.
        host = urllib.parse.urlsplit(BASE_URL).hostname
        proxy_required = bool(proxies.get('https') or proxies.get('all')) and not urllib.request.proxy_bypass(host)
        self.opener = (urllib.request.build_opener(_NoRedirect()) if proxy_required
                       else _PersistentHTTPSOpener())

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if path not in ALLOWED_PATHS:
            raise FatalSourceError("DISALLOWED_ENDPOINT")
        if self.requests >= self.max_requests:
            raise FatalSourceError("REQUEST_LIMIT_REACHED")
        if self.clock() - self.started >= self.max_seconds:
            raise FatalSourceError("DURATION_LIMIT_REACHED")
        if self.previous is not None:
            delay = self.pace - (self.clock()-self.previous)
            if delay > 0:
                self.sleeper(delay)
        self.previous = self.clock()
        self.requests += 1
        url = BASE_URL + path + ('?' + urllib.parse.urlencode(params, encoding='utf-8') if params else '')
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "XRAY-ReadOnly-Research/1"}, method='GET')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise FatalSourceError(f"HTTP_{response.status}_FAIL_CLOSED")
                raw = response.read(16_000_001)
                if len(raw) > 16_000_000:
                    raise FatalSourceError("OVERSIZE_RESPONSE")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raise FatalSourceError(f"HTTP_{e.code}_FAIL_CLOSED") from None
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError, http.client.HTTPException, ValueError, json.JSONDecodeError) as e:
            raise FatalSourceError(f"SOURCE_UNAVAILABLE_{type(e).__name__}") from None


class _PersistentHTTPSOpener:
    """One sequential TLS connection; never follows redirects or retries a GET."""
    def __init__(self):
        self.connection = None

    def open(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        base = urllib.parse.urlsplit(BASE_URL)
        if (url.scheme != 'https' or url.hostname != base.hostname or
            url.port not in (None, 443) or url.username is not None or
            url.password is not None or url.fragment or
            request.get_method() != 'GET' or url.path not in ALLOWED_PATHS):
            raise FatalSourceError('DISALLOWED_TRANSPORT_TARGET')
        if self.connection is None:
            self.connection = http.client.HTTPSConnection(
                base.hostname, timeout=timeout, context=ssl.create_default_context())
        target = url.path + ('?' + url.query if url.query else '')
        try:
            self.connection.request('GET', target, headers=dict(request.header_items()))
            return self.connection.getresponse()
        except (OSError, http.client.HTTPException):
            self.connection.close()
            raise


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FatalSourceError("REDIRECT_FORBIDDEN")


def _ticker_map(rows: Any, required: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise QualityError("BULK_NOT_LIST")
    lookup = {}
    desired = set(required)
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("symbol"), str):
            raise QualityError("MALFORMED_BULK_ROW")
        if r['symbol'] in desired:
            if r['symbol'] in lookup:
                raise QualityError("DUPLICATE_BULK_SYMBOL")
            lookup[r['symbol']] = r
    return lookup


def scan(provider: Any, *, max_markets: int | None = None,
         bridge_sink: BridgeCollector | None = None) -> dict[str, Any]:
    if max_markets is not None and (type(max_markets) is not int or max_markets < 1 or max_markets > 519):
        raise ValueError("INVALID_MARKET_LIMIT")
    begun = time.monotonic()
    start_ms = parse_epoch(provider.get('/api/v3/time')['serverTime'])
    raw_scope = provider.get('/api/v3/exchangeInfo', {'showPermissionSets': 'false'})
    scope, digest = instrument_scope(raw_scope)
    identity_count = len(scope)
    ticks = _ticker_map(provider.get('/api/v3/ticker/24hr'), [r['symbol'] for r in scope])
    books = _ticker_map(provider.get('/api/v3/ticker/bookTicker'), [r['symbol'] for r in scope])
    rank_volumes = {}
    rank_invalid = 0
    for row in scope:
        item = ticks.get(row['symbol'])
        try:
            if item is None:
                raise QualityError('MISSING_RANK_TICKER')
            rank_volumes[row['symbol']] = float(finite_decimal(item.get('quoteVolume'), nonnegative=True))
        except QualityError:
            rank_invalid += 1
            rank_volumes[row['symbol']] = -1.0
    if max_markets is not None and max_markets < identity_count and rank_invalid:
        raise QualityError('INCOMPLETE_VOLUME_RANKING')
    scope.sort(key=lambda row: (-rank_volumes[row['symbol']], row['symbol'].encode('utf-8')))
    chosen = scope[:max_markets] if max_markets is not None else scope
    counts = Counter()
    results = []
    deadlines = {interval:closed_epoch(start_ms, period) for interval,period in PERIODS.items()}
    for market in chosen:
        symbol = market['symbol']
        result = {"symbol":symbol, "identity":"SPOT_USDT_TRADING", "research_only":True,
                  "buy_candidate":False,"orders_sent":0,"notifications_sent":0}
        bars = {}
        frame_quality = {}
        # Fetch all three frames even if one frame fails QA. This guarantees
        # a truthful 3-frame request count without mixing valid and invalid data.
        for interval, required in COUNTS.items():
            raw = provider.get('/api/v3/klines', {'symbol':symbol, 'interval':interval,
                                                 'limit':(BRIDGE_COUNTS[interval] if bridge_sink is not None else required),
                                                 'endTime':deadlines[interval]})
            if bridge_sink is not None:
                try:
                    extended = parse_candles(raw, period=PERIODS[interval],
                                             expected=deadlines[interval],
                                             required=BRIDGE_COUNTS[interval])
                    bridge_sink.put(symbol, interval, extended)
                except (Warmup, QualityError) as exc:
                    bridge_sink.mark(symbol, interval, str(exc))
            try:
                bars[interval] = parse_candles(raw, period=PERIODS[interval],
                                               expected=deadlines[interval], required=required)
                frame_quality[interval] = 'PASS'
            except Warmup as e:
                frame_quality[interval] = 'WARMUP_' + str(e)
            except QualityError as e:
                frame_quality[interval] = 'FAIL_' + str(e)
        result['frame_quality'] = frame_quality
        failed = [v[5:] for v in frame_quality.values() if v.startswith('FAIL_')]
        warming = [v[7:] for v in frame_quality.values() if v.startswith('WARMUP_')]
        if failed:
            result.update(technical_data_quality='FAIL', reason=failed[0])
        elif warming:
            result.update(technical_data_quality='WARMUP', reason=warming[0])
        else:
            try:
                result['technical'] = indicators(bars)
                result['technical_data_quality'] = 'PASS'
            except Warmup as e:
                result.update(technical_data_quality='WARMUP', reason=str(e))
            except QualityError as e:
                result.update(technical_data_quality='FAIL', reason=str(e))
        counts[result['technical_data_quality']] += 1
        t = ticks.get(symbol); b = books.get(symbol)
        try:
            if not t or not b:
                raise QualityError("MISSING_TICKER_OR_BOOK")
            q = float(finite_decimal(t.get('quoteVolume'),nonnegative=True))
            bid = float(finite_decimal(b.get('bidPrice'),nonnegative=True))
            ask = float(finite_decimal(b.get('askPrice'),nonnegative=True))
            close = parse_epoch(t.get('closeTime'))
            if not (bid > 0 and ask > bid):
                raise QualityError('INVALID_BOOK')
            spread_bp = 20000*(ask-bid)/(ask+bid)
            isfresh = abs(start_ms-close) <= 120_000
            result['liquidity_snapshot']={"rolling_24h_quote_usdt":q,"spread_bp":spread_bp,
                                        "ticker_within_120s":isfresh,"book_timestamp":"UNAVAILABLE"}
            result['raw_15m_15bp_prefilter'] = q >= 15_000_000 and spread_bp <= 15 and isfresh
        except QualityError as e:
            result['liquidity_quality']='UNKNOWN_'+str(e)
            result['raw_15m_15bp_prefilter']=False
        results.append(result)
    end_ms = parse_epoch(provider.get('/api/v3/time')['serverTime'])
    end_scope, end_digest = instrument_scope(provider.get('/api/v3/exchangeInfo', {'showPermissionSets': 'false'}))
    scope_stable = digest == end_digest
    epoch_stable = start_ms // HOUR == end_ms // HOUR
    duration = time.monotonic()-begun
    count_ok = sum(counts.values()) == len(chosen)
    full_inventory = len(chosen) == identity_count
    no_qa_errors = counts['FAIL'] == 0
    report = {
      "schema":SCHEMA,"source":"BINANCE_PUBLIC_SPOT_REST","run_kind":"RESEARCH_ONLY_NO_AL",
      "http_provider_used":type(provider) is HttpProvider,
      "live_source_acceptance":(type(provider) is HttpProvider and full_inventory and
                                counts['PASS']==identity_count and scope_stable and epoch_stable), 
      "start_server_ms":start_ms,"end_server_ms":end_ms,"utc_closed_epoch_1h_ms":deadlines['1h'],
      "identity_universe":identity_count,"markets_selected":len(chosen),
      "rank_ticker_missing_or_invalid":rank_invalid,
      "technical_scanned":len(results), "technical_frames_requested":len(results)*3,
      "technical_pass":counts['PASS'],
      "technical_warmup":counts['WARMUP'],"technical_failed":counts['FAIL'],
      "status_accounting_ok":count_ok,"scope_digest_sha256":digest,
      "receipt_key":f"{SCHEMA}|{deadlines['1h']}|{digest}|{len(chosen)}",
      "scope_stable":scope_stable,"epoch_stable":epoch_stable,"complete_identity_scope":full_inventory,
      "full_technical_quality":(full_inventory and counts['PASS']==identity_count and scope_stable and epoch_stable),
      "source_qa_success":(no_qa_errors and scope_stable and epoch_stable and count_ok),
      "orders_sent":0,"notifications_sent":0,"private_strategy_evaluated":0,
      "live_al_claim":False,"native_wss_running":False,"phone_delivery_ack":False,
      "requests":getattr(provider,'requests',None),"duration_seconds":round(duration,3),
      "results":results
    }
    if bridge_sink is not None:
        bridge_sink.finish(report)
    return report


def atomic_json(path: Path, report: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ValueError('OUTPUT_SYMLINK_FORBIDDEN')
    if path.exists():
        raise ValueError('EXISTING_RECEIPT_REFUSED')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_name(path.name + '.tmp.' + str(os.getpid()))
    if tmp.is_symlink():
        raise ValueError('TEMP_SYMLINK_FORBIDDEN')
    blob = json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode('utf-8')
    try:
        with tmp.open('xb') as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        # Atomic create-only: even a concurrent writer cannot overwrite a receipt.
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise ValueError('EXISTING_RECEIPT_REFUSED') from None
        if hasattr(os, 'O_DIRECTORY'):
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='READ-ONLY closed-candle Spot/USDT technical source scan')
    ap.add_argument('--max-markets',type=int,choices=(250,400,519),default=519)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--bridge-output',type=Path,default=None)
    ap.add_argument('--pace',type=float,default=0.15)
    args = ap.parse_args(argv)
    if args.pace < 0.15:
        ap.error('production pace cannot be less than 0.15 seconds')
    if args.bridge_output is not None and args.max_markets != 519:
        ap.error('bridge requires complete 519-identity scope and does not support partial scans')
    if args.bridge_output is not None and args.bridge_output == args.output:
        ap.error('bridge must never overwrite source receipt')
    provider = HttpProvider(pace=args.pace)
    bridge_sink = BridgeCollector() if args.bridge_output is not None else None
    print(json.dumps({'event':'SOURCE_TRANSPORT', 'transport':type(provider.opener).__name__}),file=sys.stderr)
    try:
        report = scan(provider,max_markets=args.max_markets,bridge_sink=bridge_sink)
        if report['duration_seconds'] > MAX_SECONDS or report['requests'] > MAX_REQUESTS:
            raise FatalSourceError('END_OF_RUN_BUDGET_EXCEEDED')
        atomic_json(args.output, report)
        if bridge_sink is not None:
            checksum, nbytes = atomic_gzip(args.bridge_output, bridge_sink.document)
            print(json.dumps({'event':'PUBLIC_INPUT_BRIDGE_PREPARED_NOT_PRIVATE_AL',
                              'sha256':checksum,'bytes':nbytes,
                              'eligible_raw_source_markets':bridge_sink.document['exported_symbols']}),file=sys.stderr)
        print(json.dumps({k:v for k,v in report.items() if k != 'results'},ensure_ascii=False))
        return 0 if report['source_qa_success'] else 2
    except (SourceError, ValueError, TypeError, KeyError) as e:
        # Fatal errors do not create or overwrite an attestation receipt.
        print(json.dumps({'status':'FAIL_CLOSED','error':str(e), 'request_count':provider.requests,
                          'duration_seconds':round(provider.clock()-provider.started,3),
                          'orders_sent':0,'notifications_sent':0}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
