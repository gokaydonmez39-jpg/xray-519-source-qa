"""Receipt forensics: synthetic falsification + read-only pinned public evidence."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from warmup_receipt_audit import ReceiptInvalid,load_receipt,summarize,MAX_JSON

ROOT=Path(__file__).resolve().parents[1]
PINNED=(
    ROOT/"receipts/2026/10/31/20261031T0000Z-n519.json.gz",
    ROOT/"receipts/2026/10/31/20261031T0600Z-n519.json.gz",
)

def fixture():
    return {"schema":"XRAY_519_SOURCE_TECH_RESEARCH_V1",
        "identity_universe":519,"markets_selected":519,"technical_scanned":519,
        "technical_pass":518,"technical_warmup":1,"technical_failed":0,
        "orders_sent":0,"notifications_sent":0,"private_strategy_evaluated":0,
        "utc_closed_epoch_1h_ms":1793451599999,
        "results":[{"symbol":f"SYNTH{i:04d}USDT",
          "technical_data_quality":("WARMUP" if i==518 else "PASS"),
          "frame_quality":{"1h":"PASS",
                           "4h":("WARMUP_CLOSED_HISTORY_19_OF_40" if i==518 else "PASS"),
                           "1d":"PASS"},
          **({"reason":"CLOSED_HISTORY_19_OF_40"} if i==518 else {})}
          for i in range(519)]}

class ReceiptDiagnosis(unittest.TestCase):
    def setUp(self):
        self.doc=fixture()
    def test_one_warmup_with_explicit_frame(self):
        r=summarize(self.doc)
        self.assertEqual((r["technical_pass"],r["technical_warmup"],r["technical_failed"]),(518,1,0))
        self.assertEqual(r["frame_issue_distribution"]["4h:WARMUP_CLOSED_HISTORY_19_OF_40"],1)
        self.assertFalse(r["full_519_technical_quality"])
        self.assertEqual(r["source_scan_or_market_requests"],0)
        self.assertEqual(r["symbol_details_disclosed"],0)
    def test_mutated_header_false_green_rejected(self):
        self.doc["technical_pass"]=519
        self.doc["technical_warmup"]=0
        with self.assertRaisesRegex(ReceiptInvalid,"HEADER_ROWS_DISAGREE"):
            summarize(self.doc)
    def test_bad_row_false_green_rejected(self):
        self.doc["results"][-1]["technical_data_quality"]="PASS"
        with self.assertRaisesRegex(ReceiptInvalid,"FALSE_PASS"):
            summarize(self.doc)
    def test_failed_frame_not_called_warmup(self):
        self.doc["results"][-1]["frame_quality"]["4h"]="FAIL_GAP"
        with self.assertRaisesRegex(ReceiptInvalid,"WARMUP_FRAME_INCONSISTENT"):
            summarize(self.doc)
    def test_forged_full_quality_or_live_flag_rejected(self):
        for flag in ("full_technical_quality","live_source_acceptance"):
            with self.subTest(flag=flag):
                doc=copy.deepcopy(self.doc)
                doc[flag]=True
                with self.assertRaisesRegex(ReceiptInvalid,"FALSE_FULL_QUALITY_OR_LIVE_FLAG"):
                    summarize(doc)

    def test_duplicate_symbol_fails(self):
        self.doc["results"][-1]["symbol"]=self.doc["results"][0]["symbol"]
        with self.assertRaisesRegex(ReceiptInvalid,"DUPLICATE_OR_BAD_SYMBOL"):
            summarize(self.doc)
    def test_missing_frame_fails(self):
        del self.doc["results"][-1]["frame_quality"]["1d"]
        with self.assertRaisesRegex(ReceiptInvalid,"MISSING_FRAME_QUALITY"):
            summarize(self.doc)
    def test_nonzero_order_fails(self):
        self.doc["orders_sent"]=1
        with self.assertRaisesRegex(ReceiptInvalid,"NONZERO_TRADING_AUTHORITY"):
            summarize(self.doc)
    def test_518_scope_rejected(self):
        self.doc["identity_universe"]=518
        with self.assertRaisesRegex(ReceiptInvalid,"SCOPE_NOT_519"):
            summarize(self.doc)
    def test_bool_counter_rejected(self):
        self.doc["technical_pass"]=True
        with self.assertRaisesRegex(ReceiptInvalid,"INVALID_COUNTER_TYPE"):
            summarize(self.doc)
    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"receipts"/"2026"/"10"/"31"/"duplicate-n519.json.gz"
            p.parent.mkdir(parents=True)
            p.write_bytes(gzip.compress(b'{"schema":"A","schema":"B"}'))
            with self.assertRaisesRegex(ReceiptInvalid,"DUPLICATE_JSON_KEY"):
                load_receipt(p)
    def test_invalid_gzip_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"receipts"/"2026"/"10"/"31"/"broken-n519.json.gz"
            p.parent.mkdir(parents=True)
            p.write_bytes(b"not-gzip")
            with self.assertRaisesRegex(ReceiptInvalid,"INVALID_COMPRESSED_JSON"):
                load_receipt(p)
    def test_decompression_bomb_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"receipts"/"2026"/"10"/"31"/"bomb-n519.json.gz"
            p.parent.mkdir(parents=True)
            p.write_bytes(gzip.compress(b"x"*(MAX_JSON+1)))
            with self.assertRaisesRegex(ReceiptInvalid,"DECOMPRESSED_SIZE_LIMIT"):
                load_receipt(p)
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"receipts"/"2026"/"10"/"31"/"link-n519.json.gz"
            p.parent.mkdir(parents=True)
            target=p.parent/"target"
            target.write_bytes(gzip.compress(b"{}"))
            p.symlink_to(target)
            with self.assertRaisesRegex(ReceiptInvalid,"NOT_REGULAR_RECEIPT"):
                load_receipt(p)
    def test_existing_immutable_public_receipts_show_actual_reasons(self):
        for p in PINNED:
            with self.subTest(p=p.name):
                self.assertTrue(p.is_file(),"PINNED_PUBLIC_RECEIPT_MISSING")
                s=summarize(load_receipt(p))
                self.assertEqual(s["technical_pass"]+s["technical_warmup"]+s["technical_failed"],519)
                self.assertFalse(s["private_al_verified"])
                self.assertEqual(s["source_scan_or_market_requests"],0)
                # Aggregate evidence only; no market symbol list or private AL.
                print("PUBLIC_519_WARMUP_REASON_READBACK="+json.dumps(
                    {"receipt":p.name,**s},sort_keys=True))
if __name__=="__main__":
    unittest.main()
