"""Prove exact checkout rules and create-only publication with a local Git remote."""
from contextlib import chdir, redirect_stdout
from io import StringIO
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import unittest

from publish_git import publish, PublishBlocked

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/hourly-519-public-source.yml"
ARCHIVE_DAY = "2026/11/19/"
ARCHIVE_NAME = "20261119T0000Z-n525.json.gz"
NEW_NAME = "20261119T0100Z-n525.json.gz"
FIXTURES = (
    "2026/11/03/20261103T1000Z-n518.json.gz",
    "2026/11/06/20261106T1200Z-n518.json.gz",
    "2026/11/06/20261106T1300Z-n518.json.gz",
    "2026/11/06/20261106T1400Z-n518.json.gz",
    "2026/11/06/20261106T1500Z-n518.json.gz",
    "2026/11/07/20261107T1800Z-n518.json.gz",
)


def run(cwd, *args, input=None):
    result = subprocess.run(
        ["git", *args], cwd=cwd, input=input,
        check=True, text=True, capture_output=True, timeout=15,
    )
    return result.stdout.strip()


def put(root, relative, contents):
    out = root / relative
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(contents)


class HourlySparseCheckoutContract(unittest.TestCase):
    def test_natural_workflow_keeps_both_security_suites_and_original_schedule(self):
        yml = FLOW.read_text()
        self.assertIn("sparse-checkout-cone-mode: false", yml)
        self.assertEqual(yml.count("fetch-depth: 1"), 1)
        self.assertEqual(yml.count("cron:"), 2)
        self.assertIn("cron: '4 * * * *'", yml)
        self.assertIn("cron: '8 * * * *'", yml)
        self.assertEqual(yml.count("python3 -m unittest discover -s tests -q"), 1)
        self.assertEqual(yml.count("python3 -O -m unittest discover -s tests -q"), 1)
        self.assertIn('git add --sparse -- "$FILE" "$BFILE"', yml)
        self.assertIn('git add --sparse -- "$FILE"', yml)

    def test_partial_checkout_keeps_archive_history_and_publishes_one_pair(self):
        yml = FLOW.read_text()
        match = re.search(r"(?m)^          sparse-checkout: \|\n((?:^ {12}\S[^\n]*\n)+)", yml)
        self.assertIsNotNone(match)
        rules = [line.strip() for line in match[1].splitlines()]
        self.assertEqual(set(x for x in rules if x.startswith("/bridges/")),
                         {"/bridges/" + f for f in FIXTURES})
        with TemporaryDirectory(prefix="xray-sparse-source-") as d:
            parent = Path(d)
            remote, full, slim = (parent / x for x in ("remote.git", "full", "slim"))
            run(parent, "init", "--bare", "-b", "main", str(remote))
            run(remote, "config", "uploadpack.allowFilter", "true")
            run(remote, "config", "uploadpack.allowReachableSHA1InWant", "true")
            run(parent, "init", "-b", "main", str(full))
            run(full, "config", "user.name", "Source test")
            run(full, "config", "user.email", "source-test@example.invalid")
            for path in ["research_519.py", "README.md", "tests/test_gate.py",
                         "ops/source_preflight.py", ".github/workflows/kept.yml",
                         "research_lab/pit.py", "receipts/2026/10/30/20261030T1000Z-n400.json.gz"]:
                put(full, path, path.encode())
            for path in FIXTURES:
                put(full, "bridges/" + path, path.encode())
            cold = "bridges/" + ARCHIVE_DAY + ARCHIVE_NAME
            put(full, cold, b"IMMUTABLE_COLD_ARCHIVE_ORIGINAL")
            put(full, "receipts/" + ARCHIVE_DAY + ARCHIVE_NAME, b"IMMUTABLE_RECEIPT")
            run(full, "add", ".")
            run(full, "commit", "-m", "Original public tree")
            run(full, "push", remote.as_uri(), "main")
            # Reproduce the pinned Actions checkout's init and shallow filtered fetch.
            run(parent, "init", "-b", "main", str(slim))
            run(slim, "remote", "add", "origin", remote.as_uri())
            run(slim, "-c", "protocol.version=2", "fetch", "--no-tags", "--depth=1",
                "--filter=blob:none", "origin", "+refs/heads/main:refs/remotes/origin/main")
            run(slim, "sparse-checkout", "set", "--no-cone", "--stdin", input="\n".join(rules) + "\n")
            run(slim, "checkout", "-B", "main", "refs/remotes/origin/main")
            run(slim, "config", "user.name", "Source test")
            run(slim, "config", "user.email", "source-test@example.invalid")
            base = run(slim, "rev-parse", "HEAD")
            self.assertEqual(run(slim, "config", "remote.origin.partialclonefilter"), "blob:none")
            self.assertEqual(run(slim, "ls-tree", "-r", "HEAD"), run(full, "ls-tree", "-r", "HEAD"))
            self.assertFalse((slim / cold).exists())
            cold_sha = run(full, "rev-parse", "HEAD:" + cold)
            missing = run(slim, "rev-list", "--objects", "--missing=print", "HEAD")
            self.assertIn("?" + cold_sha, missing)
            for f in FIXTURES:
                self.assertEqual((slim / "bridges" / f).read_bytes(), f.encode())
            self.assertTrue((slim / "receipts/2026/10/30/20261030T1000Z-n400.json.gz").is_file())
            for f in ["research_519.py", "README.md", "tests/test_gate.py",
                      "ops/source_preflight.py", ".github/workflows/kept.yml", "research_lab/pit.py"]:
                self.assertTrue((slim / f).is_file(), f)
            pair = ["receipts/" + ARCHIVE_DAY + NEW_NAME, "bridges/" + ARCHIVE_DAY + NEW_NAME]
            for f in pair:
                put(slim, f, f.encode())
            run(slim, "add", "--sparse", "--", *pair)
            run(slim, "commit", "-m", "Append exactly one pair")
            with chdir(slim), redirect_stdout(StringIO()) as log:
                publish(base, "main", pair)
                # Idempotent remote readback, including a lost acknowledgement.
                published = run(remote, "rev-parse", "main")
                publish(base, "main", pair)
                self.assertEqual(run(remote, "rev-parse", "main"), published)
                with self.assertRaises(PublishBlocked):
                    publish(base, "main", [pair[0]])
            self.assertEqual(log.getvalue().count("PAIR_REMOTE_READBACK_PASS"), 2)
            for f in pair:
                self.assertEqual(run(remote, "show", "main:" + f), f)
            self.assertEqual(run(remote, "show", "main:" + cold), "IMMUTABLE_COLD_ARCHIVE_ORIGINAL")
            self.assertIn("?" + cold_sha,run(slim,"rev-list","--objects","--missing=print","origin/main"))
            self.assertEqual(run(slim, "show", "origin/main:" + cold), "IMMUTABLE_COLD_ARCHIVE_ORIGINAL")
            self.assertFalse((slim / cold).exists())


if __name__ == "__main__":
    unittest.main()
