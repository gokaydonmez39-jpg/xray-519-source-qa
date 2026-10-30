# XRAY-519 SOURCE + TECHNICAL QA (READ-ONLY)

## Security boundary

This is a **standalone, offline-testable source-research package**, authorized for public source research; full live quality acceptance remains gated. It does **not** import, copy, publish or modify any proprietary XRAY CORE-18/NASDAQ strategy, never places orders, never emits AL/STOP/2R candidates or notifications, never starts WSS. A separate, inactive-until-published public GitHub Actions workflow is now included for authorized deployment. It only collects public Binance Spot 1H/4H/1D *closed* OHLCV for active USDT symbols and computes descriptive technical indicators. `source_qa_success` is **not** a private-strategy success certificate. Product eligibility is **not established** by an exchange symbol appearing in the identity list or by raw volume/spread.

## Locally run tests

```
python -m unittest discover -s tests -v
python -O -m unittest discover -s tests -q
```

## Manual real Binance source pilot, on an internet-enabled host (requires separate execution/approval)

```
python research_519.py --max-markets 250 --output receipt-250.json
python research_519.py --max-markets 400 --output receipt-400.json
python research_519.py --max-markets 519 --output receipt-519.json
```

The CLI makes **anonymous GET** calls ONLY to `/api/v3/time`, `/api/v3/exchangeInfo`, `/api/v3/ticker/24hr`, `/api/v3/ticker/bookTicker` and `/api/v3/klines`. It fails closed on HTTP 418/429 and all network failures. It limits first-pass calls to 1,700, pace to at least 0.15 sec, and elapsed request-start runtime to 720 seconds. It loads 100 complete 1H + 40 complete 4H + 40 complete UTC 1D rows per symbol, each with `endTime` equal to the expected closed candle; it excludes still-forming data. New/short-history symbols are WARMUP; source/series anomalies are FAIL. If the scan begins in one UTC hour and ends in another, the receipt cannot PASS. It verifies live exchangeInfo scope again after scanning.

For 519 symbols at exactly 3 kline calls per symbol, request count is **1,563** including two `/time`, two `/exchangeInfo` and two bulk ticker/book calls; no WSS or persistent cache is assumed. Approximate *minimum* pacing is 234 seconds, plus network and processing. The actual throughput is **UNVERIFIED** without real deployment. Shared IP request weight can be consumed by other clients and rate limit headers need independent production-grade monitoring. GitHub schedule is not real-time, may be delayed/dropped, and a GitHub-hosted Actions job is not a continuously running host.

Research scope maximums 250, 400 or 519 select by rolling quote-volume **ranking**, not alphabetic order. Top 250 may include stablecoins, stock tokens or other instrument types; **not** 250 AL-eligible cryptocurrencies. No threshold is loosened: original AL rules remain in private independent CORE-18. The present program deliberately does NOT evaluate those rules.

## Acceptance protocol before *any* FINAL LIVE START

1. `OPEN_BAR_EXCLUDE`, gap/duplicate, nonfinite prices, zero-trade contradiction, taker excess, shifted scope/epoch, malformed identities and no-trade tests must pass normal and `-O` test modes.
2. A real internet-connected execution must show a 250, then 400, then 519 scope receipt within 720 sec and 1,700 calls; transient errors must remain HOLD. Strong acceptance requires **two consecutive distinct hourly epochs**, stable source scope and retained readback receipts; do not silently replace older receipts.
3. Verify explicit $0 cost guardrail/account billing policy in the owning GitHub account. On GitHub, use **a separate new public repository** with only audited source-QA code and no private strategy, and never expose private keys, lists or signals. Creating the repository makes public information irreversible, so requires explicit publication authorization; do **not** change the current private repository to public.
4. Private strategy, product identity / tradability classification, real device notification receipt and native 7×24 WSS have **separate** audits. None is implicitly PASS from this source package.

## Distinct results

`identity_universe` = current valid public Spot/USDT list; `technical_scanned` = count of selected pairs for which all three timeframes were requested (including QA failures); `technical_pass` = rows with enough valid, timely history; `technical_warmup` = underlisted history; `technical_failed` = corrupt or discontinuous data; `private_strategy_evaluated` always zero. Receipt contains no actual trade instructions.

## Pair evidence (offline structural checker)

`python verify_epoch_pair.py receipt-hour1.json receipt-hour2.json` checks two strictly consecutive hourly source receipts, request/time limits, market scope, three-frame counts, non-overlapping source-hour keys, no orders, and no false WSS/push claims. It refuses synthetic `HttpProvider=False` receipts. **JSON alone can be forged**; any live START requires independent GitHub run IDs and remote readback plus real Binance data and billing approval. Source-QA pair PASS still **does not** prove AL, no-repaint, strategy backtest, 7/24 service or iPhone ACK.

## One-action public source deployment handoff

See [`FINAL_START_AKTIVASYON_TR.md`](FINAL_START_AKTIVASYON_TR.md) and `.github/workflows/hourly-519-public-source.yml`. A newly created **separate public** repository named `gokaydonmez39-jpg/xray-519-source-qa` can stage hourly attempts automatically: 250→400→519 after each persisted stage receipt. The workflow is **deployed in the independent public repository**, and standard public GitHub runner usage is free per official documentation; no APNs, WSS, private AL strategy or order execution is introduced. Changes to existing private XRAY, CORE-18, and NASDAQ repositories are forbidden. The new repo requires explicit publication authorization.

The source host is Binance's official anonymous `https://data-api.binance.vision` (market-data-only); this reduces dependency on the regular trading/API hostname without guaranteeing connectivity from any particular GitHub runner.

## Sequential HTTPS transport

Direct standard runners reuse one TLS-verified connection without concurrent requests or automatic retries. Configured HTTPS/all proxy routes retain the original urllib transport. Request pacing, 720-second/1,700-request budgets, source schema, indicators and all quality/strategy boundaries are unchanged. Transport reuse, TLS verification, proxy routing, HTTP 301/418/429/503 rejection, wire failure and a real local persistent socket are covered by tests. 55 tests pass in both regular and optimized Python. First live source pilot: 250 scanned, 248 PASS, 2 WARMUP, zero FAIL, 756 requests, 369.458 seconds, run 41101495291; this is not full 519 quality acceptance.

The workflow fetches its remote branch before a scan, rejects stale trigger commits, and rejects an existing scope/UTC-hour receipt before making scan requests. Three tests execute this exact workflow block against isolated real git repositories. Local UTC is used only for early duplicate suppression; the existing Binance-server epoch and immutable publisher remain the acceptance and overwrite guards. A delayed duplicate produces FAIL_CLOSED with no new evidence.
