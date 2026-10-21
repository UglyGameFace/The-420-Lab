"""Centered Discord modal pickers instead of menus buried below busy chat."""
from __future__ import annotations

import discord
from .sources import COMPOUNDS
from .guidance import GUIDES, guide_message
from .fda import FDA_PRODUCTS
from .strains import result_text as strain_result_text
from .leafly import leafly_answer


class TopicPicker(discord.ui.Modal):
    def __init__(self, bot):
        from .panel import TopicSelect
        super().__init__(title="Explore Cannabis Research", timeout=300)
        self.bot = bot
        self.choice = discord.ui.Select(
            placeholder="Choose one research topic", options=TopicSelect().options)
        self.add_item(discord.ui.Label(text="Topic", component=self.choice))

    async def on_submit(self, interaction):
        from .panel import TOPICS, answer
        await answer(interaction, self.bot, "ask", TOPICS[self.choice.values[0]])


class CannabinoidPicker(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Explore Cannabinoids", timeout=300)
        self.bot = bot
        self.choice = discord.ui.Select(
            placeholder="Choose a cannabinoid",
            options=[discord.SelectOption(label=name, value=name) for name in COMPOUNDS])
        self.add_item(discord.ui.Label(text="Cannabinoid", component=self.choice))

    async def on_submit(self, interaction):
        from .panel import answer
        await answer(interaction, self.bot, "compound", self.choice.values[0])


def library_options():
    options = [
        discord.SelectOption(label="PubMed: Research Papers", value="papers:all"),
        discord.SelectOption(label="Registered Clinical Trials", value="trials"),
        discord.SelectOption(label="Historical Strain Names", value="strain"),
        discord.SelectOption(label="Database Size & Source Dates", value="database",
                             description="Live catalog count and independent data sources"),
        discord.SelectOption(label="Leafly Strain Profiles", value="leafly",
                             description="Verified pages or targeted search"),
        discord.SelectOption(label="Systematic Reviews", value="papers:systematic"),
        discord.SelectOption(label="Randomized Trials", value="papers:randomized"),
        discord.SelectOption(label="Observational Studies", value="papers:observational"),
    ]
    options.extend(
        discord.SelectOption(label="Official: " + item.title[:72], value="guide:" + name)
        for name, item in GUIDES.items())
    options.extend(
        discord.SelectOption(label="FDA: " + description[:80], value="fda:" + name)
        for name, description in FDA_PRODUCTS.items())
    return options


class LibraryPicker(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Weed Doctor Research Library", timeout=300)
        self.bot = bot
        self.choice = discord.ui.Select(
            placeholder="Select a research category", options=library_options())
        self.add_item(discord.ui.Label(text="Research category", component=self.choice))
        self.query = discord.ui.TextInput(
            placeholder="For searches: cannabis sleep or Northern Lights",
            max_length=180, required=False)
        self.add_item(discord.ui.Label(
            text="Topic or strain name (for searches)", component=self.query))

    async def on_submit(self, interaction):
        from .panel import answer
        choice = self.choice.values[0]
        if choice == "database":
            from .strain_profiles import database_embed
            await interaction.response.send_message(
                embed=database_embed(), ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        if choice.startswith("guide:"):
            await interaction.response.send_message(
                guide_message(choice.split(":", 1)[1]),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        if choice.startswith("fda:"):
            await answer(interaction, self.bot, "fda", choice.split(":", 1)[1])
            return

        term = str(self.query.value or "").strip()
        if len(term) < 2:
            await interaction.response.send_message(
                "Enter a topic or strain name in the second field for that search.",
                ephemeral=True)
            return
        if choice == "trials":
            await answer(interaction, self.bot, "trials", term[:100])
            return
        if choice == "leafly":
            if not await self.bot.admit_interaction(interaction):
                return
            await interaction.response.send_message(
                leafly_answer(term[:60]), ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        if choice == "strain":
            if not await self.bot.admit_interaction(interaction):
                return
            await interaction.response.send_message(
                strain_result_text(term[:60]), ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        if choice.startswith("papers:"):
            wait = self.bot.panel_wait(interaction.user.id)
            if wait:
                await interaction.response.send_message(
                    f"Try again in {wait} seconds.", ephemeral=True)
                return
            if not await self.bot.admit_interaction(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            result = await self.bot.papers_answer(
                term, choice.split(":", 1)[1])
            await interaction.followup.send(
                result, allowed_mentions=discord.AllowedMentions.none())
            return
        await interaction.response.send_message(
            "Unsupported research category.", ephemeral=True)
