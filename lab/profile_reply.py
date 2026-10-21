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

    # A curator-provided exact-cultivar photo always wins. Otherwise show a
    # credited *representative* real flower image, never mislabel its strain.
    if not embed.image.url:
        try:
            from .strain_media import commons_fallback
            service = getattr(bot, "strain_photo_service", None)
            photo = await service.photo() if service else commons_fallback()
            embed.set_image(url=photo.image_url)
            embed.add_field(
                name="📷 Real cannabis flower photograph",
                value=(f"**Illustrative photo only:** Not verified as {name[:60]}. "
                       f"Photo by {photo.photographer} • [{photo.source}]({photo.source_page})."),
                inline=False)
        except Exception:
            logger.info("Photo provider unavailable; keeping source-linked profile")
    embed.add_field(
        name="🧬 Independently sourced details & community reports",
        value=facts[:1024],
        inline=False,
    )
    return embed
