"""Discord slash commands for cannabis research education."""
from __future__ import annotations
import asyncio
import time
import re
from collections import OrderedDict
import logging
import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from .sources import COMPOUNDS, PUBMED_FILTERS, ScienceSources, SourceError
from .answers import GeminiAnswer, ResearchAssistant, clip_discord, study_links
from .panel import LabPanelView, panel_embed, PANEL_THEMES
from .guidance import GUIDES, guide_message
from .fda import FDA_PRODUCTS, report_message
from .strains import result_text as strain_result_text
from .leafly import leafly_reference, leafly_answer
from .strain_profiles import StrainProfileStore, database_embed, strain_embed, source_directory_embed
from .rich_sources import sourced_summary
from .health import LabHealth
from .quotas import QuotaGate, QuotaExceeded
from .control import OwnerControlView, panel as owner_panel

logger = logging.getLogger(__name__)


class LabBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.http_session = None
        self.science = None
        self.assistant = None
        self.limiter = asyncio.Semaphore(3)
        self._panel_access = OrderedDict()
        self.health = LabHealth()
        self.quota = QuotaGate()
        self.strain_profiles = StrainProfileStore()
        logger.info("Quota ledger at launch: %s", self.quota.continuity_description())
        self._heartbeat_task = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=18),
            headers={"User-Agent": "TheWeedDoctor/0.1 (Discord cannabis research bot)"})
        self.science = ScienceSources(self.http_session, os.getenv("NCBI_API_KEY", ""),
                                     os.getenv("OPENFDA_API_KEY", ""), quota=self.quota)
        key = os.getenv("GEMINI_API_KEY", "")
        ai = GeminiAnswer(self.http_session, key, os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                          quota=self.quota) if key else None
        self.assistant = ResearchAssistant(self.science, ai)
        # Register the persistent panel before syncing slash commands.
        self.add_view(LabPanelView(self))
        await self.sync_commands()
        logger.info("AI configured: %s", bool(ai))
        self._heartbeat_task = asyncio.create_task(self._health_heartbeat(), name="lab-heartbeat")

    async def sync_commands(self):
        """Publish globally for all servers and refresh the optional test guild."""
        expected = {command.name for command in self.tree.get_commands()}
        global_synced = await self.tree.sync()
        global_names = {command.name for command in global_synced}
        logger.info("Global commands synced: %s", ", ".join(sorted(global_names)))
        if expected - global_names:
            raise RuntimeError("Discord global sync omitted locally registered commands")

        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            guild_synced = await self.tree.sync(guild=guild)
            guild_names = {command.name for command in guild_synced}
            logger.info("Guild %s commands synced: %s", guild_id, ", ".join(sorted(guild_names)))
            if expected - guild_names:
                raise RuntimeError("Discord guild sync omitted locally registered commands")

    async def admit_interaction(self, interaction: discord.Interaction) -> bool:
        """Central abuse check, shared by expensive slash commands and panel forms."""
        allowlist = os.getenv("LAB_ALLOWED_GUILDS", "").strip()
        if allowlist:
            allowed = {part.strip() for part in allowlist.split(",") if part.strip()}
            if not all(item.isdigit() for item in allowed):
                await interaction.response.send_message(
                    "The Weed Doctor's server access configuration is invalid.", ephemeral=True)
                return False
            if str(interaction.guild_id) not in allowed:
                await interaction.response.send_message(
                    "The Weed Doctor's research features are not enabled for this server.",
                    ephemeral=True)
                return False
        try:
            self.quota.admit_member(interaction.user.id, interaction.guild_id)
        except QuotaExceeded as exc:
            message = (f"The Weed Doctor's {exc.kind} usage safety limit was reached. "
                       f"Try again in about {exc.retry_after} seconds.")
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    def panel_wait(self, user_id: int) -> int:
        """Bounded in-memory cooldown shared by all public panel actions."""
        now = time.monotonic()
        previous = self._panel_access.get(user_id)
        if previous is not None and now - previous < 15:
            return max(1, int(15 - (now - previous) + 0.999))
        self._panel_access[user_id] = now
        self._panel_access.move_to_end(user_id)
        if len(self._panel_access) > 2048:
            self._panel_access.popitem(last=False)
        return 0

    async def research_answer(self, question: str) -> str:
        self.health.record("research")
        try:
            async with self.limiter:
                assert self.assistant is not None
                return clip_discord(await self.assistant.answer(question))
        except Exception:
            logger.exception("Research request failed")
            return "Research lookup failed. Please try again; I won't guess about health effects."

    async def compound_answer(self, name: str) -> str:
        self.health.record("compound")
        try:
            async with self.limiter:
                assert self.science is not None
                item = await self.science.compound(name)
            if item:
                return (f"**{item.name}**: PubChem CID {item.cid}\n"
                        f"Formula: {item.formula} | Molecular weight: {item.molecular_weight} g/mol\n"
                        f"{item.url}\n\nChemistry does not establish health benefits or safe dosing.")
            return "PubChem did not find a matching record."
        except QuotaExceeded:
            return "The Weed Doctor has reached its public research request allowance. Try later."
        except (SourceError, ValueError):
            return "PubChem is temporarily unavailable for that compound."

    async def trials_answer(self, topic: str) -> str:
        self.health.record("trials")
        try:
            async with self.limiter:
                assert self.science is not None
                studies = await self.science.trials(topic)
            if studies:
                message = "**ClinicalTrials.gov studies**\n" + "\n".join(
                    f"• {s.title[:100]} ({s.status})\n  {s.url}" for s in studies)
            else:
                message = "No matching registered studies found."
            return clip_discord(message + "\n\nTrial registration does not prove a treatment works.")
        except QuotaExceeded:
            return "The Weed Doctor has reached its public research request allowance. Try later."
        except SourceError:
            return "ClinicalTrials.gov is currently unavailable."

    async def fda_answer(self, product: str) -> str:
        self.health.record("fda")
        try:
            async with self.limiter:
                assert self.science is not None
                data = await self.science.fda_reports(product)
            return clip_discord(report_message(data))
        except QuotaExceeded:
            return "The Weed Doctor has reached its public research request allowance. Try later."
        except ValueError:
            return "Choose a supported FDA-approved medicine from the menu."
        except SourceError:
            return ("openFDA safety-report data is temporarily unavailable. "
                    "These reports do not establish causation or side-effect rates.")

    async def _health_heartbeat(self):
        try:
            await self.wait_until_ready()
            while not self.is_closed():
                cache_items = len(self.science._cache) if self.science else 0
                logger.info(
                    "lab_health uptime_s=%d guilds=%d cache_items=%d total_queries=%d",
                    self.health.uptime_seconds, len(self.guilds), cache_items,
                    sum(self.health.counts.values()))
                await asyncio.sleep(900)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Lab process heartbeat failed")

    async def papers_answer(self, topic: str, kind: str = "all") -> str:
        self.health.record("research")
        try:
            async with self.limiter:
                assert self.science is not None
                studies = await self.science.pubmed(topic, kind)
        except QuotaExceeded:
            return "The Weed Doctor has reached its public research request allowance. Try later."
        except (SourceError, ValueError):
            return "Unable to retrieve indexed PubMed results with this filter right now."
        if not studies:
            return ("No PubMed results for this study-design filter. "
                    "Try a broader topic or select All Designs.")
        label = {
            "all": "All Designs", "systematic": "Systematic Reviews",
            "randomized": "Randomized Controlled Trials",
            "observational": "Observational Studies",
        }.get(kind, "All Designs")
        message = (f"**PubMed research | {label}**\n"
                   f"{study_links(studies)}\n\n"
                   "The filter reflects PubMed indexing. A study's existence or "
                   "design alone does not establish study quality, treatment "
                   "benefit, or medical suitability.")
        return clip_discord(message)

    async def on_ready(self):
        # Startup diagnostic; never log tokens or user questions.
        logger.info("Discord gateway ready: bot=%s guild_count=%d", self.user, len(self.guilds))

    async def close(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
        try:
            if self.http_session:
                await self.http_session.close()
        finally:
            await super().close()


bot = LabBot()


@bot.tree.command(name="askthc", description="PubMed research; if AI enabled, your question is sent to Gemini")
@app_commands.describe(question="Ask about effects, benefits, risks, or cannabinoid research")
@app_commands.checks.cooldown(1, 20, key=lambda i: (i.guild_id, i.user.id))
async def askthc(interaction: discord.Interaction, question: app_commands.Range[str, 4, 220]):
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.research_answer(question),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="compound", description="View cannabinoid chemistry from NIH PubChem")
@app_commands.describe(name="Select a cannabinoid")
@app_commands.choices(name=[app_commands.Choice(name=k, value=k) for k in COMPOUNDS])
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def compound(interaction: discord.Interaction, name: str):
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.compound_answer(name),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="trials", description="Find registered cannabis trials on ClinicalTrials.gov")
@app_commands.describe(topic="Example: anxiety, sleep, chronic pain")
@app_commands.checks.cooldown(1, 15, key=lambda i: (i.guild_id, i.user.id))
async def trials(interaction: discord.Interaction, topic: app_commands.Range[str, 3, 100]):
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.trials_answer(topic),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="scienceguide", description="Explore official NIH CDC and FDA cannabis guidance")
@app_commands.describe(topic="Choose an official health-information topic")
@app_commands.choices(topic=[
    app_commands.Choice(name=guide.title, value=key) for key, guide in GUIDES.items()
])
async def scienceguide(interaction: discord.Interaction, topic: str):
    bot.health.record("guides")
    await interaction.response.send_message(
        guide_message(topic), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="fdareports", description="Explore reported reactions in FDA drug-safety submissions")
@app_commands.describe(medicine="Choose an FDA-approved cannabinoid medicine")
@app_commands.choices(medicine=[
    app_commands.Choice(name=label, value=key) for key, label in FDA_PRODUCTS.items()
])
@app_commands.checks.cooldown(1, 25, key=lambda i: (i.guild_id, i.user.id))
async def fdareports(interaction: discord.Interaction, medicine: str):
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.fda_answer(medicine),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="straininfo", description="Look up historical cannabis strain information (not game commands)")
@app_commands.describe(name="Cannabis strain name, for example Northern Lights")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def straininfo(interaction: discord.Interaction, name: app_commands.Range[str, 2, 60]):
    """Separate science-only lookup from Idle Grow Op's /strain game command."""
    if not await bot.admit_interaction(interaction):
        return
    bot.health.record("strain")
    await interaction.response.send_message(
        clip_discord(leafly_answer(name)), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="leafly", description="Find verified Leafly strain profiles and available research")
@app_commands.describe(name="Strain name, such as Super Boof or Northern Lights")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def leafly(interaction: discord.Interaction, name: app_commands.Range[str, 2, 60]):
    """Leafly references alongside our independent strain-name catalog."""
    if not await bot.admit_interaction(interaction):
        return
    bot.health.record("strain")
    try:
        embed = strain_embed(name, interaction.guild_id, bot.strain_profiles)
    except Exception:
        logger.exception("Leafly profile view failed; falling back to linked references")
        embed = None
    if embed:
        await interaction.response.send_message(
            embed=embed, ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())
    else:
        await interaction.response.send_message(
            clip_discord(leafly_answer(name)), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="strainsources", description="View reliable strain data sources, photo rights and lab-test limitations")
@app_commands.describe(public="Publish source guide for everyone (Manage Server required)")
@app_commands.checks.cooldown(1, 20, key=lambda i: (i.guild_id, i.user.id))
async def strainsources(interaction: discord.Interaction, public: bool = False):
    if public and not (
        interaction.guild_id is not None and
        interaction.permissions.manage_guild
    ):
        await interaction.response.send_message(
            "Only members with Manage Server can publish this source guide.",
            ephemeral=True)
        return
    await interaction.response.send_message(
        embed=source_directory_embed(), ephemeral=not public,
        allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="straindb", description="See the current Weed Doctor strain index size and source ages")
@app_commands.describe(public="Publish the status card for everyone (Manage Server required)")
@app_commands.checks.cooldown(1, 20, key=lambda i: (i.guild_id, i.user.id))
async def straindb(interaction: discord.Interaction, public: bool = False):
    if public and not (
        interaction.guild_id is not None and
        interaction.permissions.manage_guild
    ):
        await interaction.response.send_message(
            "Only members with Manage Server can publish the database status.",
            ephemeral=True)
        return
    await interaction.response.send_message(
        embed=database_embed(), ephemeral=not public,
        allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="strainprofile", description="Credited strain details, independent facts, images and reviews")
@app_commands.describe(name="Cannabis strain name, e.g. Northern Lights")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def strainprofile(interaction: discord.Interaction, name: app_commands.Range[str, 2, 60]):
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        embed = strain_embed(name, interaction.guild_id, bot.strain_profiles)
    except Exception:
        logger.exception("Strain profile lookup failed")
        await interaction.followup.send(
            "Strain profile storage is unavailable. Try /straininfo for the offline catalog.",
            ephemeral=True)
        return
    try:
        research = await sourced_summary(bot.http_session, bot.quota, name)
    except Exception:
        logger.exception("CannaLib preview failed without exposing provider details")
        research = "Independent research is temporarily unavailable."
    embed.add_field(
        name="🧬 Independently sourced cultivar facts",
        value=research[:1024],
        inline=False)
    await interaction.followup.send(
        embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="strainreviews", description="Manager: enable, disable or clear original server strain ratings")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(enabled="Allow members to rate strain names in this server",
                       clear="Permanently erase the server's saved ratings")
async def strainreviews(interaction: discord.Interaction, enabled: bool,
                        clear: bool = False):
    try:
        if clear:
            bot.strain_profiles.clear_reviews(interaction.guild_id)
        bot.strain_profiles.set_reviews_enabled(interaction.guild_id, enabled)
    except Exception:
        logger.exception("Unable to update strain review settings")
        await interaction.response.send_message(
            "Review storage could not be updated.", ephemeral=True)
        return
    await interaction.response.send_message(
        ("Community strain ratings are now **enabled**." if enabled else
         "Community strain ratings are now **disabled**.")
        + (" Previously submitted ratings were permanently cleared." if clear else "")
        + " Only aggregate scores are shown. Reviews are personal opinions, not medical evidence.",
        ephemeral=True)


@bot.tree.command(name="strainrate", description="Rate a strain from 1 to 5 for this server only")
@app_commands.guild_only()
@app_commands.describe(name="Exact catalog strain name", stars="Score between 1 and 5")
@app_commands.checks.cooldown(1, 20, key=lambda i: (i.guild_id, i.user.id))
async def strainrate(interaction: discord.Interaction, name: app_commands.Range[str, 2, 60],
                     stars: app_commands.Range[int, 1, 5]):
    if not await bot.admit_interaction(interaction):
        return
    try:
        bot.strain_profiles.rate(interaction.guild_id, interaction.user.id, name, stars)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    except Exception:
        logger.exception("Server community strain rating failed")
        await interaction.response.send_message(
            "Ratings are currently unavailable.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"Your {stars}/5 score for **{name}** was saved privately. "
        "You can change it by rating the same name again. "
        "Community ratings are not treatment advice.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="doctorstrainset", description="Application-owner: provide a licensed strain description and image")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    name="Exact catalog strain name",
    description="Original or licensed short description (15–550 chars)",
    source_url="Public HTTPS URL attributing the source and content rights",
    rights="Legal basis for the description and optional image",
    image_url="Optional public HTTPS image URL licensed for this bot")
@app_commands.choices(rights=[
    app_commands.Choice(name="My original content", value="original"),
    app_commands.Choice(name="CC BY 4.0 with attribution", value="cc-by-4.0"),
    app_commands.Choice(name="Separately licensed", value="licensed")])
async def doctorstrainset(
    interaction: discord.Interaction, name: app_commands.Range[str, 2, 60],
    description: str, source_url: str, rights: str, image_url: str = ""):
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message(
            "Only the Discord application owner can publish profiles to every server.",
            ephemeral=True)
        return
    try:
        bot.strain_profiles.save_curated(
            name, description, source_url, image_url, rights)
    except ValueError as exc:
        await interaction.response.send_message(
            str(exc), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return
    except Exception:
        logger.exception("Curated strain profile save failed")
        await interaction.response.send_message(
            "Profile storage failed. No changes were confirmed.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"Credited profile for **{name}** saved. Use /strainprofile to preview it. "
        "You are responsible for having reuse rights for descriptions and images.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="doctorstrainclear", description="Application-owner: remove a curated description and image")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(name="Exact catalog strain name to remove")
async def doctorstrainclear(interaction: discord.Interaction,
                            name: app_commands.Range[str, 2, 60]):
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message(
            "Only the application owner can remove globally curated profiles.", ephemeral=True)
        return
    bot.strain_profiles.remove_curated(name)
    await interaction.response.send_message(
        "Curated profile removed. Catalog names and source links remain.",
        ephemeral=True)


@bot.tree.command(name="papers", description="Browse PubMed papers by indexed research design")
@app_commands.describe(topic="Cannabis research question or topic",
                       study_design="Choose a published study-design filter")
@app_commands.choices(study_design=[
    app_commands.Choice(name=label, value=value) for value, label in (
        ("all", "All Designs"),
        ("systematic", "Systematic Reviews"),
        ("randomized", "Randomized Controlled Trials"),
        ("observational", "Observational Studies"),
    )
])
@app_commands.checks.cooldown(1, 20, key=lambda i: (i.guild_id, i.user.id))
async def papers(interaction: discord.Interaction, topic: app_commands.Range[str, 3, 180],
                 study_design: str = "all"):
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.papers_answer(topic, study_design),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="labpanel", description="Post the public interactive cannabis science panel")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    title="Optional panel title (up to 75 characters)",
    intro="Optional short welcome line (up to 240 characters)",
    theme="Panel accent color",
    preview="Show the panel to only yourself instead of publishing",
    pin="Optional: add the published panel to channel Pinned Messages")
@app_commands.choices(theme=[
    app_commands.Choice(name=name.capitalize(), value=name) for name in PANEL_THEMES
])
async def labpanel(interaction: discord.Interaction, title: str | None = None,
                   intro: str | None = None, theme: str = "forest",
                   preview: bool = False, pin: bool = False):
    """Only server managers may publish a panel. Members may use its buttons."""
    bot.health.record("panel")
    if interaction.guild is None or interaction.channel is None:
        await interaction.response.send_message("Publish this panel in a server channel.", ephemeral=True)
        return
    if preview:
        await interaction.response.send_message(
            embed=panel_embed(title, intro, theme), view=LabPanelView(bot),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return
    if not (interaction.app_permissions.send_messages and interaction.app_permissions.embed_links):
        await interaction.response.send_message(
            "I need Send Messages and Embed Links in this channel to publish the panel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        posted = await interaction.channel.send(
            embed=panel_embed(title, intro, theme), view=LabPanelView(bot),
            allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logger.exception("Unable to publish Weed Doctor panel")
        await interaction.followup.send("Could not post the panel. Check my channel permissions.",
                                        ephemeral=True)
        return
    pin_message = ""
    if pin:
        try:
            await posted.pin(reason="Server manager requested pinned Weed Doctor research panel")
            pin_message = " • Added to channel pins."
        except discord.HTTPException:
            logger.warning("Published panel, but pinning failed guild=%s channel=%s",
                           interaction.guild_id, interaction.channel_id)
            pin_message = (
                " • Could not pin it. Give me **Pin Messages** permission"
                " (or Manage Messages where required), or pin it manually."
            )
    await interaction.followup.send(
        f"Public panel published: {posted.jump_url}" + pin_message,
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def extract_panel_message_id(value: str, guild_id: int, channel_id: int) -> int | None:
    """Accept only an ID or a Discord message link for this server/channel."""
    value = value.strip()
    if re.fullmatch(r"\d{17,21}", value):
        return int(value)
    found = re.fullmatch(
        r"https://(?:discord\.com|discordapp\.com)/channels/(\d{17,21})/(\d{17,21})/(\d{17,21})/?",
        value)
    if found and int(found.group(1)) == guild_id and int(found.group(2)) == channel_id:
        return int(found.group(3))
    return None


@bot.tree.command(name="labpanelupdate", description="Restyle an existing Weed Doctor panel message in this channel")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    message_link="Copy Message Link on the existing panel (or its message ID)",
    title="Updated title", intro="Updated short introduction", theme="New accent color",
    pin="Optional: true pins the panel; false removes its pin")
@app_commands.choices(theme=[
    app_commands.Choice(name=name.capitalize(), value=name) for name in PANEL_THEMES
])
async def labpanelupdate(interaction: discord.Interaction, message_link: str,
                         title: str | None = None, intro: str | None = None,
                         theme: str | None = None, pin: bool | None = None):
    if interaction.guild is None or interaction.channel is None:
        await interaction.response.send_message("Use this inside a server text channel.", ephemeral=True)
        return
    message_id = extract_panel_message_id(message_link, interaction.guild.id, interaction.channel.id)
    if message_id is None:
        await interaction.response.send_message(
            "Use a message ID or a panel link from this same channel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = await interaction.channel.fetch_message(message_id)
        if bot.user is None or message.author.id != bot.user.id:
            await interaction.followup.send("That message wasn't posted by The Weed Doctor.", ephemeral=True)
            return
        ids = [
            child.custom_id
            for component in message.components for child in getattr(component, "children", ())
            if getattr(child, "custom_id", None)
        ]
        if not any(cid.startswith("the420lab:panel:v1:") for cid in ids):
            await interaction.followup.send("That isn't a The Weed Doctor panel message.", ephemeral=True)
            return
        # Pin-only updates must preserve all existing custom branding.
        edit_kwargs = {
            "view": LabPanelView(bot),
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if title is not None or intro is not None or theme is not None:
            edit_kwargs["embed"] = panel_embed(title, intro, theme or "forest")
        await message.edit(**edit_kwargs)
    except discord.HTTPException:
        logger.exception("Unable to update Weed Doctor panel message")
        await interaction.followup.send(
            "Can't edit that panel. I may need Read Message History and Send Messages here.",
            ephemeral=True)
        return
    pin_notice = ""
    if pin is not None:
        try:
            if pin and not message.pinned:
                await message.pin(reason="Server manager enabled Weed Doctor panel pinning")
                pin_notice = " Added to channel Pinned Messages."
            elif not pin and message.pinned:
                await message.unpin(reason="Server manager disabled Weed Doctor panel pinning")
                pin_notice = " Removed from channel pins."
            else:
                pin_notice = " Pin status was already correct."
        except discord.HTTPException:
            pin_notice = (" Pin change failed. Give me Pin Messages"
                          " permission (or Manage Messages where required).")
            logger.warning("Could not change panel pin guild=%s channel=%s",
                           interaction.guild_id, interaction.channel_id)
    await interaction.followup.send(
        "Panel updated. All existing buttons remain usable." + pin_notice,
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="labcontrol", description="Application-owner control panel for AI usage and safe limits")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def labcontrol(interaction: discord.Interaction):
    """Owner only. Administrator visibility does NOT grant runtime access."""
    if not await bot.is_owner(interaction.user):
        await interaction.response.send_message(
            "Only The Weed Doctor's Discord application owner can open this control panel.",
            ephemeral=True)
        return
    try:
        details = owner_panel(bot)
    except QuotaExceeded:
        await interaction.response.send_message(
            "Quota storage is unavailable. Paid requests will remain blocked for safety.",
            ephemeral=True)
        return
    await interaction.response.send_message(
        embed=details, view=OwnerControlView(bot, interaction.user.id), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="labhealth", description="Show The Weed Doctor's process status (server managers)")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def labhealth(interaction: discord.Interaction):
    report = bot.health.report(
        len(bot.guilds), len(bot.science._cache) if bot.science else 0,
        ai_enabled=bool(bot.assistant and bot.assistant.ai and bot.quota.ai_enabled()))
    quota_lines = [f"{name}: {used}/{cap}" if used >= 0 else f"{name}: unavailable" 
                   for name, (used, cap) in bot.quota.usage().items()]
    report += "\n\n**Anonymous daily quotas:** " + " • ".join(quota_lines)
    report += "\n**Quota storage:** " + bot.quota.continuity_description()
    await interaction.response.send_message(
        report, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# Brand-forward aliases. Old /lab* commands and legacy persistent IDs remain active.
@bot.tree.command(name="doctorpanel", description="Publish The Weed Doctor public research panel")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    title="Optional panel title", intro="Optional short introduction",
    theme="Panel accent color", preview="Show only yourself before posting",
    pin="Optional: save this panel in the channel pins")
@app_commands.choices(theme=[
    app_commands.Choice(name=name.capitalize(), value=name) for name in PANEL_THEMES
])
async def doctorpanel(interaction: discord.Interaction, title: str | None = None,
                      intro: str | None = None, theme: str = "forest",
                      preview: bool = False, pin: bool = False):
    await labpanel.callback(
        interaction, title=title, intro=intro, theme=theme, preview=preview, pin=pin)


@bot.tree.command(name="doctorpanelupdate", description="Edit a posted Weed Doctor research panel")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    message_link="Panel message URL or ID in this channel",
    title="Updated title", intro="Updated introduction", theme="Accent color",
    pin="Optional: pin or unpin the panel in this channel")
@app_commands.choices(theme=[
    app_commands.Choice(name=name.capitalize(), value=name) for name in PANEL_THEMES
])
async def doctorpanelupdate(interaction: discord.Interaction, message_link: str,
                            title: str | None = None, intro: str | None = None,
                            theme: str | None = None, pin: bool | None = None):
    await labpanelupdate.callback(
        interaction, message_link=message_link, title=title, intro=intro,
        theme=theme, pin=pin)


@bot.tree.command(name="doctorcontrol", description="Weed Doctor app-owner AI and safety limits")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def doctorcontrol(interaction: discord.Interaction):
    # The underlying command verifies actual app ownership, not merely administrator status.
    await labcontrol.callback(interaction)


@bot.tree.command(name="doctorhealth", description="Weed Doctor server-manager process health")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def doctorhealth(interaction: discord.Interaction):
    await labhealth.callback(interaction)


@bot.tree.error
async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"Please wait {error.retry_after:.0f}s before trying again."
    else:
        logger.error("Command failure: %s", type(error).__name__)
        message = "Unable to complete that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    else:
        await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
