import gzip
import json
import tempfile
import unittest
from pathlib import Path
from test_source import Provider, NOW
import research_519 as core
from verify_remote_pair import audit


class RemotePairTests(unittest.TestCase):
    def record(self,root:Path,run:int,hour:int):
        p=Provider(519)
        p.hour=hour
        d=core.scan(p)
        d['http_provider_used']=True
        d['live_source_acceptance']=True
        d['public_runner']={'repository':'gokaydonmez39-jpg/xray-519-source-qa','run_id':str(run),'run_attempt':'1'}
        f=root/'receipts'/f'2026/10/30/{int(hour)}-{run}-n519.json.gz'
        f.parent.mkdir(parents=True,exist_ok=True)
        f.write_bytes(gzip.compress(json.dumps(d).encode()))
        return f
    def test_requires_two_epochs(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            self.record(root,1,NOW)
            self.assertEqual(audit(root)[1],'NEED_TWO_DISTINCT_519_HOURLY_RECEIPTS')
    def test_2_fake_structure_passes_only_structure_gate(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            self.record(root,1,NOW)
            self.record(root,2,NOW+core.HOUR)
            good,label,_=audit(root)
            self.assertTrue(good)
            self.assertEqual(label,'TWO_EPOCH_519_SOURCE_QUALITY_PASS')
            # These are deliberately mock-derived flags; never real remote acceptance.
    def test_same_run_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            self.record(root,1,NOW)
            self.record(root,1,NOW+core.HOUR)
            self.assertEqual(audit(root)[1],'SAME_GITHUB_RUN_NOT_INDEPENDENT')
    def test_nonconsecutive_hours_block(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            self.record(root,1,NOW)
            self.record(root,2,NOW+2*core.HOUR)
            good,label,issues=audit(root)
            self.assertFalse(good)
            self.assertEqual(label,'TWO_EPOCH_HOLD')
            self.assertIn('NOT_CONSECUTIVE_DISTINCT_HOURS',issues)

if __name__=='__main__':unittest.main()
