"""Restart-safe public research panel with private answers."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING
import discord
from .sources import COMPOUNDS
from .guidance import GUIDES, guide_message
if TYPE_CHECKING:
    from .bot import LabBot
log = logging.getLogger(__name__)

TOPICS = {
    "benefits": "What health benefits of THC are supported by human clinical research?",
    "risks": "What adverse effects and risks of THC use are known?",
    "anxiety": "What is the clinical evidence about THC anxiety and panic?",
    "sleep": "What does clinical research report about cannabis and sleep?",
    "tolerance": "What is known about cannabis tolerance dependence and withdrawal?",
    "edibles": "What delayed effects and adverse reactions occur with cannabis edibles?",
    "smoking": "What are the respiratory risks of smoking cannabis?",
    "vaping": "What are the health risks of vaping cannabis concentrates?",
    "medications": "What interactions between cannabinoids and medications have been studied?",
}

def panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌿 THE 420 LAB | Cannabis Science Desk",
        description="**Learn about THC, CBD, and cannabis with actual research.**\n"
                    "Explore benefits **and** risks, look up cannabinoids, or dig into clinical trials. "
                    "Start with any button below. No commands to memorize.",
        color=discord.Color.from_rgb(18, 123, 82))
    embed.add_field(name="🧠 Ask the Lab", value="Enter your own question about effects or science.", inline=False)
    embed.add_field(name="📚 Explore Topics", value="Benefits, risks, anxiety, sleep, tolerance and more.", inline=False)
    embed.add_field(name="🧬 Cannabinoids", value="THC, CBD, CBG, CBN, THCA: sourced chemical facts.", inline=False)
    embed.add_field(name="🔬 Research Library", value="Search scientific articles and trial registrations.", inline=False)
    embed.set_footer(text="Answers are private • Evidence, not hype • Not medical advice")
    return embed

async def answer(interaction: discord.Interaction, bot: LabBot, kind: str, value: str) -> None:
    """The panel uses the SAME read-only answer handlers as slash commands."""
    remaining = bot.panel_wait(interaction.user.id)
    if remaining:
        await interaction.response.send_message(
            f"Please wait {remaining} seconds before your next research request.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    if kind == "ask":
        content = await bot.research_answer(value)
    elif kind == "compound":
        content = await bot.compound_answer(value)
    elif kind == "trials":
        content = await bot.trials_answer(value)
    else:
        content = "Unsupported research request."
    await interaction.followup.send(content, allowed_mentions=discord.AllowedMentions.none())

class ResearchModal(discord.ui.Modal):
    def __init__(self, bot: LabBot, kind: str):
        if kind == "ask":
            title, label, hint, lower, upper = (
                "Ask The 420 Lab", "Your cannabis science question",
                "What are the benefits and risks of THC?", 4, 220)
        elif kind == "trials":
            title, label, hint, lower, upper = (
                "Find Registered Trials", "Condition or topic", "Sleep or chronic pain", 3, 100)
        else:
            raise ValueError("Unknown modal kind")
        super().__init__(title=title, timeout=300)
        self.bot, self.kind = bot, kind
        self.query = discord.ui.TextInput(label=label, placeholder=hint, min_length=lower,
                                          max_length=upper,
                                          style=discord.TextStyle.paragraph if kind == "ask"
                                          else discord.TextStyle.short)
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await answer(interaction, self.bot, self.kind, str(self.query.value))

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error("Research modal error: %s", type(error).__name__)
        if interaction.response.is_done():
            await interaction.followup.send("The request failed. Please retry.", ephemeral=True)
        else:
            await interaction.response.send_message("The request failed. Please retry.", ephemeral=True)

class TopicSelect(discord.ui.Select):
    def __init__(self):
        entries = [
            ("Potential benefits", "benefits", "What human studies support", "✅"),
            ("Adverse effects", "risks", "Potential physical and mental risks", "⚠️"),
            ("Anxiety and panic", "anxiety", "How THC may affect anxiety", "🧠"),
            ("Sleep", "sleep", "What clinical research says", "🌙"),
            ("Tolerance and withdrawal", "tolerance", "Dependence and withdrawal", "📉"),
            ("Edibles", "edibles", "Delayed effects and safety", "🍪"),
            ("Smoking risks", "smoking", "Lung and respiratory research", "🌬️"),
            ("Vaping risks", "vaping", "Research into vaping cannabis", "🔬"),
            ("Medication interactions", "medications", "What interactions are documented", "💊"),
        ]
        super().__init__(placeholder="Choose a research topic…", min_values=1, max_values=1,
                         options=[discord.SelectOption(label=l, value=v, description=d, emoji=e)
                                  for l, v, d, e in entries])

    async def callback(self, interaction: discord.Interaction) -> None:
        await answer(interaction, self.view.bot, "ask", TOPICS[self.values[0]])

class CompoundSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Select a cannabinoid…", min_values=1, max_values=1,
                         options=[discord.SelectOption(label=k, value=k) for k in COMPOUNDS])
    async def callback(self, interaction: discord.Interaction) -> None:
        await answer(interaction, self.view.bot, "compound", self.values[0])

class OfficialGuideSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose an official health guide…", min_values=1, max_values=1,
            options=[discord.SelectOption(label=guide.title, value=key)
                     for key, guide in GUIDES.items()])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            guide_message(self.values[0]), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())


class MemberMenu(discord.ui.View):
    def __init__(self, bot: LabBot, owner_id: int, item: discord.ui.Select):
        super().__init__(timeout=180)
        self.bot, self.owner_id = bot, owner_id
        self.add_item(item)
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Open the public panel for your own menu.", ephemeral=True)
            return False
        return True

class LibraryMenu(discord.ui.View):
    def __init__(self, bot: LabBot, owner_id: int):
        super().__init__(timeout=180)
        self.bot, self.owner_id = bot, owner_id
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Open the public panel for your own menu.", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Search PubMed", emoji="📄", style=discord.ButtonStyle.primary)
    async def papers(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResearchModal(self.bot, "ask"))
    @discord.ui.button(label="Clinical Trials", emoji="🧪", style=discord.ButtonStyle.secondary)
    async def trials(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResearchModal(self.bot, "trials"))

    @discord.ui.button(label="Official NIH / CDC / FDA Guides", emoji="📖",
                       style=discord.ButtonStyle.secondary)
    async def official_guides(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Official health guidance:** choose a reviewed topic and read the original sources.",
            view=MemberMenu(self.bot, interaction.user.id, OfficialGuideSelect()), ephemeral=True)

class LabPanelView(discord.ui.View):
    """Stable custom IDs and timeout=None enable restart-safe callbacks."""
    def __init__(self, bot: LabBot):
        super().__init__(timeout=None)
        self.bot = bot
    @discord.ui.button(label="Ask the Lab", emoji="🧠", style=discord.ButtonStyle.primary,
                       custom_id="the420lab:panel:v1:ask", row=0)
    async def ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResearchModal(self.bot, "ask"))
    @discord.ui.button(label="Explore Topics", emoji="📚", style=discord.ButtonStyle.secondary,
                       custom_id="the420lab:panel:v1:topics", row=0)
    async def topics(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Explore evidence-based topics.** Choose one for a private research response.",
            view=MemberMenu(self.bot, interaction.user.id, TopicSelect()), ephemeral=True)
    @discord.ui.button(label="Cannabinoids", emoji="🧬", style=discord.ButtonStyle.secondary,
                       custom_id="the420lab:panel:v1:compounds", row=0)
    async def compounds(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Cannabinoid chemistry:** molecular facts, not medical recommendations.",
            view=MemberMenu(self.bot, interaction.user.id, CompoundSelect()), ephemeral=True)
    @discord.ui.button(label="Research Library", emoji="🔬", style=discord.ButtonStyle.secondary,
                       custom_id="the420lab:panel:v1:library", row=1)
    async def library(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Research Library:** PubMed articles, registered trials and official health guidance.",
            view=LibraryMenu(self.bot, interaction.user.id), ephemeral=True)
    @discord.ui.button(label="Help & Safety", emoji="ℹ️", style=discord.ButtonStyle.secondary,
                       custom_id="the420lab:panel:v1:help", row=1)
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="The 420 Lab • How to Use", color=discord.Color.from_rgb(18, 123, 82))
        embed.description = (
            "**Ask:** Type any science question.\n**Topics:** Choose a preset research question.\n"
            "**Cannabinoids:** Explore PubChem chemistry.\n**Research:** Search studies, trials and official agency guides.\n\n"
            "Your responses are private. If enabled, Gemini receives your question and source excerpts; "
            "do not enter private health details. A paper or trial listing isn't proof of benefit. "
            "For severe symptoms, contact emergency services.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error("Lab panel failed: %s", type(error).__name__)
        if interaction.response.is_done():
            await interaction.followup.send("That action failed. Please try again.", ephemeral=True)
        else:
            await interaction.response.send_message("That action failed. Please try again.", ephemeral=True)
