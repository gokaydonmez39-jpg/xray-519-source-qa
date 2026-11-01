"""Offline regressions for exact Cloudflare origin proof (no API token/network)."""
import io
import json
import unittest
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError
from ops.cloudflare_source_provenance import (
    MAX_EVENTS, SCRIPT, ProvenanceError, end_epoch, query_body,
    prove, from_query_response, fetch_verified,
)

END = "20261101T2100Z"
STAMP = "20261101T2000Z"
VERS = "a570b5db-c3cf-464e-a523-da9f1ab2c46c"
TRACE = "abcdef1234567890abcdef1234567890"
EPOCH_MS = int(datetime(2026, 11, 1, 20, tzinfo=timezone.utc).timestamp() * 1000)
RUN = 41344721769

def event_root(trace=TRACE, cron="1 * * * *", outcome="ok",
               version=VERS, stamp_ms=EPOCH_MS + 114_250):
    return {
        "timestamp": stamp_ms,
        "$metadata": {"service": SCRIPT, "type": "cf-worker-event", "traceId": trace},
        "$workers": {"scriptName": SCRIPT, "eventType": "scheduled",
                     "outcome": outcome, "scriptVersion": {"id": version},
                     "event": {"cron": cron}}
    }

def event_do(trace=TRACE, run_id=RUN, decision="DISPATCH_ACCEPTED_NOT_SOURCE_PASS",
             version=VERS, stamp=STAMP, source_mode="dict", stamp_ms=EPOCH_MS+114_251):
    data={"event":"XRAY_PUBLIC_DISPATCH", "stamp":stamp,
          "runId":run_id, "decision":decision}
    if source_mode=="text": source=json.dumps(data)
    elif source_mode=="message": source={"message":json.dumps(data)}
    else: source=data
    return {
        "timestamp": stamp_ms,
        "$metadata":{"service":SCRIPT,"type":"cf-worker-log","traceId":trace},
        "$workers":{"scriptName":SCRIPT,"eventType":"fetch",
                    "entrypoint":"SourceDispatchLock","scriptVersion":{"id":version}},
        "source":source
    }

class ProofTests(unittest.TestCase):
    def test_valid_primary_proof(self):
        self.assertEqual(prove([event_root(),event_do()],END), {STAMP:RUN})
    def test_valid_backup_proof(self):
        b=event_root(cron="6 * * * *",stamp_ms=EPOCH_MS+370_250)
        self.assertEqual(prove([b,event_do(stamp_ms=EPOCH_MS+370_251)],END), {STAMP:RUN})
    def test_serialized_structured_message(self):
        for mode in ("text", "message"):
            self.assertEqual(prove([event_root(),event_do(source_mode=mode)],END),
                             {STAMP:RUN})
    def test_no_scheduled_parent(self):
        self.assertEqual(prove([event_do()],END), {})
    def test_bad_trace(self):
        self.assertEqual(prove([event_root(),event_do(trace="1"*32)],END),{})
    def test_failed_scheduled_root(self):
        self.assertEqual(prove([event_root(outcome="exception"),event_do()],END),{})
    def test_wrong_worker_service(self):
        r=event_root();r["$metadata"]["service"]="attacker";
        self.assertEqual(prove([r,event_do()],END),{})
    def test_same_trace_distant_time_must_not_promote(self):
        self.assertEqual(prove([event_root(),event_do(stamp_ms=EPOCH_MS+370_251)],END),{})
    def test_wrong_script_version(self):
        self.assertEqual(prove([event_root(),event_do(version="f"*36)],END),{})
    def test_broken_or_unknown_lock_is_not_source_proof(self):
        for decision in ("DUPLICATE_EPOCH_LOCKED","GITHUB_RUNS_UNAVAILABLE",
                         "GITHUB_HTTP_ACCESS_BLOCKED","EXISTING_SOURCE_RUN",
                         "GITHUB_NETWORK_OR_RESPONSE_UNKNOWN"):
            self.assertEqual(prove([event_root(),event_do(decision=decision)],END),{})
    def test_run_id_required_and_integer(self):
        for rid in (None, "4134", -1, True, 0):
            self.assertEqual(prove([event_root(),event_do(run_id=rid)],END),{})
    def test_conflicting_run_ids_fail_closed(self):
        self.assertEqual(prove([event_root(),event_do(run_id=1),
                                event_do(run_id=2)],END),{})
    def test_duplicate_identical_run_id_is_not_two_source_epochs(self):
        self.assertEqual(prove([event_root(),event_do(),event_do()],END),{STAMP:RUN})
    def test_out_of_nominal_window(self):
        self.assertEqual(prove([event_root(stamp_ms=EPOCH_MS+400_000),
                                event_do()],END),{})
    def test_invalid_scheduled_expression(self):
        self.assertEqual(prove([event_root(cron="4 * * * *"),event_do()],END),{})
    def test_unknown_log_format_does_not_promote(self):
        d=event_do();d["source"]='{"event":"OTHER"}';
        self.assertEqual(prove([event_root(),d],END),{})
    def test_invalid_epoch_rejected(self):
        for stamp in ("20261101T2400Z","20260230T1100Z","20261101T2015Z",""):
            with self.assertRaises(ProvenanceError):end_epoch(stamp)
    def test_api_schema_and_48h_bound(self):
        p=query_body(END)
        self.assertEqual(p["view"],"events")
        self.assertEqual(p["limit"],MAX_EVENTS)
        self.assertEqual(p["timeframe"]["to"]-p["timeframe"]["from"],
                         47*3600_000+10*60_000)
    def test_query_success_and_complete(self):
        self.assertEqual(from_query_response({"success":True,"result":{
            "events":{"count":2,"events":[event_root(),event_do()]}}},END),{STAMP:RUN})
    def test_query_truncated_fails_closed(self):
        for count in (1, MAX_EVENTS):
            with self.assertRaises(ProvenanceError):
                from_query_response({"success":True,"result":{
                    "events":{"count":count,"events":[event_root(),event_do()]}}},END)
    def test_query_failure_fails_closed(self):
        for payload in ({}, {"success":False}, {"success":True,"result":{}}):
            with self.assertRaises(ProvenanceError):from_query_response(payload,END)
    def test_no_credentials_no_request(self):
        with self.assertRaises(ProvenanceError):
            fetch_verified(END,"","",transport=lambda *_: self.fail("network"))
    def test_api_token_is_never_returned_in_error(self):
        secret="DUMMY_SECRET_TOKEN_SHOULD_NOT_LEAK_0123456789"
        def err(*a,**k):
            raise HTTPError("https://api.cloudflare.com",403,secret,{},None)
        with self.assertRaises(ProvenanceError) as cm:
            fetch_verified(END,"a"*32,secret,transport=err)
        self.assertNotIn(secret,str(cm.exception))
        self.assertEqual(str(cm.exception),"CLOUDFLARE_QUERY_TRANSPORT_FAILED")
    def test_mocked_http_query_reads_only_once(self):
        token="dummy_token_not_real_"+("a"*25)
        class Reply:
            def __init__(self, data): self.data=data
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, maxlen): return self.data[:maxlen]
        called=[]
        def stub(req,timeout):
            called.append((req.get_method(),req.full_url,
                           req.data.decode(),timeout,req.headers))
            return Reply(json.dumps({"success":True,"result":{"events":{
                "count":2,"events":[event_root(),event_do()]}}}).encode())
        proof=fetch_verified(END,"a"*32,token,transport=stub)
        self.assertEqual(proof,{STAMP:RUN})
        self.assertEqual(len(called),1)
        self.assertEqual(called[0][0],"POST")
        self.assertTrue(called[0][1].endswith("/workers/observability/telemetry/query"))
        self.assertNotIn(token,called[0][2])
        self.assertEqual(called[0][3],12)

if __name__=="__main__":
    unittest.main()
