import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyDecision, mayRetryReadOnlyGet } from './self-heal-policy.mjs';
import { executeOnce, CONFIG } from './dispatch-core.mjs';

const hour = Date.parse('2026-10-31T08:00:00Z');
const token = 'OFFLINE_FAKE_32CHAR_TOKEN_SELF_HEAL_12345';

for (const [decision, httpStatus, attempt, mode, reason] of [
  ['DISPATCH_ACCEPTED_NOT_SOURCE_PASS', null, 'primary', 'OBSERVE_ONLY', 'VERIFY_REAL_SOURCE_RECEIPT_AND_BRIDGE'],
  ['EXISTING_SOURCE_RECEIPT', null, 'primary', 'OBSERVE_ONLY', 'VERIFY_REAL_SOURCE_RECEIPT_AND_BRIDGE'],
  ['SOURCE_RUN_ALREADY_ACTIVE', null, 'primary', 'OBSERVE_ONLY', 'VERIFY_REAL_SOURCE_RECEIPT_AND_BRIDGE'],
  ['GITHUB_RUNS_UNAVAILABLE', 403, 'primary', 'REVIEW_REQUIRED', 'GITHUB_AUTH_OR_RATE_RESTRICTION'],
  ['GITHUB_RUNS_UNAVAILABLE', 401, 'primary', 'REVIEW_REQUIRED', 'GITHUB_AUTH_OR_RATE_RESTRICTION'],
  ['GITHUB_RUNS_UNAVAILABLE', 429, 'primary', 'REVIEW_REQUIRED', 'GITHUB_RATE_LIMIT'],
  ['GITHUB_RUNS_UNAVAILABLE', 503, 'primary', 'SAFE_BACKUP_CAS_ONCE', 'KNOWN_PRE_POST_FAILURE'],
  ['GITHUB_RUNS_UNAVAILABLE', 503, 'backup', 'HOLD_NO_RETRY', 'BACKUP_EXHAUSTED'],
  ['GITHUB_PRE_DISPATCH_NETWORK_ERROR', null, 'primary', 'SAFE_BACKUP_CAS_ONCE', 'KNOWN_PRE_POST_FAILURE'],
  ['SOURCE_RECEIPT_LOOKUP_UNAVAILABLE', 502, 'primary', 'SAFE_BACKUP_CAS_ONCE', 'KNOWN_PRE_POST_FAILURE'],
  ['DISPATCH_REJECTED', 503, 'primary', 'HOLD_NO_RETRY', 'POST_OR_AUDIT_UNCERTAINTY'],
  ['GITHUB_NETWORK_OR_RESPONSE_UNKNOWN', null, 'primary', 'HOLD_NO_RETRY', 'POST_OR_AUDIT_UNCERTAINTY'],
  ['DUPLICATE_EPOCH_LOCKED', null, 'backup', 'HOLD_NO_RETRY', 'SAFETY_GATE'],
  ['STALE_OR_EARLY_CRON', null, 'primary', 'HOLD_NO_RETRY', 'SAFETY_GATE'],
  ['FAKE_UNTRUSTED_DECISION', null, 'unknown', 'REVIEW_REQUIRED', 'UNKNOWN_DECISION'],
]) {
  test('deterministic no-deployment policy: '+decision+'/'+httpStatus+'/'+attempt,()=>{
    const result=classifyDecision({decision,httpStatus,attempt});
    assert.equal(result.schema,'XRAY519_SELF_HEAL_POLICY_V1');
    assert.equal(result.mode,mode);
    assert.equal(result.reason,reason);
    assert.equal(result.automaticCodeChange,false);
    assert.equal(result.automaticLockReset,false);
    assert.ok(!JSON.stringify(result).includes(token));
  });
}
test('malformed decision is always review and cannot leak input',()=>{
  const got=classifyDecision({decision:{secret:token}});
  assert.equal(got.mode,'REVIEW_REQUIRED');
  assert.ok(!JSON.stringify(got).includes(token));
});
for (const status of [502,503,504]) {
  test('one transient GET allowed with >=7 seconds of nominal guard: '+status,()=>{
    assert.equal(mayRetryReadOnlyGet({status,used:false,nominalAgeMs:83_000}),true);
    assert.equal(mayRetryReadOnlyGet({status,used:false,nominalAgeMs:83_001}),false);
    assert.equal(mayRetryReadOnlyGet({status,used:true,nominalAgeMs:40_000}),false);
  });
}
for (const status of [200,201,204,302,307,400,401,403,404,409,429,500]) {
  test('never auto-retry GET HTTP '+status,()=>{
    assert.equal(mayRetryReadOnlyGet({status,used:false,nominalAgeMs:5_000}),false);
  });
}

function simulation({
  receipt=[404], list=[200], dispatch=204, failPost=false,
  isBackup=false, age=10_000,
}={}) {
  const calls=[],marks=[],locks=new Set();
  let rc=0,lc=0;
  const offset=isBackup ? CONFIG.backupOffsetMs : CONFIG.offsetMs;
  const githubFetch=async (url,opts)=>{
    calls.push({url,method:opts.method,auth:opts.headers.Authorization,body:opts.body});
    if(url.includes('/contents/'))return {status:receipt[Math.min(rc++,receipt.length-1)]};
    if(url.includes('/runs?'))return {
      status:list[Math.min(lc++,list.length-1)],
      json:async()=>({total_count:0,workflow_runs:[]}),
    };
    if(url.includes('/dispatches')){
      if(failPost)throw new Error('POST uncertain');
      return {status:dispatch,json:async()=>({workflow_run_id:123})};
    }
    throw Error('unexpected endpoint');
  };
  const arg={
    scheduledTime:hour+offset,nowMs:hour+offset+age,
    clockMs:()=>hour+offset+age,
    token,githubFetch,
    reserve:key=>{if(locks.has(key))return false;locks.add(key);return true},
    mark:async (key,state)=>marks.push(state),
  };
  return { calls, marks, arg, run:()=>executeOnce(arg) };
}
test('AUTO-HEAL transient receipt 503 -> 404, no replay or secret exposure',async()=>{
  const t=simulation({receipt:[503,404]});
  const x=await t.run();
  assert.equal(x.decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(x.safeGetRetryUsed,true);
  assert.equal(x.selfHeal.mode,'OBSERVE_ONLY');
  assert.equal(t.calls.filter(v=>v.url.includes('/contents/')).length,2);
  assert.equal(t.calls.filter(v=>v.url.includes('/runs?')).length,6);
  assert.equal(t.calls.filter(v=>v.method==='POST').length,1);
  assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(v=>v.method==='POST').length,1);
  assert.ok(!JSON.stringify(x).includes(token));
  assert.ok(!JSON.stringify(t.marks).includes(token));
});
test('AUTO-HEAL scoped authenticated runs GET 502 -> 200, exactly one POST',async()=>{
  const t=simulation({list:[502,200]});
  const x=await t.run();
  assert.equal(x.decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(x.safeGetRetryUsed,true);
  assert.equal(t.calls.filter(v=>v.url.includes('/runs?')).length,7);
  assert.ok(t.calls.filter(v=>v.url.includes('/runs?')).every(v=>v.auth==='Bearer '+token));
  assert.equal(t.calls.filter(v=>v.method==='POST').length,1);
});
test('failed two pre-POST GETs remain fail-closed with no POST and one retry budget',async()=>{
  const t=simulation({receipt:[503,503]});
  const x=await t.run();
  assert.equal(x.decision,'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(x.httpStatus,503);
  assert.equal(x.selfHeal.mode,'SAFE_BACKUP_CAS_ONCE');
  assert.equal(x.safeGetRetryUsed,true);
  assert.equal(t.calls.filter(v=>v.method==='GET').length,2);
  assert.equal(t.calls.filter(v=>v.method==='POST').length,0);
});
for (const status of [403,429]) {
  test('HTTP '+status+' stays fail-closed, no blind retry',async()=>{
    const t=simulation({list:[status]});
    const x=await t.run();
    assert.equal(x.decision,'GITHUB_RUNS_UNAVAILABLE');
    assert.equal(x.httpStatus,status);
    assert.equal(x.safeGetRetryUsed,false);
    assert.equal(x.selfHeal.mode,'REVIEW_REQUIRED');
    assert.equal(t.calls.filter(v=>v.url.includes('/runs?')).length,1);
    assert.equal(t.calls.filter(v=>v.method==='POST').length,0);
  });
}
test('near 90s boundary blocks 503 GET retry',async()=>{
  const t=simulation({receipt:[503,404],age:89_000});
  const x=await t.run();
  assert.equal(x.decision,'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(x.safeGetRetryUsed,false);
  assert.equal(t.calls.filter(v=>v.url.includes('/contents/')).length,1);
  assert.equal(t.calls.filter(v=>v.method==='POST').length,0);
});
test('never retry ambiguous dispatch POST',async()=>{
  const t=simulation({failPost:true});
  const x=await t.run();
  assert.equal(x.decision,'GITHUB_NETWORK_OR_RESPONSE_UNKNOWN');
  assert.equal(x.selfHeal.mode,'HOLD_NO_RETRY');
  assert.equal(t.calls.filter(v=>v.method==='POST').length,1);
  assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED');
  assert.equal(t.calls.filter(v=>v.method==='POST').length,1);
});
test('backup failure is terminal, never suggests third try',async()=>{
  const t=simulation({isBackup:true,receipt:[503,503]});
  const x=await t.run();
  assert.equal(x.decision,'SOURCE_RECEIPT_LOOKUP_UNAVAILABLE');
  assert.equal(x.attempt,'backup');
  assert.equal(x.selfHeal.mode,'HOLD_NO_RETRY');
  assert.equal(x.selfHeal.reason,'BACKUP_EXHAUSTED');
  assert.equal(t.calls.filter(v=>v.method==='POST').length,0);
});

test('live clock crossing nominal 90s before POST blocks, even after green GET',async()=>{
  const t=simulation();
  let reads=0;
  t.arg.clockMs=()=>{
    reads++;
    return hour+CONFIG.offsetMs+(reads>=8 ? 90_001 : 70_000);
  };
  const x=await t.run();
  assert.equal(x.decision,'STALE_OR_EARLY_CRON');
  assert.equal(x.selfHeal.mode,'HOLD_NO_RETRY');
  assert.equal(t.calls.filter(v=>v.method==='GET').length,7);
  assert.equal(t.calls.filter(v=>v.method==='POST').length,0);
  assert.equal(t.marks.at(-1),'STALE_OR_EARLY_CRON');
});
test('live clock remaining within 90s allows exactly one POST',async()=>{
  const t=simulation();
  t.arg.clockMs=()=>hour+CONFIG.offsetMs+89_999;
  const x=await t.run();
  assert.equal(x.decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
  assert.equal(t.calls.filter(v=>v.method==='POST').length,1);
});
test('invalid live clock fails closed before dispatch',async()=>{
  const t=simulation();
  t.arg.clockMs=()=>NaN;
  const x=await t.run();
  assert.equal(x.decision,'STALE_OR_EARLY_CRON');
  assert.equal(t.calls.filter(v=>v.method==='POST').length,0);
});
