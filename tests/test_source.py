import copy
from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_519 as r

NOW = int(datetime(2026, 10, 30, 16, 15, tzinfo=timezone.utc).timestamp()*1000)


def candle(interval, expected, i, count):
    p = r.PERIODS[interval]
    o_ms = expected + 1 - (count-i)*p
    price = 10 + i*0.01
    return [o_ms, str(price), str(price+0.05), str(price-0.05), str(price+0.02),
            '100', o_ms+p-1, '1050', 10, '50', '525', '0']


class Provider:
    def __init__(self, count=519, injection=None):
        self.ids = [{'symbol':f'AAA{i:04d}USDT','baseAsset':f'AAA{i:04d}',
                     'quoteAsset':'USDT','status':'TRADING','isSpotTradingAllowed':True}
                    for i in range(count)]
        self.count = count
        self.requests = 0
        self.injection = injection
        self.calls = []
        self.hour = NOW

    def get(self, path, params=None):
        self.requests += 1
        self.calls.append((path,params))
        if path == '/api/v3/time':
            return {'serverTime':self.hour}
        if path == '/api/v3/exchangeInfo':
            return {'symbols':copy.deepcopy(self.ids)}
        if path == '/api/v3/ticker/24hr':
            return [{'symbol':item['symbol'], 'quoteVolume':str(i*1_000_000 + 100),
                     'closeTime':NOW} for i,item in enumerate(self.ids)]
        if path == '/api/v3/ticker/bookTicker':
            return [{'symbol':x['symbol'],'bidPrice':'10','askPrice':'10.001'} for x in self.ids]
        if path == '/api/v3/klines':
            interval=params['interval']; expected=params['endTime']; count=params['limit']
            bars = [candle(interval,expected,i,count) for i in range(count)]
            if self.injection:
                bars = self.injection(bars,params)
            return bars
        raise AssertionError(path)


class NegativeTests(unittest.TestCase):
    def test_open_bar_excluded_from_indicators(self):
        p=Provider(1,lambda bars,params: bars+[candle(params['interval'],params['endTime']+r.PERIODS[params['interval']],0,1)])
        result=r.scan(p)
        self.assertEqual(result['technical_pass'],1)
        self.assertEqual(result['results'][0]['technical']['asof_closed_utc_ms']['1h'],r.closed_epoch(NOW,r.HOUR))
        self.assertTrue(result['source_qa_success'])

    def test_gap_denied_and_never_buy(self):
        def damaged(bars,p):
            if p['interval']=='1h':
                first = copy.deepcopy(bars[0])
                first[0] -= r.HOUR
                first[6] -= r.HOUR
                bars.insert(0, first)
                bars.pop(-2)
            return bars
        result=r.scan(Provider(1,damaged))
        self.assertEqual(result['technical_failed'],1)
        self.assertEqual(result['results'][0]['reason'],'CLOSED_BAR_GAP')
        self.assertFalse(result['source_qa_success'])
        self.assertFalse(result['results'][0]['buy_candidate'])

    def test_quote_zero_with_nonzero_base_fails(self):
        def damaged(bars,p):
            if p['interval']=='4h': bars[-1][7]='0'
            return bars
        result=r.scan(Provider(1,damaged))
        self.assertEqual(result['technical_failed'],1)
        self.assertIn('NONZERO_VOLUME_CONTRADICTION',result['results'][0]['reason'])

    def test_taker_exceeds_total_fails(self):
        def damaged(bars,p):
            if p['interval']=='1h': bars[-1][10]='9999'
            return bars
        result=r.scan(Provider(1,damaged))
        self.assertEqual(result['technical_failed'],1)
        self.assertEqual(result['results'][0]['reason'],'TAKER_EXCEEDS_TOTAL')

    def test_missing_closed_candle_is_warmup(self):
        def short(bars,p): return bars[-10:] if p['interval']=='4h' else bars
        result=r.scan(Provider(1,short))
        self.assertEqual(result['technical_warmup'],1)
        self.assertEqual(result['technical_pass'],0)
        self.assertTrue(result['source_qa_success'])
        self.assertFalse(result['full_technical_quality'])

    def test_bad_order_duplication(self):
        def duplicate(bars,p):
            if p['interval']=='1h': bars[-1]=bars[-2]
            return bars
        result=r.scan(Provider(1,duplicate))
        self.assertEqual(result['results'][0]['reason'],'UNSORTED_OR_DUPLICATE_KLINE')

    def test_source_scope_mutated_end_of_epoch(self):
        class Changed(Provider):
            def get(self,path,params=None):
                if path=='/api/v3/exchangeInfo' and self.requests>0:
                    # second exchangeInfo, after 1h 4h 1d and final time
                    if sum(1 for p,_ in self.calls if p=='/api/v3/exchangeInfo')>=1:
                        self.ids[0]['status']='BREAK'
                return super().get(path,params)
        result=r.scan(Changed(2))
        self.assertFalse(result['scope_stable'])
        self.assertFalse(result['source_qa_success'])

    def test_epoch_transition_fails(self):
        class Changed(Provider):
            def get(self,path,params=None):
                if path=='/api/v3/time' and self.requests>=5:
                    self.hour+=r.HOUR
                return super().get(path,params)
        result=r.scan(Changed(1))
        self.assertFalse(result['epoch_stable'])
        self.assertFalse(result['source_qa_success'])

    def test_wrong_symbol_unicode_or_suspicious(self):
        p=Provider(1)
        p.ids[0]['symbol']='AA/../USDT'
        with self.assertRaisesRegex(r.QualityError,'UNSAFE_EXACT_SYMBOL'):
            r.scan(p)
        p.ids[0]['symbol']='牛来USDT'
        self.assertEqual(r.scan(p)['technical_pass'],1)

    def test_bad_numeric_nan(self):
        with self.assertRaises(r.QualityError):
            r.finite_decimal('NaN')

    def test_zero_trade_flat_valid(self):
        def zero(bars,p):
            x=bars[-1]
            x[1:6]=['10','10','10','10','0']
            x[7:11]=['0',0,'0','0']
            return bars
        self.assertEqual(r.scan(Provider(1,zero))['technical_pass'],1)

    def test_official_read_only_host(self):
        self.assertEqual(r.BASE_URL,'https://data-api.binance.vision')

    def test_unsafe_api_path_denied(self):
        provider=r.HttpProvider(pace=0)
        with self.assertRaisesRegex(r.FatalSourceError,'DISALLOWED_ENDPOINT'):
            provider.get('/api/v3/order')

    def test_request_limit_blocks_before_network(self):
        provider=r.HttpProvider(pace=0)
        provider.requests=provider.max_requests
        with self.assertRaisesRegex(r.FatalSourceError,'REQUEST_LIMIT_REACHED'):
            provider.get('/api/v3/time')

    def test_time_limit_blocks_before_network(self):
        provider=r.HttpProvider(pace=0)
        provider.started-=1000
        with self.assertRaisesRegex(r.FatalSourceError,'DURATION_LIMIT_REACHED'):
            provider.get('/api/v3/time')

    def test_http_429_fails_closed(self):
        from urllib.error import HTTPError
        class Reject:
            def open(self,*args,**kwargs):
                raise HTTPError('https://api.binance.com/api/v3/time',429,'Too Many Requests',{},None)
        provider=r.HttpProvider(pace=0)
        provider.opener=Reject()
        with self.assertRaisesRegex(r.FatalSourceError,'HTTP_429_FAIL_CLOSED'):
            provider.get('/api/v3/time')

    def test_no_automatic_trade_anywhere(self):
        result=r.scan(Provider(1))
        self.assertEqual(result['orders_sent'],0)
        self.assertEqual(result['notifications_sent'],0)
        self.assertEqual(result['private_strategy_evaluated'],0)
        self.assertFalse(result['live_al_claim'])

    def test_atomic_write_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'receipt.json'
            r.atomic_json(out,{'source_qa_success':True})
            self.assertTrue(json.loads(out.read_text())['source_qa_success'])
            with self.assertRaisesRegex(ValueError,'EXISTING_RECEIPT_REFUSED'):
                r.atomic_json(out, {'source_qa_success':False})
            self.assertTrue(json.loads(out.read_text())['source_qa_success'])
            symlink=Path(d)/'link'
            symlink.symlink_to(out)
            with self.assertRaisesRegex(ValueError,'OUTPUT_SYMLINK_FORBIDDEN'):
                r.atomic_json(symlink,{})

    def test_full_519_mock_technical_and_request_budget(self):
        p=Provider(519)
        result=r.scan(p)
        self.assertEqual(result['identity_universe'],519)
        self.assertEqual(result['technical_scanned'],519)
        self.assertEqual(result['technical_pass'],519)
        self.assertEqual(p.requests,1563)
        self.assertTrue(result['full_technical_quality'])
        self.assertFalse(result['live_source_acceptance'])
        self.assertTrue(result['source_qa_success'])
        self.assertEqual(sum(x['buy_candidate'] for x in result['results']),0)

    def test_partial_rank_refuses_missing_ticker(self):
        class MissingTicker(Provider):
            def get(self,path,params=None):
                ans=super().get(path,params)
                if path=='/api/v3/ticker/24hr':
                    return ans[:-1]
                return ans
        with self.assertRaisesRegex(r.QualityError,'INCOMPLETE_VOLUME_RANKING'):
            r.scan(MissingTicker(251),max_markets=250)

    def test_250_ranked_by_volume_not_alphabetical(self):
        p=Provider(519)
        result=r.scan(p,max_markets=250)
        self.assertEqual(result['technical_scanned'],250)
        self.assertEqual(result['results'][0]['symbol'],'AAA0518USDT')
        self.assertEqual(result['results'][-1]['symbol'],'AAA0269USDT')
        self.assertFalse(result['complete_identity_scope'])
        self.assertFalse(result['full_technical_quality'])
        self.assertEqual(p.requests,756)


if __name__=='__main__':
    unittest.main()
