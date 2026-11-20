"""Test the real hourly shell gate with isolated concurrent worker doubles."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

FLOW = Path(__file__).resolve().parents[1] / ".github/workflows/hourly-519-public-source.yml"

DOUBLE = r'''
import os, pathlib, sys, time
mode = "optimized" if sys.argv[1:2] == ["-O"] else "normal"
args = sys.argv[2:] if mode == "optimized" else sys.argv[1:]
assert args == ["-m", "unittest", "discover", "-s", "tests", "-q"]
root = pathlib.Path(os.environ["XRAY_PROBE_ROOT"])
scratch = pathlib.Path(os.environ["TMPDIR"])
(root / (mode + ".ready")).write_text(str(scratch))
(scratch / "shared-name").write_text(mode)
other = "normal" if mode == "optimized" else "optimized"
end = time.monotonic() + 3
while not (root / (other + ".ready")).is_file():
    if time.monotonic() >= end:
        sys.exit(92)
    time.sleep(0.008)
assert (scratch / "shared-name").read_text() == mode
print(mode + " LOG")
(root / (mode + ".complete")).write_text("complete")
raise SystemExit(int(os.environ["XRAY_EXIT_" + mode.upper()]))
'''


class HourlyParallelSecurityGate(unittest.TestCase):
    def setUp(self):
        cfg = FLOW.read_text(encoding="utf-8")
        guard, self.following = cfg.split(
            "      - name: Run security regression tests\n        run: |\n", 1
        )[1].split(
            "      - name: Read-only Binance scan, immutable receipt and independent readback\n", 1
        )
        self.script = textwrap.dedent(guard)
        self.assertNotIn("always()", self.following.split("        run:", 1)[0])

    def invoke(self, normal, optimized):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            bin_dir = root / "bin"
            runner = root / "runner temp"
            bin_dir.mkdir()
            runner.mkdir()
            mock = bin_dir / "python3"
            mock.write_text("#!" + sys.executable + "\n" + textwrap.dedent(DOUBLE))
            mock.chmod(0o700)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                       RUNNER_TEMP=str(runner), XRAY_PROBE_ROOT=str(root),
                       XRAY_EXIT_NORMAL=str(normal), XRAY_EXIT_OPTIMIZED=str(optimized))
            result = subprocess.run(["bash", "-c", self.script], env=env,
                                    cwd=root, text=True, capture_output=True, timeout=8)
            for key in ("normal", "optimized"):
                self.assertTrue((root / (key + ".complete")).exists(), result.stderr)
                self.assertIn(key + " LOG", result.stdout)
            a = (root / "normal.ready").read_text()
            b = (root / "optimized.ready").read_text()
            self.assertNotEqual(a, b)
            self.assertEqual(list(runner.iterdir()), [])
            return result

    def test_both_simultaneously_start_and_both_pass(self):
        r = self.invoke(0, 0)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("XRAY_SOURCE_SECURITY_REGRESSION_HOLD", r.stdout)

    def test_normal_rejects_with_both_logs_retained(self):
        r = self.invoke(7, 0)
        self.assertEqual(r.returncode, 2)
        self.assertIn("XRAY_SOURCE_GUARD normal exit=7", r.stdout)
        self.assertIn("XRAY_SOURCE_SECURITY_REGRESSION_HOLD", r.stdout)

    def test_optimized_rejects(self):
        r = self.invoke(0, 8)
        self.assertEqual(r.returncode, 2)
        self.assertIn("XRAY_SOURCE_GUARD optimized exit=8", r.stdout)

    def test_both_reject(self):
        r = self.invoke(7, 8)
        self.assertEqual(r.returncode, 2)
        self.assertIn("XRAY_SOURCE_GUARD normal exit=7", r.stdout)
        self.assertIn("XRAY_SOURCE_GUARD optimized exit=8", r.stdout)

    def test_missing_child_and_no_next_step(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools = root / "bin"
            runner = root / "runner"
            tools.mkdir()
            runner.mkdir()
            for name in ("mktemp", "mkdir", "cat", "rm"):
                (tools / name).symlink_to(shutil.which(name))
            env = dict(os.environ, RUNNER_TEMP=str(runner), PATH=str(tools))
            x = subprocess.run(["/bin/bash", "-c", self.script], env=env,
                               capture_output=True, text=True, timeout=3)
            self.assertEqual(x.returncode, 2)
            self.assertIn("XRAY_SOURCE_GUARD normal exit=127", x.stdout)
            self.assertIn("XRAY_SOURCE_GUARD optimized exit=127", x.stdout)
            self.assertIn("XRAY_SOURCE_SECURITY_REGRESSION_HOLD", x.stdout)
            self.assertEqual(list(runner.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
