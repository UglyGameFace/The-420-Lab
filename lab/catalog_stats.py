"""Transparent coverage and freshness reports for locally bundled strain catalogs."""
from __future__ import annotations
from datetime import datetime, timezone
from functools import lru_cache
import discord

from .strains import _index, load_catalog, load_modern_catalog, load_leafly_name_mirror

CATALOG_BUILD_UTC = "2026-10-20"
SOURCE_LINKS = {
    "Kushy 2017": "https://github.com/kushyapp/cannabis-dataset",
    "CI-Strains-Pro 2026": "https://github.com/Shannon-Goddard/ci-strains-pro",
    "Historical Leafly-name mirror": "https://github.com/iboc/cannabis",
}


@lru_cache(maxsize=1)
def catalog_stats() -> dict[str, int]:
    index, aliases = _index()
    return {
        "searchable": len(index),
        "legacy_rows": len(load_catalog()),
        "modern_rows": len(load_modern_catalog()),
        "leafly_new_names": len(load_leafly_name_mirror()),
        "aliases": len(aliases),
        "source_count": 3,
    }


def catalog_embed() -> discord.Embed:
    counts = catalog_stats()
    embed = discord.Embed(
        title="🌿 The Weed Doctor | Strain Database",
        description=(
            f"**{counts['searchable']:,} distinct searchable names** from "
            "three historical and openly attributed name catalogs.\n"
            "These are names and product listings, **not 30,000 lab-verified cultivars**."
        ),
        color=0x127B52,
    )
    embed.add_field(
        name="📚 Coverage",
        value=(
            f"• Kushy 2017: **{counts['legacy_rows']:,}** rows\n"
            f"• CI-Strains-Pro 2026: **{counts['modern_rows']:,}** rows\n"
            f"• Historical Leafly-name supplement: **{counts['leafly_new_names']:,}** "
            "additional names\n"
            f"• Published aliases recorded: **{counts['aliases']:,}**\n"
            "Overlapping names are deduplicated; figures should not be added together."
        ),
        inline=False,
    )
    embed.add_field(
        name="🗓️ Freshness",
        value=(
            "Local index assembled: **20 October 2026**.\n"
            "Source snapshots: **Kushy 14 Nov 2017**, "
            "**CI-Strains-Pro 2026**, historical Leafly mirror "
            "(source records individually undated).\n"
            "Catalogs **do not live-sync**; outside source updates are not automatically imported."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔎 Detailed profiles and data quality",
        value=(
            "**/strainprofile**: Source-attributed botanical and chemistry context "
            "where available, plus Leafly community-profile links.\n"
            "**Cannlytics:** batch-specific laboratory data; "
            "not interchangeable with average strain ratings.\n"
            "Licensed descriptions/photos/reviews display only when rights and actual "
            "content are available."
        ),
        inline=False,
    )
    embed.add_field(
        name="📄 Sources",
        value=(
            "[Kushy MIT](https://github.com/kushyapp/cannabis-dataset) • "
            "[CI-Strains-Pro CC BY 4.0](https://github.com/Shannon-Goddard/ci-strains-pro) • "
            "[Historical Leafly-name mirror](https://github.com/iboc/cannabis)\n"
            "[CannaLib API](https://cannalib.org/api/) • "
            "[Cannlytics lab data](https://cannlytics.com/api) • "
            "[Leafly](https://www.leafly.com/strains)"
        ),
        inline=False,
    )
    embed.set_footer(
        text="Local catalog counts only • No user tracking • No guaranteed potency or medical benefit"
    )
    return embed
