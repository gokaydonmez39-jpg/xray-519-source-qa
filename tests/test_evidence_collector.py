"""Adversarial offline tests of actual gzip SHA/canonical and GitHub provenance.

Fixtures are synthetic. No GitHub network, Binance or private runner is invoked.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops import evidence_collector as c

EPOCH = datetime(2026, 11, 1, 13, tzinfo=timezone.utc)
STAMP = "20261101T1300Z"
RUN_ID = 555333


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def payload(stamp=STAMP, run_id=RUN_ID):
    epoch = datetime.strptime(stamp,"%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    receipt = {
        "schema": "XRAY_519_SOURCE_TECH_RESEARCH_V1",
        "utc_closed_epoch_1h_ms": int(epoch.timestamp()*1000)-1,
        "source_qa_success": True,
        "scope_stable": True,
        "epoch_stable": True,
        "complete_identity_scope": True,
        "status_accounting_ok": True,
        "http_provider_used": True,
        "run_kind": "RESEARCH_ONLY_NO_AL",
        "live_al_claim": False,
        "orders_sent": 0,
        "notifications_sent": 0,
        "private_strategy_evaluated": 0,
        "technical_scanned": 519,
        "identity_universe": 519,
        "receipt_key": "fixture-key-not-real",
        "scope_digest_sha256": "c"*64,
    }
    digest = hashlib.sha256(canonical(receipt)).hexdigest()
    wrapped = dict(receipt)
    wrapped["public_runner"] = {
        "repository": c.REPO, "run_id": str(run_id), "run_attempt":"1",
        "runner_type":"GITHUB_HOSTED_STANDARD_PUBLIC"}
    wrapped["source_receipt_sha256"] = digest
    bridge = {
        "schema":"XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1",
        "source_receipt_sha256":digest,
        "source_receipt_key":receipt["receipt_key"],
        "scope_digest_sha256":receipt["scope_digest_sha256"],
        "utc_closed_epoch_1h_ms":receipt["utc_closed_epoch_1h_ms"],
        "identity_universe":519,"raw_prefilter_symbols":2,
        "exported_symbols":2,"deferred_symbols":{},
        "orders_sent":0,"notifications_sent":0,
        "private_strategy_evaluated":0,"live_al_claim":False,
    }
    return wrapped,bridge


def run(event="schedule", stamp=STAMP, rid=RUN_ID):
    epoch = datetime.strptime(stamp,"%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
    return {
        "id": rid,"workflow_id":c.WORKFLOW_ID,"name":c.WORKFLOW_NAME,
        "run_attempt":1,"head_branch":"main",
        "head_repository":{"full_name":c.REPO},
        "event":event,"status":"completed","conclusion":"success",
        "created_at":(epoch+timedelta(minutes=9)).isoformat().replace("+00:00","Z")
    }


def write_pair(root, stamp=STAMP, receipt=None, bridge=None):
    a,b = payload(stamp)
    a=receipt if receipt is not None else a
    b=bridge if bridge is not None else b
    folder = datetime.strptime(stamp,"%Y%m%dT%H00Z").strftime("%Y/%m/%d")
    path1=root/f"receipts/{folder}/{stamp}-n519.json.gz"
    path2=root/f"bridges/{folder}/{stamp}-n519.json.gz"
    path1.parent.mkdir(parents=True,exist_ok=True)
    path2.parent.mkdir(parents=True,exist_ok=True)
    path1.write_bytes(gzip.compress(canonical(a),mtime=0))
    path2.write_bytes(gzip.compress(canonical(b),mtime=0))
    return path1,path2


def summary(_):
    return {"technical_pass":489,"technical_warmup":30,"technical_failed":0}


class PairReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    @patch.object(c,"summarize",side_effect=summary)
    def test_real_compressed_pair_sha_canonical_and_epoch(self, _):
        first,second=write_pair(self.root)
        result=c.read_pair(self.root, STAMP)
        self.assertEqual(result["run_id"],RUN_ID)
        self.assertEqual(result["receipt_sha256"],
                         hashlib.sha256(first.read_bytes()).hexdigest())
        self.assertEqual(result["bridge_sha256"],
                         hashlib.sha256(second.read_bytes()).hexdigest())
        self.assertEqual(result["scanned"],519)

    @patch.object(c,"summarize",side_effect=summary)
    def test_tampered_bridge_hash_rejected(self,_):
        receipt,bridge=payload()
        bridge["source_receipt_sha256"]="f"*64
        write_pair(self.root,receipt=receipt,bridge=bridge)
        with self.assertRaisesRegex(c.EvidenceError,"CANONICAL_PAIR_HASH_MISMATCH"):
            c.read_pair(self.root,STAMP)

    @patch.object(c,"summarize",side_effect=summary)
    def test_mismatched_epoch_rejected(self,_):
        a,b=payload()
        a["utc_closed_epoch_1h_ms"]+=3600000
        write_pair(self.root,receipt=a,bridge=b)
        with self.assertRaisesRegex(c.EvidenceError,"RECEIPT_SOURCE_NOT_VERIFIED"):
            c.read_pair(self.root,STAMP)

    def test_missing_bridge_rejected(self):
        path,bpath=write_pair(self.root)
        bpath.unlink()
        with self.assertRaisesRegex(c.EvidenceError,"MISSING_OR_UNSAFE_PAIR"):
            c.read_pair(self.root,STAMP)

    def test_symlink_pair_rejected(self):
        _,bpath=write_pair(self.root)
        bpath.unlink()
        bpath.symlink_to(self.root/"non-existent")
        with self.assertRaisesRegex(c.EvidenceError,"MISSING_OR_UNSAFE_PAIR"):
            c.read_pair(self.root,STAMP)

    def test_duplicate_json_keys_rejected_before_schema(self):
        p,b=write_pair(self.root)
        p.write_bytes(gzip.compress(b'{"schema":1,"schema":2}',mtime=0))
        with self.assertRaisesRegex(c.EvidenceError,"INVALID_GZIP_JSON"):
            c.read_pair(self.root,STAMP)

    @patch.object(c,"summarize",side_effect=summary)
    def test_nonzero_execution_in_bridge_fails(self,_):
        a,b=payload()
        b["orders_sent"]=1
        write_pair(self.root,receipt=a,bridge=b)
        with self.assertRaisesRegex(c.EvidenceError,"UNSAFE_BRIDGE"):
            c.read_pair(self.root,STAMP)

    @patch.object(c,"summarize",side_effect=summary)
    def test_fake_receipt_runner_id_rejected(self,_):
        a,b=payload()
        a["public_runner"]["repository"]="other-owner/private"
        write_pair(self.root,receipt=a,bridge=b)
        with self.assertRaisesRegex(c.EvidenceError,"INVALID_RUNNER_ID"):
            c.read_pair(self.root,STAMP)


class GithubProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.pair={"stamp":STAMP,"run_id":RUN_ID,
                   "run_attempt":1,"receipt_runner_id":str(RUN_ID)}

    def test_native_schedule_verified_but_not_full_system(self):
        x=c.verify_run(self.pair, run())
        self.assertEqual(x["event"],"schedule")
        self.assertEqual(x["trigger_provenance"],"github_native_schedule")
        self.assertTrue(x["trigger_independently_verified"])

    def test_cloudflare_or_manual_dispatch_remains_unverified(self):
        x=c.verify_run(self.pair,run("workflow_dispatch"))
        self.assertFalse(x["trigger_independently_verified"])
        self.assertEqual(x["trigger_provenance"],"unknown_external_origin")

    def test_push_source_kick_without_attestation_remains_unverified(self):
        x=c.verify_run(self.pair,run("push"))
        self.assertFalse(x["trigger_independently_verified"])

    def test_fake_workflow_success_does_not_override_provenance(self):
        for changes in ({"workflow_id":1234},{"name":"not-source"},
                        {"head_branch":"feature"},{"run_attempt":2},
                        {"conclusion":"failure"},{"id":2},
                        {"head_repository":{"full_name":"other/repo"}}):
            with self.subTest(changes=changes):
                forged=run()
                forged.update(changes)
                with self.assertRaisesRegex(c.EvidenceError,"GITHUB_RUN_PROVENANCE_MISMATCH"):
                    c.verify_run(self.pair,forged)

    def test_delayed_schedule_cannot_claim_old_epoch(self):
        bad=run()
        bad["created_at"]=(EPOCH+timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(c.EvidenceError,"RUN_TIME_OUTSIDE_EPOCH"):
            c.verify_run(self.pair,bad)

    def test_run_id_and_token_validation_fail_closed(self):
        for rid,token in ((0,"token"),(RUN_ID,""),(True,"token")):
            with self.subTest(rid=rid):
                with self.assertRaises(c.EvidenceError):
                    c.fetch_github_run(rid,token)


class LiveInputAdmissionTests(unittest.TestCase):
    def test_missing_47_hours_and_one_valid_source_uses_hold(self):
        good={**c.verify_run({
            "stamp":STAMP,"run_id":RUN_ID,"run_attempt":1,
            "receipt_runner_id":str(RUN_ID),
            "source_qa_success":True,"scanned":519,"pass":489,
            "warmup":30,"failed":0,"status_accounting_ok":True,
            "orders_sent":0,"notifications_sent":0,
            "private_strategy_evaluated":0,"live_al_claim":False,
            "receipt_sha256":"a"*64,"bridge_sha256":"b"*64,
        },run())}
        with patch.object(c,"read_pair",return_value={k:v for k,v in good.items() if k not in (
                "event","trigger_provenance","trigger_independently_verified",
                "conclusion","kind","pair_bytes_independently_verified",
                "pair_canonical_independently_verified")}) as reader:
            x=c.collect(".",STAMP,lambda rid:run())
        self.assertEqual(x["fully_qualified_source_hours"],1)
        self.assertFalse(x["conditional_public_gate_pass"])
        self.assertFalse(x["full_final_start"])
        self.assertEqual(len(x["diagnostics"]),0)
        self.assertEqual(reader.call_count,48)

    def test_48_synthetic_native_source_hours_conditional_only(self):
        def fake_pair(root,stamp):
            epoch=datetime.strptime(stamp,"%Y%m%dT%H00Z").replace(tzinfo=timezone.utc)
            rid=RUN_ID+int((epoch-EPOCH).total_seconds()//3600)
            return {"stamp":stamp,"run_id":rid,"run_attempt":1,
                "receipt_runner_id":str(rid),"source_qa_success":True,
                "scanned":519,"pass":489,"warmup":30,"failed":0,
                "status_accounting_ok":True,"orders_sent":0,
                "notifications_sent":0,"private_strategy_evaluated":0,
                "live_al_claim":False,"receipt_sha256":"a"*64,
                "bridge_sha256":"b"*64}
        def lookup(rid):
            stamp=(EPOCH+timedelta(hours=rid-RUN_ID)).strftime("%Y%m%dT%H00Z")
            return run("schedule",stamp,rid)
        with patch.object(c,"read_pair",side_effect=fake_pair):
            x=c.collect(".",STAMP,lookup)
        self.assertEqual(x["fully_qualified_source_hours"],48)
        self.assertTrue(x["conditional_public_gate_pass"])
        self.assertFalse(x["full_final_start"])
        self.assertFalse(x["cloudflare_log_verified"])

    def test_dispatch_origin_never_counts_as_trusted(self):
        def p(_,stamp):
            return {"stamp":stamp,"run_id":RUN_ID,
                    "run_attempt":1,"receipt_runner_id":str(RUN_ID)}
        with patch.object(c,"read_pair",side_effect=p):
            x=c.collect(".",STAMP,lambda rid:run("workflow_dispatch"))
        self.assertEqual(x["fully_qualified_source_hours"],0)
        self.assertIn("CLOUDFLARE_OR_MANUAL_ORIGIN_UNVERIFIED",
                      x["diagnostics"][STAMP])
        self.assertFalse(x["full_final_start"])

    def test_api_error_never_fills_gap(self):
        with patch.object(c,"read_pair",return_value={
                "stamp":STAMP,"run_id":RUN_ID,"run_attempt":1}):
            x=c.collect(".",STAMP,
                        lambda rid: (_ for _ in ()).throw(c.EvidenceError(
                            "GITHUB_RUN_READ_FAILED")))
        self.assertEqual(x["fully_qualified_source_hours"],0)
        self.assertIn("GITHUB_RUN_READ_FAILED",x["diagnostics"][STAMP])


if __name__=="__main__":
    unittest.main()
