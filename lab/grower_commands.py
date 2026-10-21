"""Discord entry points for the opt-in, per-server Grower Showcase."""
from __future__ import annotations

import asyncio
from io import BytesIO
import logging

import discord
from discord import app_commands

from .growers import MAX_UPLOAD_BYTES, STAGES, clean_caption, photo_as_jpeg, verified_strain

log = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()


def _configured_channels(interaction: discord.Interaction, hub):
    if interaction.guild is None:
        raise ValueError("The Grower Showcase only works in servers.")
    config = hub.configuration(interaction.guild_id)
    if not config:
        raise ValueError("A server manager must run /growerconfig before using the showcase.")
    review = interaction.guild.get_channel(int(config[0]))
    gallery = interaction.guild.get_channel(int(config[1]))
    if not isinstance(review, discord.TextChannel) or not isinstance(gallery, discord.TextChannel):
        raise ValueError("Showcase channels have changed. Ask a manager to rerun /growerconfig.")
    return review, gallery, bool(config[2])


def _post_permissions(channel: discord.TextChannel, member: discord.Member) -> bool:
    perms = channel.permissions_for(member)
    return all((perms.view_channel, perms.send_messages, perms.attach_files,
                perms.embed_links, perms.read_message_history))


def _submission_card(byline: str, strain: str, stage: str, caption: str,
                     *, approved: bool) -> discord.Embed:
    card = discord.Embed(
        title=f"🌿 {strain[:65]} | Grower Showcase" if approved else "🌱 Grower photo awaiting review",
        color=0x127B52,
    )
    card.add_field(name="Grower", value=byline, inline=True)
    card.add_field(name="Reported stage", value=stage.title(), inline=True)
    card.add_field(name="Reported strain", value=strain, inline=False)
    if caption:
        card.add_field(name="Grow notes", value=caption[:220], inline=False)
    card.set_image(url="attachment://grower.jpg")
    card.set_footer(text=(
        "Member-submitted identification, not genetically verified. "
        "Original photo shared with this server by its contributor."
    ))
    return card


async def _remove_message(channel: discord.TextChannel, message_id: int, bot) -> None:
    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        return
    if message.author.id != bot.user.id:
        raise ValueError("A showcase message no longer belongs to this bot.")
    await message.delete()


async def _remove_submission(interaction: discord.Interaction, bot, submission_id: int,
                             *, user_id: int | None) -> None:
    hub = bot.growers
    review, gallery, _ = _configured_channels(interaction, hub)
    row = hub.lock(interaction.guild_id, submission_id, purpose="remove", user_id=user_id)
    try:
        if row[7]:
            await _remove_message(gallery, int(row[7]), bot)
        await _remove_message(review, int(row[6]), bot)
        hub.delete(interaction.guild_id, submission_id, "removing")
    except Exception:
        hub.unlock(interaction.guild_id, submission_id, row[8])
        raise


def register_grower_commands(bot) -> None:
    """Install once onto the existing command tree; no new Discord client."""

    @bot.tree.command(name="growerconfig", description="Manager: enable a private-reviewed grower photo gallery")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        review_channel="Private, age-restricted staff review channel",
        gallery_channel="Age-restricted community gallery channel",
        enabled="Allow new submissions (disabling preserves published photos)",
    )
    async def growerconfig(interaction: discord.Interaction,
                           review_channel: discord.TextChannel,
                           gallery_channel: discord.TextChannel,
                           enabled: bool = True):
        if review_channel.id == gallery_channel.id:
            await interaction.response.send_message("Review and gallery channels must differ.", ephemeral=True)
            return
        if review_channel.permissions_for(interaction.guild.default_role).view_channel:
            await interaction.response.send_message(
                "Choose a private review channel that @everyone cannot see.", ephemeral=True)
            return
        if not review_channel.is_nsfw() or not gallery_channel.is_nsfw():
            await interaction.response.send_message(
                "Both channels must be marked age-restricted for this showcase.", ephemeral=True)
            return
        member = interaction.guild.me
        if not member or not (_post_permissions(review_channel, member)
                              and _post_permissions(gallery_channel, member)):
            await interaction.response.send_message(
                "I need View Channel, Send Messages, Attach Files, Embed Links and Read History "
                "in both channels.", ephemeral=True)
            return
        try:
            bot.growers.configure(interaction.guild_id, review_channel.id,
                                  gallery_channel.id, enabled)
        except Exception:
            log.exception("Unable to configure grower showcase")
            await interaction.response.send_message("Showcase storage is unavailable.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Grower submissions **{'enabled' if enabled else 'paused'}**. "
            f"Staff review: {review_channel.mention}. Approved gallery: {gallery_channel.mention}. "
            "Photos remain server-only, and contributors can withdraw them.",
            ephemeral=True, allowed_mentions=NO_MENTIONS)

    @bot.tree.command(name="growersubmit", description="Contribute your own grow photo for staff-reviewed display")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.describe(
        strain="Exact strain catalog name, not a guessed identity",
        stage="Stage shown in your photograph",
        photo="An original JPEG, PNG, or WebP photo (up to 8 MiB)",
        notes="Optional notes for viewers, no links or personal details",
        permission="Confirm you took the photo and allow display in this server",
    )
    @app_commands.choices(stage=[app_commands.Choice(name=s.title(), value=s) for s in STAGES])
    async def growersubmit(interaction: discord.Interaction, strain: app_commands.Range[str, 2, 60],
                           stage: str, photo: discord.Attachment, permission: bool,
                           notes: app_commands.Range[str, 0, 220] = ""):
        if not permission:
            await interaction.response.send_message(
                "Submission needs your permission: only upload your own image that we may "
                "show in this server. You can withdraw it later.", ephemeral=True)
            return
        try:
            review, _, enabled = _configured_channels(interaction, bot.growers)
            if not enabled:
                raise ValueError("New grower submissions are paused in this server.")
            name = verified_strain(strain)
            if stage not in STAGES:
                raise ValueError("Unsupported growth stage.")
            caption = clean_caption(notes, maximum=220)
            byline = clean_caption(interaction.user.display_name, maximum=45) or "Community grower"
            if photo.size <= 0 or photo.size > MAX_UPLOAD_BYTES:
                raise ValueError("Upload one photo under 8 MiB.")
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if not await bot.admit_interaction(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await photo.read()
            normalized = await asyncio.to_thread(photo_as_jpeg, data)
            message = await review.send(
                embed=_submission_card(byline, name, stage, caption, approved=False),
                file=discord.File(BytesIO(normalized), filename="grower.jpg"),
                allowed_mentions=NO_MENTIONS)
            try:
                entry_id = bot.growers.submit(
                    interaction.guild_id, interaction.user.id, byline,
                    name, stage, caption, message.id)
            except Exception:
                await message.delete()
                raise
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Grower photo submission failed")
            await interaction.followup.send(
                "Submission failed. Check showcase channel permissions and storage.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Your grow photo **#{entry_id}** is awaiting staff review. "
            "Your contributor name will appear only if approved. "
            f"Use /growerwithdraw id:{entry_id} to remove it at any time. "
            "We stripped embedded camera metadata before posting.",
            ephemeral=True, allowed_mentions=NO_MENTIONS)

    @bot.tree.command(name="growerqueue", description="Manager: review the pending grower photo queue")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def growerqueue(interaction: discord.Interaction):
        try:
            review, _, _ = _configured_channels(interaction, bot.growers)
            entries = bot.growers.pending(interaction.guild_id)
            rows = [f"**#{eid}** · {strain} ({stage}) · {byline} "
                    f"· [Review photo](https://discord.com/channels/{interaction.guild_id}/"
                    f"{review.id}/{message_id})"
                    for eid, byline, strain, stage, message_id in entries]
            result = "\n".join(rows) if rows else "No pending grower photos."
        except Exception:
            log.exception("Grower queue failed")
            result = "The review queue is currently unavailable."
        await interaction.response.send_message(
            result, ephemeral=True, allowed_mentions=NO_MENTIONS)

    @bot.tree.command(name="growerreview", description="Manager: approve or reject a submitted grow photo")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(id="Submission number from /growerqueue",
                           approve="Publish to the gallery; false rejects and deletes it")
    async def growerreview(interaction: discord.Interaction, id: int, approve: bool):
        if id < 1:
            await interaction.response.send_message("Use a valid submission number.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        hub = bot.growers
        review_message = None
        gallery_message = None
        try:
            review, gallery, _ = _configured_channels(interaction, hub)
            item = hub.lock(interaction.guild_id, id, purpose="review")
            try:
                if approve:
                    review_message = await review.fetch_message(int(item[6]))
                    if not review_message.attachments or review_message.author.id != bot.user.id:
                        raise ValueError("The original review photo is missing.")
                    attachment = await review_message.attachments[0].to_file(
                        filename="grower.jpg")
                    gallery_message = await gallery.send(
                        embed=_submission_card(item[2], item[3], item[4], item[5],
                                               approved=True),
                        file=attachment, allowed_mentions=NO_MENTIONS)
                    try:
                        hub.approve(interaction.guild_id, id, gallery_message.id)
                    except Exception:
                        try:
                            await gallery_message.delete()
                            gallery_message = None
                        except discord.HTTPException:
                            log.exception("Review publication needs manual reconciliation for #%s", id)
                        raise
                else:
                    await _remove_message(review, int(item[6]), bot)
                    hub.delete(interaction.guild_id, id, "reviewing")
            except Exception:
                if gallery_message is None:
                    hub.unlock(interaction.guild_id, id, "pending")
                raise
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Grower review failed")
            await interaction.followup.send(
                "Review failed. Verify channels and retry. If already posted publicly, "
                "avoid approving twice and contact the application owner.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Submission **#{id}** {'approved and posted' if approve else 'rejected and deleted'}.",
            ephemeral=True, allowed_mentions=NO_MENTIONS)

    @bot.tree.command(name="growerprofile", description="See your showcase milestones and photo contributions")
    @app_commands.guild_only()
    @app_commands.describe(public="Share your contributor milestones in this channel")
    async def growerprofile(interaction: discord.Interaction, public: bool = False):
        try:
            approved, pending, varieties, badge = bot.growers.stats(
                interaction.guild_id, interaction.user.id)
            embed = discord.Embed(
                title="🌱 Grower Showcase | Your profile",
                description=f"**{badge}**\n"
                            f"Approved photos: **{approved}** · Awaiting review: **{pending}**\n"
                            f"Documented strain names: **{varieties}**\n\n"
                            "Milestones: 1 photo · 5 photos · 20 photos. "
                            "These are community credits, not proof of cultivar identity.",
                color=0x127B52)
            embed.set_footer(text="Server-only progress • Withdraw photos anytime with /growerwithdraw")
            await interaction.response.send_message(
                embed=embed, ephemeral=not public, allowed_mentions=NO_MENTIONS)
        except Exception:
            log.exception("Grower profile failed")
            await interaction.response.send_message("Grower profiles are unavailable.", ephemeral=True)

    @bot.tree.command(name="growerwithdraw", description="Withdraw one of your grow photos and erase its entry")
    @app_commands.guild_only()
    @app_commands.describe(id="Your submission number (from your upload receipt)")
    async def growerwithdraw(interaction: discord.Interaction, id: int):
        try:
            await _remove_submission(interaction, bot, id, user_id=interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Grower withdrawal failed")
            await interaction.response.send_message(
                "Withdrawal could not finish. Staff may need to restore channel access "
                "before the photo can be removed.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Submission **#{id}** and its saved photo posts were removed.",
            ephemeral=True)

    @bot.tree.command(name="growerremove", description="Manager: remove a grow photo from review or the gallery")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def growerremove(interaction: discord.Interaction, id: int):
        try:
            await _remove_submission(interaction, bot, id, user_id=None)
        except Exception:
            log.exception("Moderation removal failed")
            await interaction.response.send_message(
                "Removal failed. Check the submission number, bot permissions and channels.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            f"Grower submission **#{id}** removed.", ephemeral=True)
