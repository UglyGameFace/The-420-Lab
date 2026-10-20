"""Discord slash commands for cannabis research education."""
from __future__ import annotations
import asyncio
import logging
import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from .sources import COMPOUNDS, ScienceSources, SourceError
from .answers import GeminiAnswer, ResearchAssistant, clip_discord

logger = logging.getLogger(__name__)


class LabBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.http_session = None
        self.science = None
        self.assistant = None
        self.limiter = asyncio.Semaphore(3)

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=18),
            headers={"User-Agent": "The420Lab/0.1 (Discord cannabis research bot)"})
        self.science = ScienceSources(self.http_session, os.getenv("NCBI_API_KEY", ""))
        key = os.getenv("GEMINI_API_KEY", "")
        ai = GeminiAnswer(self.http_session, key, os.getenv("GEMINI_MODEL", "gemini-2.5-flash")) if key else None
        self.assistant = ResearchAssistant(self.science, ai)
        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        logger.info("Commands synced; AI configured: %s", bool(ai))

    async def close(self):
        try:
            if self.http_session:
                await self.http_session.close()
        finally:
            await super().close()


bot = LabBot()


@bot.tree.command(name="askthc", description="Ask about THC and cannabis using PubMed evidence")
@app_commands.describe(question="Ask about effects, benefits, risks, or cannabinoid research")
@app_commands.checks.cooldown(1, 20, key=lambda i: (i.guild_id, i.user.id))
async def askthc(interaction: discord.Interaction, question: app_commands.Range[str, 4, 220]):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        async with bot.limiter:
            assert bot.assistant is not None
            answer = await bot.assistant.answer(question)
    except Exception:
        logger.exception("askthc failed")
        answer = "Research lookup failed. Please try again; I won't guess about health effects."
    await interaction.followup.send(clip_discord(answer), allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="compound", description="View cannabinoid chemistry from NIH PubChem")
@app_commands.describe(name="Select a cannabinoid")
@app_commands.choices(name=[app_commands.Choice(name=k, value=k) for k in COMPOUNDS])
@app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
async def compound(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        async with bot.limiter:
            assert bot.science is not None
            item = await bot.science.compound(name)
        if item:
            message = (f"**{item.name}**: PubChem CID {item.cid}\n"
                       f"Formula: {item.formula} | Molecular weight: {item.molecular_weight} g/mol\n"
                       f"{item.url}\n\nChemistry does not establish health benefits or safe dosing.")
        else:
            message = "PubChem did not find a matching record."
    except (SourceError, ValueError):
        message = "PubChem is temporarily unavailable for that compound."
    await interaction.followup.send(message, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="trials", description="Find registered cannabis trials on ClinicalTrials.gov")
@app_commands.describe(topic="Example: anxiety, sleep, chronic pain")
@app_commands.checks.cooldown(1, 15, key=lambda i: (i.guild_id, i.user.id))
async def trials(interaction: discord.Interaction, topic: app_commands.Range[str, 3, 100]):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        async with bot.limiter:
            assert bot.science is not None
            studies = await bot.science.trials(topic)
        if studies:
            message = "**ClinicalTrials.gov studies**\n" + "\n".join(
                f"• {s.title[:100]} ({s.status})\n  {s.url}" for s in studies)
        else:
            message = "No matching registered studies found."
        message += "\n\nTrial registration does not prove a treatment works."
    except SourceError:
        message = "ClinicalTrials.gov is currently unavailable."
    await interaction.followup.send(clip_discord(message), allowed_mentions=discord.AllowedMentions.none())


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
