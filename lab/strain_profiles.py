"""Provenance-aware strain profiles, opt-in community scores and catalog health.

Never copies Leafly reviews. Owner-added descriptions and images require a
declared reuse basis and source. Ratings are first-party, anonymous in output,
and scoped to servers that have opted in.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from urllib.parse import urlsplit
from pathlib import Path

from .strains import (
    compact, find_matches, load_catalog, load_modern_catalog,
    load_leafly_name_mirror, _index,
)

FIRST_INDEXED = "2026-10-20"
CANNLYTICS_RESULTS = "https://huggingface.co/datasets/cannlytics/cannabis_results"
CANNLYTICS_API = "https://cannlytics.com/api"
COMMONS_SEARCH = "https://commons.wikimedia.org/wiki/Special:MediaSearch"


def catalog_counts() -> dict[str, int]:
    names, _ = _index()
    return {
        "distinct": len(names),
        "kushy": len(load_catalog()),
        "ci": len(load_modern_catalog()),
        "historical_leafly_added": len(load_leafly_name_mirror()),
    }


def _url(value: str, *, optional: bool = False) -> str:
    if not value and optional:
        return ""
    if len(value) > 450 or any(c in value for c in ("\n", "\r", "<", ">", "@")):
        raise ValueError("Use a short public HTTPS source URL")
    url = urlsplit(value)
    host = (url.hostname or "").lower()
    if (url.scheme != "https" or not host or "." not in host
            or host.endswith(".local") or host == "localhost"
            or url.username or url.password
            or re.match(r"^\d+\.\d+\.\d+\.\d+$", host)):
        raise ValueError("Use a public HTTPS URL, not a local or credentialed address")
    return value


def _summary(value: str) -> str:
    value = re.sub(r"[<>@\x00-\x1f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not 15 <= len(value) <= 550:
        raise ValueError("Description must contain 15 to 550 characters")
    return value


class StrainProfileStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("LAB_STRAIN_DB_PATH", "strain-profiles.sqlite3")
        file = Path(self.path)
        if str(file.parent) not in ("", "."):
            file.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS curated_profiles (
                name_key TEXT PRIMARY KEY, description TEXT NOT NULL,
                source_url TEXT NOT NULL, image_url TEXT NOT NULL,
                rights TEXT NOT NULL, updated_utc TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS server_config (
                guild TEXT PRIMARY KEY, reviews_enabled INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS strain_votes (
                guild TEXT NOT NULL, name_key TEXT NOT NULL,
                voter_hash TEXT NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                updated_utc TEXT NOT NULL,
                PRIMARY KEY (guild, name_key, voter_hash)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('salt',?)",
                       (secrets.token_hex(32),))

    def _connect(self):
        return sqlite3.connect(self.path, timeout=3.0)

    def save_curated(self, name: str, description: str, source: str,
                     image_url: str, rights: str):
        key = compact(name)
        if not 2 <= len(key) <= 60:
            raise ValueError("Enter a valid strain name")
        if rights not in ("original", "cc-by-4.0", "licensed"):
            raise ValueError("Rights must be original, cc-by-4.0, or licensed")
        if not find_matches(name):
            raise ValueError("First select a name in the catalog")
        info = _summary(description)
        link = _url(source)
        picture = _url(image_url, optional=True)
        updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with closing(self._connect()) as db, db:
            db.execute("""INSERT INTO curated_profiles VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name_key) DO UPDATE SET
                description=excluded.description,source_url=excluded.source_url,
                image_url=excluded.image_url,rights=excluded.rights,
                updated_utc=excluded.updated_utc""",
                (key, info, link, picture, rights, updated))

    def remove_curated(self, name: str):
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM curated_profiles WHERE name_key=?",
                       (compact(name),))

    def curated(self, name: str):
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT description,source_url,image_url,rights,updated_utc "
                "FROM curated_profiles WHERE name_key=?", (compact(name),)).fetchone()

    def set_reviews_enabled(self, guild_id: int, enabled: bool):
        with closing(self._connect()) as db, db:
            db.execute("""INSERT INTO server_config VALUES(?,?)
                ON CONFLICT(guild) DO UPDATE SET reviews_enabled=excluded.reviews_enabled""",
                (str(guild_id), int(enabled)))

    def clear_reviews(self, guild_id: int):
        """Owner-requested hard deletion of this server's user vote history."""
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM strain_votes WHERE guild=?", (str(guild_id),))

    def reviews_enabled(self, guild_id: int) -> bool:
        with closing(self._connect()) as db:
            result = db.execute(
                "SELECT reviews_enabled FROM server_config WHERE guild=?",
                (str(guild_id),)).fetchone()
        return bool(result and result[0])

    def rate(self, guild_id: int, user_id: int, name: str, score: int):
        if type(score) is not int or not 1 <= score <= 5:
            raise ValueError("Rating must be 1–5")
        if not self.reviews_enabled(guild_id):
            raise ValueError("This server has not enabled community ratings")
        entries = find_matches(name)
        if not entries or entries[0].approximate or compact(entries[0].name) != compact(name):
            raise ValueError("Use an exact strain name from the catalog")
        key = compact(name)
        with closing(self._connect()) as db, db:
            salt = db.execute(
                "SELECT value FROM metadata WHERE key='salt'").fetchone()[0]
            identity = hmac.new(bytes.fromhex(salt),
                                f"{guild_id}:{user_id}".encode(),
                                hashlib.sha256).hexdigest()
            db.execute("""INSERT INTO strain_votes VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(guild,name_key,voter_hash) DO UPDATE SET
                rating=excluded.rating,updated_utc=excluded.updated_utc""",
                (str(guild_id), key, identity, score,
                 datetime.now(timezone.utc).strftime("%Y-%m-%d")))

    def review_stats(self, guild_id: int, name: str) -> tuple[int, float | None]:
        if not self.reviews_enabled(guild_id):
            return 0, None
        with closing(self._connect()) as db:
            count, avg = db.execute(
                "SELECT COUNT(*), AVG(rating) FROM strain_votes "
                "WHERE guild=? AND name_key=?",
                (str(guild_id), compact(name))).fetchone()
        return count, round(avg, 2) if avg is not None else None


def database_embed():
    import discord
    from .leafly import VERIFIED_PROFILES
    counts = catalog_counts()
    embed = discord.Embed(
        title="🌿 The Weed Doctor | Strain Database",
        description=f"**{counts['distinct']:,} distinct searchable names**\n"
                    "Locally packaged indexes, not a live Leafly mirror.",
        color=0x127B52)
    embed.add_field(name="Catalog sources",
        value=(f"**Kushy (MIT):** {counts['kushy']:,} entries • snapshot 2017-11-14\n"
               f"**CI-Strains-Pro (CC BY 4.0):** {counts['ci']:,} entries • release 2026\n"
               f"**Historic Leafly-name mirror:** +{counts['historical_leafly_added']:,} "
               "previously missing names • source data date not verified\n"
               f"**Verified Leafly profile links:** {len(VERIFIED_PROFILES)}"),
        inline=False)
    embed.add_field(name="Freshness and updates",
        value=(f"**Current packaged index assembled:** {FIRST_INDEXED}\n"
               "No automatic Leafly sync. A newer app deployment does not imply "
               "the source datasets were updated."),
        inline=False)
    embed.add_field(name="Detail sources",
        value=("**Live botanical context:** [CannaLib](https://cannalib.org/api/) " 
               "(read-only attributed lookup; separate from our local count).\n"
               "**Credited short descriptions:** [Flower & Freedom](https://flowerandfreedom.com/api/) "
               "(free on-demand records; source-reported effects, exact update dates and sample context).\n"
               "**Alternative profiles:** [StrainAPI](https://www.strainapi.com/docs/) " 
               "(on-demand breeder, lineage and terpene fields, separate from name index).\n"
               "**Community descriptions and photos:** Leafly original pages; "
               "only permission-cleared content is shown inside Discord.\n"
               "**Lab reports:** [Cannlytics public results](" + CANNLYTICS_RESULTS
               + ") (sample-specific, not strain-wide potency).\n"
               "**Photos:** [Wikimedia Commons](" + COMMONS_SEARCH
               + ") (check individual image license).\n"
               "**Community rating:** Optional, original ratings from this server."),
        inline=False)
    embed.set_footer(text="Names do not establish genetics, effects or lab potency • Source dates ≠ deployment date")
    return embed



def source_directory_embed():
    """Public guide to what each provider actually supplies."""
    import discord
    embed = discord.Embed(
        title="🔬 The Weed Doctor | Sources & Content Rights",
        description=(
            "Different sources answer different questions. "
            f"**{catalog_counts()['distinct']:,}** local search names are not "
            "the same number of lab-tested profiles, photos, or current review pages."
        ),
        color=0x127B52)
    embed.add_field(
        name="🌼 Flower & Freedom | Original credited summaries",
        value=(
            "[Free read-only API](https://flowerandfreedom.com/api/) • "
            "Now connected on demand before other botanical references, "
            "with a one-hour bounded cache. About 50 published profiles "
            "contain short original descriptions, reported aromas, "
            "source update dates and sample-qualified laboratory context. "
            "This is a smaller, independent dataset, not Leafly content. "
            "No images or community review counts are included."
        ), inline=False)
    embed.add_field(
        name="🧬 CannaLib | Source-attributed cultivar facts",
        value=(
            "[CannaLib API](https://cannalib.org/api/) • Connected on demand, "
            "with API safety limits. Breeder, catalog type, reported terpenes "
            "and sourced chemical ranges when available. Free access requires "
            "attribution; no bulk syncing. **Not a Leafly review feed.**"
        ), inline=False)
    embed.add_field(
        name="⭐ Find My Seeds | Public community score and photo source",
        value=(
            "[Free strain API](https://www.findmyseeds.com/find-my-seeds-public-api/) "
            "• Connected as an exact-name, on-demand lookup with a bounded "
            "one-hour cache. Where available, shows the provider's short "
            "overview, reported effects and flavors, **its own rating and "
            "review count**, with a link to the original page and photos. "
            "This is not a Leafly score or a lab-tested effect."
        ), inline=False)
    embed.add_field(
        name="🌱 StrainAPI | Additional descriptions and claims",
        value=(
            "[StrainAPI documentation](https://www.strainapi.com/docs/) • "
            "Connected as an on-demand fallback, with an exact-name check. "
            "Displays short attributed breeder, lineage, terpene, aroma and "
            "flavor fields. Full descriptions and images are **not** copied "
            "into our database without appropriate reuse rights."
        ), inline=False)
    embed.add_field(
        name="🧪 Cannlytics | Real lab certificates",
        value=(
            "[Cannlytics Cannabis Results](https://github.com/cannlytics/cannabis_results) "
            "• Separate public dataset (CC BY 4.0, subject to third-party rights), "
            "reporting many sample-level COAs from multiple states. "
            "Useful for actual batch cannabinoid/terpene measurements and testing dates. "
            "**Not yet linked into each strain profile**, and never a universal potency claim."
        ), inline=False)
    embed.add_field(
        name="📸 Pictures & referenced descriptions",
        value=(
            "[Find My Seeds API](https://www.findmyseeds.com/find-my-seeds-public-api/) "
            "provides community review counts, profile photos and descriptions "
            "on its public profiles; image re-use rights and API stability "
            "must be confirmed before embedding third-party media. "
            "[Wikimedia Commons](https://commons.wikimedia.org/wiki/Special:MediaSearch) "
            "may provide reusable images, but each photo has its **own** license. "
            "[Leafly](https://www.leafly.com/strains) has individual community "
            "profiles; proprietary media/reviews aren't imported. The app owner "
            "can add a credited description and licensed picture using "
            "**/doctorstrainset**. No fake stock photo or review counts."
        ), inline=False)
    embed.add_field(
        name="⭐ Community ratings & update dates",
        value=(
            "Our own optional per-server ratings come from **/strainrate**, "
            "enabled by **/strainreviews**. They are **not** Leafly ratings. "
            "Use **/straindb** for exact local-name counts and source dates: "
            "Kushy 2017, CI-Strains-Pro 2026 and an undated historical mirror. "
            "External provider updates do not automatically refresh those local files."
        ), inline=False)
    embed.set_footer(
        text="Community opinions ≠ medical evidence • Specific batch COAs ≠ strain-wide promises")
    return embed


def strain_embed(name: str, guild_id: int | None, store: StrainProfileStore):
    import discord
    from .leafly import profile_for, leafly_search_url
    matches = find_matches(name, limit=3)
    exact = matches and compact(matches[0].name) == compact(name) and not matches[0].approximate
    display = matches[0].name if exact else name
    embed = discord.Embed(
        title="🌿 Strain profile | " + display[:80],
        color=0x127B52)
    if exact:
        first = matches[0]
        facts = (f"**Catalog type:** {first.kind}\n"
                 f"**Source:** {', '.join(first.sources)}")
        if first.breeder and first.breeder.lower() not in ("unknown breeder", "none"):
            facts += f"\n**Listed breeder:** {first.breeder}"
        embed.add_field(name="Name reference", value=facts[:950], inline=False)
    else:
        embed.add_field(name="Name not verified", value=(
            "No exact catalog match. Try /straininfo for spelling suggestions. "
            "The link below is not a confirmed individual strain profile."), inline=False)
    curator = store.curated(display) if exact else None
    if curator:
        description, url, image_url, rights, updated = curator
        embed.add_field(name="Credited description", value=description, inline=False)
        embed.add_field(name="Description provenance",
                        value=f"[Original source]({url}) • Rights: {rights} • saved {updated}",
                        inline=False)
        if image_url:
            embed.set_image(url=image_url)
    else:
        embed.add_field(name="Description & photo", value=(
            "No reuse-authorized description or image has been provided for this name. "
            "See the original reference or an independently licensed source."), inline=False)
    profile = profile_for(display)
    if profile:
        embed.add_field(name="Leafly community profile",
                        value=f"[View original profile]({profile[1]}) "
                              "(external user reports, not clinical evidence)", inline=False)
    else:
        site = leafly_search_url(display)
        if site:
            embed.add_field(name="Leafly search",
                            value=f"[Search possible matches]({site}) (not a verified profile)",
                            inline=False)
    if guild_id:
        if store.reviews_enabled(guild_id):
            count, average = store.review_stats(guild_id, display)
            value = (f"{average:.2f}/5 from {count} unique server raters"
                     if count else "No community ratings yet. Use /strainrate.")
        else:
            value = "Disabled in this server. Managers may opt in using /strainreviews."
        embed.add_field(name="The Weed Doctor community rating", value=value,
                        inline=False)
    embed.add_field(
        name="Other research",
        value=f"[Independent sample-specific lab results]({CANNLYTICS_RESULTS}). "
              "A lab sample is not proof of potency for all products with this name.",
        inline=False)
    embed.set_footer(text="Catalog labels and community scores are not medical advice.")
    return embed
