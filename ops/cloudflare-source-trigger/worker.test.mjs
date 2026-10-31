import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const cfg=JSON.parse(fs.readFileSync(new URL('./wrangler.jsonc',import.meta.url),'utf8'));
test('UTC :01 cron and SQLite lock on Free-compatible configuration',()=>{
  assert.deepEqual(cfg.triggers.crons,['1 * * * *','6 * * * *']);
  // Cloudflare live Observability (2026-10-31) identifies this exact script.
  // A mismatch can deploy a second Worker rather than repair the existing one.
  assert.equal(cfg.name, 'xray-519-source-qa');
  assert.equal(cfg.durable_objects.bindings[0].class_name,'SourceDispatchLock');
  assert.equal(cfg.exports.SourceDispatchLock.storage,'sqlite');
  assert.equal(cfg.workers_dev,false);
  assert.ok(!JSON.stringify(cfg).includes('TOKEN'));
});
test('Worker has no HTTP public dispatch route, private strategy or order path',()=>{
  const src=fs.readFileSync(new URL('./worker.mjs',import.meta.url),'utf8');
  assert.match(src,/fetch\(\) \{ return new Response\('Not found', \{ status: 404 \}\)/);
  assert.match(src,/ON CONFLICT\(epoch\) DO NOTHING RETURNING epoch/);
  assert.match(src,/redirect: 'manual'/);
  assert.doesNotMatch(src,/redirect: '(?:error|follow)'/);
  assert.doesNotMatch(src,/api\/v3\/order|xray-crypto-godzilla-omega/);
});


import vm from 'node:vm';

// Exercise the real scheduled() implementation with the Cloudflare-only import
// replaced by a stub. No external requests, live secrets or scheduled events.
function cronHarness({ decision = 'INVALID_SCHEDULE', status = 200, reject = false, malformed = false, cron = '1 * * * *' } = {}) {
  let invoked = 0, noRetry = 0;
  const logs = [], errors = [];
  const source = fs.readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8')
    .replace("import { DurableObject } from 'cloudflare:workers';", 'class DurableObject {}')
    .replace("import { executeOnce } from './dispatch-core.mjs';", 'const executeOnce = async () => {};')
    .replace('export class SourceDispatchLock', 'class SourceDispatchLock')
    .replace('export default {', 'const workerEntry = {');
  const context = {
    Response,
    console: { log: (...v) => logs.push(v), error: (...v) => errors.push(v) },
  };
  vm.runInNewContext(source + '\n' + 'globalThis.cronWorker = workerEntry;', context);
  const controller = {
    cron,
    scheduledTime: Date.parse('2026-10-31T13:01:45.563Z'),
    noRetry: () => { noRetry += 1; },
  };
  const env = {
    SOURCE_DISPATCH_LOCK: {
      idFromName: () => 'xray-519-singleton',
      get: () => ({
        fetch: async () => {
          invoked += 1;
          if (reject) throw new Error('fake network failure');
          if (malformed) return {status, json: async () => {throw new Error('bad json')}};
          return {status, json: async () => ({decision})};
        },
      }),
    },
  };
  return {
    run: () => context.cronWorker.scheduled(controller, env, {}),
    snapshot: () => ({invoked, noRetry, logs, errors}),
  };
}

for (const decision of ['DISPATCH_ACCEPTED_NOT_SOURCE_PASS', 'EXISTING_SOURCE_RECEIPT', 'EXISTING_SOURCE_RUN', 'SOURCE_RUN_ALREADY_ACTIVE']) {
  test('Cron accepted decision ' + decision + ' stays ok without retry or AL claim', async () => {
    const h = cronHarness({decision});
    await h.run();
    const s = h.snapshot();
    assert.equal(s.invoked, 1);
    assert.equal(s.noRetry, 0);
    assert.equal(s.errors.length, 0);
    assert.ok(s.logs.some(v => v.includes('XRAY_PUBLIC_DISPATCH_CRON_RESULT')));
  });
}

for (const decision of ['INVALID_SCHEDULE', 'SECRET_NOT_CONFIGURED', 'GITHUB_RUNS_UNAVAILABLE', 'DISPATCH_REJECTED', 'DUPLICATE_EPOCH_LOCKED', 'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN']) {
  test('Cron blocked decision ' + decision + ' fails without Cloudflare retry', async () => {
    const h = cronHarness({decision});
    await assert.rejects(h.run(), new RegExp('XRAY_PUBLIC_DISPATCH_NOT_ACCEPTED:' + decision));
    const s = h.snapshot();
    assert.equal(s.invoked, 1);
    assert.equal(s.noRetry, 1);
    assert.ok(s.errors.some(v => v.includes('XRAY_PUBLIC_DISPATCH_NOT_ACCEPTED')));
  });
}

test('unknown dispatch decision never logs attacker-controlled content', async () => {
  const h = cronHarness({decision: 'LEAK_FAKE_SECRET_ABC'});
  await assert.rejects(h.run(), /UNEXPECTED_DECISION/);
  assert.equal(h.snapshot().noRetry, 1);
  assert.ok(!JSON.stringify(h.snapshot()).includes('LEAK_FAKE_SECRET_ABC'));
});

test('HTTP 500, invalid JSON and internal exception fail closed without retries', async () => {
  for (const opts of [{status:500}, {malformed:true}, {reject:true}]) {
    const h = cronHarness(opts);
    await assert.rejects(h.run(), /XRAY_PUBLIC_DISPATCH_/);
    assert.equal(h.snapshot().noRetry, 1);
  }
});

test('wrong Cron expression is refused before any Durable Object invocation', async () => {
  const h = cronHarness({cron:'0 * * * *'});
  await assert.rejects(h.run(), /XRAY_PUBLIC_DISPATCH_WRONG_CRON/);
  assert.equal(h.snapshot().invoked, 0);
  assert.equal(h.snapshot().noRetry, 1);
});


function auditHarness({ decision = 'DUPLICATE_EPOCH_LOCKED', rows = {}, throwRead = false } = {}) {
  const logs = [], sqlCalls = [];
  const src = fs.readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8')
    .replace("import { DurableObject } from 'cloudflare:workers';",
      'class DurableObject { constructor(ctx, env) { this.ctx = ctx; this.env = env; } }')
    .replace("import { executeOnce } from './dispatch-core.mjs';",
      'const executeOnce = async () => ({decision: "' + decision + '", stamp: "20261031T1400Z"});')
    .replace('export class SourceDispatchLock', 'class SourceDispatchLock')
    .replace('export default {', 'const workerEntry = {');
  const ctx = {
    Response, Request, URL,
    console: { log: s => logs.push(JSON.parse(s)), error: () => {} },
  };
  vm.runInNewContext(src + '\n' + 'globalThis.lockObject = SourceDispatchLock;', ctx);
  const storage = {
    sql: {exec: (query, ...args) => {
      sqlCalls.push({ query, args });
      if (query.startsWith('CREATE TABLE')) return { rowsWritten: 0 };
      if (!query.startsWith('SELECT state, reserved_at FROM dispatch_epoch')) {
        throw Error('Unexpected SQL in read-only audit test');
      }
      if (throwRead) throw Error('SQLite unavailable');
      return { toArray: () => rows[args[0]] ? [rows[args[0]]] : [] };
    }},
  };
  const d = new ctx.lockObject({storage}, { GITHUB_ACTIONS_DISPATCH_TOKEN: 'TEST_NOT_REAL_SECRET_1234567890' });
  const request = new Request('https://internal/trigger', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({scheduledTime:Date.parse('2026-10-31T14:01:46.844Z')}),
  });
  return {run:() => d.fetch(request), logs, sqlCalls};
}

test('duplicate audit identifies prior and current reservation without mutation or retry', async () => {
  const h = auditHarness({rows:{
    '2026-10-31T13:00:00Z': {state:'DISPATCH_REJECTED',reserved_at:Date.parse('2026-10-31T13:01:46Z')},
    '2026-10-31T14:00:00Z': {state:'RESERVED',reserved_at:Date.parse('2026-10-31T14:01:45Z')},
  }});
  const response=await h.run();
  assert.equal(response.status,200);
  assert.equal((await response.json()).decision,'DUPLICATE_EPOCH_LOCKED');
  assert.equal(h.logs[0].previousEpoch,'2026-10-31T13:00:00Z');
  assert.equal(h.logs[0].previousLock.state,'DISPATCH_REJECTED');
  assert.equal(h.logs[0].duplicateLock.state,'RESERVED');
  assert.equal(h.sqlCalls.filter(c => c.query.startsWith('SELECT')).length,2);
  assert.equal(h.sqlCalls.filter(c => /UPDATE|DELETE|INSERT/.test(c.query)).length,0);
  assert.ok(!JSON.stringify(h.logs).includes('TEST_NOT_REAL_SECRET'));
});

test('unknown state is sanitized rather than echoed to Cloudflare log', async () => {
  const h = auditHarness({rows:{
    '2026-10-31T14:00:00Z': {state:'FAKE_PRIVATE_SECRET_DO_NOT_LOG',reserved_at:Date.parse('2026-10-31T14:01:45Z')},
  }});
  await h.run();
  assert.equal(h.logs[0].duplicateLock.state,'UNKNOWN_STATE');
  assert.ok(!JSON.stringify(h.logs).includes('FAKE_PRIVATE_SECRET'));
  assert.equal(h.logs[0].previousLock.state,'ABSENT');
});

test('unavailable diagnostic SELECT never bypasses or releases source epoch lock', async () => {
  const h=auditHarness({throwRead:true});
  const response=await h.run();
  assert.equal((await response.json()).decision,'DUPLICATE_EPOCH_LOCKED');
  assert.equal(h.logs[0].previousLock.state,'READBACK_UNAVAILABLE');
  assert.equal(h.logs[0].duplicateLock.state,'READBACK_UNAVAILABLE');
  assert.equal(h.sqlCalls.filter(c => /UPDATE|DELETE|INSERT/.test(c.query)).length,0);
});

test('nonduplicate logs previous epoch only without exposing current lock', async () => {
  const h=auditHarness({decision:'DISPATCH_ACCEPTED_NOT_SOURCE_PASS',rows:{
    '2026-10-31T13:00:00Z': {state:'EXISTING_SOURCE_RUN',reserved_at:Date.parse('2026-10-31T13:01:45Z')},
  }});
  const response=await h.run();
  assert.equal((await response.json()).decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(h.logs[0].previousLock.state,'EXISTING_SOURCE_RUN');
  assert.equal(h.logs[0].duplicateLock,undefined);
  assert.equal(h.sqlCalls.filter(c => c.query.startsWith('SELECT')).length,1);
});


for (const reportedRowsWritten of [0, 2]) {
test('real Worker reserve: first RETURNING accepted with rowsWritten=' + reportedRowsWritten + ', duplicate blocked', async () => {
  // Regression for 2026-10-31 15:01:46.902 UTC: the original adapter persisted
  // RESERVED but reported DUPLICATE_EPOCH_LOCKED in the same invocation.
  // This SQL fake intentionally exposes a pre-consumption rowsWritten=0, like
  // a lazy cursor. The only trustworthy result is the RETURNING row itself.
  const { executeOnce } = await import('./dispatch-core.mjs');
  const records = new Map(), requests = [], writes = [], logs = [];
  const previous = '2026-10-31T14:00:00Z';
  records.set(previous, {epoch: previous, reserved_at: 1793455306844, state: 'RESERVED'});
  const db = {
    exec(query, ...args) {
      if (query.startsWith('CREATE TABLE')) return { rowsWritten: 0, toArray: () => [] };
      if (query.startsWith('INSERT ')) {
        const [epoch, reserved_at, state] = args;
        const fresh = !records.has(epoch);
        if (fresh) records.set(epoch, { epoch, reserved_at, state });
        writes.push({ operation: 'INSERT', epoch, fresh });
        return {
          rowsWritten: reportedRowsWritten, // May include indexed writes or be pre-consumption.
          toArray: () => query.includes('RETURNING epoch') && fresh ? [{ epoch }] : [],
        };
      }
      if (query.startsWith('UPDATE dispatch_epoch')) {
        const [state, epoch] = args;
        if (!records.has(epoch)) throw Error('UNEXPECTED_MISSING_RESERVATION');
        records.get(epoch).state = state;
        writes.push({ operation: 'UPDATE', epoch });
        return { rowsWritten: 0, toArray: () => [] };
      }
      if (query.startsWith('SELECT state, reserved_at')) {
        const row = records.get(args[0]);
        return { toArray: () => row ? [{ state: row.state, reserved_at: row.reserved_at }] : [] };
      }
      throw Error('UNEXPECTED_SQL');
    },
  };
  const nowMs = Date.parse('2026-10-31T15:01:46.902Z');
  class Clock extends Date { static now() { return nowMs; } }
  const fetchStub = async (url, opts) => {
    // Mirror Cloudflare's Fetch restriction, which Node's global fetch does not enforce.
    if (opts.redirect !== 'manual') throw new TypeError('CLOUDFLARE_UNSUPPORTED_REDIRECT_MODE');
    requests.push({ url, method: opts.method, redirect: opts.redirect });
    if (url.includes('/contents/')) return { status: 404 };
    if (url.includes('/runs?')) return {
      status: 200, json: async () => ({ total_count: 0, workflow_runs: [] }),
    };
    if (url.includes('/dispatches')) return {
      status: 200, json: async () => ({ workflow_run_id: 123456 }),
    };
    throw Error('UNEXPECTED_NETWORK');
  };
  const source = fs.readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8')
    .replace("import { DurableObject } from 'cloudflare:workers';",
      'class DurableObject { constructor(ctx, env) { this.ctx=ctx; this.env=env; } }')
    .replace("import { executeOnce } from './dispatch-core.mjs';",
      'const executeOnce = globalThis.injectedExecuteOnce;')
    .replace('export class SourceDispatchLock', 'class SourceDispatchLock')
    .replace('export default {', 'const workerEntry = {');
  const ctx = {
    Response, Request, URL, AbortSignal, Date: Clock, injectedExecuteOnce: executeOnce,
    fetch: fetchStub, console: { log: s => logs.push(JSON.parse(s)), error: () => {} },
  };
  vm.runInNewContext(source + '\nglobalThis.LockClass=SourceDispatchLock;', ctx);
  const object = new ctx.LockClass({ storage: { sql: db } }, {
    GITHUB_ACTIONS_DISPATCH_TOKEN: 'TEST_TOKEN_NEVER_REAL_0123456789',
  });
  const makeRequest = () => new Request('https://internal/trigger', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scheduledTime: nowMs }),
  });
  const first = await object.fetch(makeRequest());
  assert.equal((await first.json()).decision, 'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  const epoch = '2026-10-31T15:00:00Z';
  assert.equal(records.get(epoch).state, 'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(records.get(epoch).reserved_at, nowMs);
  const second = await object.fetch(makeRequest());
  assert.equal((await second.json()).decision, 'DUPLICATE_EPOCH_LOCKED');
  assert.equal(requests.filter(x => x.method === 'POST').length, 1);
  assert.equal(writes.filter(x => x.operation === 'INSERT' && x.fresh).length, 1);
  assert.equal(records.size, 2);
  assert.equal(records.get(previous).state, 'RESERVED');
  assert.equal(records.get(previous).reserved_at, 1793455306844);
  assert.equal(logs[0].previousLock.state, 'RESERVED');
  assert.equal(logs[1].duplicateLock.state, 'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.ok(!writes.some(x => x.operation === 'DELETE'));
});
}
