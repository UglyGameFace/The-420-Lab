"""Single-processor, restart-safe R2 stage queue for the Grower Showcase."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import discord

from .grower_commands import _post_permissions, _submission_card
from .grower_intake import IntakeError

log = logging.getLogger(__name__)


async def deliver_one(bot, job):
    """Never retry ambiguous Discord sends automatically."""
    guild_id, sid, key, review_id = job
    try:
        guild = bot.get_guild(int(guild_id))
        if guild is None:
            raise ValueError("Grower guild is not currently in the gateway cache")
        channel = guild.get_channel(int(review_id))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Original grower review channel was removed")
        if (not channel.is_nsfw()
                or channel.permissions_for(guild.default_role).view_channel
                or not guild.me or not _post_permissions(channel, guild.me)):
            raise ValueError("Original grower review channel is not private/age-restricted")
        row = bot.growers.item(int(guild_id), sid)
        if row is None or row[8] != "uploading":
            raise ValueError("Queued grower record changed before processing")
        with TemporaryDirectory(prefix="grower-stage-") as tmp:
            original = Path(tmp) / "original"
            normalized = Path(tmp) / "clean.jpg"
            await bot.grower_intake.download(key, original)
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "lab.grower_image_worker",
                str(original), str(normalized),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=35)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise ValueError("Grower image sanitization timed out")
            if proc.returncode != 0:
                # Do not expose original image contents or filenames in logs.
                raise ValueError("Grower image could not be sanitized")
            # This is the only Discord post. If the response is lost, the
            # submission remains 'uploading' for moderator reconciliation.
            with normalized.open("rb") as source:
                post = await channel.send(
                    embed=_submission_card(
                        row[2], row[3], row[4], row[5],
                        approved=False, submission_id=sid),
                    file=discord.File(source, filename="grower.jpg"),
                    allowed_mentions=discord.AllowedMentions.none())
            bot.growers.finish_staged_upload(int(guild_id), sid, post.id)
        # R2 deletion is best-effort; retain durable 'cleanup' record on failure.
        try:
            await bot.grower_intake.delete(key)
            bot.growers.stage_cleanup(int(guild_id), sid)
        except Exception:
            log.exception("Grower staging cleanup delayed id=%s", sid)
    except asyncio.CancelledError:
        raise
    except Exception:
        # A failed or uncertain Discord send must not be retried blindly.
        log.exception("Grower processing interrupted id=%s; staff recovery required", sid)


async def run_queue(bot):
    """One consumer for this bot process; SQLite claims are atomic."""
    try:
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                expired = bot.growers.expire_queued()
                if expired:
                    log.warning("Expired %d waiting grower image(s) after 30 minutes", expired)
                for guild, sid, key in bot.growers.cleanup_entries():
                    try:
                        await bot.grower_intake.delete(key)
                        bot.growers.stage_cleanup(int(guild), sid)
                    except Exception:
                        log.exception("Grower queue cleanup retry id=%s", sid)
                item = bot.growers.claim_stage()
                if item is not None:
                    await deliver_one(bot, item)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Grower queue cycle failed")
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        return
