"""Synthetic full gzip pairs, exercising byte-identical production V1 and V2 seam."""
import copy, gzip, tempfile, unittest
from pathlib import Path
from test_versioned_scope_v2 import fixture, STAMP0
from versioned_scope_v2 import canonical, digest, decode_receipt, epoch, Hold, verify_pinned_epoch
from ops.versioned_scope_acceptance import REPO, WORKFLOW_ID, WORKFLOW_NAME, read_pair

class Integration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.build()
    def build(self,n=531):
        f=fixture(n); r=decode_receipt(f['receipt_bytes']); self.r=r
        self.kw={k:f[k] for k in ('start_metadata','end_metadata','observed_start_ms','observed_end_ms')}
        r.update(schema='XRAY_519_SOURCE_TECH_RESEARCH_V1',source='BINANCE_PUBLIC_SPOT_REST',run_kind='RESEARCH_ONLY_NO_AL',http_provider_used=True,source_qa_success=True,scope_stable=True,epoch_stable=True,complete_identity_scope=True,status_accounting_ok=True,technical_frames_requested=3*n,full_technical_quality=False,live_source_acceptance=False,native_wss_running=False,phone_delivery_ack=False)
        r['receipt_key']=f"{r['schema']}|{r['utc_closed_epoch_1h_ms']}|{r['scope_digest_sha256']}|{n}"
        for x in r['results']: x['raw_15m_15bp_prefilter']=False
        self.b=dict(schema='XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1',source=r['source'],source_receipt_key=r['receipt_key'],scope_digest_sha256=r['scope_digest_sha256'],identity_universe=n,utc_closed_epoch_1h_ms=r['utc_closed_epoch_1h_ms'],source_start_server_ms=r['start_server_ms'],source_end_server_ms=r['end_server_ms'],orders_sent=0,notifications_sent=0,private_strategy_evaluated=0,live_al_claim=False,raw_prefilter_symbols=0,exported_symbols=n-1,transport_profile='FULL_QUALITY_READY_V2',transport_ready_count=n-1,transport_deferred_count=1,markets={x['symbol']:{} for x in r['results'][1:]},deferred_symbols={r['results'][0]['symbol']:'WARMUP'})
        self.run=dict(id=123,workflow_id=WORKFLOW_ID,name=WORKFLOW_NAME,head_branch='main',head_repository={'full_name':REPO},run_attempt=1,status='completed',conclusion='success',created_at='2026-11-28T11:01:00Z',event='schedule')
        self.proof={}
        self.rp=self.root/'receipts/2026/11/28'/f'{STAMP0}-n{n}.json.gz'; self.bp=self.root/'bridges/2026/11/28'/self.rp.name
        for p in (self.rp,self.bp): p.parent.mkdir(parents=True,exist_ok=True)
        self.write()
    def write(self):
        r=copy.deepcopy(self.r); r['source_receipt_sha256']=digest(canonical(r)); self.b['source_receipt_sha256']=r['source_receipt_sha256']; r['public_runner']={'repository':REPO,'run_id':'123','run_attempt':'1'}
        self.rp.write_bytes(gzip.compress(canonical(r),mtime=0)); self.bp.write_bytes(gzip.compress(canonical(self.b),mtime=0))
    def verify(self): return verify_pinned_epoch(self.root,STAMP0,run_lookup=lambda _:self.run,cloudflare_proof=self.proof,**self.kw)
    def held(self):
        with self.assertRaises(Hold): self.verify()
    def test_real_v1_v2_seam(self):
        result=self.verify(); self.assertEqual(result['scope_count'],531); self.assertEqual(result['technical_warmup'],1); self.assertFalse(result['full_final_start'])
        self.assertEqual(result['receipt_sha256'],read_pair(self.root,STAMP0)['receipt_sha256'])
    def test_boundary_scopes(self):
        for n in (401,518,519,520,564):
            self.rp.unlink(); self.bp.unlink(); self.build(n); self.assertEqual(self.verify()['scope_count'],n)
    def test_cf_exact(self): self.run['event']='workflow_dispatch'; self.proof[STAMP0]=123; self.assertEqual(self.verify()['origin'],'cloudflare_cron_trace_exact_run')
    def test_cf_wrong_id(self): self.run['event']='workflow_dispatch'; self.proof[STAMP0]=124; self.held()
    def test_wrong_run(self): self.run['id']=124; self.held()
    def test_wrong_branch(self): self.run['head_branch']='other'; self.held()
    def test_failed_run(self): self.run['conclusion']='failure'; self.held()
    def test_naive_run_time(self): self.run['created_at']='2026-11-28T11:01:00'; self.held()
    def test_missing_run(self): self.run=None; self.held()
    def test_missing_bridge(self): self.bp.unlink(); self.held()
    def test_bad_gzip(self): self.bp.write_bytes(b'bad'); self.held()
    def test_conflicting_pairs(self): self.bp.with_name(f'{STAMP0}-n519.json.gz').write_bytes(self.bp.read_bytes()); self.held()
    def test_grafted_market(self): self.b['markets']['OTHERUSDT']=self.b['markets'].pop(next(iter(self.b['markets']))); self.write(); self.held()
    def test_bridge_count(self): self.b['transport_ready_count']-=1; self.write(); self.held()
    def test_bridge_boolean_counter(self): self.b['orders_sent']=False; self.write(); self.held()
    def test_legacy_profile_not_new_v2(self): self.b.update(transport_profile='PREFILTER_V1',raw_prefilter_symbols=1,exported_symbols=0); self.write(); self.held()
    def test_cross_hash(self): self.b['source_receipt_sha256']='a'*64; self.bp.write_bytes(gzip.compress(canonical(self.b),mtime=0)); self.held()
    def test_identity_substitution(self): self.kw['start_metadata']['symbols'][0].update(symbol='OTHERUSDT',baseAsset='OTHER'); self.kw['end_metadata']=copy.deepcopy(self.kw['start_metadata']); self.held()
    def test_independent_observation_missing(self): self.kw['end_metadata']=None; self.held()
    def test_late_observation(self): self.kw['observed_end_ms']+=900000; self.held()
