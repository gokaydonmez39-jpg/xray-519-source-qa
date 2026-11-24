"""Bounded HTTP 500 recovery; no live calls or historical replay."""
import json
import unittest
from unittest.mock import patch
import research_519 as r
from test_transport import Connection, Response

PARAMS={'symbol':'BTCUSDT','interval':'1h','limit':100,'endTime':1795550399999}

class Bounded500Tests(unittest.TestCase):
    def exercise(self, statuses, *, path='/api/v3/klines', params=PARAMS,
                 budget=1700, calls=1, duration=720):
        Connection.instances=[]
        queue=iter(statuses)
        def reply(_):
            response=Response(json.dumps({'fixture':True}).encode())
            response.status=response.code=next(queue)
            return response
        with patch('urllib.request.getproxies',return_value={}), patch(
                'http.client.HTTPSConnection',Connection), patch.object(
                Connection,'getresponse',reply):
            p=r.HttpProvider(pace=0,max_requests=budget,max_seconds=duration,
                             sleeper=lambda _:None)
            results=[]
            for _ in range(calls):
                try:
                    results.append(p.get(path,params))
                except r.FatalSourceError as exc:
                    results.append(str(exc))
            targets=[target for c in Connection.instances for _,target,_ in c.calls]
            return p,results,targets

    def test_500_to_200_same_request_new_connection(self):
        p,results,targets=self.exercise([500,200])
        self.assertEqual(results,[{'fixture':True}])
        self.assertEqual(p.requests,2)
        self.assertEqual(p.http500_recoveries,1)
        self.assertEqual(targets[0],targets[1])
        self.assertEqual(len(Connection.instances),2)
        self.assertTrue(Connection.instances[0].closed)
        self.assertEqual(p.last_request,{'path':'/api/v3/klines','symbol':'BTCUSDT','interval':'1h'})

    def test_persistent_500_fails_after_one_retry(self):
        p,results,_=self.exercise([500,500])
        self.assertEqual(results,['HTTP_500_FAIL_CLOSED'])
        self.assertEqual(p.requests,2)

    def test_non500_and_other_endpoints_never_retry(self):
        for status in (301,400,403,418,429,502,503,504):
            with self.subTest(status=status):
                p,results,_=self.exercise([status])
                self.assertEqual(results,[f'HTTP_{status}_FAIL_CLOSED'])
                self.assertEqual(p.requests,1)
        for path,params in (('/api/v3/time',None),('/api/v3/klines',dict(PARAMS,startTime=1)),
                            ('/api/v3/klines',{k:v for k,v in PARAMS.items() if k!='endTime'})):
            p,results,_=self.exercise([500],path=path,params=params)
            self.assertEqual(results,['HTTP_500_FAIL_CLOSED'])
            self.assertEqual(p.requests,1)

    def test_global_cap_and_request_duration_budgets(self):
        p,results,_=self.exercise([500,200,500,200,500],calls=3)
        self.assertEqual(p.requests,5)
        self.assertEqual(p.http500_recoveries,2)
        self.assertEqual(results[-1],'HTTP_500_FAIL_CLOSED')
        for kwargs in ({'budget':1},{'duration':8}):
            p,results,_=self.exercise([500],**kwargs)
            self.assertEqual(p.requests,1)
            self.assertEqual(results,['HTTP_500_FAIL_CLOSED'])

if __name__=='__main__':
    unittest.main()
