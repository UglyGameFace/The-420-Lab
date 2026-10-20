"""Network-mocked regression tests. No live tokens required."""
import importlib.util
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from lab.answers import DISCLAIMER, GeminiAnswer, ResearchAssistant, study_design, study_links
from lab.sources import ScienceSources, SourceError, Study
from lab.fda import FDA_PRODUCTS, FDAReportTerms, FDA_ENDPOINT, parse_terms, report_message


class DummyResponse:
    def __init__(self, data=None, status=200, body=""):
        self.data, self.status, self.body = data or {}, status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.data

    async def text(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


class SourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_pubmed_xml_and_cache(self):
        xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID>
        <Article><ArticleTitle>Cannabis &amp; sleep</ArticleTitle>
        <Journal><Title>Science</Title></Journal><Abstract>
        <AbstractText>Uncertain result.</AbstractText></Abstract></Article>
        </MedlineCitation></PubmedArticle></PubmedArticleSet>"""
        fake = FakeSession([DummyResponse({"esearchresult": {"idlist": ["12345", "evil"]}}), DummyResponse(body=xml)])
        science = ScienceSources(fake)
        found = await science.pubmed("Does THC help with sleep?")
        self.assertEqual(found, await science.pubmed("Does THC help with sleep?"))
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(found[0].url, "https://pubmed.ncbi.nlm.nih.gov/12345/")
        self.assertIn("Uncertain result", found[0].abstract)
        self.assertNotIn("evil", fake.calls[1][1]["params"]["id"])

    async def test_empty_search(self):
        fake = FakeSession([DummyResponse({"esearchresult": {"idlist": []}})])
        self.assertEqual(await ScienceSources(fake).pubmed("sleep"), [])
        self.assertEqual(len(fake.calls), 1)

    async def test_cbd_only_question_retrieves_cbd_literature(self):
        fake = FakeSession([
            DummyResponse({"esearchresult": {"idlist": []}}),
            DummyResponse({"esearchresult": {"idlist": []}})])
        science = ScienceSources(fake)
        await science.pubmed("Can CBD help with anxiety?")
        await science.pubmed("How do THC and CBD differ?")
        cbd_term = fake.calls[0][1]["params"]["term"]
        comparison_term = fake.calls[1][1]["params"]["term"]
        self.assertIn("cannabidiol[Title/Abstract]", cbd_term)
        self.assertNotIn("tetrahydrocannabinol[Title/Abstract]", cbd_term)
        self.assertIn("tetrahydrocannabinol[Title/Abstract]", comparison_term)

    async def test_pubchem_allowlisted(self):
        fake = FakeSession([DummyResponse({"PropertyTable": {"Properties": [
            {"CID": 123, "MolecularFormula": "C21H30O2", "MolecularWeight": "314.5"}]}})])
        science = ScienceSources(fake)
        with self.assertRaises(ValueError):
            await science.compound("https://untrusted.example")
        result = await science.compound("THC")
        self.assertEqual(result.url, "https://pubchem.ncbi.nlm.nih.gov/compound/123")
        self.assertIn("delta-9-tetrahydrocannabinol", fake.calls[0][0])

    async def test_clinical_trials_validation(self):
        fake = FakeSession([DummyResponse({"studies": [
            {"protocolSection": {"identificationModule": {
                "nctId": "NCT12345678", "briefTitle": "Example"},
                "statusModule": {"overallStatus": "COMPLETED"}}},
            {"protocolSection": {"identificationModule": {"nctId": "bad"}}}
        ]})])
        studies = await ScienceSources(fake).trials("sleep")
        self.assertEqual(len(studies), 1)
        self.assertEqual(studies[0].url, "https://clinicaltrials.gov/study/NCT12345678")

    async def test_upstream_error(self):
        with self.assertRaises(SourceError):
            await ScienceSources(FakeSession([DummyResponse(status=429)])).pubmed("anxiety")


class AnswerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.studies = [Study("3344", "Reported experiences", "Journal", "Not conclusive evidence.")]

    async def test_without_ai_links_only(self):
        sources = AsyncMock()
        sources.pubmed.return_value = self.studies
        answer = await ResearchAssistant(sources, None).answer("Anxiety?")
        self.assertIn("AI synthesis is not configured", answer)
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/3344/", answer)
        self.assertIn("not proof", answer)

    async def test_no_research_no_claims(self):
        sources = AsyncMock()
        sources.pubmed.return_value = []
        answer = await ResearchAssistant(sources, None).answer("Anything")
        self.assertIn("couldn't find relevant", answer)

    async def test_ai_failure_keeps_valid_links(self):
        sources = AsyncMock()
        sources.pubmed.return_value = self.studies
        ai = AsyncMock()
        ai.generate.side_effect = SourceError("offline")
        answer = await ResearchAssistant(sources, ai).answer("Anxiety?")
        self.assertIn("temporarily unavailable", answer)
        self.assertIn(self.studies[0].url, answer)

    async def test_ai_mentions_are_neutralized(self):
        fake = FakeSession([DummyResponse({"candidates": [{"content": {
            "parts": [{"text": "@everyone uncertain"}]}}]})])
        answer = await GeminiAnswer(fake, "testkey").generate("Question?", self.studies)
        self.assertNotIn("@everyone", answer)
        self.assertIn("@\u200beveryone", answer)
        self.assertEqual(fake.calls[0][1]["headers"]["x-goog-api-key"], "testkey")

    async def test_unverified_ai_link_is_not_displayed(self):
        fake = FakeSession([DummyResponse({"candidates": [{"content": {
            "parts": [{"text": "Check https://unverified.example/bad"}]}}]})])
        answer = await GeminiAnswer(fake, "testkey").generate("Question?", self.studies)
        self.assertNotIn("https://unverified.example", answer)
        self.assertIn("[unverified link omitted]", answer)

    async def test_empty_ai_output(self):
        fake = FakeSession([DummyResponse({"candidates": [{"content": {"parts": []}}]})])
        with self.assertRaises(SourceError):
            await GeminiAnswer(fake, "test").generate("Question?", self.studies)

    async def test_long_ai_output_retains_disclaimer_and_source(self):
        sources = AsyncMock()
        sources.pubmed.return_value = self.studies
        ai = AsyncMock()
        ai.generate.return_value = "x" * 1800
        answer = await ResearchAssistant(sources, ai).answer("Anxiety?")
        self.assertLessEqual(len(answer), 1900)
        self.assertIn(self.studies[0].url, answer)
        self.assertIn(DISCLAIMER, answer)


class EvidenceMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_pubmed_indexed_study_design_and_year(self):
        xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>31415</PMID>
        <Article><ArticleTitle>Clinical research</ArticleTitle><Journal>
        <Title>Medical Review</Title><JournalIssue><PubDate><Year>2025</Year>
        </PubDate></JournalIssue></Journal><PublicationTypeList>
        <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList><Abstract><AbstractText>A limited study.</AbstractText></Abstract>
        </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
        fake = FakeSession([DummyResponse({"esearchresult": {"idlist": ["31415"]}}),
                            DummyResponse(body=xml)])
        found = await ScienceSources(fake).pubmed("THC safety")
        self.assertEqual(found[0].year, "2025")
        self.assertEqual(found[0].publication_types, ("Randomized Controlled Trial",))
        self.assertIn("Randomized controlled trial", study_links(found))
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/31415/", study_links(found))

    async def test_unclassified_study_is_not_labeled_as_proven(self):
        study = Study("55", "A promising title", "Journal", "No quality data")
        result = study_links([study])
        self.assertIn("Design not classified by PubMed", result)
        self.assertNotIn("High quality", result)

    async def test_medline_date_year_fallback(self):
        xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>777</PMID>
        <Article><ArticleTitle>Example</ArticleTitle><Journal><Title>J</Title>
        <JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate>
        </JournalIssue></Journal><PublicationTypeList>
        <PublicationType>Systematic Review</PublicationType>
        </PublicationTypeList></Article></MedlineCitation></PubmedArticle>
        </PubmedArticleSet>"""
        fake = FakeSession([DummyResponse({"esearchresult": {"idlist": ["777"]}}),
                            DummyResponse(body=xml)])
        found = await ScienceSources(fake).pubmed("pain")
        self.assertEqual(found[0].year, "2019")
        self.assertEqual(study_design(found[0].publication_types), "Systematic review")


class OfficialGuideTests(unittest.TestCase):
    def test_official_domains_only(self):
        from urllib.parse import urlparse
        from lab.guidance import GUIDES, guide_message
        allowed = {"www.nccih.nih.gov", "www.cdc.gov", "www.fda.gov"}
        self.assertEqual(len(GUIDES), 6)
        for topic, entry in GUIDES.items():
            message = guide_message(topic)
            self.assertIn("not individualized medical advice", message)
            self.assertLessEqual(len(message), 1900)
            for _, url in entry.links:
                parsed = urlparse(url)
                self.assertEqual(parsed.scheme, "https")
                self.assertIn(parsed.hostname, allowed)
                self.assertIn(url, message)

    def test_unknown_guide_is_rejected(self):
        from lab.guidance import guide_message
        self.assertNotIn("http", guide_message("https://example.com"))



class FDASafetyReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_medicine_query_is_exact_and_bounded(self):
        fake = FakeSession([DummyResponse({
            "meta": {"last_updated": "2026-07-30"},
            "results": [{"term": "NAUSEA", "count": 12},
                        {"term": "FATIGUE", "count": 9}]
        })])
        science = ScienceSources(fake)
        data = await science.fda_reports("epidiolex")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][0], FDA_ENDPOINT)
        params = fake.calls[0][1]["params"]
        self.assertEqual(params["search"], 'patient.drug.medicinalproduct:"EPIDIOLEX"')
        self.assertEqual(params["count"], "patient.reaction.reactionmeddrapt.exact")
        self.assertEqual(params["limit"], 5)
        self.assertNotIn("api_key", params)
        self.assertEqual(data.reactions, (("NAUSEA", 12), ("FATIGUE", 9)))
        self.assertIn("does NOT prove", report_message(data))
        self.assertNotIn("%", report_message(data))

    async def test_invalid_search_cannot_reach_provider(self):
        fake = FakeSession([])
        with self.assertRaises(ValueError):
            await ScienceSources(fake).fda_reports("anything OR cancer")
        self.assertEqual(fake.calls, [])

    async def test_api_key_is_optional_and_not_displayed(self):
        fake = FakeSession([DummyResponse({"results": [{"term": "FATIGUE", "count": 1}]})])
        data = await ScienceSources(fake, openfda_key="super-private").fda_reports("marinol")
        self.assertEqual(fake.calls[0][1]["params"]["api_key"], "super-private")
        self.assertNotIn("super-private", report_message(data))

    async def test_404_means_no_matching_report_terms(self):
        fake = FakeSession([DummyResponse(status=404)])
        data = await ScienceSources(fake).fda_reports("syndros")
        self.assertEqual(data.reactions, ())
        self.assertIn("No matching report terms", report_message(data))

    async def test_openfda_error_does_not_fabricate_result(self):
        fake = FakeSession([DummyResponse(status=429)])
        with self.assertRaises(SourceError):
            await ScienceSources(fake).fda_reports("cesamet")

    def test_malformed_and_untrusted_fda_terms_are_ignored(self):
        payload = {"results": [
            {"term": "@everyone <https://malicious.example>", "count": 2},
            {"term": "FATIGUE", "count": -1},
            {"term": "NAUSEA", "count": 1.5},
            {"term": "HEADACHE", "count": 3}
        ]}
        data = parse_terms(payload, "marinol")
        answer = report_message(data)
        self.assertNotIn("@everyone", answer)
        self.assertNotIn("https://malicious", answer)
        self.assertNotIn("FATIGUE", answer)
        self.assertIn("Headache", answer)

    async def test_cache_avoids_repeat_openfda_hits(self):
        fake = FakeSession([DummyResponse({"results": [{"term": "HEADACHE", "count": 3}]})])
        science = ScienceSources(fake)
        self.assertEqual(await science.fda_reports("epidiolex"),
                         await science.fda_reports("epidiolex"))
        self.assertEqual(len(fake.calls), 1)


class StrainCatalogTests(unittest.TestCase):
    def test_snapshot_index_is_attributed_and_bounded(self):
        from lab.strains import load_catalog, lookup, result_text
        self.assertGreater(len(load_catalog()), 5000)
        self.assertLess(len(load_catalog()), 15000)
        matches = lookup("Northern Lights")
        self.assertTrue(matches)
        self.assertLessEqual(len(matches), 5)
        output = result_text("Northern Lights")
        self.assertIn("Historical", output)
        self.assertIn("2017", output)
        self.assertIn("do not reliably predict", output)
        self.assertNotIn("Pain relief", output)

    def test_lookup_does_not_allow_mass_mentions(self):
        from lab.strains import lookup, result_text
        self.assertEqual(lookup("@everyone"), [])
        self.assertEqual(lookup("a"), [])
        self.assertNotIn("@everyone", result_text("@everyone"))

    def test_mit_license_notice_preserved(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "ATTRIBUTIONS.md"
        notice = path.read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2016-present, Kushy", notice)
        self.assertIn("MIT License", notice)


class DiscordRegistryTests(unittest.TestCase):
    def test_expected_slash_commands(self):
        if importlib.util.find_spec("discord") is None:
            self.skipTest("discord.py not installed in this local environment")
        from lab.bot import bot
        commands = {command.name for command in bot.tree.get_commands()}
        self.assertEqual(commands, {"askthc", "compound", "trials", "labpanel", "scienceguide", "fdareports", "strain"})
        self.assertFalse(bot.intents.message_content)


if __name__ == "__main__":
    unittest.main()



@unittest.skipUnless(importlib.util.find_spec("discord"), "discord.py is required")
class CommandSyncScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_and_configured_guild_are_both_synced(self):
        from lab.bot import bot
        synced = [SimpleNamespace(name=c.name) for c in bot.tree.get_commands()]
        self.assertIn("labpanel", {c.name for c in synced})
        with patch.dict(os.environ, {"DISCORD_GUILD_ID": "1514374173517152418"}):
            with patch.object(bot.tree, "sync", new_callable=AsyncMock) as do_sync:
                with patch.object(bot.tree, "copy_global_to") as copied:
                    do_sync.return_value = synced
                    await bot.sync_commands()
        self.assertEqual(do_sync.await_count, 2)
        self.assertEqual(do_sync.await_args_list[0].kwargs, {})
        self.assertEqual(do_sync.await_args_list[1].kwargs["guild"].id, 1514374173517152418)
        copied.assert_called_once()

    async def test_unconfigured_guild_keeps_global_commands_current(self):
        from lab.bot import bot
        synced = [SimpleNamespace(name=c.name) for c in bot.tree.get_commands()]
        with patch.dict(os.environ, {"DISCORD_GUILD_ID": ""}):
            with patch.object(bot.tree, "sync", new_callable=AsyncMock) as do_sync:
                with patch.object(bot.tree, "copy_global_to") as copied:
                    do_sync.return_value = synced
                    await bot.sync_commands()
        do_sync.assert_awaited_once_with()
        copied.assert_not_called()

    async def test_missing_command_fails_sync_check(self):
        from lab.bot import bot
        with patch.dict(os.environ, {"DISCORD_GUILD_ID": ""}):
            with patch.object(bot.tree, "sync", new_callable=AsyncMock) as do_sync:
                do_sync.return_value = [SimpleNamespace(name="askthc")]
                with self.assertRaisesRegex(RuntimeError, "omitted"):
                    await bot.sync_commands()

@unittest.skipUnless(importlib.util.find_spec("discord"), "discord.py is required")
class PublicPanelTests(unittest.TestCase):
    def test_panel_is_persistent_and_has_five_actions(self):
        from lab.bot import bot
        from lab.panel import LabPanelView, panel_embed, TOPICS
        view = LabPanelView(bot)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 5)
        ids = [item.custom_id for item in view.children]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(x.startswith("the420lab:panel:v1:") for x in ids))
        self.assertIn("Answers are private", panel_embed().footer.text)
        self.assertIn("risks", TOPICS)

    def test_library_exposes_official_guides(self):
        from lab.bot import bot
        from lab.panel import LibraryMenu, OfficialGuideSelect
        menu = LibraryMenu(bot, 123)
        self.assertIn("Official NIH / CDC / FDA Guides", [item.label for item in menu.children])
        self.assertEqual(len(OfficialGuideSelect().options), 6)

    def test_library_shows_fda_safety_reports(self):
        from lab.bot import bot
        from lab.panel import LibraryMenu, FDAProductSelect
        menu = LibraryMenu(bot, 123)
        self.assertIn("FDA Safety Reports", [item.label for item in menu.children])
        self.assertEqual(len(FDAProductSelect().options), 4)

    def test_library_has_strain_reference(self):
        from lab.bot import bot
        from lab.panel import LibraryMenu
        self.assertIn("Strain Name Reference",
                      [item.label for item in LibraryMenu(bot, 123).children])

    def test_panel_cooldown_is_bounded(self):
        from lab.bot import bot
        bot._panel_access.clear()
        self.assertEqual(bot.panel_wait(9001001), 0)
        self.assertGreater(bot.panel_wait(9001001), 0)
        bot._panel_access.clear()

    def test_publish_command_requires_manage_guild(self):
        from lab.bot import bot
        command = bot.tree.get_command("labpanel")
        self.assertTrue(command.default_permissions.manage_guild)
