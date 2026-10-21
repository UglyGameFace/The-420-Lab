"""Mocked fallback / source-field tests; do not call real strain providers."""
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from lab.strainapi_client import exact_record, format_record, source_summary
from lab.rich_sources import sourced_summary


class Body:
    def __init__(self, value):
        self.value = json.dumps(value).encode()
    async def read(self, limit):
        return self.value[:limit]


class Response:
    def __init__(self, value, status=200):
        self.content = Body(value)
        self.status = status
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


class StrainAPISchemaTests(unittest.TestCase):
    def test_requires_exact_name(self):
        self.assertIsNone(exact_record([{"name": "Blue Dream XL"}], "Blue Dream"))
        self.assertEqual(exact_record([{"name": "Blue Dream"}], "blue dream")["name"], "Blue Dream")

    def test_source_fields_exclude_description_images_and_potency(self):
        row = {
            "name": "Blue Dream", "slug": "blue-dream",
            "breeder": "Some Breeder", "genetics": "Blueberry x Haze",
            "terpenes": ["Limonene", "Myrcene"],
            "description": "Long copyrighted paragraph",
            "image": {"url": "https://other.site/photo.jpg"},
            "thc": {"min": 20}, "effects": {"mental": "medical cure"}
        }
        output = format_record(row, "Blue Dream")
        self.assertIn("Blueberry x Haze", output)
        self.assertIn("www.strainapi.com/blue-dream/", output)
        self.assertIn("Myrcene", output)
        for forbidden in ("copyrighted paragraph", "photo.jpg", "20", "medical cure"):
            self.assertNotIn(forbidden, output)

    def test_does_not_accept_different_detail_name(self):
        self.assertIn("No exact", format_record({"name": "Blue Dream XL"}, "Blue Dream"))


class StrainAPIRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_then_detail_and_count_each_http(self):
        session = MagicMock()
        session.get.side_effect = [
            Response([{"name": "Blue Dream", "slug": "blue-dream"}]),
            Response({"name": "Blue Dream", "slug": "blue-dream",
                      "breeder": "Reference Grower", "terpenes": ["Myrcene"]}),
        ]
        quota = MagicMock()
        with patch.dict("os.environ", {"STRAINAPI_ENABLED": "true"}):
            result = await source_summary(session, quota, "Blue Dream")
        self.assertIn("Reference Grower", result)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(quota.take_provider.call_count, 2)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    async def test_refuses_fabricated_match_and_invalid_slug(self):
        session = MagicMock()
        session.get.return_value = Response([{"name": "Blue Dream XL", "slug": "blue-dream-xl"}])
        result = await source_summary(session, MagicMock(), "Blue Dream")
        self.assertIn("No exact", result)
        self.assertEqual(session.get.call_count, 1)
        session.get.reset_mock()
        session.get.return_value = Response([{"name": "Blue Dream", "slug": "../../admin"}])
        result = await source_summary(session, MagicMock(), "Blue Dream")
        self.assertIn("Invalid source identifier", result)
        self.assertEqual(session.get.call_count, 1)

    async def test_quota_denial_fails_without_http(self):
        from lab.quotas import QuotaExceeded
        session = MagicMock()
        quota = MagicMock()
        quota.take_provider.side_effect = QuotaExceeded("provider", 60)
        result = await source_summary(session, quota, "Blue Dream")
        self.assertIn("safety quota", result.lower())
        session.get.assert_not_called()


class RichFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_only_when_primary_did_not_find_data(self):
        with patch("lab.rich_sources.cannalib", new_callable=AsyncMock,
                   return_value="No exact-name source record confirmed.") as first:
            with patch("lab.rich_sources.strainapi", new_callable=AsyncMock,
                       return_value="**Listed breeder:** Test\nSource: StrainAPI") as second:
                content = await sourced_summary(None, None, "Test")
        first.assert_awaited_once()
        second.assert_awaited_once()
        self.assertIn("StrainAPI", content)

    async def test_no_extra_provider_after_budget_denial(self):
        with patch("lab.rich_sources.cannalib", new_callable=AsyncMock,
                   return_value="Provider's bot-wide safety allowance reached"):
            with patch("lab.rich_sources.strainapi", new_callable=AsyncMock) as second:
                result = await sourced_summary(None, None, "Test")
        second.assert_not_awaited()
        self.assertIn("allowance", result)


if __name__ == "__main__":
    unittest.main()
