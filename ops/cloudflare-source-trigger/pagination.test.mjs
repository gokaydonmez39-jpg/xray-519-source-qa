import test from 'node:test';
import assert from 'node:assert/strict';
import {CONFIG,executeOnce} from './dispatch-core.mjs';

const hour=Date.parse('2026-10-31T08:00:00Z');
const statuses=['queued','in_progress','waiting','requested','pending'];
function harness({sameHour=[],active={},bad=null,history=100}={}){
  const calls=[],locks=new Set();
  const run={id:123,workflow_id:CONFIG.workflowId,head_branch:'main',status:'completed',created_at:new Date(hour).toISOString()};
  const arg={scheduledTime:hour+60000,nowMs:hour+70000,token:'TEST_FAKE_TOKEN_0123456789_ABC',
    reserve:key=>{if(locks.has(key))return false;locks.add(key);return true;},
    mark:async()=>{},githubFetch:async(raw,opts)=>{
      const url=new URL(raw);calls.push({url,opts});
      if(url.pathname.includes('/contents/'))return {status:404};
      if(url.pathname.endsWith('/dispatches'))return {status:204};
      if(url.pathname.endsWith('/actions/runs'))return {status:200,json:async()=>({total_count:history,workflow_runs:Array.from({length:100},(_,i)=>({...run,id:i,workflow_id:999,created_at:new Date(hour-3600000).toISOString()}))})};
      assert.ok(url.pathname.endsWith('/actions/workflows/'+CONFIG.workflowFile+'/runs'));
      assert.equal(url.searchParams.get('branch'),'main');
      assert.equal(url.searchParams.get('per_page'),'1');
      const status=url.searchParams.get('status');
      const list=status?(active[status]||[]):sameHour;
      if(!status)assert.equal(url.searchParams.get('created'),'>='+new Date(hour).toISOString().replace('.000Z','Z'));
      else assert.ok(statuses.includes(status));
      if(bad && bad.query===(status||'epoch')) {
        if(bad.throw)throw Error('offline');
        return {status:bad.http||200,json:async()=>bad.payload};
      }
      return {status:200,json:async()=>({total_count:list.length,workflow_runs:list.slice(0,1)})};
    }};
  return {arg,calls,run:()=>executeOnce(arg),sample:run};
}
const posts=t=>t.calls.filter(x=>x.opts.method==='POST');
test('100, 101 and 10000 unrelated historical runs do not permanently lock source',async()=>{
  for(const history of [100,101,10000]){
    const t=harness({history});assert.equal((await t.run()).decision,'DISPATCH_ACCEPTED_NOT_SOURCE_PASS');
    assert.equal(posts(t).length,1);assert.equal(t.calls.length,8);
    assert.ok(!t.calls.some(x=>x.url.pathname.endsWith('/actions/runs')));
    assert.ok(t.calls.filter(x=>x.opts.method==='GET').every(x=>!x.opts.headers.Authorization));
    assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED');assert.equal(posts(t).length,1);
  }
});
test('same epoch source run blocks even with 10000 historical runs',async()=>{
  const t=harness();
  const x=harness({sameHour:[t.sample]});assert.equal((await x.run()).decision,'EXISTING_SOURCE_RUN');
  assert.equal(posts(x).length,0);
});
for(const status of statuses)test('old '+status+' source run blocks independently of latest history',async()=>{
  const t=harness();const x=harness({active:{[status]:[{...t.sample,status,created_at:new Date(hour-86400000).toISOString()}]}});
  assert.equal((await x.run()).decision,'SOURCE_RUN_ALREADY_ACTIVE');assert.equal(posts(x).length,0);
});
for(const payload of [null,{}, {workflow_runs:[]}, {total_count:0,workflow_runs:[{}]}, {total_count:1,workflow_runs:[]}, {total_count:-1,workflow_runs:[]}, {total_count:'0',workflow_runs:[]}, {total_count:0.5,workflow_runs:[]}, {total_count:1,workflow_runs:[null]}]){
  test('malformed or contradictory list fails closed '+JSON.stringify(payload),async()=>{
    const t=harness({bad:{query:'epoch',payload}});assert.equal((await t.run()).decision,'GITHUB_RUNS_INDETERMINATE');assert.equal(posts(t).length,0);
  });
}
for(const query of ['epoch',...statuses])test('API error for '+query+' blocks and preserves epoch lock',async()=>{
  const t=harness({bad:{query,http:429}});assert.equal((await t.run()).decision,'GITHUB_RUNS_UNAVAILABLE');
  assert.equal((await t.run()).decision,'DUPLICATE_EPOCH_LOCKED');assert.equal(posts(t).length,0);
});
test('network failure never dispatches',async()=>{
  const t=harness({bad:{query:'pending',throw:true}});assert.equal((await t.run()).decision,'GITHUB_PRE_DISPATCH_NETWORK_ERROR');assert.equal(posts(t).length,0);
});
test('invalid run time blocks',async()=>{
  const t=harness();const x=harness({sameHour:[{...t.sample,created_at:'invalid'}]});
  assert.equal((await x.run()).decision,'GITHUB_RUN_TIME_INVALID');assert.equal(posts(x).length,0);
});
test('wrong workflow or branch in filtered result fails closed',async()=>{
  const t=harness();
  for(const delta of [{workflow_id:999},{head_branch:'other'},{id:null}]){
    const x=harness({sameHour:[{...t.sample,...delta}]});assert.equal((await x.run()).decision,'GITHUB_RUNS_INDETERMINATE');assert.equal(posts(x).length,0);
  }
});
