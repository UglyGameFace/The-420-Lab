"""Discord entry points for the opt-in, per-server Grower Showcase."""
from __future__ import annotations

import asyncio
from io import BytesIO
import logging
import os

import discord
from discord import app_commands

from .growers import MAX_UPLOAD_BYTES, STAGES, clean_caption, photo_as_jpeg, verified_strain

log = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()
# If another image is still uploading, reject after a short wait without
# buffering any attachment. User can safely retry; no record was reserved.
GROWER_IMAGE_QUEUE_WAIT = 10


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


async def _saved_channel(interaction: discord.Interaction, channel_id: str):
    """Resolve an original post channel, even after the manager changes settings."""
    channel = interaction.guild.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await interaction.client.fetch_channel(int(channel_id))
        except discord.NotFound:
            return None  # The channel was deleted; its messages no longer exist.
    if (not isinstance(channel, discord.TextChannel)
            or channel.guild.id != interaction.guild_id):
        raise ValueError("The saved showcase channel cannot be accessed safely.")
    return channel


def _post_permissions(channel: discord.TextChannel, member: discord.Member) -> bool:
    perms = channel.permissions_for(member)
    return all((perms.view_channel, perms.send_messages, perms.attach_files,
                perms.embed_links, perms.read_message_history))


def _submission_card(byline: str, strain: str, stage: str, caption: str,
                     *, approved: bool, submission_id: int | None = None) -> discord.Embed:
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
    marker = (f"Grower submission #{submission_id} | " if approved else
              f"Grower upload #{submission_id} | ") if submission_id else ""
    card.set_footer(text=(
        marker + "Member-submitted identification, not genetically verified. "
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
                             *, user_id: int | None, purpose: str = "remove") -> None:
    hub = bot.growers
    row = hub.lock(interaction.guild_id, submission_id, purpose=purpose, user_id=user_id)
    deletion_started = False
    try:
        if row[7]:
            if not row[10]:
                raise ValueError("The saved gallery channel is missing; contact staff.")
            gallery = await _saved_channel(interaction, row[10])
            if gallery:
                deletion_started = True
                await _remove_message(gallery, int(row[7]), bot)
        review = await _saved_channel(interaction, row[9])
        if review:
            deletion_started = True
            await _remove_message(review, int(row[6]), bot)
        hub.delete(interaction.guild_id, submission_id, "removing")
    except Exception:
        # Once a Discord delete starts, its result may be uncertain. Keep the
        # durable removal state for an idempotent staff/member retry.
        if not deletion_started and row[8] in ("pending", "approved"):
            hub.unlock(interaction.guild_id, submission_id, row[8])
        raise


def register_grower_commands(bot) -> None:
    """Install once onto the existing command tree; no new Discord client."""

    @bot.tree.command(name="growerstorage", description="Application owner: test Grower Showcase database continuity")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(action="Arm before restarting, verify in the new process, or inspect status")
    @app_commands.choices(action=[
        app_commands.Choice(name="Storage status", value="status"),
        app_commands.Choice(name="Arm restart/redeploy test", value="arm"),
        app_commands.Choice(name="Verify continuity after restart", value="verify"),
    ])
    async def growerstorage(interaction: discord.Interaction, action: str = "status"):
        if not await bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "Only the application owner can perform the storage continuity test.",
                ephemeral=True)
            return
        try:
            if action == "arm":
                bot.growers.arm_storage_probe()
                result = ("**Storage probe armed.** New member photo uploads are paused. "
                          "Restart or redeploy the bot, then use "
                          "`/growerstorage action:verify` from this server. "
                          "Do not infer that a successful simple restart proves "
                          "data survives a full redeployment.")
            elif action == "verify":
                verified = bot.growers.verify_storage_probe()
                result = (f"**Cross-process SQLite continuity verified** at {verified}. "
                          "The previous probe was found after a process change, and "
                          "the database passed its integrity check. "
                          "A separate redeployment test and backup still need validation.")
            elif action == "status":
                state, timestamp = bot.growers.storage_status()
                summary = {
                    "unarmed": "No continuity probe has been armed.",
                    "armed_this_process": "Armed in the current process; restart is still required.",
                    "ready_to_verify": "Probe recovered in a different process; run action:verify.",
                    "verified": "Cross-process continuity previously verified.",
                }[state]
                result = (f"**Grower SQLite storage:** {summary} "
                          + (f"Last checkpoint: {timestamp}." if timestamp else "")
                          + " This is not proof of Discloud redeploy retention or backups.")
            else:
                raise ValueError("Choose status, arm, or verify.")
        except ValueError as exc:
            result = str(exc)
        except Exception:
            log.exception("Grower storage continuity check failed")
            result = "Storage check failed. Inspect the bot logs and configured database path."
        await interaction.response.send_message(
            result, ephemeral=True, allowed_mentions=NO_MENTIONS)

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
            if (os.getenv("LAB_GROWER_REQUIRE_STORAGE_PROOF", "true").lower()
                    not in ("false", "0", "off")):
                if not bot.growers.storage_ready():
                    raise ValueError(
                        "Grower uploads are paused until the application owner verifies "
                        "database continuity with /growerstorage. This protects member "
                        "photos and withdrawal records across bot restarts.")
            name = verified_strain(strain)
            if stage not in STAGES:
                raise ValueError("Unsupported growth stage.")
            caption = clean_caption(notes, maximum=220)
            byline = clean_caption(interaction.user.display_name, maximum=45) or "Community grower"
            if photo.size <= 0 or photo.size > MAX_UPLOAD_BYTES:
                raise ValueError("Upload one photo under 8 MiB.")
            if not review.is_nsfw() or review.permissions_for(interaction.guild.default_role).view_channel:
                raise ValueError("The review channel must remain private and age-restricted.")
            member = interaction.guild.me
            if not member or not _post_permissions(review, member):
                raise ValueError("The bot no longer has review-channel upload permissions.")
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if not await bot.admit_interaction(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        slot_taken = False
        try:
            try:
                await asyncio.wait_for(bot.grower_image_slots.acquire(),
                                       timeout=GROWER_IMAGE_QUEUE_WAIT)
                slot_taken = True
            except asyncio.TimeoutError as exc:
                raise ValueError(
                    "The photo processor is busy. Try again shortly; "
                    "no image was accepted or saved.") from exc
            data = await photo.read()
            normalized = await asyncio.to_thread(photo_as_jpeg, data)
            entry_id = bot.growers.begin_upload(
                interaction.guild_id, interaction.user.id, byline,
                name, stage, caption, review.id)
            # An upload may succeed despite an API timeout. Never delete the
            # reservation or blindly resend; staff reconcile its unique marker.
            message = await review.send(
                embed=_submission_card(byline, name, stage, caption,
                                       approved=False, submission_id=entry_id),
                file=discord.File(BytesIO(normalized), filename="grower.jpg"),
                allowed_mentions=NO_MENTIONS)
            bot.growers.finish_upload(interaction.guild_id, entry_id, message.id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Grower photo submission failed; reserved_id=%s",
                          locals().get("entry_id"))
            if "entry_id" in locals():
                notice = (f"Upload **#{entry_id}** could not be confirmed. Do not resend it. "
                          "After five minutes, staff can inspect /growerqueue and "
                          "use /growerrecover to reconcile the original photo.")
            else:
                notice = "Submission failed before posting. Check image, permissions and storage."
            await interaction.followup.send(notice, ephemeral=True,
                                            allowed_mentions=NO_MENTIONS)
            return
        finally:
            if slot_taken:
                bot.grower_image_slots.release()
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
            entries = bot.growers.pending(interaction.guild_id)
            rows = [f"**#{eid}** · {strain} ({stage}) · {byline} "
                    f"· [Review photo](https://discord.com/channels/{interaction.guild_id}/"
                    f"{channel_id}/{message_id})"
                    for eid, byline, strain, stage, message_id, channel_id in entries]
            interrupted = bot.growers.interrupted(interaction.guild_id)
            if interrupted:
                rows.append("**Interrupted operations:** " + ", ".join(
                    f"#{number} ({status})" for number, status in interrupted)
                    + ". Staff: use /growerrecover.")
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
        if not approve:
            try:
                await _remove_submission(interaction, bot, id, user_id=None, purpose="reject")
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
            except Exception:
                log.exception("Grower rejection did not finish")
                await interaction.followup.send(
                    "Rejection could not be confirmed. Do not retry immediately; use "
                    "/growerqueue and /growerrecover if the removal was interrupted.",
                    ephemeral=True)
            else:
                await interaction.followup.send(
                    f"Submission **#{id}** rejected and deleted.",
                    ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        hub = bot.growers
        review_message = None
        gallery_message = None
        publication_uncertain = False
        try:
            item = hub.lock(interaction.guild_id, id, purpose="review")
            try:
                review = await _saved_channel(interaction, item[9])
                if approve:
                    if review is None:
                        raise ValueError("The review photo's channel was deleted.")
                    _, gallery, _ = _configured_channels(interaction, hub)
                    if not gallery.is_nsfw() or not review.is_nsfw():
                        raise ValueError("Both showcase channels must remain age-restricted.")
                    if review.permissions_for(interaction.guild.default_role).view_channel:
                        raise ValueError("The staff review channel is no longer private.")
                    member = interaction.guild.me
                    if not member or not _post_permissions(gallery, member):
                        raise ValueError("The bot no longer has gallery publishing permissions.")
                    hub.prepare_review(interaction.guild_id, id, gallery.id)
                    review_message = await review.fetch_message(int(item[6]))
                    if not review_message.attachments or review_message.author.id != bot.user.id:
                        raise ValueError("The original review photo is missing.")
                    attachment = await review_message.attachments[0].to_file(
                        filename="grower.jpg")
                    # A network error may occur after Discord accepted the post.
                    # Keep the durable review lock until staff reconcile it.
                    publication_uncertain = True
                    gallery_message = await gallery.send(
                        embed=_submission_card(item[2], item[3], item[4], item[5],
                                               approved=True, submission_id=id),
                        file=attachment, allowed_mentions=NO_MENTIONS)
                    try:
                        hub.approve(interaction.guild_id, id, gallery_message.id, gallery.id)
                    except Exception:
                        try:
                            await gallery_message.delete()
                            gallery_message = None
                            publication_uncertain = False
                        except discord.HTTPException:
                            log.exception("Review publication needs manual reconciliation for #%s", id)
                        raise
            except Exception:
                if not publication_uncertain:
                    hub.unlock(interaction.guild_id, id, "pending")
                raise
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Grower review failed")
            await interaction.followup.send(
                "Review could not be confirmed. Do not approve it again immediately. "
                "If the request interrupted, staff can use /growerqueue and "
                "/growerrecover after five minutes.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Submission **#{id}** approved and posted.",
            ephemeral=True, allowed_mentions=NO_MENTIONS)

    @bot.tree.command(name="growerrecover", description="Manager: reconcile an interrupted photo review or removal")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(id="Interrupted submission number from /growerqueue",
                           confirmed_not_published="Only after checking original review/gallery channel for any posted photo")
    async def growerrecover(interaction: discord.Interaction, id: int,
                            confirmed_not_published: bool = False):
        if id < 1:
            await interaction.response.send_message("Use a valid submission number.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        hub = bot.growers
        try:
            item = hub.item(interaction.guild_id, id)
            if not item:
                message = "That submission no longer exists."
            elif item[8] == "removing":
                await _remove_submission(interaction, bot, id, user_id=None)
                message = f"Interrupted removal for **#{id}** resumed and the entry was erased."
            elif item[8] == "uploading":
                if not hub.upload_is_interrupted(interaction.guild_id, id):
                    message = "That upload is still active. Wait five minutes before recovery."
                else:
                    found = []
                    review = await _saved_channel(interaction, item[9])
                    if review is not None:
                        marker = f"Grower upload #{id} | "
                        async for post in review.history(limit=250):
                            if (post.author.id == bot.user.id
                                    and any((embed.footer.text or "").startswith(marker)
                                            for embed in post.embeds)):
                                found.append(post)
                    if len(found) > 1:
                        message = ("Multiple private review photos match this ID. "
                                   "Resolve the duplicates manually before recovery.")
                    elif len(found) == 1:
                        hub.finish_upload(interaction.guild_id, id, found[0].id)
                        message = (f"Recovered upload **#{id}** into the staff queue. "
                                   "No duplicate was posted.")
                    elif confirmed_not_published:
                        hub.discard_interrupted_upload(interaction.guild_id, id)
                        message = f"Unposted upload reservation **#{id}** cleared."
                    else:
                        message = ("No matching photo was found in the last 250 review-channel "
                                   "messages. Search the **entire original channel** before "
                                   "setting confirmed_not_published:true. The reservation "
                                   "is preserved to prevent losing track of a posted photo.")
            elif item[8] != "reviewing":
                message = f"Submission **#{id}** is **{item[8]}**. No recovery is needed."
            elif not hub.review_is_interrupted(interaction.guild_id, id):
                message = "That review is still active. Wait at least five minutes before recovery."
            else:
                found = []
                if item[10]:
                    gallery = await _saved_channel(interaction, item[10])
                    if gallery is not None:
                        marker = f"Grower submission #{id} | "
                        async for post in gallery.history(limit=250):
                            if (post.author.id == bot.user.id
                                    and any((embed.footer.text or "").startswith(marker)
                                            for embed in post.embeds)):
                                found.append(post)
                if len(found) > 1:
                    message = ("More than one matching gallery post exists. Do not republish; "
                               "remove duplicates manually and retry recovery.")
                elif len(found) == 1:
                    hub.approve(interaction.guild_id, id, found[0].id, int(item[10]))
                    message = f"Recovered **#{id}** from its existing gallery post. No duplicate created."
                elif confirmed_not_published:
                    hub.requeue_interrupted_review(interaction.guild_id, id)
                    message = (f"Submission **#{id}** returned to the staff review queue. "
                               "No new gallery post was created.")
                else:
                    message = ("No identified gallery post was found in the most recent 250 "
                               "messages of the saved gallery. Check the **entire** gallery "
                               "manually before retrying with confirmed_not_published:true. "
                               "The submission remains locked to prevent duplicate publication.")
        except ValueError as exc:
            message = str(exc)
        except Exception:
            log.exception("Grower recovery failed")
            message = "Recovery failed; no success has been confirmed. Review bot permissions and logs."
        await interaction.followup.send(message, ephemeral=True,
                                        allowed_mentions=NO_MENTIONS)

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
            if not public:
                uploads = bot.growers.my_uploads(interaction.guild_id, interaction.user.id)
                if uploads:
                    embed.add_field(
                        name="My recent upload IDs",
                        value="\n".join(f"#{item_id} · {name} · {status}"
                                        for item_id, name, status in uploads),
                        inline=False)
            embed.set_footer(text="Server-only progress • Withdraw photos anytime with /growerwithdraw")
            await interaction.response.send_message(
                embed=embed, ephemeral=not public, allowed_mentions=NO_MENTIONS)
        except Exception:
            log.exception("Grower profile failed")
            await interaction.response.send_message("Grower profiles are unavailable.", ephemeral=True)

    @bot.tree.command(name="growerjournal", description="See your approved photo timeline and grow stages")
    @app_commands.guild_only()
    @app_commands.describe(strain="Optional exact strain name to filter your journal",
                           public="Publish your own grow timeline in this channel")
    async def growerjournal(interaction: discord.Interaction,
                            strain: app_commands.Range[str, 2, 60] | None = None,
                            public: bool = False):
        if public and not (isinstance(interaction.channel, discord.TextChannel)
                           and interaction.channel.is_nsfw()):
            await interaction.response.send_message(
                "Public grow journals can only be shared in age-restricted text channels.",
                ephemeral=True)
            return
        try:
            entries = bot.growers.journal(interaction.guild_id, interaction.user.id,
                                         strain or "")
            rows = [f"**{stage.title()}** · {name} · {date[:10]} "
                    f"· [Photo](https://discord.com/channels/{interaction.guild_id}/"
                    f"{channel_id}/{message_id})"
                    + (f" · {caption}" if caption else "")
                    for _, name, stage, caption, message_id, date, channel_id in entries]
            embed = discord.Embed(
                title="📷 My Grower Journal",
                description=("\n".join(rows) if rows else
                             "No approved photos yet. Use /growersubmit when enabled.")[:3900],
                color=0x127B52)
            embed.set_footer(text="Most recent 12 approved photos • Member-reported strain/stage")
            await interaction.response.send_message(
                embed=embed, ephemeral=not public, allowed_mentions=NO_MENTIONS)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
        except Exception:
            log.exception("Grower journal failed")
            await interaction.response.send_message("The grower journal is unavailable.", ephemeral=True)

    @bot.tree.command(name="growerwithdraw", description="Withdraw one of your grow photos and erase its entry")
    @app_commands.guild_only()
    @app_commands.describe(id="Your submission number (from your upload receipt)")
    async def growerwithdraw(interaction: discord.Interaction, id: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await _remove_submission(interaction, bot, id, user_id=interaction.user.id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Grower withdrawal failed")
            await interaction.followup.send(
                "Withdrawal could not finish. Staff may need to restore channel access "
                "before the photo can be removed.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Submission **#{id}** and its saved photo posts were removed.",
            ephemeral=True)

    @bot.tree.command(name="growerremove", description="Manager: remove a grow photo from review or the gallery")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def growerremove(interaction: discord.Interaction, id: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await _remove_submission(interaction, bot, id, user_id=None)
        except Exception:
            log.exception("Moderation removal failed")
            await interaction.followup.send(
                "Removal failed. Check the submission number, bot permissions and channels.",
                ephemeral=True)
            return
        await interaction.followup.send(
            f"Grower submission **#{id}** removed.", ephemeral=True)
