# XRAY CRYPTO GODZILLA Ω — External Research Gate V1
## Implementation and evidence, 1 November 2026

**Scope:** only public `gokaydonmez39-jpg/xray-519-source-qa`. This is a strictly **read-only, offline**, no-network research method library. It is not the Qlib engine, Kronos model or Freqtrade execution system. The private P30/CORE-18, NASDAQ, live source scanner, Cloudflare cron, stop/target strategy, trading permission, alerts and WSS runtime are unchanged.

### Seven external sources (technical review; not software installs)

| Upstream | License | Evidence to reuse | Decision |
|---|---|---|---|
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | GPL-3.0 | lookahead and recursive indicator testing methodology | **Already implemented**, preserve `freqtrade_causality_shadow.py`; add standalone prefix invariance gate |
| [microsoft/qlib](https://github.com/microsoft/qlib) | MIT | time-series train/validation/test, training-only normalization, out-of-sample research | **Method-only integration** in `research_lab/pit_audit.py` |
| [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) | MIT code, model-weight license to be separately verified | candidate forecasting experiment and naïve-baseline benchmark | **Method-only interface**; no model download/GPU |
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | Apache-2.0 | bull/bear/risk critical discussion | concept only; LLM drift, cost and data-time risk |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | MIT | paper ledger/benchmark discipline | concept only, no external API provider |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | repository README says MIT but no top-level LICENSE / no GitHub license metadata observed | agent paper trading | **HOLD**: license and authority not established |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | Apache-2.0 | read-only order-book microstructure and spread ideas | **HOLD**: exchange execution bot architecture conflicts with source-only scope |

External projects were read to understand techniques. **No upstream code, model weights, dependencies, account secrets or execution permissions are copied/installed.** Original source licenses apply to any future direct code integration. The GitHub star count is not an alpha-quality metric.

### Supported actual gates

1. **Point-in-time:** per-symbol sorted closed 1H decisions; strict last closed candle, feature availability and forecast timestamp not after decision, model training time before decision, label not used before actual availability.
2. **Data quality:** reject NaN/Infinity, duplicate symbol/decision, bad OHLC reference prices, misaligned hours and absent labels. A missing/WARMUP candle is not imputed.
3. **Purged walk-forward:** whole UTC epochs, no random cross-sectional train/test leakage. Any training/validation sample whose label plus at least one hour embargo overlaps the next split boundary is **dropped**. Entire train/validation/test partitions are required.
4. **Training-only features:** normalizer learns only from training rows. Unknown future regime never enters fit.
5. **Causality:** a prefix calculation must equal the corresponding indicator output from the longer series. This is a diagnostic for obvious repaint and does not prove absence of all strategy lookahead.
6. **Benchmark:** compare candidate forecasts only to the last-closed-price naïve baseline, use absolute error and distinct UTC epochs; require default minimum **200 observations and 100 distinct epochs** for a *sample-size eligibility check*, not statistical significance or production acceptance. `score_shadow_forecasts()` **always returns `promotion_allowed=false`, `model_verified=false` and `oos_verified=false`**, even on apparently favorable synthetic data.
7. **Source provenance:** tests pin the real public immutable 2026-10-31 21:00Z gzip receipt by SHA256, explicitly verify 519 scanned = 489 PASS + 30 WARMUP + 0 FAIL, and no private AL or orders. Real production receipt is not a verified ML training dataset.

### External validation prerequisites NOT met yet

- No sufficiently long timestamp-accurate 519 historical research archive with documented delistings, symbol churn, and Binance spot eligibility point-in-time.
- No Kronos model artifact SHA, weight license, inferencing environment, CPU/GPU cost or actual model forecasts. Therefore **no Kronos prediction is claimed**.
- No external Qlib runtime installed, long-history model training, or real walk-forward out-of-sample returns. Therefore **no Qlib model outcome is claimed**.
- No true independent trade outcomes, bid/ask, spread/slippage, liquidation/gap or tail-loss distribution across regimes. No profitability or hit-rate claim.
- Private P30 live runner cost/zero-fee and native WSS/iPhone alert acknowledgement are still independent HOLD gates.

### Acceptance thresholds fixed before results

| Gate | Predeclared threshold | Observed |
|---|---|---|
| Public read-only safety | no new network, order, API key, private job or Cloudflare Worker edits | changes limited to `research_lab/` and tests |
| Unit causality, PIT and boundary checks | all normal and optimized CI tests PASS, including deliberate negatives | verify GitHub PR CI before merge |
| Known frozen public receipt | exact source gzip SHA and 519/489/30/0 accounting | verify GitHub PR CI before merge |
| Offline shadow eligibility | 200 examples and 100 distinct epochs **minimum**, train-only fit, purged walk-forward | no live model evidence — HOLD |
| Model advantage | walk-forward OOS beats naive/buy-and-hold after fees and realistic spread/slippage, robust across market regimes and trials | unknown — HOLD |
| Private signal admission | secure cost/provenance/closed bar + paper-trade + WSS + delivery ACK gates | unknown — HOLD |
| 48h operational reliability | **48 consecutive UTC epochs** independently evidenced; no NOOP counted twice | historic gap exists — not yet met |

### Sixteen independent audit lenses

| Lens | Concrete validation |
|---|---|
| Einstein | Decompose sources, predictions and execution; do not assume popularity = edge |
| Euler | Hour-indexed folds, reproducible source and model SHA256, 0 extra runtime dependencies |
| Gauss | Distinct epochs, non-finite rejection; full confidence intervals/power still pending |
| Newton | Falsifiable timestamp and benchmark rules with real CI outcomes |
| Leibniz | Exact invariants: no future features, no model promotion, no orders |
| Turing | Deterministic normal/`-O`, positive and hostile input cases |
| Shannon | Compare signal with naïve baseline, prevent copying market noise |
| Bayes | Prior belief about efficacy stays unchanged until genuine OOS evidence |
| Popper | Negative tests for open candles, future labels, duplicates, forward-trained models |
| Feynman | Separate source QA, private signal, UI and broker into distinct layers |
| Lamport | UTC epoch grouping and simultaneous symbol leakage guard; public dispatch lock remains separate |
| Deming | Before/after CI counts, immutable artifacts, operational failure must not be relabeled PASS |
| Kahneman | No promoting synthetic examples or best-performing cherry-picked model |
| Thorp | Stop/target and risk-budget validation must happen on private approved side; none here |
| Simons | Walk-forward and falsification before signal research |
| Taleb | WARMUP, gaps, liquidity shocks and tails not covered by a naïve mean-error score |

### Rollback and noninterference

If the research gate test fails, abandon the unmerged branch; if a future merged research-only implementation regresses, revert research-only files and tests. There is no reason to touch receipts, source-run schedule, Durable Object lock, NASDAQ, private branch or WSS. Never present successful source QA or a synthetic model benchmark as **FULL GODZILLA FINAL START**.
