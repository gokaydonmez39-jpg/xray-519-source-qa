# Hummingbot v2.17.0 methods — XRAY crypto public-source research-only integration

## Decision and scope
Integrates only **read-only methodology** from [Hummingbot v2.17.0](https://github.com/hummingbot/hummingbot/tree/v2.17.0), whose source is Apache-2.0 licensed. Our implementation is independent; no Hummingbot runtime, order executor, authenticated connector, paid service, or copied Hummingbot source is included.

Source-only, once per **existing** hourly public Binance 519/518 dynamic scope run:
- Reuses the immutable and SHA-bound `FULL_QUALITY_READY_V2` public bridge already produced by `research_519.py`.
- Validates every ready symbol's 100 x 1H, 70 x 4H, 60 x 1D *fully closed* sequential bars, quality and timestamp, and dynamic identity accounting.
- Aggregates 20 previously **closed** hourly bars using Binance's public `taker_quote` and `quote_volume`: `sum(2 * taker_buy_quote - total_quote)`. This is a **bar-based taker flow estimate** / cumulative quoted delta, NOT trade-level tick reconstruction, predictive evidence or an Hummingbot backtest.
- Classifies diagnostic *per-symbol 20h ratio* into buy (>2%), sell (<-2%), nearly balanced; zero quote becomes UNKNOWN, never a buy/sell. **The 2% is a descriptive, unvalidated cutoff, NOT an AL threshold**.
- Prints an aggregate-only SHA-bound JSON result to the **existing** workflow log (no per-symbol raw bars or strategy information). Source receipt SHA, scope digest, and compressed bridge SHA are present.
- Executes with **zero new API calls**, zero database writes, zero new hourly cron/job, no private-source modifications, zero new dependencies, and `NO_ORDER` / `NO_PUSH` / `FULL_FINAL_START=HOLD`.

## Falsification/acceptance (defined prior to release)
- Offline unit tests: success for positive, negative, neutral, zero-quote, dynamic 401-564 identity, gzip/SHA provenance; fail for duplicate/out-of-order/future/incomplete candles, NaN, taker exceeding total, scope mismatch and order authorization; run both Python normal and `-O`.
- Source CI must pass using the existing workflows. The additional diagnostics invoke is **non-veto** to avoid breaking the existing verified source pipeline; any failure prints `HUMMINGBOT_PUBLIC_FLOW_SHADOW_HOLD_NONVETO` and must not be reported as PASS.
- First subsequent **real** source job with the new code must visibly emit a parsed result bound to that exact saved source SHA, and its old bridge/receipt/readback and independent private source gates must remain unchanged. **Until that run the integration is source-wired but live output acceptance remains UNKNOWN**.
- Candidate / expected benefit: UNKNOWN until separately preregistered walk-forward OOS and fee/slippage comparisons. It does not upgrade original canonical AL criteria.

## Not integrated (intentional NO-GO)
Full Hummingbot engine / Docker / executors / credentials / trade functions, Binance depth WebSocket snapshot+diff live feed, 518 concurrent always-on WSS, persistent 14-day WSS and 60-day OOS, and any order/alert permission. There is no actual depth-event sequence in the public bridge; order book snapshot+diff validation cannot be claimed without a separately justified (cost-free) feed and independent 14-day continuity proof. Existing bookTicker best bid/ask spread is not a full order book.

## Rollback
Revert the source-only PR (new module, tests, this document and one invocation in existing hourly workflow). There is no historical source-data rewrite, private database write, changed automation, new host, or execution change to undo.
