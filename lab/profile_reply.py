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
    embed.add_field(
        name="🧬 Independently sourced details & community reports",
        value=facts[:1024],
        inline=False,
    )
    return embed
