"""Separate completed public source coverage from unachievable new-listing warmups."""
import copy
import unittest
from test_source import Provider, NOW
import research_519 as core
from verify_epoch_pair import validate_pair


class CoverageTests(unittest.TestCase):
    def pair(self):
        p1=Provider(2);p2=Provider(2)
        p2.hour=NOW+core.HOUR
        a=core.scan(p1);b=core.scan(p2)
        for i,r in enumerate((a,b),start=1):
            r['http_provider_used']=True
            r['public_runner']={'repository':'gokaydonmez39-jpg/xray-519-source-qa','run_id':str(i)}
        return a,b

    def test_two_hours_complete_warmup_is_coverage_pass(self):
        a,b=self.pair()
        for r in (a,b):
            r['results'][0]['technical_data_quality']='WARMUP'
            r['results'][0].pop('technical',None)
            r['results'][0]['reason']='CLOSED_HISTORY_20_OF_40'
            r['results'][0]['frame_quality']['1d']='WARMUP_CLOSED_HISTORY_20_OF_40'
            r['technical_pass']=1
            r['technical_warmup']=1
            r['live_source_acceptance']=False
            r['full_technical_quality']=False
        self.assertTrue(validate_pair(a,b,allow_warmup=True)[0])

    def test_failed_qa_cannot_pass_coverage(self):
        a,b=self.pair()
        a['technical_failed']=1
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

    def test_duplicate_market_row_fails(self):
        a,b=self.pair()
        a['results'][1]['symbol']=a['results'][0]['symbol']
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

    def test_same_run_fails(self):
        a,b=self.pair()
        b['public_runner']['run_id']='1'
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

    def test_bad_data_status_fails(self):
        a,b=self.pair()
        a['results'][1]['technical_data_quality']='FAIL'
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

    def test_bad_request_count_fails(self):
        a,b=self.pair()
        a['requests']=7
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

    def test_disconnected_epochs_fail(self):
        a,b=self.pair()
        b['utc_closed_epoch_1h_ms']+=core.HOUR
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

    def test_scope_drift_fails(self):
        a,b=self.pair()
        b['scope_digest_sha256']='0'*64
        self.assertFalse(validate_pair(a,b,allow_warmup=True)[0])

if __name__=='__main__':unittest.main()
