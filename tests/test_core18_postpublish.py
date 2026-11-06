"""Isolated negative and positive tests for post-remote-readback CORE18 gate."""
from __future__ import annotations

import copy
import contextlib
import io
import tempfile
import gzip
import hashlib
import json
import unittest
from pathlib import Path

from ops.core18_postpublish import main, verify_pair_then_project
from test_core18_compact_log import raw, sample

RUN = "42219779437"
ATTEMPT = 1


def fixture():
    source = sample()
    src = raw(source)
    digest = hashlib.sha256(src).hexdigest()
    pub = copy.deepcopy(source)
    pub["source_receipt_sha256"] = digest
    pub["public_runner"] = {
        "repository": "gokaydonmez39-jpg/xray-519-source-qa",
        "run_id": RUN,
        "run_attempt": str(ATTEMPT),
        "runner_type": "GITHUB_HOSTED_STANDARD_PUBLIC",
    }
    names = [r["symbol"] for r in source["results"]]
    bridge = {
        "schema": "XRAY_PUBLIC_PRIVATE_CLOSED_BAR_BRIDGE_V1",
        "transport_profile": "FULL_QUALITY_READY_V2",
        "source_receipt_sha256": digest,
        "source_receipt_key": source["receipt_key"],
        "scope_digest_sha256": source["scope_digest_sha256"],
        "identity_universe": 518,
        "utc_closed_epoch_1h_ms": source["utc_closed_epoch_1h_ms"],
        "markets": {name: {} for name in names},
        "deferred_symbols": {},
        "exported_symbols": 518,
        "transport_ready_count": 518,
        "transport_deferred_count": 0,
        "orders_sent": 0,
        "notifications_sent": 0,
        "live_al_claim": False,
    }
    return src, pub, bridge


def gz(obj):
    return gzip.compress(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":"), allow_nan=False).encode(), mtime=0)


def call(src, pub, bridge, *, run=RUN, attempt=ATTEMPT):
    return verify_pair_then_project(src, gz(pub), gz(bridge),
                                    runner_id=run, run_attempt=attempt)


class PostPublishedSourceGateTests(unittest.TestCase):
    def test_valid_three_way_sha_but_never_remote_or_trade_claim(self):
        src, pub, bridge = fixture()
        result = call(src, pub, bridge)
        self.assertEqual(result["status"], "PASS_18OF18_SOURCE_INPUTS_ONLY")
        self.assertEqual(result["record_count"], 18)
        self.assertEqual(result["source_sha256"], hashlib.sha256(src).hexdigest())
        self.assertTrue(result["postpublish_pair_sha_verified"])
        self.assertFalse(result["remote_readback_inferred"])
        self.assertEqual(result["orders_sent"], 0)
        self.assertEqual(result["notifications_sent"], 0)
        self.assertFalse(result["full_final_start"])

    def test_wrong_published_sha_fails(self):
        src, pub, bridge = fixture()
        pub["source_receipt_sha256"] = "0" * 64
        self.assertEqual(call(src, pub, bridge)["reason"],
                         "SOURCE_PUBLISHED_BRIDGE_SHA_MISMATCH")

    def test_wrong_bridge_sha_fails(self):
        src, pub, bridge = fixture()
        bridge["source_receipt_sha256"] = "a" * 64
        self.assertEqual(call(src, pub, bridge)["reason"],
                         "SOURCE_PUBLISHED_BRIDGE_SHA_MISMATCH")

    def test_wrong_original_body_fails(self):
        src, pub, bridge = fixture()
        pub["source_qa_success"] = False
        self.assertEqual(call(src, pub, bridge)["reason"],
                         "PUBLISHED_SOURCE_CONTENT_MISMATCH")

    def test_forged_run_id_fails(self):
        src, pub, bridge = fixture()
        self.assertEqual(call(src, pub, bridge, run="42219779438")["reason"],
                         "PUBLISH_RUNNER_PROVENANCE_MISMATCH")

    def test_runner_attempt_forgery_fails(self):
        src, pub, bridge = fixture()
        self.assertEqual(call(src, pub, bridge, attempt=2)["reason"],
                         "PUBLISH_RUNNER_PROVENANCE_MISMATCH")

    def test_broken_symbol_accounting_fails(self):
        src, pub, bridge = fixture()
        bridge["markets"].pop("BTCUSDT")
        self.assertEqual(call(src, pub, bridge)["reason"],
                         "BRIDGE_IDENTITY_ACCOUNTING_INVALID")

    def test_deferred_market_cannot_fake_complete_18(self):
        src, pub, bridge = fixture()
        bridge["deferred_symbols"]["BTCUSDT"] = "SOURCE_FRAME_NOT_PASS"
        bridge["markets"].pop("BTCUSDT")
        bridge["exported_symbols"] = 517
        bridge["transport_ready_count"] = 517
        bridge["transport_deferred_count"] = 1
        # Invalid cross-layer claim: source rows still say BTC is PASS.
        result = call(src, pub, bridge)
        self.assertEqual(result["status"], "HOLD")

    def test_stale_core_market_fails_without_invented_card(self):
        src, pub, bridge = fixture()
        # A real source mutation must also use its real updated digest.
        source = json.loads(src)
        source["results"][0]["liquidity_snapshot"]["ticker_within_120s"] = False
        updated = raw(source)
        digest = hashlib.sha256(updated).hexdigest()
        pub["results"] = source["results"]
        pub["source_receipt_sha256"] = digest
        bridge["source_receipt_sha256"] = digest
        result = call(updated, pub, bridge)
        self.assertEqual(result["reason"], "CORE18_TICKER_NOT_FRESH")
        self.assertEqual(result["records"], [])

    def test_malformed_gzip_fails(self):
        src, pub, bridge = fixture()
        result = verify_pair_then_project(src, b"not-gzip", gz(bridge),
                                          runner_id=RUN, run_attempt=ATTEMPT)
        self.assertEqual(result["reason"], "SOURCE_PAIR_PARSE_OR_GZIP_HOLD")

    def test_invalid_runner_identity_fails(self):
        src, pub, bridge = fixture()
        self.assertEqual(call(src, pub, bridge, run="0001")["reason"],
                         "RUNNER_IDENTITY_INVALID")

    def _run_cli(self, src, pub, bridge):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "source.json").write_bytes(src)
            (base / "receipt.gz").write_bytes(gz(pub))
            (base / "bridge.gz").write_bytes(gz(bridge))
            output = io.StringIO()
            argv = [
                "--source", str(base / "source.json"),
                "--receipt", str(base / "receipt.gz"),
                "--bridge", str(base / "bridge.gz"),
                "--runner-id", RUN, "--run-attempt", str(ATTEMPT),
            ]
            with contextlib.redirect_stdout(output):
                code = main(argv)
            entries = [line for line in output.getvalue().splitlines()
                       if line.startswith("CORE18_PUBLIC_INPUTS_V1=")]
            self.assertEqual(len(entries), 1)
            return code, json.loads(entries[0].split("=", 1)[1])

    def test_real_deferred_bridge_holds_core18_but_preserves_source_job(self):
        src, pub, bridge = fixture()
        bridge["deferred_symbols"]["BTCUSDT"] = "SOURCE_FRAME_NOT_PASS"
        bridge["markets"].pop("BTCUSDT")
        bridge["exported_symbols"] = 517
        bridge["transport_ready_count"] = 517
        bridge["transport_deferred_count"] = 1
        code, projection = self._run_cli(src, pub, bridge)
        self.assertEqual(code, 0)
        self.assertEqual(projection["status"], "HOLD")
        self.assertEqual(projection["reason"], "CORE18_BRIDGE_DEFERRED")
        self.assertEqual(projection["records"], [])

    def test_corrupt_published_sha_fails_source_job_closed(self):
        src, pub, bridge = fixture()
        pub["source_receipt_sha256"] = "0" * 64
        code, projection = self._run_cli(src, pub, bridge)
        self.assertEqual(code, 2)
        self.assertEqual(projection["status"], "HOLD")
        self.assertEqual(projection["reason"],
                         "SOURCE_PUBLISHED_BRIDGE_SHA_MISMATCH")

    def test_only_after_published_pair_remote_verification(self):
        code = Path("research_519.py").read_text()
        wf = Path(".github/workflows/hourly-519-public-source.yml").read_text()
        self.assertNotIn("CORE18_PUBLIC_INPUTS_V1=", code)
        self.assertIn("python3 -m ops.core18_postpublish", wf)
        self.assertLess(wf.index("python3 publish_git.py"),
                        wf.index("python3 -m ops.core18_postpublish"))
        self.assertLess(wf.index("python3 verify_remote_pair.py"),
                        wf.index("python3 -m ops.core18_postpublish"))


if __name__ == "__main__":
    unittest.main()
