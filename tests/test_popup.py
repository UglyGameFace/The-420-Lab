"""Regression coverage: categories should open centered forms, not in-channel menus."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lab.popup import TopicPicker, CannabinoidPicker, LibraryPicker, library_options
from lab.panel import TOPICS, LabPanelView
from lab.bot import bot


class PopupStructureTests(unittest.TestCase):
    def test_modal_selects_are_wrapped_in_discord_labels(self):
        for modal in (TopicPicker(bot), CannabinoidPicker(bot), LibraryPicker(bot)):
            payload = modal.to_dict()
            self.assertTrue(payload["components"])
            category = payload["components"][0]
            self.assertEqual(category["type"], 18)  # Modal Label component.
            self.assertEqual(category["component"]["type"], 3)  # String select.
            self.assertTrue(category["component"]["options"])

    def test_options_cover_research_sources_and_topics(self):
        topics = {item.value for item in TopicPicker(bot).choice.options}
        self.assertEqual(topics, set(TOPICS))
        compounds = {item.value for item in CannabinoidPicker(bot).choice.options}
        self.assertIn("THC", compounds)
        choices = {item.value for item in library_options()}
        for value in ("trials", "strain", "sources", "database", "papers:all", "papers:randomized",
                      "guide:overview", "fda:epidiolex"):
            self.assertIn(value, choices)
        self.assertLessEqual(len(choices), 25)

    def test_all_seven_public_panel_buttons_remain_persistent(self):
        view = LabPanelView(bot)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 7)
        self.assertTrue(all(item.custom_id.startswith("the420lab:panel:v1:")
                            for item in view.children))


class PopupInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_category_buttons_open_modal_without_ephemeral_menu(self):
        view = LabPanelView(bot)
        controls = {item.label: item for item in view.children}
        for name in ("Explore Topics", "Cannabinoids", "Research Library"):
            response = SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock())
            interaction = SimpleNamespace(response=response)
            await controls[name].callback(interaction)
            response.send_modal.assert_awaited_once()
            response.send_message.assert_not_awaited()

    async def test_source_guide_is_private_and_does_not_spend_api_requests(self):
        modal = LibraryPicker(bot)
        modal.choice._values = ["sources"]
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(response=response)
        with patch.object(bot, "admit_interaction", new_callable=AsyncMock) as admit:
            await modal.on_submit(interaction)
            admit.assert_not_awaited()
        self.assertTrue(response.send_message.await_args.kwargs["ephemeral"])
        content = response.send_message.await_args.kwargs["embed"]
        self.assertIn("Sources", content.title)

    async def test_library_official_guide_needs_no_paid_provider_call(self):
        modal = LibraryPicker(bot)
        modal.choice._values = ["guide:overview"]
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(response=response)
        with patch.object(bot, "admit_interaction", new_callable=AsyncMock) as admit:
            await modal.on_submit(interaction)
            admit.assert_not_awaited()
        response.send_message.assert_awaited_once()
        self.assertTrue(response.send_message.await_args.kwargs["ephemeral"])

    async def test_library_missing_search_term_does_not_consume_quota(self):
        modal = LibraryPicker(bot)
        modal.choice._values = ["papers:all"]
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(response=response)
        with patch.object(bot, "admit_interaction", new_callable=AsyncMock) as admit:
            await modal.on_submit(interaction)
            admit.assert_not_awaited()
        self.assertIn("Enter a topic", response.send_message.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
