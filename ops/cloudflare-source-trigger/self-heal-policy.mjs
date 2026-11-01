// Deterministic XRAY-519 public-source recovery policy, no side effects.
// The Cloudflare Worker may log this allowlisted classification. It never
// grants trading, private runner, lock deletion or autonomous code deployment.
const PRE_POST_RETRYABLE = new Set([
  'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE', 'GITHUB_RUNS_UNAVAILABLE',
  'GITHUB_RUNS_INDETERMINATE', 'GITHUB_RUN_TIME_INVALID',
  'GITHUB_PRE_DISPATCH_NETWORK_ERROR',
]);
const AWAIT_EVIDENCE = new Set([
  'DISPATCH_ACCEPTED_NOT_SOURCE_PASS', 'EXISTING_SOURCE_RECEIPT',
  'EXISTING_SOURCE_RUN', 'SOURCE_RUN_ALREADY_ACTIVE',
]);
const NEVER_RETRY = new Set([
  'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN', 'DISPATCH_REJECTED',
  'POST_RESERVATION_AUDIT_FAILURE',
]);
const HARD_HOLD = new Set([
  'INVALID_SCHEDULE', 'STALE_OR_EARLY_CRON', 'SECRET_NOT_CONFIGURED',
  'BAD_ADAPTER', 'LOCK_STORAGE_FAILURE', 'DUPLICATE_EPOCH_LOCKED',
]);

// Use fixed codes rather than untrusted server response bodies. Never log
// tokens, arbitrary exception strings, URLs or GitHub response payloads.
export function classifyDecision({ decision, httpStatus = null } = {}) {
  const result = { schema: 'XRAY519_SELF_HEAL_POLICY_V1',
    mode: 'REVIEW_REQUIRED', reason: 'UNKNOWN_DECISION',
    automaticCodeChange: false, automaticLockReset: false };
  if (typeof decision !== 'string') return result;
  if (AWAIT_EVIDENCE.has(decision)) {
    return {...result, mode:'OBSERVE_ONLY', reason:'VERIFY_REAL_SOURCE_RECEIPT_AND_BRIDGE'};
  }
  if (NEVER_RETRY.has(decision)) {
    return {...result, mode:'HOLD_NO_RETRY', reason:'POST_OR_AUDIT_UNCERTAINTY'};
  }
  if (HARD_HOLD.has(decision)) {
    return {...result, mode:'HOLD_NO_RETRY', reason:'SAFETY_GATE'};
  }
  if (PRE_POST_RETRYABLE.has(decision)) {
    if (httpStatus === 401 || httpStatus === 403) {
      return {...result, mode:'REVIEW_REQUIRED', reason:'GITHUB_AUTH_OR_RATE_RESTRICTION'};
    }
    if (httpStatus === 429) {
      return {...result, mode:'REVIEW_REQUIRED', reason:'GITHUB_RATE_LIMIT'};
    }
    // The only automatic recovery is the existing, single-winner :06
    // pre-POST CAS; never unlock, backfill, retry a POST or add a 3rd try.
    return {...result, mode:'SAFE_BACKUP_CAS_ONCE', reason:'KNOWN_PRE_POST_FAILURE'};
  }
  return result;
}

export const TRANSIENT_READ_ONLY_HTTP = Object.freeze([502, 503, 504]);

// At most one extra GET per UTC epoch, only when there is enough of the
// already enforced nominal 90s Cron freshness budget for one extra 6s GET.
// No 403/429 retry, no POST retry, no time-window relaxation.
export function mayRetryReadOnlyGet({status, used = false, nominalAgeMs} = {}) {
  return !used && TRANSIENT_READ_ONLY_HTTP.includes(status) &&
    Number.isFinite(nominalAgeMs) &&
    nominalAgeMs >= 0 && nominalAgeMs <= 83_000;
}
