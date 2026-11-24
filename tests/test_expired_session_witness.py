"""Expired corroboration window regression. All fixtures are offline, no market replay."""
import contextlib
import io
import unittest
import research_519 as r
from bridge_519 import BridgeCollector, BridgeError
from test_source import NOW, Provider

OP = (NOW // r.DAY - 5) * r.DAY
CL = OP + 1800000 - 1
E1 = r.closed_epoch(NOW, r.HOUR)
E4 = r.closed_epoch(NOW, 4*r.HOUR)

def bar(op, close):
    return [op, '10', '11', '9', '10', '100', close, '1000', 10, '50', '500', '0']

class Witness:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    def get(self, path, params):
        self.calls.append((path, params))
        return self.rows

class ExpiredWitnessTests(unittest.TestCase):
    def setUp(self):
        self.raw4 = [bar(OP, CL), bar(OP+12*r.HOUR, OP+16*r.HOUR-1)]
        self.raw1 = [bar(OP, CL), bar(OP+13*r.HOUR, OP+14*r.HOUR-1)]
    def test_exact_witness_and_bounded_read(self):
        p = Witness(self.raw1)
        self.assertTrue(r.expired_1h_session_witness(p, symbol='AAA0001USDT',
            raw4=self.raw4, expected4=E4, expected1=E1))
        self.assertEqual(p.calls, [('/api/v3/klines', {'symbol':'AAA0001USDT',
            'interval':'1h','startTime':OP,'endTime':OP+16*r.HOUR-1,'limit':16})])
    def test_mismatch_and_no_gap_rejected(self):
        for raw1 in ([bar(OP,CL+1),self.raw1[1]],
                     [bar(OP,CL),bar(OP+r.HOUR,OP+2*r.HOUR-1)],
                     [self.raw1[1],self.raw1[0]], [self.raw1[0]],
                     [self.raw1[0],bar(OP+17*r.HOUR,OP+18*r.HOUR-1)]):
            with self.subTest(raw1=raw1):
                self.assertFalse(r.expired_1h_session_witness(Witness(raw1),
                    symbol='AAA0001USDT',raw4=self.raw4,expected4=E4,expected1=E1))
    def test_second_bad_bar_and_recent_marker_do_not_probe(self):
        p = Witness(self.raw1)
        bad = self.raw4+[bar(OP+16*r.HOUR,OP+17*r.HOUR-1)]
        self.assertFalse(r.expired_1h_session_witness(p,symbol='AAA0001USDT',
            raw4=bad,expected4=E4,expected1=E1))
        self.assertFalse(r.expired_1h_session_witness(p,symbol='AAA0001USDT',
            raw4=self.raw4,expected4=E4,expected1=OP+24*r.HOUR-1))
        self.assertEqual(p.calls,[])
    def test_full_bridge_quarantines_without_technical_data(self):
        def inject(bars, params):
            if params['symbol']=='AAA0001USDT' and params['interval']=='4h':
                idx=next(i for i,x in enumerate(bars) if x[0]==OP)
                bars[idx][6]=CL
                del bars[idx+1:idx+3]
                for _ in range(2):
                    first=list(bars[0]); first[0]-=4*r.HOUR; first[6]-=4*r.HOUR
                    bars.insert(0,first)
            return bars
        class P(Provider):
            def get(self,path,params=None):
                if path=='/api/v3/klines' and 'startTime' in params:
                    self.requests+=1
                    self.calls.append((path,params))
                    return [bar(OP,CL),bar(OP+13*r.HOUR,OP+14*r.HOUR-1)]
                return super().get(path,params)
        p=P(401,inject)
        p.ids[0]['symbol']='BTCUSDT'; p.ids[0]['baseAsset']='BTC'
        sink=BridgeCollector(full_scope=True)
        report=r.scan(p,max_markets=519,bridge_sink=sink)
        row=next(x for x in report['results'] if x['symbol']=='AAA0001USDT')
        self.assertTrue(report['source_qa_success'])
        self.assertEqual(report['session_quarantine_count'],1)
        self.assertEqual(report['technical_pass'],400)
        self.assertNotIn('technical',row)
        self.assertFalse(row['buy_candidate'])
        self.assertNotIn('AAA0001USDT',sink.document['markets'])
        self.assertEqual(sink.document['transport_deferred_count'],1)
        self.assertEqual(len([x for x in p.calls if x[1] and 'startTime' in x[1]]),1)
        self.assertEqual(report['orders_sent'],0)
        self.assertEqual(report['notifications_sent'],0)

if __name__=='__main__':
    unittest.main()
