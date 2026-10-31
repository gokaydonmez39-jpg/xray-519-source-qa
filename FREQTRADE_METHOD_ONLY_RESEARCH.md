# Freqtrade-inspired offline methodology — XRAY 519 public source QA

**NO Freqtrade installation or integration.** Official references:
https://www.freqtrade.io/en/stable/lookahead-analysis/
https://www.freqtrade.io/en/stable/recursive-analysis/

The new files are standalone, zero-network tests calling already-existing
`research_519.indicators` and `research_519.ema` with invented OHLCV.
They do not run Freqtrade's own backtest/strategy engine, cannot prove
private AL signal quality and cannot read private CORE-18.

## Falsification contract (before CI)
- Reject a future/forming candle in **all three frames**: 1H, 4H and 1D.
- Reject missing frames, stale final close, duplicates/gaps, missing warmup,
  malformed OHLC, NaN. Never substitute or interpolate.
- Constant-price EMA must be stable to longer/shorter startup input.
  An intentionally nonstationary synthetic EMA must report startup
  sensitivity: a recursive divergence is DIAGNOSTIC and not automatically AL.
- The existing Binance source GET-only path allowlist must stay unchanged.
- Run Python and `-O` tests in existing source-only GitHub PR CI, not private
  paid compute. 0 orders, 0 private keys, 0 live WSS, 0 API calls, 0 alerts.

## Outstanding operational NO-GO
Last independently verified distinct 519-source epochs: **489 PASS,
30 WARMUP, 0 FAIL**. Coverage is 519; it is not a 519/519 technical quality
pass. Source-only success does not establish live private AL, product
eligibility, iPhone delivery acknowledgement, reliable 7x24 GitHub schedule,
or native WebSocket. No strategy, cloud production config or scheduler changes.

This is a Freqtrade *inspired* static/structural sample; the real Freqtrade
lookahead-analysis can miss untriggered signals and recursive-analysis can
misclassify different strategies. Full audit of CORE-18 is unsupported
without its verified code and market data in an approved private environment.

## Rollback
Close PR and delete isolated branch. No `main` or scheduled source job
has to change; source-only workflow was not edited.


## Independent diagnosis of the 30 WARMUP sources (pinned public receipts)
`warmup_receipt_audit.py` reads only already-committed public compressed
source receipts, rejecting duplicate JSON keys, gzip bombs, symlinks,
mismatched row/header accounting, duplicate market IDs, misleading PASS with
WARMUP/FAIL frame flags, and any nonzero order/private-strategy metadata.
It exposes only counts and per-frame/reason aggregates, never symbols.
`tests/test_warmup_receipt_audit.py` reads the immutable 2026-10-31 00:00
and 06:00 UTC 519 receipts during offline CI; emitted log records start
`PUBLIC_519_WARMUP_REASON_READBACK=`. This is an audit of an existing
public artifact, **not** a new provider scan, model outcome, notification,
or WARMUP remediation. The fixed historical receipts are not evidence of
the next scheduled epoch or the revised publisher's live success.

Run locally without any network:
```
python3 warmup_receipt_audit.py --receipt receipts/2026/10/31/20261031T0600Z-n519.json.gz
```


## Measured root cause — two real persisted Binance source receipts
Real, independent GitHub CI Run [41221505649](https://github.com/gokaydonmez39-jpg/xray-519-source-qa/actions/runs/41221505649) read **both persisted public** 2026-10-31 00:00 UTC and 06:00 UTC receipts (no new Binance request).

Each receipt independently contains 519 distinct source rows:
**489 PASS / 30 WARMUP / 0 FAIL**. All 30 WARMUP source rows have a
short **1D closed-candle history**. At 06:00 UTC the exact 1D
short-history distribution is:
`3/40: 5, 10/40: 5, 17/40: 4, 18/40: 1, 24/40: 4,
31/40: 7, 37/40: 1, 38/40: 3`; sum **30**. Exactly five of these
also have short 1H and 4H history: across the 00:00 -> 06:00 UTC
receipts, 1H increases `60/100 -> 66/100` and 4H
`15/40 -> 16/40`. Daily history does not improve over those six
hours because the next UTC day had not closed.

**Disposition:** historical shortfall is real, not an ingestion gap to
repair by inventing missing candles. Retain WARMUP until independently
observed enough fully closed daily history, preserve 519 coverage
distinct from 519 quality, and keep private strategy execution
and real phone delivery separate. Counts are for those two specific
dated observations only; no claim of later auto-maturation.
The public source `source_qa_success=true` means no corrupt
scan/source failure; it does **not** mean full technical 519 PASS.

This PR additionally rejects a receipt that simultaneously reports
any WARMUP and claims `full_technical_quality=true` or
`live_source_acceptance=true` (false-green regression).
