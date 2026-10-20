"""Regression coverage for bot-wide, provider and member abuse protection."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from lab.quotas import QuotaGate, QuotaExceeded


class QuotaGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "budget.sqlite3")

    def gate(self, **values):
        settings = {key: str(value) for key, value in values.items()}
        with patch.dict(os.environ, settings):
            return QuotaGate(self.path)

    def test_gemini_minute_and_daily_limits_survive_new_instances(self):
        gate = self.gate(LAB_GEMINI_MINUTE_LIMIT=2, LAB_GEMINI_DAILY_LIMIT=3)
        gate.take_gemini(now=100)
        gate.take_gemini(now=101)
        with self.assertRaises(QuotaExceeded) as exc:
            self.gate(LAB_GEMINI_MINUTE_LIMIT=2, LAB_GEMINI_DAILY_LIMIT=3).take_gemini(now=102)
        self.assertEqual(exc.exception.kind, "gemini")
        gate.take_gemini(now=180)
        with self.assertRaises(QuotaExceeded):
            gate.take_gemini(now=240)
        # New UTC day resets both windows without manual intervention.
        gate.take_gemini(now=86400)

    def test_provider_limit_cannot_be_bypassed_with_new_member_ids(self):
        gate = self.gate(LAB_PROVIDER_MINUTE_LIMIT=2, LAB_PROVIDER_DAILY_LIMIT=10)
        gate.take_provider(now=120)
        gate.take_provider(now=121)
        with self.assertRaises(QuotaExceeded):
            gate.take_provider(now=122)
        gate.take_provider(now=180)

    def test_user_and_guild_cooldown_and_global_command_limit(self):
        gate = self.gate(LAB_USER_10M_LIMIT=1, LAB_GUILD_HOUR_LIMIT=2,
                         LAB_GLOBAL_MINUTE_LIMIT=3, LAB_GLOBAL_DAILY_LIMIT=3)
        gate.admit_member(111, 901, now=1.0, utc=120)
        with self.assertRaises(QuotaExceeded) as exc:
            gate.admit_member(111, 901, now=2.0, utc=121)
        self.assertEqual(exc.exception.kind, "member")
        gate.admit_member(222, 901, now=3.0, utc=122)
        with self.assertRaises(QuotaExceeded) as exc:
            gate.admit_member(333, 901, now=4.0, utc=123)
        self.assertEqual(exc.exception.kind, "server")
        gate.admit_member(333, 902, now=5.0, utc=124)
        with self.assertRaises(QuotaExceeded) as exc:
            gate.admit_member(444, 903, now=6.0, utc=125)
        self.assertEqual(exc.exception.kind, "command")

    def test_no_identifiers_or_questions_in_persisted_budget(self):
        gate = self.gate()
        gate.admit_member(123456789012345678, 987654321012345678, now=2.0, utc=120)
        gate.take_gemini(now=120)
        with sqlite3.connect(self.path) as db:
            scopes = db.execute("SELECT scope FROM budget_counts").fetchall()
        text = repr(scopes)
        self.assertNotIn("123456789012345678", text)
        self.assertNotIn("987654321012345678", text)
        self.assertNotIn("What is THC", text)
        self.assertIn("gemini-daily", text)

    def test_invalid_quotas_fail_startup_not_silently_disable_guard(self):
        with patch.dict(os.environ, {"LAB_GEMINI_DAILY_LIMIT": "0"}):
            with self.assertRaises(ValueError):
                QuotaGate(self.path)

    def test_quota_storage_error_fails_closed(self):
        gate = self.gate()
        gate.db_path = self.temp.name  # SQLite cannot open a directory as a DB.
        with self.assertRaises(QuotaExceeded) as exc:
            gate.take_gemini(now=120)
        self.assertEqual(exc.exception.kind, "storage-unavailable")

    def test_anonymous_usage_counters(self):
        gate = self.gate()
        gate.take_gemini()
        usage = gate.usage()
        self.assertEqual(usage["gemini"][0], 1)
        self.assertGreater(usage["gemini"][1], 0)


class ProtectedNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_quota_rejection_prevents_pubmed_http(self):
        from lab.sources import ScienceSources
        session = MagicMock()
        quota = MagicMock()
        quota.take_provider.side_effect = QuotaExceeded("provider", 10)
        with self.assertRaises(QuotaExceeded):
            await ScienceSources(session, quota=quota).pubmed("Cannabis and sleep")
        session.get.assert_not_called()

    async def test_gemini_limit_prevents_post(self):
        from lab.answers import GeminiAnswer
        from lab.sources import Study
        session = MagicMock()
        quota = MagicMock()
        quota.take_gemini.side_effect = QuotaExceeded("gemini", 10)
        with self.assertRaises(QuotaExceeded):
            await GeminiAnswer(session, "not-a-real-key", quota=quota).generate(
                "Is THC safe?", [Study("123", "Title", "Journal", "Uncertain result")])
        session.post.assert_not_called()

    async def test_member_block_is_ephemeral(self):
        from lab.bot import bot
        user = SimpleNamespace(id=111)
        response = SimpleNamespace(is_done=lambda: False, send_message=AsyncMock())
        interaction = SimpleNamespace(user=user, guild_id=901, response=response)
        with patch.object(bot.quota, "admit_member", side_effect=QuotaExceeded("member", 20)):
            self.assertFalse(await bot.admit_interaction(interaction))
        self.assertTrue(response.send_message.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
