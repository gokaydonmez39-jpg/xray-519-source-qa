"""No-network tests of public bridge deferred-reason logging contract."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from ops.bridge_reason_summary import read_gzip, summarize


class DeferredReasonSummaryTests(unittest.TestCase):
    def good(self):
        return {
            "transport_profile": "FULL_QUALITY_READY_V2",
            "identity_universe": 401,
            "transport_ready_count": 399,
            "transport_deferred_count": 2,
            "markets": {f"BASE{i}USDT": {} for i in range(399)},
            "deferred_symbols": {
                "AUSDT": "SOURCE_FRAME_NOT_PASS",
                "BUSDT": {"1h": "CLOSED_HISTORY_40_OF_100"},
            },
        }

    def test_reason_counts_and_fail_closed_flags(self):
        doc = self.good()
        output = summarize(doc)
        self.assertEqual(output["frames_deferred"], 2)
        self.assertEqual(output["frames_ready"], 399)
        self.assertEqual(
            output["reason_categories"],
            {"FRAME_FETCH_INCOMPLETE": 1, "SOURCE_FRAME_NOT_PASS": 1},
        )
        self.assertEqual(output["frame_issue_details"], {"1h:CLOSED_HISTORY_40_OF_100": 1})
        self.assertFalse(output["orders_permitted"])
        self.assertFalse(output["notifications_permitted"])
        self.assertFalse(output["full_final_start"])
        self.assertNotIn("AUSDT", json.dumps(output))

    def test_invalid_counts_rejected(self):
        doc = self.good()
        doc["transport_deferred_count"] = 1
        with self.assertRaises(ValueError):
            summarize(doc)

    def test_overlap_rejected(self):
        doc = self.good()
        doc["deferred_symbols"]["BASE0USDT"] = "SOURCE_FRAME_NOT_PASS"
        doc["transport_deferred_count"] = 3
        doc["identity_universe"] = 402
        with self.assertRaises(ValueError):
            summarize(doc)

    def test_bad_reasons_rejected(self):
        doc = self.good()
        doc["deferred_symbols"]["AUSDT"] = {"1h": ""}
        with self.assertRaises(ValueError):
            summarize(doc)

    def test_actual_gzip_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                json.dump(self.good(), stream)
            result = read_gzip(path)
            self.assertEqual(result["frames_ready"], 399)


if __name__ == "__main__":
    unittest.main()
