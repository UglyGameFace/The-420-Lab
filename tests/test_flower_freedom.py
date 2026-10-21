"""Provider regression: safe, credited and appropriately limited strain context."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from lab.flower_freedom_client import (
    _CACHE, _slug, format_record, source_summary,
)
from lab.rich_sources import sourced_summary


class FakeReply:
    def __init__(self, payload, status=200):
        self.status = status
        self.content = SimpleNamespace(read=AsyncMock(
            return_value=json.dumps(payload).encode("utf-8")))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def sample(name="Blue Dream"):
    return {
        "data": {
            "name": name,
            "aliases": [],
            "url": "https://flowerandfreedom.com/strains/blue-dream/",
            "summary": "Blueberry aromas and source-reported characteristics.",
            "genetics": {"description": "Blueberry x Haze"},
            "reported_effects": ["Creative", "Happy"],
            "aroma_descriptions": ["Berry"],
            "updated_at": "2026-10-01",
            "chemistry": {"samples": [{"id": "specific-batch-123"}]},
        }
    }


class FlowerFormatTests(unittest.TestCase):
    def test_exact_name_and_source_attribution(self):
        response = format_record(sample(), "Blue Dream")
        self.assertIn("**Flower & Freedom:** Blue Dream", response)
        self.assertIn("Source description", response)
        self.assertIn("Source updated:** 2026-10-01", response)
        self.assertIn("batch-specific", response)
        self.assertIn("flowerandfreedom.com/api/", response)
        self.assertNotIn("THC 25%", response)
        self.assertLessEqual(len(response), 900)

    def test_mismatched_result_must_not_impersonate_requested_strain(self):
        self.assertFalse(format_record(sample(), "Lemon Haze").startswith("**"))

    def test_malicious_or_unknown_input_is_not_a_url(self):
        for value in ("@everyone", "https://example.com", "<@123>", "abc" + chr(96)):
            self.assertEqual(_slug(value), "")
        self.assertEqual(_slug("Blue Dream"), "blue-dream")

    def test_untrusted_profile_url_is_rejected(self):
        bad = sample()
        bad["data"]["url"] = "https://evil.example/strains/blue-dream/"
        self.assertFalse(format_record(bad, "Blue Dream").startswith("**"))


class FlowerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _CACHE.clear()

    async def test_one_quota_count_and_bounded_caching(self):
        session = MagicMock()
        session.get.return_value = FakeReply(sample())
        quota = MagicMock()
        with patch.dict("os.environ", {"FLOWER_FREEDOM_ENABLED": "true"}):
            first = await source_summary(session, quota, "Blue Dream")
            second = await source_summary(session, quota, "Blue Dream")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("**"))
        quota.take_provider.assert_called_once()
        session.get.assert_called_once()
        self.assertIn("/blue-dream.json", session.get.call_args.args[0])
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    async def test_fallback_used_if_no_flower_profile(self):
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="No exact source profile.") as flower, patch(
                   "lab.rich_sources.cannalib", new_callable=AsyncMock,
                   return_value="**Breeder:** Independent") as canna, patch(
                   "lab.rich_sources.strainapi", new_callable=AsyncMock
                   ) as third:
            result = await sourced_summary(None, None, "Blue Dream")
        flower.assert_awaited_once()
        canna.assert_awaited_once()
        third.assert_not_awaited()
        self.assertIn("CannaLib", result)

    async def test_fallback_not_called_after_credited_flower_result(self):
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="**Flower & Freedom:** Blue Dream") as flower, patch(
                   "lab.rich_sources.cannalib", new_callable=AsyncMock
                   ) as canna:
            text = await sourced_summary(None, None, "Blue Dream")
        self.assertIn("Flower", text)
        flower.assert_awaited_once()
        canna.assert_not_awaited()

    async def test_global_quota_exhaustion_is_not_bypassed(self):
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="Research safety allowance reached; try again later."), patch(
                   "lab.rich_sources.cannalib", new_callable=AsyncMock
                   ) as canna:
            result = await sourced_summary(None, None, "Blue Dream")
        canna.assert_not_awaited()
        self.assertIn("allowance reached", result)


if __name__ == "__main__":
    unittest.main()
