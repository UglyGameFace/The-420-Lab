"""Tests for credited third-party strain profiles and mobile panel parity."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from lab.findmyseeds_client import format_record, exact_record, source_summary, _CACHE


PAYLOAD = {"items": [{
    "name": "Blue Dream", "slug": "blue-dream",
    "url": "https://www.findmyseeds.com/strains/blue-dream/",
    "breeder": "Example Genetics", "type": "Hybrid",
    "excerpt": "A source-provided short description of this cultivar.",
    "rating": 4.4, "rating_count": 18,
    "effects": ["Creative", "Happy"], "flavors": ["Berry"],
    "terpenes": ["Myrcene"],
}, {"name": "Blue Dream XL", "rating": 5.0, "rating_count": 1000,
    "url": "https://www.findmyseeds.com/strains/blue-dream-xl/"}]}


class FindMySeedsParsingTests(unittest.TestCase):
    def test_exact_profile_shows_attributed_reviews_with_sample_count(self):
        message = format_record(PAYLOAD, "Blue Dream")
        self.assertIn("Source overview", message)
        self.assertIn("Find My Seeds community score", message)
        self.assertIn("4.4/5 (18 reports)", message)
        self.assertIn("https://www.findmyseeds.com/strains/blue-dream/", message)
        self.assertIn("Data provided by Find My Seeds", message)

    def test_no_cross_strain_fuzzy_attribution(self):
        self.assertIsNone(exact_record(PAYLOAD, "Blue Dreamz"))
        self.assertFalse(format_record(PAYLOAD, "Blue Dreamz").startswith("**"))

    def test_reject_external_lookalike_link(self):
        forged = {"items": [{**PAYLOAD["items"][0], "url":
                             "https://www.findmyseeds.com.evil.org/strains/blue-dream/"}]}
        self.assertIn("No verified", format_record(forged, "Blue Dream"))

    def test_absent_rating_is_not_turned_into_fake_score(self):
        payload = {"items": [{**PAYLOAD["items"][0], "rating_count": 0, "rating": None}]}
        self.assertNotIn("community score", format_record(payload, "Blue Dream"))

    def test_markup_and_tags_stripped(self):
        payload = {"items": [{**PAYLOAD["items"][0],
                              "excerpt": "<b>Test</b> @everyone <script>x</script>"}]}
        result = format_record(payload, "Blue Dream")
        self.assertNotIn("<", result)
        self.assertNotIn("@everyone", result)


class FindMySeedsNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_one_request_and_cached_answer(self):
        from lab.findmyseeds_client import URL
        _CACHE.clear()
        response = MagicMock()
        response.status = 200
        response.content.read = AsyncMock(return_value=json.dumps(PAYLOAD).encode())
        context = AsyncMock()
        context.__aenter__.return_value = response
        context.__aexit__.return_value = None
        session = MagicMock()
        session.get.return_value = context
        quota = MagicMock()
        first = await source_summary(session, quota, "Blue Dream")
        second = await source_summary(session, quota, "Blue Dream")
        self.assertEqual(first, second)
        self.assertIn("community score", first)
        session.get.assert_called_once()
        self.assertEqual(session.get.call_args.args[0], URL)
        quota.take_provider.assert_called_once()

    async def test_global_quota_stops_http(self):
        from lab.quotas import QuotaExceeded
        _CACHE.clear()
        session = MagicMock()
        quota = MagicMock()
        quota.take_provider.side_effect = QuotaExceeded("provider", 60)
        response = await source_summary(session, quota, "Blue Dream")
        self.assertIn("safety allowance", response)
        session.get.assert_not_called()

    async def test_pipeline_includes_both_original_summary_and_external_rating(self):
        from lab.rich_sources import sourced_summary
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="**Flower & Freedom:** Short original description."), \
             patch("lab.rich_sources.findmyseeds", new_callable=AsyncMock,
                   return_value="**Find My Seeds:** 4.4/5 (18 reports)"), \
             patch("lab.rich_sources.cannalib", new_callable=AsyncMock) as fallback:
            result = await sourced_summary(None, None, "Blue Dream")
            self.assertIn("Flower & Freedom", result)
            self.assertIn("Find My Seeds", result)
            fallback.assert_not_awaited()


class MobilePanelRichProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_find_strains_uses_same_rich_data_as_slash(self):
        from lab.panel import StrainQueryModal
        from lab.bot import bot
        modal = StrainQueryModal()
        modal.search_term._value = "Blue Dream"
        response = SimpleNamespace(defer=AsyncMock())
        followup = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            client=bot, response=response, followup=followup, guild_id=321,
        )
        fake_embed = object()
        with patch.object(bot, "admit_interaction", new_callable=AsyncMock,
                          return_value=True), \
             patch("lab.profile_reply.build_strain_profile", new_callable=AsyncMock,
                   return_value=fake_embed) as factory:
            await modal.on_submit(interaction)
        response.defer.assert_awaited_once()
        factory.assert_awaited_once_with(bot, "Blue Dream", 321)
        self.assertIs(followup.send.await_args.kwargs["embed"], fake_embed)
        self.assertTrue(followup.send.await_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
