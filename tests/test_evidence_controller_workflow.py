"""Never let the read-only controller grow an unauthorized write surface."""
from pathlib import Path
import ast
import unittest


ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/".github/workflows/xray-519-readonly-evidence-controller.yml"


class ControllerWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content=PATH.read_text(encoding="utf-8")

    def test_trigger_is_only_source_complete_and_hourly_watch(self):
        text=self.content
        self.assertIn("workflow_run:",text)
        self.assertIn("types: [completed]",text)
        self.assertIn("cron: '17 * * * *'",text)
        self.assertNotIn("workflow_dispatch:",text)
        self.assertNotIn("repository_dispatch:",text)

    def test_public_readonly_permissions_and_no_external_credentials(self):
        text=self.content
        self.assertIn("  contents: read",text)
        self.assertIn("  actions: read",text)
        for disallowed in (
            "contents: write","actions: write","issues: write",
            "pull-requests: write","CLOUDFLARE_API_TOKEN",
            "GITHUB_ACTIONS_DISPATCH_TOKEN","POST https://internal",
            "npx wrangler deploy","git push","xray-crypto-godzilla-omega",
            "api/v3/order","workflow_dispatch:",
        ):
            with self.subTest(disallowed=disallowed):
                self.assertNotIn(disallowed,text)

    def test_checkout_is_main_without_persistent_credentials(self):
        text=self.content
        self.assertIn("ref: main",text)
        self.assertIn("persist-credentials: false",text)
        self.assertIn("head_branch == 'main'",text)

    def test_python_inline_audit_has_valid_syntax(self):
        text=self.content
        start=text.split("          python3 - <<'PY'\n",1)[1]
        block=start.split("\n          PY",1)[0]
        code="\n".join(line[10:] if line.startswith("          ") else line
                       for line in block.splitlines())
        ast.parse(code)
        self.assertIn("fetch_github_run",code)
        self.assertIn("collect(",code)
        self.assertIn('GITHUB_STEP_SUMMARY',code)
        self.assertIn('FULL FINAL START: **HOLD**',code)

    def test_readonly_evidence_controller_is_actually_schedulable(self):
        text=self.content
        self.assertIn("workflow_run:",text)
        self.assertIn("github.event.workflow_run.head_repository.full_name",text)
        self.assertIn("cron: '17 * * * *'",text)
        self.assertIn("runs-on: ubuntu-24.04",text)
        self.assertNotIn("runs-on: [self-hosted",text)

    def test_job_summary_always_has_final_hold(self):
        text=self.content
        self.assertIn("FULL FINAL START: **HOLD**",text)
        self.assertIn("pair_and_run_verified_count",text)
        self.assertIn("fully_qualified_source_hours",text)
        self.assertNotIn("FULL FINAL START: PASS",text)

    def test_observability_failures_do_not_trigger_recovery(self):
        text=self.content
        self.assertNotIn("curl -X POST",text)
        self.assertNotIn("SOURCE_DISPATCH_LOCK",text)
        self.assertNotIn("GITHUB_OUTPUT",text)
        self.assertIn("XRAY519_READONLY_EVIDENCE_AUDIT_RECORDED",text)


if __name__=="__main__":
    unittest.main()
