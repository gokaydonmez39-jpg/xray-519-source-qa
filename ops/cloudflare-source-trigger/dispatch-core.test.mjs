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
test('GitHub workflow-run list GET is authenticated; anonymous 403 cannot block a healthy token',async()=>{
  const t=mock();
  const baseFetch=t.arg.githubFetch;
  const expectedAuth='Bearer '+t.arg.token;
  // Exact regression: old code sends no Authorization and receives HTTP 403.
  t.arg.githubFetch=async(url,opts)=>{
    if(url.includes('/actions/workflows/')&&url.includes('/runs?')&&
       opts.headers.Authorization!==expectedAuth)return {status:403};
    return baseFetch(url,opts);
  };
  const result=await t.run();
  assert.equal(result.decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  const listCalls=t.calls.filter(c=>c.url.includes('/runs?'));
  assert.equal(listCalls.length,6);
  assert.ok(listCalls.every(c=>c.method==='GET'&&c.headers.Authorization===expectedAuth));
  const receipt=t.calls.find(c=>c.url.includes('/contents/'));
  assert.equal(receipt.headers.Authorization,undefined,'leave existing public receipt GET unchanged');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,1);
  assert.equal(JSON.stringify(result).includes(t.arg.token),false,'token must never be in results');
  assert.equal([...t.status.values()][0],'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
});

test('authenticated HTTP 403 workflow-run list remains fail-closed without a dispatch',async()=>{
  const t=mock({listStatus:403});
  const first=await t.run();
  assert.equal(first.decision,'GITHUB_RUNS_UNAVAILABLE');
  assert.equal(first.httpStatus,403);
  assert.equal(first.stamp,'20261031T0800Z');
  const list=t.calls.filter(c=>c.url.includes('/runs?'));
  assert.equal(list.length,1);
  assert.equal(list[0].headers.Authorization,'Bearer '+t.arg.token);
  assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
  assert.equal(JSON.stringify(first).includes(t.arg.token),false);
  const before=t.calls.length;
  assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.length,before,'do not retry a locked epoch in core');
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

test('HTTP 3xx is fail-closed at all GitHub stages', async () => {
  const cases = [
    { options: { receipt: 302 }, expected: 'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE', post: false },
    { options: { listStatus: 307 }, expected: 'GITHUB_RUNS_UNAVAILABLE', post: false },
    { options: { dispatchStatus: 308 }, expected: 'DISPATCH_REJECTED', post: true },
  ];
  for (const { options, expected, post } of cases) {
    const t = mock(options);
    const first = await t.run();
    assert.equal(first.decision, expected);
    assert.equal(t.calls.some(c => c.method === 'POST'), post);
    const count = t.calls.length;
    assert.equal((await t.run()).decision, 'DUPLICATE_EPOCH_LOCKED');
    assert.equal(t.calls.length, count, 'redirect failures must not be retried');
  }
});

test('GET receipt network error is known pre-dispatch and must not poison whole epoch',async()=>{
  const t=mock({throwOn:'/contents/'});
  assert.equal((await t.run()).decision,'GITHUB_PRE_DISPATCH_NETWORK_ERROR');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
  assert.equal(t.status.get('2026-10-31T08:00:00Z'),'GITHUB_PRE_DISPATCH_NETWORK_ERROR');
});
test('GET source-run list network failure stays pre-POST; no API dispatch attempted',async()=>{
  const t=mock({throwOn:'/runs?'});
  assert.equal((await t.run()).decision,'GITHUB_PRE_DISPATCH_NETWORK_ERROR');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,0);
});
test('POST dispatch network failure remains ambiguous and can NEVER be retried',async()=>{
  const t=mock({throwOn:'/dispatches'});
  assert.equal((await t.run()).decision,'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN');
  assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(c=>c.method==='POST').length,1);
});
