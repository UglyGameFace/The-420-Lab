"""Regressions for clearly sourced strain details and quiet provider failures."""
import unittest
from unittest.mock import AsyncMock, patch

from lab.rich_sources import sourced_summary


class SourceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_unavailable_show_one_status_not_four_errors(self):
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="Flower & Freedom temporarily unavailable."), patch(
                   "lab.rich_sources.findmyseeds", new_callable=AsyncMock,
                   return_value="Find My Seeds temporarily unavailable."), patch(
                   "lab.rich_sources.cannalib", new_callable=AsyncMock,
                   return_value="Provider currently unavailable for this query."), patch(
                   "lab.rich_sources.strainapi", new_callable=AsyncMock,
                   return_value="Alternative source temporarily unavailable."):
            result = await sourced_summary(None, None, "Northern Lights")
        self.assertEqual(result, "No additional independently confirmed source record available.")
        self.assertNotIn("temporarily unavailable", result)

    async def test_source_confirmed_result_survives_other_failure(self):
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="**Flower & Freedom:** Northern Lights\n**Source description:** factual summary"), patch(
                   "lab.rich_sources.findmyseeds", new_callable=AsyncMock,
                   return_value="Find My Seeds temporarily unavailable.") as community, patch(
                   "lab.rich_sources.cannalib", new_callable=AsyncMock) as cannalib:
            result = await sourced_summary(None, None, "Northern Lights")
        self.assertIn("**Flower & Freedom:** Northern Lights", result)
        self.assertNotIn("temporarily unavailable", result)
        cannalib.assert_not_awaited()
        community.assert_awaited_once()

    async def test_community_source_can_work_without_other_provider(self):
        with patch("lab.rich_sources.flower", new_callable=AsyncMock,
                   return_value="Flower & Freedom temporarily unavailable."), patch(
                   "lab.rich_sources.findmyseeds", new_callable=AsyncMock,
                   return_value="**Find My Seeds:** Northern Lights\n**Source overview:** X"):
            result = await sourced_summary(None, None, "Northern Lights")
        self.assertTrue(result.startswith("**Find My Seeds:**"))
        self.assertNotIn("Flower & Freedom temporarily unavailable", result)


if __name__ == "__main__":
    unittest.main()
