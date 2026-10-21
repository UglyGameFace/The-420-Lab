"""Mocked coverage for optional CannaLib read-only source and quota boundaries."""
import json
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock, patch

from lab.cannalib_client import record_for, brief, source_summary, CREDIT
from lab.quotas import QuotaExceeded


class FakeBody:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    async def read(self, count):
        return self.payload[:count]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.content = FakeBody(payload)
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class RecordTests(TestCase):
    def test_requires_exact_strain_not_first_fuzzy_candidate(self):
        self.assertIsNone(record_for({"data": [{"name": "Blue Dream Extra"}]}, "Blue Dream"))
        match = record_for({"data": [{"name": "Blue Dream"}]}, "blue dream")
        self.assertEqual(match["name"], "Blue Dream")

    def test_untrusted_provider_text_is_safe(self):
        self.assertNotIn("@everyone", brief("@everyone"))
        self.assertNotIn("<", brief("<@123>"))
        self.assertLessEqual(len(brief("x" * 500)), 80)


class SourceTests(IsolatedAsyncioTestCase):
    async def test_one_lookup_only_when_result_exact(self):
        quota = MagicMock()
        session = MagicMock()
        session.get.return_value = FakeResponse({"data": [
            {"name": "Blue Dream", "type": "hybrid", "breeder": "Catalog",
             "top_terpenes": ["myrcene", "pinene"], "thc_range": "12-20"},
            {"name": "Blue Dream Variant", "thc_range": "30"},
        ]})
        with patch.dict(os.environ, {"CANNALIB_ENABLED": "true", "CANNALIB_API_KEY": ""}):
            message = await source_summary(session, quota, "Blue Dream")
        self.assertIn("myrcene", message)
        self.assertIn("THC range claimed", message)
        self.assertNotIn("30", message)
        quota.take_cannalib.assert_called_once_with()
        quota.take_provider.assert_called_once_with()
        session.get.assert_called_once()
        self.assertEqual(session.get.call_args.kwargs["allow_redirects"], False)
        self.assertEqual(session.get.call_args.kwargs["params"]["limit"], 3)

    async def test_global_budget_denial_prevents_http(self):
        quota = MagicMock()
        quota.take_cannalib.side_effect = QuotaExceeded("cannalib", 100)
        session = MagicMock()
        message = await source_summary(session, quota, "Blue Dream")
        self.assertIn("allowance", message.lower())
        session.get.assert_not_called()

    async def test_feature_kill_switch_prevents_http(self):
        quota = MagicMock()
        session = MagicMock()
        with patch.dict(os.environ, {"CANNALIB_ENABLED": "false"}):
            message = await source_summary(session, quota, "Blue Dream")
        self.assertIn("disabled", message)
        session.get.assert_not_called()

    async def test_bad_provider_status_falls_back_without_inventing(self):
        quota = MagicMock()
        session = MagicMock()
        session.get.return_value = FakeResponse({}, status=429)
        response = await source_summary(session, quota, "Blue Dream")
        self.assertIn("rate limit", response.lower())
        self.assertIn("cannalib.org", CREDIT)

    async def test_bad_schema_is_not_a_fabricated_fact(self):
        quota = MagicMock()
        session = MagicMock()
        session.get.return_value = FakeResponse({"arbitrary": 1})
        response = await source_summary(session, quota, "Blue Dream")
        self.assertIn("No exact-name", response)
