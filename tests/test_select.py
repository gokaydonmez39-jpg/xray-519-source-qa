import gzip
import json
from pathlib import Path
import tempfile
import unittest
from test_source import Provider
import research_519 as core
from select_scope import next_size,valid_receipt
from publish_receipt import prepare

class SelectStageTests(unittest.TestCase):
    def test_stage_progression_and_bad_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            self.assertEqual(next_size(root),250)
            report=core.scan(Provider(250))
            report['http_provider_used']=True # synthetic fixture ONLY, not real source proof
            (root/'r.json').write_text(json.dumps(report))
            file250,_=prepare(root/'r.json',root,owner_repo='gokaydonmez39-jpg/xray-519-source-qa',run_id='1',run_attempt='1',mode='250')
            self.assertEqual(valid_receipt(root/file250),250)
            self.assertEqual(next_size(root),400)
            # Synthetic 400 fixture has same hour close and distinct filename.
            report=core.scan(Provider(400))
            report['http_provider_used']=True
            (root/'r.json').write_text(json.dumps(report))
            file400,_=prepare(root/'r.json',root,owner_repo='gokaydonmez39-jpg/xray-519-source-qa',run_id='2',run_attempt='1',mode='400')
            self.assertEqual(next_size(root),519)
            (root/file400).write_bytes(b'broken data')
            self.assertEqual(next_size(root),400)
    def test_bad_file_does_not_upgrade(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            f=root/'receipts/2026/10/30/20261030T1000Z-n400.json.gz'
            f.parent.mkdir(parents=True)
            f.write_bytes(gzip.compress(json.dumps({'public_runner':{'repository':'other','run_id':'1'},'markets_selected':400}).encode()))
            self.assertIsNone(valid_receipt(f))
            self.assertEqual(next_size(root),250)

if __name__=='__main__':unittest.main()
