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
    const result = await executeOnce({
      scheduledTime: message?.scheduledTime,
      nowMs: Date.now(),
      token: this.env.GITHUB_ACTIONS_DISPATCH_TOKEN,
      reserve: (epoch, nowMs) => sql.exec(
        'INSERT OR IGNORE INTO dispatch_epoch(epoch,reserved_at,state) VALUES(?,?,?)',
        epoch, nowMs, 'RESERVED',
      ).rowsWritten === 1,
      mark: async (epoch, state) => { sql.exec('UPDATE dispatch_epoch SET state=? WHERE epoch=?', state, epoch); },
      githubFetch: (url, options) => fetch(url, { ...options, redirect: 'error', signal: AbortSignal.timeout(6000) }),
    });
    // No secrets or market signals in audit output.
    console.log(JSON.stringify({ event: 'XRAY_PUBLIC_DISPATCH', ...result }));
    return Response.json(result);
  }
}

export default {
  async scheduled(controller, env, ctx) {
    // Fail closed and expose dispatch failures as Cron errors, never false "ok".
    // noRetry prevents Cloudflare retries after an ambiguous GitHub response.
    if (controller.cron !== '1 * * * *') {
      controller.noRetry();
      console.error('XRAY_PUBLIC_DISPATCH_WRONG_CRON');
      throw new Error('XRAY_PUBLIC_DISPATCH_WRONG_CRON');
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
