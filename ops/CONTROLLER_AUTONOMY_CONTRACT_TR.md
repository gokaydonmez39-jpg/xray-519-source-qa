# XRAY CRYPTO GODZILLA Ω — Evidence-Gated Autonomous Controller V1
**Status:** DRAFT research-safety infrastructure. This PR does not create new workflow dispatches, invoke Binance, read private P30, alter Cloudflare worker/SQLite, send orders, enable notifications, or change NASDAQ.

## Problem, objective, nonnegotiable baseline
Hourly source runs, backup Cron, selfHeal classification and immutable artifact publication are components, **not** a proven end-to-end closed-loop controller. In particular:
- 2026-11-01 13:10Z native `schedule` run `41309984339` was `success` **but NOOP**, because a valid 13:00Z 519 pair already existed. Workflow success must not be counted as a second source PASS.
- The 2026-11-01 11:00Z source hole cannot be repaired later.
- Historical `main` before this PR was `7c7ebb4921d0528434eb6c12414134fa07b52631`, PR #27 merged and Cloudflare build succeeded, but live `selfHeal` proof requires a Worker log.
- Existing salt-okunur otomasyonun kuralı kullanıcı isteği kapsamında `COUNT=52` yerine `COUNT=100` olarak uzatıldı; `is_enabled=true` doğrulandı. `next_run_time` alanı hâlâ `null` döndüğünden yeni çalışmanın zamanında gerçekleştiği söylenemez. Süre dolması FINAL kabul değildir.

## A. Pure offline source gate
`ops/autonomy_acceptance.py::evaluate_public_window(records, end_stamp=...)`
- Anchors to **exactly 48 UTC hourly epochs ending at explicit `end_stamp`**. No after-the-fact threshold or convenient older window.
- Only unique `kind=SOURCE` rows count, with unique GitHub run ID matching receipt runner identity, matching event and independently checked trigger provenance.
- `kind=NOOP` counts ZERO. Two distinct source-claims for one epoch, missing hours, fake provenance, reused run ID, unsuccessful source, inconsistent 519 accounting, technical FAIL, missing/uncorroborated receipt+bridge SHA256, unauthorized private execution, orders and notifications all fail.
- A passed synthetic/externally supplied ledger is labeled **`SOURCE_ONLY_OFFLINE_ELIGIBILITY_NOT_LIVE_ACCEPTANCE`**. The function explicitly always returns `live_evidence_independently_collected=false` and `full_final_start=false`. The caller's boolean claims/strings are *not* cryptographic verification.
- Bu saf kabul fonksiyonu ağ/kimlik bilgisi kullanmaz. Aynı PR içindeki yeni `ops/evidence_collector.py`, public main checkout gerçek gzip bytes+canonical SHA ve salt-okunur GitHub workflow-run API metadata doğrulaması yapar; `.github/workflows/xray-519-readonly-evidence-controller.yml` kaynak çalışma tamamlanınca veya :17 UTC'de denetim tetiklemek üzere STAGED'dir. **Cloudflare Worker canlı logu/sürüm orijini doğrulama ve üretim deploy hâlâ eksiktir**; GitHub `workflow_dispatch` olayı Cloudflare kanıtı yerine geçmez.

## B. Evidence-gated candidate promotion
`evaluate_candidate(candidate)` only returns `RESEARCH_SHADOW_ELIGIBLE` or `HOLD_RESEARCH`, NEVER code merge, source-runtime install, model verified, real alpha or trading permission.
- Research-method candidates: license, offline/PIT negative tests, data origin, zero incremental cost, no execution permission, security review, rollback.
- Signal-model candidates: all the above plus purged walk-forward, non-survivorship, spread/slippage/liquidity costs, multi-regime robustness, distinct OOS baseline, paper shadow; at least 200 observations and 100 distinct epochs **for eligibility**, not a claim of statistical significance.
- Historic PR #22 (external source shadow/AGIPro) and #23 (adversarial risk) remain DRAFT; they are not automatically installed or promoted.

## C. Scientific, adversarial and operational design lenses
- **Einstein/Feynman:** separate source QA, signal, execution, notification; describe causal mechanism instead of a magic 'AI' label.
- **Euler/Gauss/Leibniz:** deterministic UTC invariants, distributions, finite data and formally fixed thresholds.
- **Newton/Popper/Turing:** falsifiable causal assumptions, red/green negative tests and code-path proofs.
- **Shannon/Bayes/Kahneman:** marginal information vs baseline, calibrated priors, selective-source and backtest selection biases.
- **Lamport/Deming:** immutable event identities, distributed lock/clock provenance, incident→repair→verified loop.
- **Thorp/Simons/Taleb:** capital loss before return, realistic friction, purged OOS and black-swan/survivorship stress.

## P0–P3 actual remaining end-to-end gaps
P0 — **Trusted evidence ingestion + 48h acceptance**: GitHub raw pair, independent receipt canonical SHA ve source-run provenance okuyan kontrolcü STAGED; Cloudflare invocation/version doğrulaması eksik. 48 gerçek devamlı saat olmadan PASS yok.
P0 — **Real post-deploy selfHeal**: verify natural :01/:06 decision and whether 403 fixed under live authenticated GitHub GET; NOT proven from Worker build.
P1 — **Recovery controller orchestration**: observed decision→approved safety policy→single allowed recovery→proof→closed incident; no uncertain POST retries or SQL deletion.
P1 — **Automated candidate lifecycle**: discover→license/security review→reproducible independent PIT/OOS tests→research shadow→paper benchmark→human-approved source promotion. Offline decision gate here is a first component, not a working bot or installation.
P1 — **Private P30**: historical `SOURCE_FILE_UNSAFE` remains without new, cost-approved, live private PASS.
P2 — **14-day native WSS / device delivery ACK**, 60-day paper/OOS, market regimes and executable signal risk controls: independent acceptance and cost protection.
P2 — **Trusted patch bot** requires isolated GitHub App identity, least privilege, branch protection, adversarial PR tests, no automatic production merge and approval; absent here.
P3 — 48 saat ChatGPT monitörü `COUNT=100` biçiminde uzatıldı (sonraki run zamanı belirsiz); public Github native read-only evidence job henüz üretimde değil; rollback, maliyet ve cihaz teslim raporu ayrı.

## Hard safety constraints and pre-mortem
False PASS (green NOOP counted twice): fail if duplicated epoch or NOOP; only independent immutable artifacts count.
Fake provenance or forged input: fail runtime admission; offline synthetic pass never LIVE FINAL; require trusted collector.
Coverage gap: anchor 48 UTC hours at explicit end; old 11Z gap cannot disappear.
Lookahead/oos overfit: PIT and purged walk-forward, per-regime baseline and slippage after fees; no real model claim.
Run collision/delay: do not change Cron, DO reserve or 90s gate; private <=15 minute freshness independent.
Quota/license/security: zero incremental cost evidence, no upstream package blindly installed, no private runner.
Production regression: abandon DRAFT branch or revert only this patch; preserve locks, receipts, NASDAQ and original workflow.

## Test proof and release gate
Regression suite `python3 -m unittest discover -s tests -q` and `python3 -O -m unittest discover -s tests -q` through existing public PR CI. Real data is not generated by unit tests. Any CI success remains DRAFT; merge/deploy needs explicit approval.
