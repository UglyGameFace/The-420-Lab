"""Discord slash commands for cannabis research education."""
from __future__ import annotations
import asyncio
import time
from collections import OrderedDict
import logging
import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from .sources import COMPOUNDS, ScienceSources, SourceError
from .answers import GeminiAnswer, ResearchAssistant, clip_discord
from .panel import LabPanelView, panel_embed
from .guidance import GUIDES, guide_message
from .fda import FDA_PRODUCTS, report_message
from .strains import result_text as strain_result_text

logger = logging.getLogger(__name__)


class LabBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.http_session = None
        self.science = None
        self.assistant = None
        self.limiter = asyncio.Semaphore(3)
        self._panel_access = OrderedDict()

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=18),
            headers={"User-Agent": "The420Lab/0.1 (Discord cannabis research bot)"})
        self.science = ScienceSources(self.http_session, os.getenv("NCBI_API_KEY", ""),
                                     os.getenv("OPENFDA_API_KEY", ""))
        key = os.getenv("GEMINI_API_KEY", "")
        ai = GeminiAnswer(self.http_session, key, os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")) if key else None
        self.assistant = ResearchAssistant(self.science, ai)
        # Register the persistent panel before syncing slash commands.
        self.add_view(LabPanelView(self))
        await self.sync_commands()
        logger.info("AI configured: %s", bool(ai))

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
        try:
            async with self.limiter:
                assert self.assistant is not None
                return clip_discord(await self.assistant.answer(question))
        except Exception:
            logger.exception("Research request failed")
            return "Research lookup failed. Please try again; I won't guess about health effects."

    async def compound_answer(self, name: str) -> str:
        try:
            async with self.limiter:
                assert self.science is not None
                item = await self.science.compound(name)
            if item:
                return (f"**{item.name}**: PubChem CID {item.cid}\n"
                        f"Formula: {item.formula} | Molecular weight: {item.molecular_weight} g/mol\n"
                        f"{item.url}\n\nChemistry does not establish health benefits or safe dosing.")
            return "PubChem did not find a matching record."
        except (SourceError, ValueError):
            return "PubChem is temporarily unavailable for that compound."

    async def trials_answer(self, topic: str) -> str:
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
        except SourceError:
            return "ClinicalTrials.gov is currently unavailable."

    async def fda_answer(self, product: str) -> str:
        try:
            async with self.limiter:
                assert self.science is not None
                data = await self.science.fda_reports(product)
            return clip_discord(report_message(data))
        except ValueError:
            return "Choose a supported FDA-approved medicine from the menu."
        except SourceError:
            return ("openFDA safety-report data is temporarily unavailable. "
                    "These reports do not establish causation or side-effect rates.")

    async def on_ready(self):
        # Startup diagnostic; never log tokens or user questions.
        logger.info("Discord gateway ready: bot=%s guild_count=%d", self.user, len(self.guilds))

    async def close(self):
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
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.research_answer(question),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="compound", description="View cannabinoid chemistry from NIH PubChem")
@app_commands.describe(name="Select a cannabinoid")
@app_commands.choices(name=[app_commands.Choice(name=k, value=k) for k in COMPOUNDS])
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def compound(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.compound_answer(name),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="trials", description="Find registered cannabis trials on ClinicalTrials.gov")
@app_commands.describe(topic="Example: anxiety, sleep, chronic pain")
@app_commands.checks.cooldown(1, 15, key=lambda i: (i.guild_id, i.user.id))
async def trials(interaction: discord.Interaction, topic: app_commands.Range[str, 3, 100]):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.trials_answer(topic),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="scienceguide", description="Explore official NIH CDC and FDA cannabis guidance")
@app_commands.describe(topic="Choose an official health-information topic")
@app_commands.choices(topic=[
    app_commands.Choice(name=guide.title, value=key) for key, guide in GUIDES.items()
])
async def scienceguide(interaction: discord.Interaction, topic: str):
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
    await interaction.response.defer(ephemeral=True, thinking=True)
    await interaction.followup.send(await bot.fda_answer(medicine),
                                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="strain", description="Search an attributed historical cannabis strain-name reference")
@app_commands.describe(name="Strain or cultivar name, not an effect prediction")
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def strain(interaction: discord.Interaction, name: app_commands.Range[str, 2, 60]):
    await interaction.response.send_message(
        strain_result_text(name), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="labpanel", description="Post the public interactive cannabis science panel")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def labpanel(interaction: discord.Interaction):
    """Only server managers may publish a panel. Members may use its buttons."""
    if interaction.guild is None or interaction.channel is None:
        await interaction.response.send_message("Publish this panel in a server channel.", ephemeral=True)
        return
    if not (interaction.app_permissions.send_messages and interaction.app_permissions.embed_links):
        await interaction.response.send_message(
            "I need Send Messages and Embed Links in this channel to publish the panel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        posted = await interaction.channel.send(
            embed=panel_embed(), view=LabPanelView(bot),
            allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logger.exception("Unable to publish Lab panel")
        await interaction.followup.send("Could not post the panel. Check my channel permissions.",
                                        ephemeral=True)
        return
    await interaction.followup.send(f"Public panel published: {posted.jump_url}", ephemeral=True)


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
