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
    const stub = env.SOURCE_DISPATCH_LOCK.get(env.SOURCE_DISPATCH_LOCK.idFromName('xray-519-singleton'));
    const response = await stub.fetch('https://internal/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scheduledTime: controller.scheduledTime }),
    });
    if (response.status !== 200) console.error('XRAY_PUBLIC_DISPATCH_INTERNAL_FAILURE', response.status);
  },
  fetch() { return new Response('Not found', { status: 404 }); },
};
