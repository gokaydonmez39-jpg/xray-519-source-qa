"""Real local file:// shallow, promisor, sparse checkout tests; no network or real epoch publication."""
import hashlib, os, subprocess, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
PUBLISHER=Path(__file__).with_name('publish_git.py')

def run(cwd,*args,check=True,env=None):
    return subprocess.run(args,cwd=cwd,check=check,capture_output=True,text=True,timeout=30,env=env)

def git(cwd,*args,check=True):return run(cwd,'git',*args,check=check).stdout.strip()

class RealCheckoutTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.remote=self.root/'remote.git';self.peer=self.root/'peer';self.work=self.root/'work'
        git(self.root,'init','--bare','--initial-branch=main',str(self.remote))
        git(self.remote,'config','uploadpack.allowFilter','true');git(self.remote,'config','uploadpack.allowAnySHA1InWant','true')
        git(self.root,'clone',str(self.remote),str(self.peer));self.identity(self.peer)
        self.write(self.peer,'research_519.py',b'# synthetic source only\n')
        self.write(self.peer,'bridges/2030/01/01/20300101T0000Z-n531.json.gz',os.urandom(256*1024))
        self.oldpath='bridges/2030/01/01/20300101T0000Z-n531.json.gz'
        git(self.peer,'add','.');git(self.peer,'commit','-m','fixture base');git(self.peer,'push','origin','main')
        self.base=git(self.peer,'rev-parse','HEAD');self.oldblob=git(self.peer,'rev-parse','HEAD:'+self.oldpath)
        git(self.root,'clone','--depth=1','--filter=blob:none','--no-checkout',self.remote.as_uri(),str(self.work))
        self.identity(self.work);git(self.work,'sparse-checkout','init','--no-cone');git(self.work,'sparse-checkout','set','/*','!/*/','/receipts/');git(self.work,'checkout','main')
        self.assertEqual(git(self.work,'rev-parse','--is-shallow-repository'),'true')
        self.assertEqual(git(self.work,'config','--bool','--get','remote.origin.promisor'),'true')
        self.assertEqual(git(self.work,'config','--get','remote.origin.partialclonefilter'),'blob:none')
        self.assertFalse((self.work/self.oldpath).exists())
        self.assertIn('?'+self.oldblob,git(self.work,'rev-list','--objects','--all','--missing=print').splitlines())
        stamp=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=1)
        self.receipt=stamp.strftime('receipts/%Y/%m/%d/%Y%m%dT%H00Z-n531.json.gz');self.bridge=self.receipt.replace('receipts/','bridges/',1)
        for p in [self.receipt,self.bridge]: self.write(self.work,p,b'SYNTHETIC_ONLY '+p.encode())
        git(self.work,'add','--sparse','--',self.receipt,self.bridge);git(self.work,'commit','-m','synthetic pair')
    def identity(self,p):git(p,'config','user.name','fixture');git(p,'config','user.email','fixture@example.invalid')
    def write(self,root,p,b): f=root/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b)
    def advance(self,p,b):self.write(self.peer,p,b);git(self.peer,'add','--',p);git(self.peer,'commit','-m','advance');git(self.peer,'push','origin','main')
    def publish(self,*extra):return run(self.work,'python3',str(PUBLISHER),'--base',self.base,'--branch','main',*extra,self.receipt,self.bridge,check=False)
    def verify_pair(self):
        for p in (self.receipt,self.bridge):
            v=subprocess.run(['git','show','main:'+p],cwd=self.remote,check=True,capture_output=True).stdout
            self.assertEqual(hashlib.sha256(v).digest(),hashlib.sha256((self.work/p).read_bytes()).digest())
        self.assertEqual(git(self.remote,'rev-parse','main:'+self.oldpath),self.oldblob)
    def test_promisor_publish_preserves_old_archive_and_idempotence(self):
        r=self.publish();self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.verify_pair();head=git(self.remote,'rev-parse','main')
        r=self.publish();self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(git(self.remote,'rev-parse','main'),head)
        self.assertIn('?'+self.oldblob,git(self.work,'rev-list','--objects','--all','--missing=print').splitlines())
    def test_promisor_advanced_archive_preserved(self):
        path='receipts/2030/01/01/20300101T0100Z-n531.json.gz';self.advance(path,b'separate synthetic receipt')
        r=self.publish();self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.verify_pair();self.assertEqual(git(self.remote,'show','main:'+path),'separate synthetic receipt')
    def test_changed_source_holds(self):
        self.advance('research_519.py',b'# changed\n');head=git(self.remote,'rev-parse','main');r=self.publish();self.assertEqual(r.returncode,2);self.assertIn('SOURCE_CHANGED_DURING_SCAN',r.stdout);self.assertEqual(git(self.remote,'rev-parse','main'),head)
    def test_expired_epoch_cli_blocks_without_remote_change(self):
        head=git(self.remote,'rev-parse','main');r=self.publish('--require-current-epoch');self.assertEqual(r.returncode,2);self.assertIn('OUTSIDE_CURRENT_LIVE_PUBLISH_WINDOW',r.stdout);self.assertEqual(git(self.remote,'rev-parse','main'),head)

if __name__=='__main__':unittest.main(verbosity=2)
