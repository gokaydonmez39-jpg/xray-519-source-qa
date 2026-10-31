// XRAY-519 PUBLIC SOURCE TRIGGER ONLY. No trading, private repo, source strategy or billing changes.
export const CONFIG = Object.freeze({
  repository: 'gokaydonmez39-jpg/xray-519-source-qa',
  workflowId: 402070622,
  workflowFile: 'hourly-519-public-source.yml',
  scope: '519',
  offsetMs: 60_000, // Cloudflare cron: UTC minute 01; prior 1H candle has closed.
  maxDelayMs: 90_000, // Never dispatch a stale source epoch.
  maxFutureMs: 5_000,
  hourMs: 3_600_000,
});
const API = `https://api.github.com/repos/${CONFIG.repository}`;

export function epochOf(scheduledTime, nowMs) {
  if (!Number.isSafeInteger(scheduledTime) || !Number.isSafeInteger(nowMs) ||
      scheduledTime < 0 || scheduledTime % CONFIG.hourMs !== CONFIG.offsetMs) {
    return { ok: false, code: 'INVALID_SCHEDULE' };
  }
  const delay = nowMs - scheduledTime;
  if (delay < -CONFIG.maxFutureMs || delay > CONFIG.maxDelayMs ||
      Math.floor(nowMs / CONFIG.hourMs) !== Math.floor(scheduledTime / CONFIG.hourMs)) {
    return { ok: false, code: 'STALE_OR_EARLY_CRON' };
  }
  const hour = Math.floor(scheduledTime / CONFIG.hourMs) * CONFIG.hourMs;
  const iso = new Date(hour).toISOString();
  return {
    ok: true, epoch: iso.slice(0, 13) + ':00:00Z',
    stamp: iso.slice(0, 4) + iso.slice(5, 7) + iso.slice(8, 10) + 'T' + iso.slice(11, 13) + '00Z',
    dir: iso.slice(0, 4) + '/' + iso.slice(5, 7) + '/' + iso.slice(8, 10),
    startMs: hour,
  };
}

function headers(token) {
  return {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2026-03-10',
    'User-Agent': 'xray519-public-source-cloudflare-trigger/1.0',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function out(decision, stamp, extra = {}) {
  return { decision, stamp, ...extra };
}

// Runtime must provide a Durable Object SQLite-backed INSERT-OR-IGNORE reserve function.
// The lock is taken *before* all GitHub calls, to bound to <=1 attempted dispatch per UTC epoch.
// Failures deliberately remain locked (no automatic retries or ambiguous duplicate runs).
export async function executeOnce({ scheduledTime, nowMs, token, reserve, mark, githubFetch }) {
  const time = epochOf(scheduledTime, nowMs);
  if (!time.ok) return out(time.code, null);
  if (typeof token !== 'string' || token.length < 24) return out('SECRET_NOT_CONFIGURED', time.stamp);
  if (typeof githubFetch !== 'function' || typeof reserve !== 'function' || typeof mark !== 'function') {
    return out('BAD_ADAPTER', time.stamp);
  }
  let locked;
  try { locked = reserve(time.epoch, nowMs); }
  catch { return out('LOCK_STORAGE_FAILURE', time.stamp); }
  if (!locked) return out('DUPLICATE_EPOCH_LOCKED', time.stamp);

  async function state(code, extra = {}) {
    try { await mark(time.epoch, code); }
    catch { return out('POST_RESERVATION_AUDIT_FAILURE', time.stamp, { priorDecision: code }); }
    return out(code, time.stamp, extra);
  }
  const receiptPath = `receipts/${time.dir}/${time.stamp}-n519.json.gz`;
  const receiptUrl = `${API}/contents/${receiptPath}?ref=main`;
  try {
    const receipt = await githubFetch(receiptUrl, { method: 'GET', headers: headers() });
    if (receipt.status === 200) return await state('EXISTING_SOURCE_RECEIPT');
    if (receipt.status !== 404) return await state('SOURCE_RECEIPT_LOOKUP_UNAVAILABLE', { httpStatus: receipt.status });

    // Existence queries scoped to this workflow avoid the repository's first-100
    // history trap. A positive count blocks immediately; proving absence requires
    // a consistent zero count and empty page. Pagination is never needed.
    const activeStatuses = ['queued', 'in_progress', 'waiting', 'requested', 'pending'];
    const queries = [
      { created: '>=' + time.epoch },
      ...activeStatuses.map(status => ({ status })),
    ];
    for (const query of queries) {
      const params = new URLSearchParams({ branch: 'main', per_page: '1', ...query });
      const listUrl = `${API}/actions/workflows/${CONFIG.workflowFile}/runs?${params}`;
      const runs = await githubFetch(listUrl, { method: 'GET', headers: headers() });
      if (runs.status !== 200) return await state('GITHUB_RUNS_UNAVAILABLE', { httpStatus: runs.status });
      const data = await runs.json();
      if (!data || !Number.isSafeInteger(data.total_count) || data.total_count < 0 ||
          !Array.isArray(data.workflow_runs) ||
          data.workflow_runs.length !== Math.min(data.total_count, 1)) {
        return await state('GITHUB_RUNS_INDETERMINATE');
      }
      if (data.total_count === 0) continue;
      const run = data.workflow_runs[0];
      if (!run || !Number.isSafeInteger(run.id) || run.id <= 0 ||
          run.workflow_id !== CONFIG.workflowId || run.head_branch !== 'main') {
        return await state('GITHUB_RUNS_INDETERMINATE');
      }
      const created = typeof run.created_at === 'string' ? Date.parse(run.created_at) : NaN;
      if (!Number.isFinite(created)) return await state('GITHUB_RUN_TIME_INVALID');
      if (created > nowMs + 30_000 ||
          (query.created && created < time.startMs) ||
          (query.status && run.status !== query.status)) {
        return await state('GITHUB_RUNS_INDETERMINATE');
      }
      return await state(query.created ? 'EXISTING_SOURCE_RUN' : 'SOURCE_RUN_ALREADY_ACTIVE', { runId: run.id });
    }
    const dispatchUrl = `${API}/actions/workflows/${CONFIG.workflowFile}/dispatches`;
    const response = await githubFetch(dispatchUrl, {
      method: 'POST',
      headers: { ...headers(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main', inputs: { max_markets: CONFIG.scope } }),
    });
    // GitHub's Actions API may use 200 with run id (current version) or 204 empty response.
    if (response.status !== 200 && response.status !== 204) {
      return await state('DISPATCH_REJECTED', { httpStatus: response.status });
    }
    let runId = null;
    if (response.status === 200) {
      const payload = await response.json();
      if (Number.isSafeInteger(payload?.workflow_run_id)) runId = payload.workflow_run_id;
    }
    return await state('DISPATCH_ACCEPTED_NOT_SOURCE_PASS', { runId, sourceEpoch: time.epoch });
  } catch {
    return await state('GITHUB_NETWORK_OR_RESPONSE_UNKNOWN');
  }
}
