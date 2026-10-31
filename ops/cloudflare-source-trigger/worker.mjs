import { DurableObject } from 'cloudflare:workers';
import { executeOnce } from './dispatch-core.mjs';

export class SourceDispatchLock extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ctx.storage.sql.exec(`CREATE TABLE IF NOT EXISTS dispatch_epoch (
      epoch TEXT PRIMARY KEY, reserved_at INTEGER NOT NULL, state TEXT NOT NULL
    )`);
  }

  async fetch(request) {
    if (request.method !== 'POST' || new URL(request.url).pathname !== '/trigger') {
      return new Response('Not found', { status: 404 });
    }
    let message;
    try { message = await request.json(); }
    catch { return Response.json({ decision: 'MALFORMED_REQUEST' }, { status: 400 }); }
    const sql = this.ctx.storage.sql;
    // Backup reservations never reset the original SQLite epoch or its
    // reserved_at value. A second chance is allowed ONLY after a recorded
    // pre-dispatch lookup failure, through atomic compare-and-swap.
    let backupInvocation = false;
    const result = await executeOnce({
      scheduledTime: message?.scheduledTime,
      nowMs: Date.now(),
      token: this.env.GITHUB_ACTIONS_DISPATCH_TOKEN,
      reserve: (epoch, nowMs, isBackup) => {
        backupInvocation = isBackup === true;
        // Initial reservation remains immutable for audit. Lazy rowsWritten
        // is NOT an insertion signal; only RETURNING proves a new row.
        const inserted = sql.exec(
          'INSERT INTO dispatch_epoch(epoch,reserved_at,state) VALUES(?,?,?) ' +
          'ON CONFLICT(epoch) DO NOTHING RETURNING epoch',
          epoch, nowMs, backupInvocation ? 'BACKUP_RESERVED_PREPOST' : 'RESERVED',
        ).toArray();
        if (inserted.length === 1 && inserted[0].epoch === epoch) return true;
        if (!backupInvocation) return false;
        // The ONLY retryable original states are known to occur before POST.
        // Ambiguous network, an accepted dispatch, a rejection after POST,
        // RESERVED, and any previous BACKUP_* state are NEVER retried.
        // Atomic UPDATE ... RETURNING is a single-winner compare-and-swap.
        const retry = sql.exec(
          'UPDATE dispatch_epoch SET state=? WHERE epoch=? AND state IN (?,?,?,?) RETURNING epoch',
          'BACKUP_RESERVED_PREPOST', epoch,
          'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE',
          'GITHUB_RUNS_UNAVAILABLE',
          'GITHUB_RUNS_INDETERMINATE',
          'GITHUB_RUN_TIME_INVALID',
        ).toArray();
        return retry.length === 1 && retry[0].epoch === epoch;
      },
      mark: async (epoch, state) => {
        const persisted = backupInvocation ? 'BACKUP_' + state : state;
        sql.exec('UPDATE dispatch_epoch SET state=? WHERE epoch=?', persisted, epoch);
      },
      githubFetch: (url, options) => fetch(url, { ...options, redirect: 'manual', signal: AbortSignal.timeout(6000) }),
    });
    // Read-only SQLite diagnostics: a duplicate lock does not prove that a
    // GitHub dispatch happened. Inspect previous/current reservation state
    // without releasing, retrying, or editing the single-dispatch lock.
    const knownStates = [
      'RESERVED', 'DISPATCH_ACCEPTED_NOT_SOURCE_PASS',
      'EXISTING_SOURCE_RECEIPT', 'EXISTING_SOURCE_RUN',
      'SOURCE_RUN_ALREADY_ACTIVE', 'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE',
      'GITHUB_RUNS_UNAVAILABLE', 'GITHUB_RUNS_INDETERMINATE',
      'GITHUB_RUN_TIME_INVALID', 'DISPATCH_REJECTED',
      'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN', 'POST_RESERVATION_AUDIT_FAILURE',
    ];
    const safeStates = new Set([
      ...knownStates, ...knownStates.map(state => 'BACKUP_' + state),
      'BACKUP_RESERVED_PREPOST',
    ]);
    function readLock(epoch) {
      try {
        const row = sql.exec(
          'SELECT state, reserved_at FROM dispatch_epoch WHERE epoch=? LIMIT 1',
          epoch,
        ).toArray()[0];
        if (!row) return { state: 'ABSENT' };
        return {
          state: safeStates.has(row.state) ? row.state : 'UNKNOWN_STATE',
          reservedAtMs: Number.isSafeInteger(row.reserved_at) ? row.reserved_at : null,
        };
      } catch {
        return { state: 'READBACK_UNAVAILABLE' };
      }
    }
    const fields = {};
    const raw = message?.scheduledTime;
    if (Number.isSafeInteger(raw) && raw >= 3_600_000) {
      const hourMs = Math.floor(raw / 3_600_000) * 3_600_000;
      const prevEpoch = new Date(hourMs - 3_600_000).toISOString().slice(0, 13) + ':00:00Z';
      fields.previousEpoch = prevEpoch;
      fields.previousLock = readLock(prevEpoch);
      if (result.decision === 'DUPLICATE_EPOCH_LOCKED') {
        const currentEpoch = new Date(hourMs).toISOString().slice(0, 13) + ':00:00Z';
        fields.duplicateLock = readLock(currentEpoch);
      }
    }
    // No secrets, private strategy, or market signals in audit output.
    console.log(JSON.stringify({ event: 'XRAY_PUBLIC_DISPATCH', ...result, ...fields }));
    return Response.json(result);
  }
}

export default {
  async scheduled(controller, env, ctx) {
    // Fail closed and expose dispatch failures as Cron errors, never false "ok".
    // noRetry prevents Cloudflare retries after an ambiguous GitHub response.
    if (controller.cron !== '1 * * * *' && controller.cron !== '6 * * * *') {
      controller.noRetry();
      console.error('XRAY_PUBLIC_DISPATCH_WRONG_CRON');
      throw new Error('XRAY_PUBLIC_DISPATCH_WRONG_CRON');
    }
    // Reject a mistaken schedule-to-minute pairing before touching SQLite.
    const expectedMinute = controller.cron === '1 * * * *' ? 1 : 6;
    if (!Number.isSafeInteger(controller.scheduledTime) ||
        new Date(controller.scheduledTime).getUTCMinutes() !== expectedMinute) {
      controller.noRetry();
      console.error('XRAY_PUBLIC_DISPATCH_CRON_MINUTE_MISMATCH');
      throw new Error('XRAY_PUBLIC_DISPATCH_CRON_MINUTE_MISMATCH');
    }
    let response;
    try {
      const stub = env.SOURCE_DISPATCH_LOCK.get(env.SOURCE_DISPATCH_LOCK.idFromName('xray-519-singleton'));
      response = await stub.fetch('https://internal/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scheduledTime: controller.scheduledTime }),
      });
    } catch {
      controller.noRetry();
      console.error('XRAY_PUBLIC_DISPATCH_INTERNAL_EXCEPTION');
      throw new Error('XRAY_PUBLIC_DISPATCH_INTERNAL_EXCEPTION');
    }
    if (response.status !== 200) {
      controller.noRetry();
      console.error('XRAY_PUBLIC_DISPATCH_INTERNAL_HTTP_FAILURE', response.status);
      throw new Error('XRAY_PUBLIC_DISPATCH_INTERNAL_HTTP_FAILURE');
    }
    let result;
    try {
      result = await response.json();
    } catch {
      controller.noRetry();
      console.error('XRAY_PUBLIC_DISPATCH_INVALID_RESPONSE');
      throw new Error('XRAY_PUBLIC_DISPATCH_INVALID_RESPONSE');
    }
    // "Accepted" means accepted for processing, not source data or AL success.
    const accepted = new Set([
      'DISPATCH_ACCEPTED_NOT_SOURCE_PASS', 'EXISTING_SOURCE_RECEIPT',
      'EXISTING_SOURCE_RUN', 'SOURCE_RUN_ALREADY_ACTIVE',
    ]);
    const knownBlocked = new Set([
      'INVALID_SCHEDULE', 'STALE_OR_EARLY_CRON', 'SECRET_NOT_CONFIGURED',
      'BAD_ADAPTER', 'LOCK_STORAGE_FAILURE', 'DUPLICATE_EPOCH_LOCKED',
      'POST_RESERVATION_AUDIT_FAILURE', 'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE',
      'GITHUB_RUNS_UNAVAILABLE', 'GITHUB_RUNS_INDETERMINATE',
      'GITHUB_RUN_TIME_INVALID', 'DISPATCH_REJECTED',
      'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN',
    ]);
    const decision = result && result.decision;
    if (!accepted.has(decision)) {
      controller.noRetry();
      const safeCode = knownBlocked.has(decision) ? decision : 'UNEXPECTED_DECISION';
      console.error('XRAY_PUBLIC_DISPATCH_NOT_ACCEPTED', safeCode);
      throw new Error('XRAY_PUBLIC_DISPATCH_NOT_ACCEPTED:' + safeCode);
    }
    console.log('XRAY_PUBLIC_DISPATCH_CRON_RESULT', decision);
  },
  fetch() { return new Response('Not found', { status: 404 }); },
};
