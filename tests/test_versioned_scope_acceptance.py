"""Synthetic offline negative and happy path checks. No network or trading."""
import copy
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ops import versioned_scope_acceptance as a

STAMP = "20261103T1000Z"


def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",", ":"),ensure_ascii=False,allow_nan=False).encode()


def sample(n=518, stamp=STAMP, run_id=12345):
    epoch = a._epoch(stamp)
    close_ms = int(epoch.timestamp()*1000)-1
    rows = [{"symbol":f"X{i:04d}USDT", "identity":"SPOT_USDT_TRADING",
             "research_only":True,"buy_candidate":False,"orders_sent":0,
             "notifications_sent":0,"technical_data_quality": "PASS" if i < n-26 else "WARMUP"} for i in range(n)]
    receipt = {"schema":"XRAY_519_SOURCE_TECH_RESEARCH_V1","source":"BINANCE_PUBLIC_SPOT_REST",
               "run_kind":"RESEARCH_ONLY_NO_AL","http_provider_used":True,"source_qa_success":True,
               "scope_stable":True,"epoch_stable":True,"complete_identity_scope":True,
               "status_accounting_ok":True,"identity_universe":n,"markets_selected":n,
               "technical_scanned":n,"technical_frames_requested":3*n,
               "technical_pass":n-26,"technical_warmup":26,"technical_failed":0,
               "full_technical_quality":False,"live_source_acceptance":False,
               "results":rows,"scope_digest_sha256":"a"*64,
               "utc_closed_epoch_1h_ms":close_ms,
               "receipt_key":f"XRAY_519_SOURCE_TECH_RESEARCH_V1|{close_ms}|{'a'*64}|{n}",
               "orders_sent":0,"notifications_sent":0,"private_strategy_evaluated":0,
               "live_al_claim":False,"native_wss_running":False,"phone_delivery_ack":False}
    digest = hashlib.sha256(canon(receipt)).hexdigest()
    wrapped = {**receipt,"public_runner":{"repository":a.REPO,"run_id":str(run_id),"run_attempt":"1"},
               "source_receipt_sha256":digest}
    bridge = {"schema":"XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1",
              "source_receipt_sha256":digest,"source_receipt_key":receipt["receipt_key"],
              "scope_digest_sha256":receipt["scope_digest_sha256"],
              "utc_closed_epoch_1h_ms":close_ms,"identity_universe":n,
              "raw_prefilter_symbols":2,"exported_symbols":2,"deferred_symbols":{},
              "orders_sent":0,"notifications_sent":0,"private_strategy_evaluated":0,
              "live_al_claim":False}
    return wrapped,bridge


def write(root, n=518, stamp=STAMP, run_id=12345, pair=None):
    receipt,bridge = pair or sample(n,stamp,run_id)
    path = a._epoch(stamp).strftime("%Y/%m/%d")
    rp=root/f"receipts/{path}/{stamp}-n{n}.json.gz"
    bp=root/f"bridges/{path}/{stamp}-n{n}.json.gz"
    rp.parent.mkdir(parents=True,exist_ok=True)
    bp.parent.mkdir(parents=True,exist_ok=True)
    rp.write_bytes(gzip.compress(canon(receipt),mtime=0))
    bp.write_bytes(gzip.compress(canon(bridge),mtime=0))
    return rp,bp


def run(pair, event="schedule"):
    return {"id":pair["run_id"],"workflow_id":a.WORKFLOW_ID,"name":a.WORKFLOW_NAME,
            "run_attempt":pair["run_attempt"],"head_branch":"main",
            "head_repository":{"full_name":a.REPO},"status":"completed","conclusion":"success",
            "event":event,"created_at":(a._epoch(pair["stamp"])+timedelta(minutes=5)).isoformat()}


class ScopeReaderTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)

    def test_valid_drifted_518_with_26_warmups_is_observation_not_final(self):
        write(self.root)
        r=a.read_pair(self.root,STAMP)
        self.assertEqual((r["scope_count"],r["technical_pass"],r["technical_warmup"]),(518,492,26))
        self.assertFalse(r["full_technical_quality"])

    def test_legacy_519_does_not_need_mutation(self):
        write(self.root,n=519)
        self.assertEqual(a.read_pair(self.root,STAMP)["scope_count"],519)

    def test_mixed_scope_conflict_fails_closed(self):
        write(self.root,n=518)
        write(self.root,n=519)
        with self.assertRaisesRegex(a.EvidenceHold,"CONFLICTING"):
            a.read_pair(self.root,STAMP)

    def test_missing_bridge_fails_closed(self):
        _,bridge=write(self.root)
        bridge.unlink()
        with self.assertRaisesRegex(a.EvidenceHold,"CONFLICTING"):
            a.read_pair(self.root,STAMP)

    def test_tampered_bridge_hash_fails_closed(self):
        r,b=sample()
        b["source_receipt_sha256"]="0"*64
        write(self.root,pair=(r,b))
        with self.assertRaisesRegex(a.EvidenceHold,"CANONICAL_PAIR_HASH_MISMATCH"):
            a.read_pair(self.root,STAMP)

    def test_full_scope_flags_cannot_hide_warmup(self):
        r,b=sample()
        r["full_technical_quality"]=True
        write(self.root,pair=(r,b))
        with self.assertRaisesRegex(a.EvidenceHold,"FULL_SCOPE_ACCOUNTING_INVALID"):
            a.read_pair(self.root,STAMP)

    def test_duplicate_symbol_rejected(self):
        r,b=sample()
        r["results"][1]["symbol"]=r["results"][0]["symbol"]
        write(self.root,pair=(r,b))
        with self.assertRaisesRegex(a.EvidenceHold,"INVALID_MARKET_ROW"):
            a.read_pair(self.root,STAMP)

    def test_live_order_in_bridge_rejected(self):
        r,b=sample()
        b["orders_sent"]=1
        write(self.root,pair=(r,b))
        with self.assertRaisesRegex(a.EvidenceHold,"EXECUTION_OR_ALERT_FORBIDDEN"):
            a.read_pair(self.root,STAMP)

    def test_unauthorized_pilot_scope_rejected(self):
        write(self.root,n=400)
        with self.assertRaisesRegex(a.EvidenceHold,"SCOPE_NOT_FULL"):
            a.read_pair(self.root,STAMP)

    def test_unverifiable_dispatch_origin_not_trusted(self):
        write(self.root)
        pair=a.read_pair(self.root,STAMP)
        self.assertIsNone(a.verify_origin(pair,run(pair,"workflow_dispatch")))
        self.assertEqual(a.verify_origin(pair,run(pair,"workflow_dispatch"),pair["run_id"]),
                         "cloudflare_cron_trace_exact_run")
        forged=run(pair)
        forged["id"]=5
        with self.assertRaisesRegex(a.EvidenceHold,"RUN_METADATA_NOT_VERIFIED"):
            a.verify_origin(pair,forged)

    def test_window_missing_epoch_keeps_hold(self):
        write(self.root)
        report=a.collect_shadow(self.root,STAMP,lambda rid:run({"run_id":rid,"run_attempt":1,"stamp":STAMP}))
        self.assertEqual(report["paired_authenticated_hours"],1)
        self.assertFalse(report["shadow_complete_48h"])
        self.assertFalse(report["full_final_start"])

    def test_48_consecutive_epochs_with_identity_transition_is_shadow_only(self):
        end=a._epoch(STAMP)
        records={}
        for h in range(48):
            stamp=(end-timedelta(hours=47-h)).strftime("%Y%m%dT%H00Z")
            scope=519 if h < 24 else 518
            run_id=20000+h
            write(self.root,n=scope,stamp=stamp,run_id=run_id)
            records[run_id]=run({"run_id":run_id,"run_attempt":1,"stamp":stamp})
        output=a.collect_shadow(self.root,STAMP,lambda rid:records[rid])
        self.assertEqual(output["paired_authenticated_hours"],48)
        self.assertEqual(output["trusted_origin_hours"],48)
        self.assertTrue(output["shadow_complete_48h"])
        self.assertEqual(len(output["scope_versions"]),2)
        self.assertEqual(output["warmup_present_hours"],48)
        self.assertFalse(output["full_final_start"])
        self.assertFalse(output["alert_release"])

    def test_duplicate_run_id_across_epochs_is_not_counted_twice(self):
        end=a._epoch(STAMP)
        previous=(end-timedelta(hours=1)).strftime("%Y%m%dT%H00Z")
        write(self.root,n=518,stamp=previous,run_id=12345)
        write(self.root,n=518,stamp=STAMP,run_id=12345)
        output=a.collect_shadow(self.root,STAMP,lambda rid:run({"run_id":rid,"run_attempt":1,"stamp":previous}))
        self.assertEqual(output["paired_authenticated_hours"],1)
        self.assertEqual(output["diagnostics"][STAMP],"RUN_REUSED_IN_WINDOW")
        self.assertFalse(output["shadow_complete_48h"])

    def test_single_518_hour_explicitly_reports_not_final(self):
        write(self.root)
        report=a.collect_shadow(self.root,STAMP,lambda rid:run({"run_id":rid,"run_attempt":1,"stamp":STAMP}))
        self.assertEqual(report["trusted_origin_hours"],1)
        self.assertEqual(report["scope_versions"][0]["scope_version"],"518:"+"a"*64)
        self.assertTrue(report["legacy_519_contract_unchanged"])
        self.assertFalse(report["alert_release"])


if __name__=="__main__":
    unittest.main()
