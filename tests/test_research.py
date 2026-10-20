"""Network-mocked regression tests. No live tokens required."""
import unittest
from unittest.mock import AsyncMock
from lab.answers import GeminiAnswer, ResearchAssistant
from lab.sources import ScienceSources, SourceError, Study


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
        self.assertIn("Educational information", answer)


if __name__ == "__main__":
    unittest.main()
