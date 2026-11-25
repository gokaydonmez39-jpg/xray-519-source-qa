"""Offline regressions for exact Cloudflare origin proof (no API token/network)."""
import io
import json
import unittest
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError
from ops.cloudflare_source_provenance import (
    MAX_EVENTS, SCRIPT, ProvenanceError, end_epoch, query_body,
    prove, from_query_response, fetch_verified, compare_fixed_window,
    COMPARISON_EPOCH, COMPARISON_RUN,
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
        "$metadata":{"service":SCRIPT,"type":"cf-worker","traceId":trace},
        "$workers":{"scriptName":SCRIPT,"eventType":"fetch",
                    "entrypoint":"SourceDispatchLock","scriptVersion":{"id":version}},
        "source":source
    }

class CloudflareFullWindowReportSafety(unittest.TestCase):
    def record(self, origin="cloudflare_cron_trace_exact_run", verified=True):
        return {"trigger_provenance":origin,
                "trigger_independently_verified":verified}

    def test_one_cloudflare_hour_does_not_claim_48h_log_complete(self):
        from ops.evidence_collector import _cloudflare_window_accepted
        self.assertFalse(_cloudflare_window_accepted([self.record()],1))
    def test_47_cloudflare_hours_do_not_claim_complete(self):
        from ops.evidence_collector import _cloudflare_window_accepted
        self.assertFalse(_cloudflare_window_accepted([self.record() for _ in range(47)],47))
    def test_exactly_48_valid_hours_with_cf_and_native_origin(self):
        from ops.evidence_collector import _cloudflare_window_accepted
        records=[self.record()]+[self.record("github_native_schedule") for _ in range(47)]
        self.assertTrue(_cloudflare_window_accepted(records,48))
    def test_mismatched_or_incomplete_origin_forces_hold(self):
        from ops.evidence_collector import _cloudflare_window_accepted
        good=[self.record() for _ in range(48)]
        self.assertFalse(_cloudflare_window_accepted(good,47))
        good[-1]["trigger_independently_verified"]=False
        self.assertFalse(_cloudflare_window_accepted(good,48))
    def test_48_native_only_does_not_claim_cloudflare_verification(self):
        from ops.evidence_collector import _cloudflare_window_accepted
        good=[self.record("github_native_schedule") for _ in range(48)]
        self.assertFalse(_cloudflare_window_accepted(good,48))

class CloudflareProvenanceAdmissionRegression(unittest.TestCase):
    def _valid_record(self, provenance):
        return {
            "kind":"SOURCE", "stamp":STAMP, "run_id":RUN, "receipt_runner_id":str(RUN),
            "trigger_provenance":provenance, "event":"workflow_dispatch",
            "trigger_independently_verified":True,
            "conclusion":"success","source_qa_success":True,
            "scanned":519,"pass":489,"warmup":30,"failed":0,
            "status_accounting_ok":True,
            "orders_sent":0,"notifications_sent":0,"private_strategy_evaluated":0,
            "live_al_claim":False,
            "pair_bytes_independently_verified":True,
            "pair_canonical_independently_verified":True,
            "receipt_sha256":"a"*64,"bridge_sha256":"b"*64
        }
    def test_cloudflare_trace_exact_run_is_countable_only_after_all_safety_checks(self):
        from ops.autonomy_acceptance import _source_failures
        good=self._valid_record("cloudflare_cron_trace_exact_run")
        self.assertEqual(_source_failures(good),[])
        wrong=dict(good,trigger_independently_verified=False)
        self.assertIn("TRIGGER_PROVENANCE_UNVERIFIED",_source_failures(wrong))
        wrong=dict(good,event="push")
        self.assertIn("TRIGGER_PROVENANCE_UNVERIFIED",_source_failures(wrong))
    def test_origin_typo_and_legacy_unproved_origin_rejected(self):
        from ops.autonomy_acceptance import _source_failures
        for origin in ("unknown_external_origin", "cloudflare_primary",
                       "cloudflare_cro_trace_exact_run", ""):
            record=self._valid_record(origin)
            self.assertIn("TRIGGER_PROVENANCE_UNVERIFIED",_source_failures(record))

class EvidenceCollectorIntegrationTests(unittest.TestCase):
    def _case(self, event="workflow_dispatch"):
        from ops.evidence_collector import WORKFLOW_ID, WORKFLOW_NAME, REPO
        pair = {"stamp": STAMP, "run_id": RUN, "run_attempt": 1}
        run = {"id": RUN, "workflow_id": WORKFLOW_ID, "name": WORKFLOW_NAME,
               "run_attempt": 1, "head_branch": "main",
               "head_repository": {"full_name": REPO},
               "status": "completed", "conclusion": "success",
               "created_at": "2026-11-01T20:01:54Z", "event": event}
        return pair, run

    def test_unproven_workflow_dispatch_remains_hold(self):
        from ops.evidence_collector import verify_run
        pair, run = self._case()
        d = verify_run(pair,run)
        self.assertFalse(d["trigger_independently_verified"])
        self.assertEqual(d["trigger_provenance"], "unknown_external_origin")

    def test_exact_cloudflare_trace_run_unlocks_only_origin_for_that_epoch(self):
        from ops.evidence_collector import verify_run
        pair, run = self._case()
        d = verify_run(pair,run,cloudflare_run_id=RUN)
        self.assertTrue(d["trigger_independently_verified"])
        self.assertEqual(d["trigger_provenance"],"cloudflare_cron_trace_exact_run")
        self.assertEqual(d["run_id"],RUN)
        self.assertEqual(d["pair_bytes_independently_verified"],True)

    def test_wrong_run_id_cannot_promote_workflow_dispatch(self):
        from ops.evidence_collector import verify_run
        pair, run = self._case()
        for wrong in (RUN+1,str(RUN),True,None):
            d = verify_run(pair,run,cloudflare_run_id=wrong)
            self.assertFalse(d["trigger_independently_verified"])

    def test_native_schedule_proven_without_cloudflare(self):
        from ops.evidence_collector import verify_run
        pair,run=self._case("schedule")
        d=verify_run(pair,run)
        self.assertTrue(d["trigger_independently_verified"])
        self.assertEqual(d["trigger_provenance"],"github_native_schedule")

class ProofTests(unittest.TestCase):
    def test_expected_backup_red_rows_count_once(self):
        from ops.cloudflare_source_provenance import summarize_invocations
        root=event_root(cron="6 * * * *",outcome="exception",
                         stamp_ms=EPOCH_MS+370_000)
        decision=event_do(stamp_ms=EPOCH_MS+370_001,
                          decision="DUPLICATE_EPOCH_LOCKED")
        decision["source"]["duplicateLock"]={"state":"DISPATCH_ACCEPTED_NOT_SOURCE_PASS"}
        copies=[root,decision,decision,dict(decision)]
        summary=summarize_invocations(copies,END)
        self.assertEqual(summary["raw_log_rows"],4)
        self.assertEqual(summary["distinct_scheduled_invocations"],1)
        self.assertEqual(summary["expected_backup_duplicate"],1)
        self.assertEqual(summary["real_failures_or_holds"],0)

    def test_blocked_backup_stays_true_hold(self):
        from ops.cloudflare_source_provenance import summarize_invocations
        root=event_root(cron="6 * * * *",outcome="exception",
                        stamp_ms=EPOCH_MS+370_000)
        decision=event_do(stamp_ms=EPOCH_MS+370_001,
                          decision="DUPLICATE_EPOCH_LOCKED")
        decision["source"]["duplicateLock"]={"state":"GITHUB_HTTP_ACCESS_BLOCKED"}
        summary=summarize_invocations([root,decision],END)
        self.assertEqual(summary["real_failures_or_holds"],1)
        self.assertEqual(summary["expected_backup_duplicate"],0)

    def test_unknown_trace_cannot_be_green(self):
        from ops.cloudflare_source_provenance import summarize_invocations
        x=summarize_invocations([event_root()],END)
        self.assertEqual(x["unclassified_holds"],1)
        self.assertEqual(x["accepted_not_source_pass"],0)

    def test_successful_primary_is_accepted_not_source_pass(self):
        from ops.cloudflare_source_provenance import summarize_invocations
        x=summarize_invocations([event_root(),event_do()],END)
        self.assertEqual(x["accepted_not_source_pass"],1)
        self.assertEqual(x["expected_backup_duplicate"],0)

    def test_one_failure_trace_with_3_red_lines_is_not_3_failures(self):
        from ops.cloudflare_source_provenance import summarize_invocations
        root=event_root(outcome="exception")
        err=event_do(decision="GITHUB_RUNS_UNAVAILABLE")
        x=summarize_invocations([root,err,err,err],END)
        self.assertEqual(x["real_failures_or_holds"],1)
        self.assertEqual(x["distinct_scheduled_invocations"],1)

    def test_valid_primary_proof(self):
        self.assertEqual(prove([event_root(),event_do()],END), {STAMP:RUN})
    def test_valid_backup_proof(self):
        b=event_root(cron="6 * * * *",stamp_ms=EPOCH_MS+370_250)
        self.assertEqual(prove([b,event_do(stamp_ms=EPOCH_MS+370_251)],END), {STAMP:RUN})
    def test_serialized_structured_message(self):
        for mode in ("text", "message"):
            self.assertEqual(prove([event_root(),event_do(source_mode=mode)],END),
                             {STAMP:RUN})
    def test_documented_and_observed_cloudflare_log_type_both_strictly_verified(self):
        for log_type in ("cf-worker", "cf-worker-log"):
            with self.subTest(type=log_type):
                d=event_do()
                d["$metadata"]["type"]=log_type
                self.assertEqual(prove([event_root(),d],END),{STAMP:RUN})
        d=event_do();d["$metadata"]["type"]="cf-worker-event"
        self.assertEqual(prove([event_root(),d],END),{})
        d=event_do();d["$metadata"]["type"]="untrusted"
        self.assertEqual(prove([event_root(),d],END),{})

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
        self.assertIs(p["dry"], True, "telemetry query must not persist result data")
        self.assertEqual(p["limit"],MAX_EVENTS)
        self.assertEqual(p["timeframe"]["to"]-p["timeframe"]["from"],
                         47*3600_000+10*60_000)
    def test_query_success_and_complete(self):
        self.assertEqual(from_query_response({"success":True,"result":{"run":{"status":"COMPLETED"},
            "events":{"count":2,"events":[event_root(),event_do()]}}},END),{STAMP:RUN})
    def test_query_truncated_fails_closed(self):
        for count in (1, MAX_EVENTS):
            with self.assertRaises(ProvenanceError):
                from_query_response({"success":True,"result":{
                    "events":{"count":count,"events":[event_root(),event_do()]}}},END)
    def test_running_query_is_hold(self):
        with self.assertRaises(ProvenanceError):
            from_query_response({"success":True,"result":{"run":{"status":"STARTED"},
                "events":{"count":2,"events":[event_root(),event_do()]}}},END)

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
            return Reply(json.dumps({"success":True,"result":{"run":{"status":"COMPLETED"},"events":{
                "count":2,"events":[event_root(),event_do()]}}}).encode())
        proof=fetch_verified(END,"a"*32,token,transport=stub)
        self.assertEqual(proof,{STAMP:RUN})
        self.assertEqual(len(called),1)
        self.assertEqual(called[0][0],"POST")
        self.assertTrue(called[0][1].endswith("/workers/observability/telemetry/query"))
        self.assertNotIn(token,called[0][2])
        self.assertEqual(called[0][3],12)


class OriginObservationTests(unittest.TestCase):
    def measure(self, records, stamp=STAMP):
        payload = {"success": True, "result": {"run": {"status": "COMPLETED"},
                   "events": {"events": records, "count": len(records)}}}
        proof, diag = from_query_response(payload, stamp, include_diagnostics=True)
        self.assertEqual(proof, from_query_response(payload, stamp))
        self.assertEqual(diag["schema"], "XRAY_CLOUDFLARE_ORIGIN_OBSERVATION_V1")
        self.assertEqual(diag["queried_epoch_count"], 48)
        self.assertNotIn(TRACE, json.dumps(diag))
        self.assertNotIn(str(RUN), json.dumps(diag))
        return proof, diag

    def test_current_correlation_is_still_exact(self):
        proof, observed = self.measure([event_root(), event_do()])
        self.assertEqual(proof, {STAMP: RUN})
        self.assertEqual(observed["current_epoch_reason"], "EXACT_CLOUDFLARE_RUN_PROOF_OBSERVED")
        self.assertEqual(observed["epochs_with_exact_correlation"], 1)

    def test_successful_query_is_not_evidence_of_a_scheduled_log(self):
        proof, observed = self.measure([event_root(), event_do()], END)
        self.assertEqual(proof, {STAMP: RUN})
        self.assertEqual(observed["epochs_with_observed_scheduled_log"], 1)
        self.assertEqual(observed["current_epoch_reason"], "NO_SCHEDULED_LOG_FOR_EPOCH_IN_QUERY")

    def test_missing_parent_decision_and_legacy_204_are_separate(self):
        for records, reason in [
            ([event_root(outcome="exception")], "NO_UNAMBIGUOUS_ELIGIBLE_SCHEDULED_ROOT"),
            ([event_root(), event_do(trace="1"*32)], "NO_SAME_TRACE_DISPATCH_LOG_IN_QUERY"),
            ([event_root(), event_do(decision="EXISTING_SOURCE_RUN")],
             "NO_SAME_EPOCH_ACCEPTED_DISPATCH_LOG_IN_QUERY"),
            ([event_root(), event_do(run_id=None)], "ACCEPTED_DISPATCH_LOG_WITHOUT_EXACT_RUN_ID"),
        ]:
            with self.subTest(reason=reason):
                proof, observed = self.measure(records)
                self.assertEqual(proof, {})
                self.assertEqual(observed["current_epoch_reason"], reason)

    def test_version_clock_conflict_and_malformed_log_cannot_authorize(self):
        malformed = event_do()
        malformed.pop("timestamp")
        odd = event_do()
        odd["$workers"]["scriptVersion"] = []
        for records, reason in [
            ([event_root(), event_do(version="b"*36)], "ACCEPTED_DISPATCH_VERSION_OR_CLOCK_NOT_PROVEN"),
            ([event_root(), event_do(stamp_ms=EPOCH_MS+240_000)], "ACCEPTED_DISPATCH_VERSION_OR_CLOCK_NOT_PROVEN"),
            ([event_root(), event_do(), event_do(run_id=RUN+1)], "CONFLICTING_CLOUDFLARE_RUN_IDS"),
            ([event_root(), malformed], "NO_SAME_TRACE_DISPATCH_LOG_IN_QUERY"),
            ([event_root(), odd], "ACCEPTED_DISPATCH_VERSION_OR_CLOCK_NOT_PROVEN"),
        ]:
            with self.subTest(reason=reason):
                proof, observed = self.measure(records)
                self.assertEqual(proof, {})
                self.assertEqual(observed["current_epoch_reason"], reason)

    def test_summary_retains_one_dry_query_and_exposes_only_aggregates(self):
        class Response(io.BytesIO):
            pass
        events = [event_root(), event_do(run_id=None)]
        body = {"success":True,"result":{"run":{"status":"COMPLETED"},
                "events":{"events":events,"count":len(events)}}}
        calls = []
        def send(request, timeout):
            calls.append(json.loads(request.data))
            self.assertEqual(timeout, 12)
            return Response(json.dumps(body).encode())
        proof, summary = fetch_verified(STAMP, "a"*32, "not-a-real-token-"*3,
                                        transport=send, include_summary=True)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["dry"])
        self.assertEqual(proof, {})
        self.assertEqual(summary["raw_log_rows"], 2)
        self.assertEqual(summary["origin_observation"]["current_epoch_reason"],
                         "ACCEPTED_DISPATCH_LOG_WITHOUT_EXACT_RUN_ID")



class FixedWindowComparisonTests(unittest.TestCase):
    def fixtures(self):
        h = int(end_epoch(COMPARISON_EPOCH).timestamp()*1000)
        root = event_root(stamp_ms=h+70_000)
        reply = event_do(run_id=COMPARISON_RUN, stamp=COMPARISON_EPOCH, stamp_ms=h+71_000)
        return h, [root, reply]

    def test_same_cutoff_two_dry_reads_exact_run_only_as_diagnostic(self):
        h, rows = self.fixtures()
        calls = []
        def transport(req, timeout):
            body = json.loads(req.data)
            self.assertEqual(timeout, 12)
            self.assertTrue(body["dry"])
            calls.append(body)
            events = [] if len(calls) == 1 else rows
            return io.BytesIO(json.dumps({"success": True, "result": {
                "run": {"status": "COMPLETED", "timeframe": body["timeframe"]},
                "statistics": {"abr_level": 4 if not events else 1},
                "events": {"count": len(events), "events": events}}}).encode())
        result = compare_fixed_window("a"*32, "test-token-"*3, transport)
        self.assertEqual(len(calls), 2)
        a, b = calls
        self.assertEqual(a.pop("timeframe"), {"from": h-47*3600000, "to": h+600000})
        self.assertEqual(b.pop("timeframe"), {"from": h-3000000, "to": h+600000})
        self.assertEqual(a, b)
        self.assertFalse(result["release_authority"])
        self.assertFalse(result["wide"]["exact_expected_run"])
        self.assertTrue(result["one_hour"]["exact_expected_run"])
        self.assertEqual(result["wide"]["query_abr_level"], 4)
        self.assertEqual(result["one_hour"]["target_rows"], 2)
        self.assertNotIn(str(COMPARISON_RUN), json.dumps(result))
        self.assertNotIn(TRACE, json.dumps(result))

    def test_mismatched_echo_and_truncation_cannot_be_observed(self):
        _, rows = self.fixtures()
        calls = []
        def transport(req, timeout):
            body = json.loads(req.data)
            calls.append(body)
            return io.BytesIO(json.dumps({"success": True, "result": {
                "run": {"status": "COMPLETED", "timeframe": {"from": 0, "to": 1}},
                "events": {"count": 3 if len(calls)==1 else 2, "events": rows}}}).encode())
        r = compare_fixed_window("a"*32, "test-token-"*3, transport)
        self.assertEqual(r["wide"]["status"], "CLOUDFLARE_QUERY_TRUNCATED")
        self.assertEqual(r["one_hour"]["status"], "TIMEFRAME_ECHO_MISMATCH")
        self.assertFalse(r["release_authority"])

    def test_transport_failure_is_sanitized_and_other_query_still_runs(self):
        calls = []
        def transport(req, timeout):
            calls.append(req)
            if len(calls)==1:
                raise OSError("do not disclose exact credential or response")
            return io.BytesIO(b'{"success":true,"result":{"run":{"status":"COMPLETED"},"events":{"count":0,"events":[]}}}')
        result = compare_fixed_window("a"*32, "test-token-"*3, transport)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["wide"]["status"], "CLOUDFLARE_QUERY_TRANSPORT_FAILED")
        self.assertEqual(result["one_hour"]["timeframe_echo"], "NOT_RETURNED")
        self.assertFalse(result["one_hour"]["exact_expected_run"])
        self.assertFalse(result["release_authority"])



class EpochIncidentDiagnosticsTests(unittest.TestCase):
    def measure(self, events):
        from ops.cloudflare_source_provenance import summarize_epoch_incidents
        result = summarize_epoch_incidents(events, STAMP)
        self.assertFalse(result["release_authority"])
        self.assertEqual(result["queried_epochs"], 48)
        self.assertLessEqual(len(result["incident_epochs"]), 48)
        self.assertNotIn(TRACE, json.dumps(result))
        self.assertNotIn(str(RUN), json.dumps(result))
        return next((r for r in result["incident_epochs"] if r["epoch_utc"]=="2026-11-01T20:00:00Z"), None)
    def test_primary_failure_and_backup_access_lock(self):
        root=event_root(outcome="exception")
        failure=event_do(decision="GITHUB_RUNS_UNAVAILABLE")
        backup=event_root(trace="b"*32,cron="6 * * * *",outcome="exception",stamp_ms=EPOCH_MS+370000)
        locked=event_do(trace="b"*32,decision="DUPLICATE_EPOCH_LOCKED",stamp_ms=EPOCH_MS+370001)
        locked["source"]["duplicateLock"]={"state":"GITHUB_HTTP_ACCESS_BLOCKED"}
        result=self.measure([root,failure,backup,locked])
        self.assertEqual(result["primary"]["decision"],"GITHUB_RUNS_UNAVAILABLE")
        self.assertEqual(result["backup"]["lock_state"],"GITHUB_HTTP_ACCESS_BLOCKED")
        self.assertEqual(result["backup"]["status"],"FAILURE_OR_HOLD")
    def test_healthy_pair_is_omitted(self):
        backup=event_root(trace="b"*32,cron="6 * * * *",stamp_ms=EPOCH_MS+370000)
        locked=event_do(trace="b"*32,decision="DUPLICATE_EPOCH_LOCKED",stamp_ms=EPOCH_MS+370001)
        locked["source"]["duplicateLock"]={"state":"DISPATCH_ACCEPTED_NOT_SOURCE_PASS"}
        self.assertIsNone(self.measure([event_root(),event_do(),backup,locked]))
    def test_unobserved_and_mismatched_trace_are_not_green(self):
        self.assertEqual(self.measure([])["primary"]["status"],"NO_SCHEDULED_LOG")
        for changed in (event_do(version="b"*36),event_do(stamp="20261101T1900Z"),event_do(stamp_ms=EPOCH_MS+250000)):
            self.assertEqual(self.measure([event_root(),changed])["primary"]["status"],"MISSING_MATCHED_DECISION")
    def test_ambiguous_and_malformed_never_leak(self):
        self.assertEqual(self.measure([event_root(),event_root(),event_do()])["primary"]["status"],"MULTIPLE_ROOTS")
        bad=event_do(decision={"secret":"DUMMY_DO_NOT_LEAK"})
        bad["source"]["duplicateLock"]={"state":["DUMMY_DO_NOT_LEAK"]}
        row=self.measure([event_root(),bad])
        self.assertEqual(row["primary"]["status"],"UNKNOWN_DECISION")
        self.assertNotIn("DUMMY_DO_NOT_LEAK",json.dumps(row))
        from ops.cloudflare_source_provenance import summarize_invocations
        self.assertEqual(summarize_invocations([event_root(),bad],STAMP)["real_failures_or_holds"],1)
    def test_conflicting_decision_and_lock_hold(self):
        a=event_do(decision="DUPLICATE_EPOCH_LOCKED")
        b=event_do(decision="DUPLICATE_EPOCH_LOCKED")
        a["source"]["duplicateLock"]={"state":"RESERVED"}
        b["source"]["duplicateLock"]={"state":"GITHUB_HTTP_ACCESS_BLOCKED"}
        self.assertEqual(self.measure([event_root(),a,b])["primary"]["status"],"CONFLICTING_DECISIONS")

    def test_http_rejection_status_is_exact_and_bounded(self):
        for code in (403, 429, 422, 500, 503):
            d=event_do(decision="DISPATCH_REJECTED")
            d["source"]["httpStatus"]=code
            self.assertEqual(self.measure([event_root(outcome="exception"),d])["primary"]["http_status"],code)
        for code in (None,True,"503",99,600,{"secret":"DUMMY_DO_NOT_LEAK"}):
            d=event_do(decision="DISPATCH_REJECTED")
            d["source"]["httpStatus"]=code
            row=self.measure([event_root(outcome="exception"),d])
            self.assertIsNone(row["primary"]["http_status"])
            self.assertNotIn("DUMMY_DO_NOT_LEAK",json.dumps(row))
    def test_conflicting_http_status_does_not_invent_cause(self):
        a=event_do(decision="DISPATCH_REJECTED")
        b=event_do(decision="DISPATCH_REJECTED")
        a["source"]["httpStatus"]=403
        b["source"]["httpStatus"]=503
        row=self.measure([event_root(outcome="exception"),a,b])
        self.assertEqual(row["primary"]["status"],"CONFLICTING_DECISIONS")
        self.assertIsNone(row["primary"]["http_status"])
    def test_non_http_decision_cannot_publish_status(self):
        d=event_do(decision="DUPLICATE_EPOCH_LOCKED")
        d["source"]["httpStatus"]=503
        self.assertIsNone(self.measure([event_root(outcome="exception"),d])["primary"]["http_status"])


if __name__=="__main__":
    unittest.main()
