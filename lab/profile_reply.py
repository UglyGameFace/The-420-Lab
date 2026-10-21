"""One shared rich profile builder for slash commands and public panel forms."""
from __future__ import annotations
import logging

from .strain_profiles import strain_embed
from .rich_sources import sourced_summary

logger = logging.getLogger(__name__)


async def build_strain_profile(bot, name: str, guild_id: int | None):
    """Keep name, independent descriptions and server review stats together."""
    embed = strain_embed(name, guild_id, bot.strain_profiles)
    try:
        facts = await sourced_summary(bot.http_session, bot.quota, name)
    except Exception:
        logger.exception("Independent strain providers unavailable")
        facts = "Independent strain information is temporarily unavailable."
    # Cannlytics is optional, requires a private API key and never overrides
    # the independently sourced profiles or falsely promises batch potency.
    try:
        from .cannlytics_client import strain_summary
        extra = await strain_summary(bot.http_session, bot.quota, name)
        if extra:
            embed.add_field(name="🧪 Cannlytics strain information",
                            value=extra[:1024], inline=False)
    except Exception:
        logger.info("Cannlytics lookup skipped")

    if facts.startswith("**"):
        embed.add_field(
            name="🧬 Source-confirmed details & community reports",
            value=facts[:1024],
            inline=False,
        )
    else:
        embed.add_field(
            name="Additional source status",
            value="No additional name-matched provider details could be verified "
                  "right now. Use the linked source profiles for their latest information.",
            inline=False,
        )
    return embed
