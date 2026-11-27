"""Synthetic isolated bare Git and process-group regression; never contacts a remote service."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import test_publish_git as fixture

ROOT=Path(__file__).resolve().parents[1]

class PublisherTimeoutTests(unittest.TestCase):
    setUp=fixture.GitPublishTests.setUp
    git=fixture.GitPublishTests.git
    advance=fixture.GitPublishTests.advance
    module=fixture.GitPublishTests.module

    def run_publisher(self, mod, shim, **kw):
        before=Path.cwd()
        try:
            os.chdir(self.work)
            with patch.object(mod,'git',side_effect=shim):
                mod.publish(self.base,'main',[self.path,self.bridge],**kw)
        finally:
            os.chdir(before)

    def remote_pair(self):
        return all(self.git(self.remote,'show','main:'+p).encode()==(self.work/p).read_bytes() for p in (self.path,self.bridge))

    def test_baseline_push_timeout_stops_without_retry(self):
        spec=importlib.util.spec_from_file_location('original',ROOT/'publish_git.original.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        real=mod.git;pushes=[]
        def shim(*a,**kw):
            if a[0]=='push':
                pushes.append(a)
                raise subprocess.TimeoutExpired('git',30)
            return real(*a,**kw)
        with self.assertRaises(subprocess.TimeoutExpired):self.run_publisher(mod,shim)
        self.assertEqual(len(pushes),1)
        self.assertEqual(self.git(self.remote,'rev-parse','main').strip(),self.base)

    def test_push_timeout_before_acceptance_retries(self):
        mod=self.module();real=mod.git;pushes=[]
        def shim(*a,**kw):
            if a[0]=='push':
                pushes.append(a)
                if len(pushes)==1:raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:push')
            return real(*a,**kw)
        self.run_publisher(mod,shim)
        self.assertEqual(len(pushes),2);self.assertTrue(self.remote_pair())
        self.assertTrue(all('--force' not in x for x in pushes))

    def test_lost_ack_remote_already_accepted_no_duplicate(self):
        mod=self.module();real=mod.git;pushes=[];commits=[]
        def shim(*a,**kw):
            if a[0]=='push':
                pushes.append(a);r=real(*a,**kw);self.assertEqual(r.returncode,0)
                commits.append(self.git(self.remote,'rev-parse','main').strip())
                raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:push')
            return real(*a,**kw)
        self.run_publisher(mod,shim)
        self.assertEqual(len(pushes),1);self.assertTrue(self.remote_pair())
        self.assertEqual(self.git(self.remote,'rev-parse','main').strip(),commits[0])
        self.assertEqual(self.git(self.remote,'rev-list','--count','main').strip(),'2')

    def test_fetch_timeout_then_success(self):
        mod=self.module();real=mod.git;fetches=[]
        def shim(*a,**kw):
            if a[0]=='fetch':
                fetches.append(a)
                if len(fetches)==1:raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:fetch')
            return real(*a,**kw)
        self.run_publisher(mod,shim);self.assertEqual(len(fetches),3);self.assertTrue(self.remote_pair())

    def test_readback_timeout_rechecks_exact_pair(self):
        mod=self.module();real=mod.git;fetches=[];pushes=[]
        def shim(*a,**kw):
            if a[0]=='push':pushes.append(a)
            if a[0]=='fetch':
                fetches.append(a)
                if len(fetches)==2:raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:fetch')
            return real(*a,**kw)
        self.run_publisher(mod,shim);self.assertEqual(len(pushes),1);self.assertTrue(self.remote_pair())

    def test_timeout_exhaustion_stops_without_remote_change(self):
        mod=self.module();real=mod.git;pushes=[]
        def shim(*a,**kw):
            if a[0]=='push':
                pushes.append(a);raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:push')
            return real(*a,**kw)
        with self.assertRaisesRegex(mod.PublishBlocked,'REMOTE_PUSH_RETRY_EXHAUSTED'):self.run_publisher(mod,shim)
        self.assertEqual(len(pushes),3);self.assertEqual(self.git(self.remote,'rev-parse','main').strip(),self.base)

    def test_timeout_with_conflicting_remote_never_overwrites(self):
        mod=self.module();real=mod.git;pushes=[]
        def shim(*a,**kw):
            if a[0]=='push':
                pushes.append(a);self.advance(self.path,b'conflict');raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:push')
            return real(*a,**kw)
        with self.assertRaisesRegex(mod.PublishBlocked,'EPOCH_PATH_ALREADY_EXISTS'):self.run_publisher(mod,shim)
        self.assertEqual(len(pushes),1);self.assertEqual(self.git(self.remote,'show','main:'+self.path),'conflict')

    def test_timeout_with_changed_execution_source_blocks(self):
        mod=self.module();real=mod.git;pushes=[]
        def shim(*a,**kw):
            if a[0]=='push':
                pushes.append(a);self.advance('research_519.py',b'v2');raise mod.GitOperationTimeout('GIT_OPERATION_TIMEOUT:push')
            return real(*a,**kw)
        with self.assertRaisesRegex(mod.PublishBlocked,'SOURCE_CHANGED_DURING_SCAN'):self.run_publisher(mod,shim)
        self.assertEqual(len(pushes),1);self.assertNotIn(self.path,self.git(self.remote,'ls-tree','-r','--name-only','main'))

class DeadlineAndProcessTests(unittest.TestCase):
    module=fixture.GitPublishTests.module
    def test_expired_budget_blocks_before_spawn(self):
        mod=self.module();tok=mod._deadline.set(time.monotonic()-1)
        try:
            with patch.object(mod.subprocess,'Popen') as pop:
                with self.assertRaisesRegex(mod.PublishBlocked,'PUBLISH_DEADLINE_EXPIRED'):mod.git('push','origin','x')
                pop.assert_not_called()
        finally:mod._deadline.reset(tok)

    def test_budget_invalid_inputs(self):
        mod=self.module()
        for invalid in (0,-1,151,float('nan'),float('inf'),True):
            with self.subTest(invalid=invalid),self.assertRaisesRegex(mod.PublishBlocked,'INVALID_PUBLISH_BUDGET'):mod.publish('x','main',[],budget_seconds=invalid)
        for invalid in (0,4,True):
            with self.subTest(attempts=invalid),self.assertRaisesRegex(mod.PublishBlocked,'INVALID_RETRY_BUDGET'):mod.publish('x','main',[],attempts=invalid)

    def test_current_epoch_deadline_boundary(self):
        mod=self.module();epoch=datetime(2030,1,1,12,tzinfo=timezone.utc).timestamp();p='receipts/2030/01/01/20300101T1200Z-n531.json.gz'
        self.assertEqual(mod.current_epoch_budget([p],now=epoch),150)
        self.assertEqual(mod.current_epoch_budget([p],now=epoch+685),1)
        for age in (-1,686,690,3600):
            with self.subTest(age=age),self.assertRaises(mod.PublishBlocked):mod.current_epoch_budget([p],now=epoch+age)
        with self.assertRaisesRegex(mod.PublishBlocked,'LIVE_RECEIPT_PATH_EPOCH_MISMATCH'):mod.current_epoch_budget([p.replace('/01/01/','/01/02/')],now=epoch)

    def test_group_timeout_kills_delayed_child_and_sanitizes(self):
        mod=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);sentinel=d/'child_was_alive';fake=d/'git';ready=d/'child_spawned'
            child="import time; from pathlib import Path; time.sleep(3.0); Path("+repr(str(sentinel))+").write_text('alive')"
            fake.write_text('#!'+sys.executable+'\nimport subprocess,time,sys\nfrom pathlib import Path\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'])\nPath('+repr(str(ready))+').write_text("spawned")\nprint("SIMULATED_CREDENTIAL_DO_NOT_PRINT",file=sys.stderr,flush=True)\ntime.sleep(20)\n')
            fake.chmod(0o700);env=dict(os.environ,PATH=str(d)+os.pathsep+os.environ['PATH'])
            with patch.object(mod,'_GIT_TIMEOUT_SECONDS',1.5):
                t=time.monotonic()
                with self.assertRaisesRegex(mod.GitOperationTimeout,'^GIT_OPERATION_TIMEOUT:push$') as ctx:mod.git('push','origin','dummy',env=env)
                self.assertLess(time.monotonic()-t,6);self.assertNotIn('SIMULATED_CREDENTIAL',str(ctx.exception))
            self.assertTrue(ready.exists());time.sleep(3.2);self.assertFalse(sentinel.exists())

if __name__=='__main__':unittest.main()
