import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from test_source import Provider
import research_519 as src
import publish_receipt as pub


class PublishReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.report=src.scan(Provider(2))
        # A synthetic flag is used ONLY to exercise publication-gate branches.
        # It does not attest a real HTTP execution or a GitHub hosted runner.
        self.report['http_provider_used']=True
        self.source=self.root/'source.json'
    def write(self,data=None):
        self.source.write_text(json.dumps(data if data is not None else self.report),encoding='utf-8')
    def run_publication(self, data=None, **kw):
        self.write(data)
        return pub.prepare(self.source,self.root,owner_repo=kw.get('repo','gokaydonmez39-jpg/xray-519-source-qa'),run_id='12345',run_attempt='1',mode=kw.get('mode','519'))
    def test_safe_compressed_evidence_and_duplicate_block(self):
        rel, sha=self.run_publication()
        self.assertTrue((self.root/rel).exists())
        self.assertEqual(len(sha),64)
        public=json.loads(gzip.decompress((self.root/rel).read_bytes()))
        self.assertEqual(public['public_runner']['run_id'],'12345')
        self.assertEqual(public['orders_sent'],0)
        with self.assertRaisesRegex(pub.ReceiptError,'DUPLICATE_RECEIPT_REFUSED'):
            self.run_publication()
    def test_wrong_repo_blocks(self):
        with self.assertRaisesRegex(pub.ReceiptError,'WRONG_REPOSITORY'):
            self.run_publication(repo='gokaydonmez39-jpg/kripto-radar')
    def test_synthetic_source_refused(self):
        d=copy.deepcopy(self.report);d['source_qa_success']=False
        with self.assertRaisesRegex(pub.ReceiptError,'SOURCE_EVIDENCE_GATE_FAILED'):
            self.run_publication(d)
    def test_unsafe_public_fields_blocked(self):
        d=copy.deepcopy(self.report);d['secret']='DO_NOT_PUBLISH'
        with self.assertRaisesRegex(pub.ReceiptError,'UNKNOWN_TOP_LEVEL_FIELDS_STOP_PUBLICATION'):
            self.run_publication(d)
    def test_buy_candidate_blocked(self):
        d=copy.deepcopy(self.report);d['results'][0]['buy_candidate']=True
        with self.assertRaisesRegex(pub.ReceiptError,'TRADE_CANDIDATE_FORBIDDEN'):
            self.run_publication(d)
    def test_full_universe_research_required(self):
        d=copy.deepcopy(self.report);d['identity_universe']=3
        with self.assertRaisesRegex(pub.ReceiptError,'SOURCE_EVIDENCE_GATE_FAILED'):
            self.run_publication(d)
    def test_nested_private_field_must_not_be_published(self):
        d=copy.deepcopy(self.report)
        d['results'][0]['technical']['private_key']='TOP_SECRET'
        with self.assertRaisesRegex(pub.ReceiptError,'UNKNOWN_NESTED_PUBLIC_FIELD'):
            self.run_publication(d)

    def test_unknown_result_field_blocked(self):
        d=copy.deepcopy(self.report);d['results'][0]['private_strategy']='x'
        with self.assertRaisesRegex(pub.ReceiptError,'UNKNOWN_RESULT_FIELD_STOP_PUBLICATION'):
            self.run_publication(d)
    def test_source_qa_failure_blocks(self):
        d=copy.deepcopy(self.report);d['technical_failed']=1
        with self.assertRaisesRegex(pub.ReceiptError,'SOURCE_EVIDENCE_GATE_FAILED'):
            self.run_publication(d)

if __name__=='__main__':unittest.main()
