"""Exercise quota storage across separate Python interpreter processes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LedgerContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "quota.sqlite3")
        self.root = Path(__file__).resolve().parents[1]

    def execute(self, code: str, *, path: str | None = None) -> str:
        env = dict(os.environ, LAB_QUOTA_DB_PATH=path or self.path,
                   LAB_GEMINI_DAILY_LIMIT="30", LAB_AI_ENABLED="true")
        env["PYTHONPATH"] = str(self.root)
        run = subprocess.run(
            [sys.executable, "-c", code], cwd=self.root,
            env=env, capture_output=True, text=True, timeout=15)
        if run.returncode != 0:
            self.fail(f"subprocess failed: {run.stderr[-700:]}")
        return run.stdout.strip()

    def test_fresh_interpreter_sees_prior_paused_ai_and_lowered_caps(self):
        first = self.execute(
            "from lab.quotas import QuotaGate; q=QuotaGate(); "
            "assert not q.ledger_seen_before; q.set_ai_enabled(False); "
            "q.set_limit('gemini_daily', 2); print(q.continuity_description())")
        self.assertIn("First observed launch", first)

        second = self.execute(
            "from lab.quotas import QuotaGate; q=QuotaGate(); "
            "assert q.ledger_seen_before; assert q.boot_number==2; "
            "assert q.limit('gemini_daily')==2; assert not q.ai_enabled(); "
            "print(q.continuity_description())")
        self.assertIn("Prior quota ledger found", second)

        third = self.execute(
            "from lab.quotas import QuotaGate; q=QuotaGate(); "
            "assert q.boot_number==3; assert not q.ai_enabled(); "
            "print(q.boot_number)")
        self.assertEqual(third, "3")

    def test_empty_replacement_ledger_is_reported_not_misclassified(self):
        self.execute("from lab.quotas import QuotaGate; QuotaGate()")
        alternate = str(Path(self.temp.name) / "replacement.sqlite3")
        observed = self.execute(
            "from lab.quotas import QuotaGate; q=QuotaGate(); "
            "print(q.continuity_description())", path=alternate)
        self.assertIn("persistence is unverified", observed)

    def test_earlier_usage_still_applies_after_fresh_interpreter(self):
        self.execute(
            "from lab.quotas import QuotaGate; q=QuotaGate(); "
            "q.set_limit('gemini_daily', 1); q.take_gemini(); print('used')")
        outcome = self.execute(
            "from lab.quotas import QuotaGate,QuotaExceeded; q=QuotaGate(); "
            "assert q.limit('gemini_daily')==1; "
            "try_deny = False\n"
            "try:\n q.take_gemini()\n"
            "except QuotaExceeded:\n try_deny = True\n"
            "assert try_deny\nprint('blocked')")
        self.assertEqual(outcome, "blocked")


if __name__ == "__main__":
    unittest.main()
