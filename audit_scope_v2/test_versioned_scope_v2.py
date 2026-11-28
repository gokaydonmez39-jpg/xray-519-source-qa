import copy, gzip, unittest
from datetime import timedelta
from versioned_scope_v2 import *

STAMP0='20261128T1100Z'
def fixture(n=531):
    rows=[{'symbol':f'X{i}USDT','baseAsset':f'X{i}','quoteAsset':'USDT','status':'TRADING','isSpotTradingAllowed':True} for i in range(n)]
    meta={'symbols':rows}; _, d=identity(meta); h=int(epoch(STAMP0).timestamp()*1000)
    r={'scope_digest_sha256':d,'identity_universe':n,'markets_selected':n,'technical_scanned':n,'start_server_ms':h+7000,'end_server_ms':h+300000,'utc_closed_epoch_1h_ms':h-1,'technical_pass':n-1,'technical_warmup':1,'technical_failed':0,'orders_sent':0,'notifications_sent':0,'private_strategy_evaluated':0,'live_al_claim':False,'results':[{'symbol':x['symbol'],'identity':'SPOT_USDT_TRADING','technical_data_quality':'PASS' if i else 'WARMUP','research_only':True,'buy_candidate':False,'orders_sent':0,'notifications_sent':0} for i,x in enumerate(rows)]}
    raw=gzip.compress(canonical(r),mtime=0); bridge=b'fixture bridge bytes, not a validated real bridge'; pair={'stamp':STAMP0,'scope_count':n,'scope_digest_sha256':d,'scope_version':f'{n}:{d}','run_id':123,'run_attempt':1,'receipt_sha256':digest(raw),'bridge_sha256':digest(bridge),'technical_pass':n-1,'technical_warmup':1,'technical_failed':0}
    return dict(pair=pair,origin='github_native_schedule',receipt_bytes=raw,bridge_bytes=bridge,start_metadata=meta,end_metadata=copy.deepcopy(meta),observed_start_ms=h,observed_end_ms=h+301000)

def change_receipt(f,fn):
    r=decode_receipt(f['receipt_bytes']); fn(r); f['receipt_bytes']=gzip.compress(canonical(r),mtime=0); f['pair']['receipt_sha256']=digest(f['receipt_bytes'])

class TestV2(unittest.TestCase):
    def check_hold(self,f,reason):
        with self.assertRaisesRegex(Hold,reason): verify_epoch(**f)
    def test_scope_valid(self):
        for n in [401,518,519,520,531,564]:
            with self.subTest(n=n): self.assertEqual(verify_epoch(**fixture(n))['scope_count'],n)
    def test_scope_bounds(self):
        for n in [400,565]:
            with self.subTest(n=n),self.assertRaisesRegex(Hold,'SCOPE_OUTSIDE'): fixture(n)
    def test_order_independence(self):
        f=fixture(); f['end_metadata']['symbols'].reverse(); self.assertEqual(verify_epoch(**f)['scope_count'],531)
    def test_unsupported_assets_filtered(self):
        f=fixture(); f['end_metadata']['symbols'] += [{'status':'BREAK'},{'status':'TRADING','isSpotTradingAllowed':False,'quoteAsset':'USDT'},{'status':'TRADING','isSpotTradingAllowed':True,'quoteAsset':'USDC'}]; self.assertEqual(verify_epoch(**f)['scope_count'],531)
    def test_duplicate(self):
        f=fixture(); f['end_metadata']['symbols'].append(f['end_metadata']['symbols'][0]); self.check_hold(f,'IDENTITY_DUPLICATE')
    def test_changed_same_count(self):
        f=fixture(); f['end_metadata']['symbols'][0].update(symbol='OTHERUSDT',baseAsset='OTHER'); self.check_hold(f,'IDENTITY_CHANGED')
    def test_spoof_both(self):
        f=fixture(); f['end_metadata']['symbols'][0].update(symbol='OTHERUSDT',baseAsset='OTHER'); f['start_metadata']=copy.deepcopy(f['end_metadata']); self.check_hold(f,'IDENTITY_DIGEST_MISMATCH')
    def test_wrong_base(self):
        f=fixture(); f['end_metadata']['symbols'][0]['baseAsset']='OTHER'; self.check_hold(f,'IDENTITY_INVALID')
    def test_unknown_origin(self):
        f=fixture(); f['origin']='manual'; self.check_hold(f,'ORIGIN')
    def test_late_observation(self):
        f=fixture(); f['observed_end_ms']+=900000; self.check_hold(f,'IDENTITY_OBSERVATION')
    def test_observation_after_start(self):
        f=fixture(); f['observed_start_ms']+=8000; self.check_hold(f,'IDENTITY_OBSERVATION')
    def test_missing_observation(self):
        f=fixture(); f['start_metadata']=None; self.check_hold(f,'EXCHANGEINFO_INVALID')
    def test_modified_bytes(self):
        f=fixture(); f['bridge_bytes']+=b'x'; self.check_hold(f,'PAIR_BYTES_CHANGED')
    def test_grafted_receipt(self):
        f=fixture(); change_receipt(f,lambda r:r['results'][0].update(symbol='OTHERUSDT')); self.check_hold(f,'RECEIPT_IDENTITY_MISMATCH')
    def test_duplicate_receipt(self):
        f=fixture(); change_receipt(f,lambda r:r['results'][0].update(symbol=r['results'][1]['symbol'])); self.check_hold(f,'RECEIPT_IDENTITY_MISMATCH')
    def test_orders(self):
        f=fixture(); change_receipt(f,lambda r:r['results'][0].update(orders_sent=1)); self.check_hold(f,'UNAUTHORIZED_ROW')
    def test_bool_counter(self):
        f=fixture(); change_receipt(f,lambda r:r.update(technical_warmup=True)); self.check_hold(f,'QUALITY_ACCOUNTING')
    def test_bad_quality(self):
        f=fixture(); change_receipt(f,lambda r:r['results'][0].update(technical_data_quality='FAIL')); self.check_hold(f,'IDENTITY_OR_QUALITY')
    def test_scope_version(self):
        f=fixture(); f['pair']['scope_version']='531:'+'a'*64; self.check_hold(f,'SCOPE_VERSION')
    def test_epoch(self):
        f=fixture(); change_receipt(f,lambda r:r.update(utc_closed_epoch_1h_ms=1)); self.check_hold(f,'RECEIPT_EPOCH')
    def records(self):
        base=verify_epoch(**fixture()); end=epoch(STAMP0); return [dict(base,stamp=(end-timedelta(hours=i)).strftime('%Y%m%dT%H00Z'),run_id=i+1,receipt_sha256=digest(f'r{i}'.encode()),bridge_sha256=digest(f'b{i}'.encode())) for i in range(48)]
    def test_48_complete_no_release(self):
        r=evaluate_window(self.records(),STAMP0); self.assertEqual(r['eligible_hours'],48); self.assertTrue(r['offline_window_complete']); self.assertFalse(r['full_final_start']); self.assertFalse(r['orders_permitted'])
    def test_missing(self): self.assertEqual(evaluate_window(self.records()[1:],STAMP0)['eligible_hours'],47)
    def test_duplicate_epoch(self):
        r=self.records(); self.assertEqual(evaluate_window(r+[r[0]],STAMP0)['eligible_hours'],47)
    def test_duplicate_run(self):
        r=self.records(); r[0]['run_id']=r[1]['run_id']; self.assertEqual(evaluate_window(r,STAMP0)['eligible_hours'],46)
    def test_duplicate_hash(self):
        r=self.records(); r[0]['receipt_sha256']=r[1]['receipt_sha256']; self.assertEqual(evaluate_window(r,STAMP0)['eligible_hours'],46)
    def test_scope_transition(self):
        r=self.records(); r[0].update(scope_count=519,scope_version='519:'+'a'*64); self.assertEqual(evaluate_window(r,STAMP0)['eligible_hours'],48)
    def test_noop_not_eligible(self):
        r=self.records(); r[0]['status']='NOOP'; self.assertEqual(evaluate_window(r,STAMP0)['eligible_hours'],47)
    def test_forged_release_flag(self):
        r=self.records(); r[0]['full_final_start']=True; self.assertEqual(evaluate_window(r,STAMP0)['eligible_hours'],47)
    def test_receipt_claims(self):
        f=fixture(); change_receipt(f,lambda r:r.update(live_al_claim=True)); self.check_hold(f,'UNAUTHORIZED_RECEIPT')
    def test_bool_order_counter(self):
        f=fixture(); change_receipt(f,lambda r:r['results'][0].update(orders_sent=False)); self.check_hold(f,'UNAUTHORIZED_ROW')
    def test_exact_h15_boundary(self):
        f=fixture(); h=int(epoch(STAMP0).timestamp()*1000); f['observed_end_ms']=h+900000; self.assertEqual(verify_epoch(**f)['scope_count'],531); f['observed_end_ms']+=1; self.check_hold(f,'IDENTITY_OBSERVATION')
    def test_bad_calendar(self):
        f=fixture(); f['pair']['stamp']='20261131T1100Z'; self.check_hold(f,'INVALID_EPOCH')
    def test_mixed_pair_count(self):
        f=fixture(); f['pair']['scope_count']=519; self.check_hold(f,'IDENTITY_DIGEST')
    def test_unsafe_symbol(self):
        f=fixture(); f['end_metadata']['symbols'][0].update(symbol='X/USDT',baseAsset='X/'); self.check_hold(f,'IDENTITY_INVALID')

if __name__=='__main__': unittest.main()
