"""Read-only, bounded PubMed, PubChem and ClinicalTrials.gov adapters."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import re
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET
import aiohttp

NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
TRIALS = "https://clinicaltrials.gov/api/v2/studies"
COMPOUNDS = {
    "THC": "delta-9-tetrahydrocannabinol",
    "CBD": "cannabidiol",
    "CBG": "cannabigerol",
    "CBN": "cannabinol",
    "THCA": "tetrahydrocannabinolic acid",
}


class SourceError(Exception):
    """Source failed or provided unusable data."""


@dataclass(frozen=True)
class Study:
    pmid: str
    title: str
    journal: str
    abstract: str

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


@dataclass(frozen=True)
class Compound:
    name: str
    cid: int
    formula: str
    molecular_weight: str

    @property
    def url(self) -> str:
        return f"https://pubchem.ncbi.nlm.nih.gov/compound/{self.cid}"


@dataclass(frozen=True)
class Trial:
    nct_id: str
    title: str
    status: str

    @property
    def url(self) -> str:
        return f"https://clinicaltrials.gov/study/{self.nct_id}"


class ScienceSources:
    """One session per process, with bounded cache and NIH rate pacing."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str = ""):
        self.session = session
        self.api_key = api_key
        self._cache: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
        self._ncbi_lock = asyncio.Lock()
        self._next_ncbi = 0.0

    async def _pace_ncbi(self):
        # 2.5 requests/second, below the unkeyed NCBI 3/second limit.
        async with self._ncbi_lock:
            await asyncio.sleep(max(0, self._next_ncbi - time.monotonic()))
            self._next_ncbi = time.monotonic() + .4

    async def _json(self, url: str, params: dict | None = None, *, ncbi: bool = False) -> dict:
        if ncbi:
            await self._pace_ncbi()
        try:
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    raise SourceError(f"Research provider HTTP {response.status}")
                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    raise SourceError("Unexpected response data")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise SourceError("Research provider unavailable") from exc

    async def _xml(self, url: str, params: dict) -> ET.Element:
        await self._pace_ncbi()
        try:
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    raise SourceError(f"PubMed HTTP {response.status}")
                body = await response.text()
            return ET.fromstring(body)
        except (aiohttp.ClientError, asyncio.TimeoutError, ET.ParseError) as exc:
            raise SourceError("PubMed detail unavailable") from exc

    async def _cached(self, key: tuple, factory):
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            self._cache.move_to_end(key)
            return cached[1]
        result = await factory()
        self._cache[key] = (time.monotonic() + 900, result)
        self._cache.move_to_end(key)
        while len(self._cache) > 256:
            self._cache.popitem(last=False)
        return result

    async def pubmed(self, question: str) -> list[Study]:
        question = question.strip()[:220]
        if not question:
            return []
        return await self._cached(("pubmed", question.lower()), lambda: self._pubmed(question))

    async def _pubmed(self, question: str) -> list[Study]:
        stopwords = {"what", "does", "with", "about", "could", "would", "should", "which", "these",
                     "those", "have", "been", "from", "they", "them", "that", "this", "are",
                     "can", "the", "and", "for", "how", "why", "thc", "cbd", "cannabis", "weed",
                     "marijuana", "cannabinoids"}
        words = [word for word in re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", question.lower())
                 if word not in stopwords]
        keywords = list(dict.fromkeys(words))[:4]
        term = "(cannabis[Title/Abstract] OR cannabinoid*[Title/Abstract] OR tetrahydrocannabinol[Title/Abstract])"
        if keywords:
            term += " AND (" + " OR ".join(f"{w}[Title/Abstract]" for w in keywords) + ")"
        params = {"db": "pubmed", "term": term, "retmode": "json", "retmax": "3",
                  "sort": "relevance", "tool": "The420Lab"}
        if self.api_key:
            params["api_key"] = self.api_key
        result = await self._json(f"{NCBI}/esearch.fcgi", params, ncbi=True)
        ids = [str(i) for i in result.get("esearchresult", {}).get("idlist", [])
               if str(i).isdigit()][:3]
        if not ids:
            return []
        params = {"db": "pubmed", "id": ",".join(ids), "rettype": "abstract",
                  "retmode": "xml", "tool": "The420Lab"}
        if self.api_key:
            params["api_key"] = self.api_key
        root = await self._xml(f"{NCBI}/efetch.fcgi", params)
        studies = []
        for item in root.findall(".//PubmedArticle"):
            pmid = item.findtext(".//MedlineCitation/PMID", "").strip()
            if not pmid.isdigit():
                continue
            node = item.find(".//Article/ArticleTitle")
            title = "".join(node.itertext()).strip() if node is not None else "Untitled"
            journal = item.findtext(".//Article/Journal/Title", "Unknown journal").strip()
            sections = item.findall(".//Article/Abstract/AbstractText")
            abstract = " ".join(" ".join(n.itertext()).strip() for n in sections).strip()
            studies.append(Study(pmid, title[:220], journal[:120], abstract[:2400]))
        return studies

    async def compound(self, name: str) -> Compound | None:
        name = name.upper().strip()
        if name not in COMPOUNDS:
            raise ValueError("Unsupported cannabinoid")
        return await self._cached(("compound", name), lambda: self._compound(name))

    async def _compound(self, name: str) -> Compound | None:
        encoded = quote(COMPOUNDS[name], safe="")
        url = f"{PUBCHEM}/compound/name/{encoded}/property/MolecularFormula,MolecularWeight/JSON"
        result = await self._json(url)
        rows = result.get("PropertyTable", {}).get("Properties", [])
        if not rows:
            return None
        row = rows[0]
        return Compound(name, int(row["CID"]), str(row.get("MolecularFormula", "Unknown")),
                        str(row.get("MolecularWeight", "Unknown")))

    async def trials(self, topic: str) -> list[Trial]:
        topic = topic.strip()[:100]
        if not topic:
            return []
        return await self._cached(("trials", topic.lower()), lambda: self._trials(topic))

    async def _trials(self, topic: str) -> list[Trial]:
        data = await self._json(TRIALS, {"query.term": f"cannabis AND {topic}", "pageSize": 5, "format": "json"})
        results = []
        for item in data.get("studies", []):
            section = item.get("protocolSection", {})
            ident = section.get("identificationModule", {})
            nct = str(ident.get("nctId", ""))
            if not re.fullmatch(r"NCT\d{8}", nct):
                continue
            results.append(Trial(nct, str(ident.get("briefTitle", "Untitled trial"))[:220],
                                 str(section.get("statusModule", {}).get("overallStatus", "Unknown"))))
        return results
