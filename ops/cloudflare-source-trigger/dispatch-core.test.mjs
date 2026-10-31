import test from 'node:test';
import assert from 'node:assert/strict';
import { CONFIG, epochOf, executeOnce } from './dispatch-core.mjs';

const hour=Date.parse('2026-10-31T08:00:00.000Z'),scheduledTime=hour+60_000,nowMs=hour+70_000;
function mock({receipt=404,runs=[],listStatus=200,dispatchStatus=200,throwOn='' }={}){
  const locks=new Set(),calls=[],status=new Map();
  const githubFetch=async(url,opts)=>{
    calls.push({url,method:opts.method,headers:opts.headers,body:opts.body});
    if(throwOn&&url.includes(throwOn))throw Error('network');
    if(url.includes('/contents/'))return {status:receipt};
    if(url.includes('/runs?')){
      const q=new URL(url).searchParams;
      const selected=runs.filter(r=>r.workflow_id===CONFIG.workflowId&&r.head_branch==='main')
        .filter(r=>q.has('created') ? Date.parse(r.created_at)>=hour : r.status===q.get('status'));
      return {status:listStatus,json:async()=>({total_count:selected.length,workflow_runs:selected.slice(0,1)})};
    }
    if(url.includes('/dispatches'))return {status:dispatchStatus,json:async()=>({workflow_run_id:789})};
    throw Error('unexpected');
  };
  const arg={scheduledTime,nowMs,token:'TEST_FAKE_TOKEN_0123456789_ABC',githubFetch,
    reserve:(key)=>{if(locks.has(key))return false;locks.add(key);return true;},
    mark:async(key,value)=>{status.set(key,value)}};
  return{arg,calls,status,run:()=>executeOnce(arg)};
}
test('UTC :01 and last-close deterministic epoch',()=>{
  assert.deepEqual(epochOf(scheduledTime,nowMs),{ok:true,epoch:'2026-10-31T08:00:00Z',stamp:'20261031T0800Z',dir:'2026/10/31',startMs:hour});
  assert.equal(epochOf(scheduledTime,scheduledTime+90_001).code,'STALE_OR_EARLY_CRON');
  assert.equal(epochOf(scheduledTime+60_000,nowMs).code,'INVALID_SCHEDULE');
});
test('exactly one public Github workflow dispatch',async()=>{
  const t=mock();const x=await t.run(),y=await t.run();
  assert.equal(x.decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(y.decision,'DUPLICATE_EPOCH_LOCKED');
  const post=t.calls.filter(x=>x.method==='POST');assert.equal(post.length,1);
  assert.equal(post[0].url,'https://api.github.com/repos/'+CONFIG.repository+'/actions/workflows/hourly-519-public-source.yml/dispatches');
  assert.deepEqual(JSON.parse(post[0].body),{ref:'main',inputs:{max_markets:'519'}});
  assert.ok(!JSON.stringify(t.calls).includes('xray-crypto-godzilla-omega'));
});
test('existing receipt skips',async()=>{const t=mock({receipt:200});assert.equal((await t.run()).decision,'EXISTING_SOURCE_RECEIPT');assert.equal(t.calls.filter(x=>x.method==='POST').length,0)});
test('existing workflow run same hour skips',async()=>{const t=mock({runs:[{workflow_id:CONFIG.workflowId,head_branch:'main',created_at:new Date(hour).toISOString(),status:'completed',id:32}]});assert.equal((await t.run()).decision,'EXISTING_SOURCE_RUN')});
test('prior active run skips',async()=>{const t=mock({runs:[{workflow_id:CONFIG.workflowId,head_branch:'main',created_at:new Date(hour-3_600_000).toISOString(),status:'in_progress',id:33}]});assert.equal((await t.run()).decision,'SOURCE_RUN_ALREADY_ACTIVE')});
test('missing token never accesses Github',async()=>{const t=mock();t.arg.token='';assert.equal((await t.run()).decision,'SECRET_NOT_CONFIGURED');assert.equal(t.calls.length,0)});
test('receipt API error and run API error both block',async()=>{const a=mock({receipt:403});assert.equal((await a.run()).decision,'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');const b=mock({listStatus:429});assert.equal((await b.run()).decision,'GITHUB_RUNS_UNAVAILABLE')});
test('dispatch API error is locked, not retried',async()=>{const t=mock({dispatchStatus:403});assert.equal((await t.run()).decision,'DISPATCH_REJECTED');assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED')});
test('network uncertainty is fail-closed',async()=>{const t=mock({throwOn:'/dispatches'});assert.equal((await t.run()).decision,'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN');assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED')});
test('204 without run id is NOT a source success claim',async()=>{const t=mock({dispatchStatus:204});assert.equal((await t.run()).decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS')});
test('concurrent requests reserve same key once',async()=>{const t=mock();const r=await Promise.all([t.run(),t.run()]);assert.equal(r.filter(x=>x.decision==='DISPATCH_ACCEPTED_NOT_SOURCE_PASS').length,1)});
test('unrelated old runs do not block the scoped source workflow',async()=>{const t=mock({runs:Array.from({length:100},(_,i)=>({id:i}))});assert.equal((await t.run()).decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS')});


test('actual Cloudflare Cron scheduledTime at :01:45.563 retains correct UTC source hour', async () => {
  const actualHour = Date.parse('2026-10-31T13:00:00Z');
  const s = actualHour + 105_563; // Cloudflare invocation observed at 16:01:45.563 GMT+3
  const n = actualHour + 106_801;
  assert.deepEqual(epochOf(s, n), {
    ok: true, epoch: '2026-10-31T13:00:00Z',
    stamp: '20261031T1300Z', dir: '2026/10/31', startMs: actualHour,
  });
  const t = mock();
  t.arg.scheduledTime = s;
  t.arg.nowMs = n;
  assert.equal((await t.run()).decision, 'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal((await t.run()).decision, 'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(c => c.method === 'POST').length, 1);
});

test('delayed :01 Cron timestamps never relax 90-second nominal freshness', async () => {
  const s = hour + 119_999;
  assert.equal(epochOf(s, hour + 150_000).ok, true);
  assert.equal(epochOf(s, hour + 150_001).code, 'STALE_OR_EARLY_CRON');
  const late = mock();
  late.arg.scheduledTime = s;
  late.arg.nowMs = hour + 150_001;
  assert.equal((await late.run()).decision, 'STALE_OR_EARLY_CRON');
  assert.equal(late.calls.length, 0);
});

test('reject adjacent minutes, future events, noninteger and wrong UTC hour', async () => {
  for (const offset of [0, 59_999, 120_000, 180_000, 3_599_999]) {
    assert.equal(epochOf(hour + offset, hour + offset).code, 'INVALID_SCHEDULE');
  }
  assert.equal(epochOf(hour + 105_563, hour + 100_562).code, 'STALE_OR_EARLY_CRON');
  assert.equal(epochOf(hour + 105_563, hour + 3_600_000).code, 'STALE_OR_EARLY_CRON');
  for (const invalid of [null, undefined, 1_793_451_705.563, NaN, Infinity, -1, '1793451705563']) {
    assert.equal(epochOf(invalid, hour + 106_000).code, 'INVALID_SCHEDULE');
  }
});
