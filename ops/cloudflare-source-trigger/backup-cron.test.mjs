import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { epochOf, executeOnce } from './dispatch-core.mjs';

const hour = Date.parse('2026-10-31T20:00:00Z');
const epoch = '2026-10-31T20:00:00Z';
const cfg = JSON.parse(fs.readFileSync(new URL('./wrangler.jsonc', import.meta.url), 'utf8'));

test('primary and secondary Cloudflare cron have distinct times, one UTC source epoch', () => {
  assert.deepEqual(cfg.triggers.crons, ['1 * * * *', '6 * * * *']);
  const primary = epochOf(hour + 60_000, hour + 61_000);
  const secondary = epochOf(hour + 360_000, hour + 361_000);
  assert.equal(primary.ok, true);
  assert.equal(secondary.ok, true);
  assert.equal(secondary.epoch, primary.epoch);
  assert.equal(secondary.stamp, '20261031T2000Z');
  assert.equal(epochOf(hour + 300_000, hour + 301_000).code, 'INVALID_SCHEDULE');
  assert.equal(epochOf(hour + 360_000, hour + 450_001).code, 'STALE_OR_EARLY_CRON');
});

function system({ failFirstStage = false, failNetworkOnce = false, priorState = null, backupStatus = 204 } = {}) {
  const rows = new Map();
  if (priorState) rows.set(epoch, { epoch, reserved_at: hour + 61_000, state: priorState });
  const calls = [], sqlCalls = [], logs = [];
  let nowMs = hour + 66_000, receiptStatus = failFirstStage ? 503 : 404, networkFailed = false;
  const sql = {
    exec(statement, ...args) {
      sqlCalls.push({ statement, args });
      if (statement.startsWith('CREATE TABLE')) return { toArray: () => [] };
      if (statement.startsWith('INSERT INTO dispatch_epoch')) {
        const [key, reservedAt, state] = args;
        if (rows.has(key)) return { toArray: () => [] };
        rows.set(key, { epoch:key, reserved_at:reservedAt, state });
        return { toArray: () => [{ epoch:key }] };
      }
      if (statement.startsWith('SELECT state, reserved_at')) {
        const r=rows.get(args[0]);
        return { toArray: () => r ? [{ state:r.state, reserved_at:r.reserved_at }] : [] };
      }
      if (statement.startsWith('UPDATE dispatch_epoch') && statement.includes('RETURNING epoch')) {
        const [state, key] = args;
        const row=rows.get(key);
        const expected=['SOURCE_RECEIPT_LOOKUP_UNAVAILABLE','GITHUB_RUNS_UNAVAILABLE',
                        'GITHUB_RUNS_INDETERMINATE','GITHUB_RUN_TIME_INVALID'];
        if (!row || !expected.includes(row.state)) return { toArray: () => [] };
        row.state=state;
        return { toArray: () => [{ epoch:key }] };
      }
      if (statement.startsWith('UPDATE dispatch_epoch SET state=')) {
        const [state, key] = args;
        const row=rows.get(key);
        if (!row) throw Error('MISSING_LOCK_ROW');
        row.state=state;
        return { toArray: () => [] };
      }
      throw Error('UNEXPECTED_SQL:' + statement);
    },
  };
  const realWorker=fs.readFileSync(new URL('./worker.mjs',import.meta.url),'utf8');
  const source=realWorker
    .replace("import { DurableObject } from 'cloudflare:workers';", 'class DurableObject { constructor(ctx,env){this.ctx=ctx;this.env=env;} }')
    .replace("import { executeOnce } from './dispatch-core.mjs';", 'const executeOnce = globalThis.injectedExecuteOnce;')
    .replace('export class SourceDispatchLock', 'class SourceDispatchLock')
    .replace('export default {', 'const workerEntry = {');
  const clock=class extends Date { static now(){return nowMs;} };
  const fetchStub=async(url, options)=>{
    calls.push({url, method:options?.method, redirect:options?.redirect});
    if(url.includes('/contents/')) { if (failNetworkOnce && !networkFailed) { networkFailed = true; throw Error('simulated Cloudflare GET timeout'); } return { status:receiptStatus }; }
    if(url.includes('/runs?')) return {status:200,json:async()=>({total_count:0,workflow_runs:[]})};
    if(url.includes('/dispatches')) return {status:backupStatus,json:async()=>({workflow_run_id:123})};
    throw Error('UNEXPECTED_GITHUB_URL');
  };
  const context={Response,Request,URL,Date:clock,AbortSignal,
    injectedExecuteOnce:executeOnce,fetch:fetchStub,
    console:{log:s=>logs.push(JSON.parse(s)),error:()=>{}}};
  vm.runInNewContext(source+'\nglobalThis.TestObject=SourceDispatchLock;globalThis.TestWorker=workerEntry;',context);
  const obj=new context.TestObject({storage:{sql}},{
    GITHUB_ACTIONS_DISPATCH_TOKEN:'OFFLINE_FAKE_TOKEN_FOR_TEST_0123456789'
  });
  async function invoke(offset, nowOffset=1000) {
    nowMs = hour + offset + nowOffset;
    const req=new Request('https://internal/trigger',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({scheduledTime:hour+offset})
    });
    const res=await obj.fetch(req);
    return (await res.json()).decision;
  }
  return {invoke,rows,calls,sqlCalls,logs,setReceiptStatus:s=>{receiptStatus=s;}};
}

test('no original epoch reservation: secondary trigger may dispatch once', async()=>{
  const t=system();
  assert.equal(await t.invoke(360_000),'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(await t.invoke(360_000),'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,1);
  assert.equal(t.rows.get(epoch).reserved_at,hour+361_000);
});

test('failed pre-POST GitHub GET may be retried once at backup, preserving original reservation', async()=>{
  const t=system({failFirstStage:true});
  assert.equal(await t.invoke(60_000),'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(t.rows.get(epoch).state,'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
  t.setReceiptStatus(404);
  assert.equal(await t.invoke(360_000),'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(t.rows.get(epoch).state,'BACKUP_DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(t.rows.get(epoch).reserved_at,hour+61_000);
  assert.equal(await t.invoke(360_000),'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,1);
  assert.equal(t.sqlCalls.filter(c=>c.statement.includes('DELETE')).length,0);
});

for (const previous of ['RESERVED','DISPATCH_REJECTED','GITHUB_NETWORK_OR_RESPONSE_UNKNOWN',
                        'DISPATCH_ACCEPTED_NOT_SOURCE_PASS','EXISTING_SOURCE_RUN']) {
  test('ambiguous or completed initial state '+previous+' never re-dispatches',async()=>{
    const t=system({priorState:previous});
    assert.equal(await t.invoke(360_000),'DUPLICATE_EPOCH_LOCKED');
    assert.equal(t.rows.get(epoch).state,previous);
    assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
  });
}

test('backup GET failure is retained as terminal backup error: no third attempt',async()=>{
  const t=system({priorState:'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE',failFirstStage:true});
  assert.equal(await t.invoke(360_000),'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(t.rows.get(epoch).state,'BACKUP_SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(await t.invoke(360_000),'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
});

test('no private references, no credential emission and no destructive lock operations',async()=>{
  const t=system({priorState:'GITHUB_RUNS_UNAVAILABLE'});
  assert.equal(await t.invoke(360_000),'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  const combined=JSON.stringify(t.logs)+JSON.stringify(t.calls);
  assert.ok(!combined.includes('OFFLINE_FAKE_TOKEN'));
  assert.ok(!combined.includes('xray-crypto-godzilla-omega'));
  assert.equal(t.sqlCalls.some(c=>/DELETE|DROP TABLE|UPDATE dispatch_epoch SET reserved_at/i.test(c.statement)),false);
});

test('actual scheduled() accepts :06 and rejects mismatched Cron minute without touching Durable Object', async()=>{
  const source=fs.readFileSync(new URL('./worker.mjs',import.meta.url),'utf8')
    .replace("import { DurableObject } from 'cloudflare:workers';", 'class DurableObject {}')
    .replace("import { executeOnce } from './dispatch-core.mjs';", 'const executeOnce = async()=>{};')
    .replace('export class SourceDispatchLock','class SourceDispatchLock')
    .replace('export default {','const workerEntry = {');
  const logs=[],errors=[];
  const ctx={Response,Date,console:{log:(...v)=>logs.push(v),error:(...v)=>errors.push(v)}};
  vm.runInNewContext(source+'\nglobalThis.TargetWorker = workerEntry;',ctx);
  let calls=0, noRetry=0;
  const env={SOURCE_DISPATCH_LOCK:{
    idFromName:()=> 'xray-519-singleton',
    get:()=>({fetch:async()=>{calls++;return {status:200,json:async()=>({decision:'EXISTING_SOURCE_RUN'})};}})
  }};
  const backup={cron:'6 * * * *',scheduledTime:hour+360_000,noRetry:()=>{noRetry++;}};
  await ctx.TargetWorker.scheduled(backup,env,{});
  assert.equal(calls,1);
  assert.equal(noRetry,0);
  assert.ok(logs.some(x=>x.includes('XRAY_PUBLIC_DISPATCH_CRON_RESULT')));

  const mismatched={cron:'1 * * * *',scheduledTime:hour+360_000,noRetry:()=>{noRetry++;}};
  await assert.rejects(ctx.TargetWorker.scheduled(mismatched,env,{}),/XRAY_PUBLIC_DISPATCH_CRON_MINUTE_MISMATCH/);
  assert.equal(calls,1,'minute mismatch must never touch SQLite lock');
  assert.equal(noRetry,1);
  assert.ok(errors.some(x=>x.includes('XRAY_PUBLIC_DISPATCH_CRON_MINUTE_MISMATCH')));
});

test('primary GET timeout before GitHub POST recovers safely at :06 with CAS single winner',async()=>{
  const t=system({failNetworkOnce:true});
  assert.equal(await t.invoke(60_000),'GITHUB_PRE_DISPATCH_NETWORK_ERROR');
  assert.equal(t.rows.get(epoch).state,'GITHUB_PRE_DISPATCH_NETWORK_ERROR');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
  assert.equal(await t.invoke(360_000),'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(t.rows.get(epoch).state,'BACKUP_DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(t.rows.get(epoch).reserved_at,hour+61_000);
  assert.equal(await t.invoke(360_000),'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,1);
  assert.equal(t.sqlCalls.filter(c=>/DELETE|DROP TABLE/.test(c.statement)).length,0);
});
