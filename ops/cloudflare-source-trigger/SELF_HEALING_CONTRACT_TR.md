# XRAY-519 SELF-HEALING ENGINE — Production gate, public-only
Status: **STAGED / DRAFT**. This document describes code committed to an isolated feature branch, NOT a deployed or proven continuous service.

## Immutable scope
- Public `gokaydonmez39-jpg/xray-519-source-qa` only. NO NASDAQ repo, Alpaca/Sheets, private P30 execution, orders, notifications, billing upgrade, secret rotation, receipt/bridge overwrites or destructive DO SQLite operations.
- Source-only recovery may start **at most one** GitHub dispatch POST per closed UTC epoch, with the existing primary :01 / backup :06 compare-and-swap and native :04 / :08 independent opportunity.
- GitHub schedule and Cloudflare Cron have no hard timeliness SLA. Accepted POST is never 519 source PASS.
- Preserve existing 90,000ms nominal freshness, no backfill of missed epoch, no third retry, no ambiguous POST retry.

## Layer 1: deterministic automatic diagnosis
`self-heal-policy.mjs::classifyDecision` maps ONLY known allowlisted decision codes and numeric HTTP status to stable `XRAY519_SELF_HEAL_POLICY_V1` output, returned as `selfHeal` by `dispatch-core.mjs` and recorded by existing structured `XRAY_PUBLIC_DISPATCH` Worker log. It contains mode and reason codes, never token, URL, response body or private data.
- `OBSERVE_ONLY`: workflow POST was accepted or a receipt/active run exists; independently verify the immutable receipt/bridge pair. No false PASS.
- `SAFE_BACKUP_CAS_ONCE`: known pre-POST failure eligible for the **already implemented** atomic :06 single-winner backup, unless backup has been used.
- `HOLD_NO_RETRY`: ambiguous/attempted POST, exhausted backup, duplicate lock, stale epoch or other safety gate. Never unlock.
- `REVIEW_REQUIRED`: unknown error, HTTP 401/403/429 or uncertain policy. Diagnose evidence before editing any code.
- Every mode sets `automaticCodeChange=false`, `automaticLockReset=false`.

## Layer 2: bounded automatic recovery
Only if a GitHub read-only GET returns HTTP 502, 503 or 504, `preDispatchGet` may repeat that **same GET** once per Worker invocation. It uses exactly the same endpoint and headers, no time-window expansion. The retry requires at least 7 seconds remaining against the 90-second nominal Cron freshness at the time of the failing GET. It NEVER retries 401/403/429, non-GET operations, a dispatch POST or a backup-completed epoch. An unresolved pre-POST failure may still use the old, single-use backup CAS. New telemetry `safeGetRetryUsed` is included in the audit; a retry never counts as a successful source epoch.

Known limitations: the in-invocation retry consumes one extra GitHub GET but no additional CI runner. In the worst case it may marginally increase API traffic; it is not a guarantee against upstream downtime. If its code produces regressions, revert the feature's merge commit, **not** immutable evidence or SQLite rows.

## Layer 3: isolated repair recommendation, NOT autonomous privileged deployment
The classifier is an input to a human-reviewed incident and DRAFT PR workflow; its output is not a patch executable by itself. Generating arbitrary source code and automatically merging to production on untrusted external errors would bypass the risk contract. New rule sets must first have adversarial negative tests, green public CI, no new external calls, no secrets disclosure and an explicit deployment authorization. This is a security cap, not a missing silent permission. Unknown errors stay fail-closed with structured diagnosis.

## Acceptance tests, fixed before live observations
1. Deterministic positive/negative policy table (HTTP 403/429, 502/503/504, arbitrary unknown codes, backup exhaustion, ambiguous POST).
2. Simulation of a single transient GET recovery to exactly one POST and idempotent no-POST on duplicate.
3. One failed GET retry then HOLD; no 403/429 retry; no retry near 90s deadline; no third attempt; no token in result.
4. Existing full public Cloudflare offline CI must pass (including CAS races, pagination, malformed list, retry and privacy guards).
5. After **explicit merge and build approval**, independently confirm Worker version actually in service and two natural primary/backup Cron opportunities without 403, duplicates, secret leak, or stale dispatch.
6. Only future **48 distinct contiguous** UTC epochs with `source_qa_success=true`, `technical_scanned=519`, `technical_failed=0`, verified immutable matching canonical SHA256, run provenance and zero orders/notifications can pass public acceptance. NOOP not counted. Missing 2026-11-01 11Z may never be backfilled.
7. Private P30 <=15min, 14-day native WSS, 60-day paper/OOS and phone ACK are separate HOLD gates and cannot be approved by this public-only work.

## Rollback and pre-mortem
- API 403 continues: keep HOLD, inspect structured HTTP status and GitHub x-ratelimit headers, do not rotate or widen token without consent.
- 503 persists: one safe GET retry and original backup CAS only; otherwise fail-closed. No infinite-loop retries.
- Duplicate or uncertain dispatch POST: never release lock or retry. Inspect run provenance and previous/duplicate lock states in read-only logs.
- Freshness overruns or wrong UTC epoch: reject, no historical fake evidence.
- Unexpected cost/security regression: stop feature deployment; revert feature commit, preserve main evidence and single DB lock history.
