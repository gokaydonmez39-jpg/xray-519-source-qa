import copy
import unittest
from test_source import Provider, NOW
import research_519 as src
from verify_epoch_pair import validate_pair


class PairTests(unittest.TestCase):
    def pair(self):
        p1=Provider(2);p2=Provider(2)
        p2.hour=NOW+src.HOUR
        a=src.scan(p1)
        b=src.scan(p2)
        return a,b

    def test_mock_must_never_certify_real_source(self):
        a,b=self.pair()
        ok,why=validate_pair(a,b)
        self.assertFalse(ok)
        self.assertIn('1:NOT_REAL_SOURCE_RECEIPT',why)
        self.assertIn('2:NOT_REAL_SOURCE_RECEIPT',why)

    def test_dual_epoch_structural_good_requires_real_provenance_flag(self):
        a,b=self.pair()
        for x in (a,b):
            x['http_provider_used']=True
            x['live_source_acceptance']=True
        ok,why=validate_pair(a,b)
        self.assertTrue(ok,why)
        # This test uses fabricated flags; it tests validator branches,
        # absolutely NOT a real live receipt or production acceptance.

    def test_duplicate_epoch_blocked(self):
        a,b=self.pair()
        b['utc_closed_epoch_1h_ms']=a['utc_closed_epoch_1h_ms']
        ok,why=validate_pair(a,b)
        self.assertFalse(ok)
        self.assertIn('NOT_CONSECUTIVE_DISTINCT_HOURS',why)

    def test_any_order_record_blocked(self):
        a,b=self.pair()
        a['orders_sent']=1
        ok,why=validate_pair(a,b)
        self.assertFalse(ok)
        self.assertIn('1:UNSAFE_ORDERS_SENT',why)

    def test_scope_change_blocked(self):
        a,b=self.pair()
        b['scope_digest_sha256']='f'*64
        ok,why=validate_pair(a,b)
        self.assertFalse(ok)
        self.assertIn('SCOPE_CHANGED_BETWEEN_HOURS',why)

if __name__=='__main__':
    unittest.main()
