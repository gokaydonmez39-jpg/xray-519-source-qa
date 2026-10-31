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
