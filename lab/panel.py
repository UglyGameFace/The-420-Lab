"""Restart-safe public research panel with private answers."""
from __future__ import annotations
import asyncio
import logging
import re
from typing import TYPE_CHECKING
import discord
from .sources import COMPOUNDS
from .guidance import GUIDES, guide_message
from .fda import FDA_PRODUCTS
from .strains import result_text as strain_result_text
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

PANEL_THEMES = {
    "forest": 0x127B52,
    "mint": 0x2BBF91,
    "violet": 0x7255B8,
    "slate": 0x4B6473,
}

def safe_panel_text(value: str | None, *, max_length: int) -> str:
    """Keep public, per-server branding free of mass mentions and links."""
    if not value:
        return ""
    value = re.sub(r"https?://\S+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[<>@]", "", value).replace(chr(96), "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_length]

def panel_embed(title: str | None = None, intro: str | None = None,
                theme: str = "forest") -> discord.Embed:
    heading = safe_panel_text(title, max_length=75) or "THE WEED DOCTOR | Cannabis Science Desk"
    opening = safe_panel_text(intro, max_length=240) or (
        "Learn about THC, CBD, and cannabis using published research and official health guidance."
    )
    embed = discord.Embed(
        title="🌿 " + heading,
        description=f"**{opening}**\nChoose a button to explore benefits and risks, "
                    "cannabinoids, research, and historical strain names.",
        color=PANEL_THEMES.get(theme, PANEL_THEMES["forest"]))
    embed.add_field(name="🧠 Ask the Doctor", value="Enter your own question about effects or science.", inline=False)
    embed.add_field(name="📚 Explore Topics", value="Benefits, risks, anxiety, sleep, tolerance and more.", inline=False)
    embed.add_field(name="🧬 Cannabinoids", value="THC, CBD, CBG, CBN, THCA: sourced chemical facts.", inline=False)
    embed.add_field(name="🌱 Find Strains", value="Tap **Find Strains**, or use **/strains** and enter a name such as Northern Lights.", inline=False)
    embed.add_field(name="🔬 Research Library", value="PubMed, clinical trials, FDA reports, and official guides.", inline=False)
    embed.set_footer(text="Answers are private • Evidence, not hype • Not a medical professional")
    return embed

async def answer(interaction: discord.Interaction, bot: LabBot, kind: str, value: str) -> None:
    """The panel uses the SAME read-only answer handlers as slash commands."""
    remaining = bot.panel_wait(interaction.user.id)
    if remaining:
        await interaction.response.send_message(
            f"Please wait {remaining} seconds before your next research request.", ephemeral=True)
        return
    if not await bot.admit_interaction(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    if kind == "ask":
        content = await bot.research_answer(value)
    elif kind == "compound":
        content = await bot.compound_answer(value)
    elif kind == "trials":
        content = await bot.trials_answer(value)
    elif kind == "fda":
        content = await bot.fda_answer(value)
    else:
        content = "Unsupported research request."
    await interaction.followup.send(content, allowed_mentions=discord.AllowedMentions.none())

class ResearchModal(discord.ui.Modal):
    def __init__(self, bot: LabBot, kind: str):
        if kind == "ask":
            title, label, hint, lower, upper = (
                "Ask The Weed Doctor", "Your cannabis science question",
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


class FDAProductSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Select an FDA-approved medicine…", min_values=1, max_values=1,
            options=[discord.SelectOption(label=label, value=key)
                     for key, label in FDA_PRODUCTS.items()])

    async def callback(self, interaction: discord.Interaction):
        await answer(interaction, self.view.bot, "fda", self.values[0])


class StrainQueryModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Find a Cannabis Strain", timeout=300)
        self.search_term = discord.ui.TextInput(
            label="Enter a strain name", placeholder="Example: Northern Lights",
            min_length=2, max_length=60)
        self.add_item(self.search_term)

    async def on_submit(self, interaction: discord.Interaction):
        if not await interaction.client.admit_interaction(interaction):
            return
        await interaction.response.send_message(
            strain_result_text(str(self.search_term.value)), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())


class PapersModal(discord.ui.Modal):
    def __init__(self, bot: LabBot, kind: str):
        super().__init__(title="Browse PubMed Evidence", timeout=300)
        self.bot = bot
        self.kind = kind
        self.query = discord.ui.TextInput(
            label="Cannabis science topic", placeholder="Try: cannabis and sleep",
            min_length=3, max_length=180)
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        remaining = self.bot.panel_wait(interaction.user.id)
        if remaining:
            await interaction.response.send_message(
                f"Try again in {remaining} seconds.", ephemeral=True)
            return
        if not await self.bot.admit_interaction(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        content = await self.bot.papers_answer(str(self.query.value), self.kind)
        await interaction.followup.send(
            content, allowed_mentions=discord.AllowedMentions.none())


class StudyDesignSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="All Study Designs", value="all"),
            discord.SelectOption(label="Systematic Reviews", value="systematic"),
            discord.SelectOption(label="Randomized Controlled Trials", value="randomized"),
            discord.SelectOption(label="Observational Studies", value="observational"),
        ]
        super().__init__(placeholder="Select study type…", options=options,
                         min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PapersModal(self.view.bot, self.values[0]))


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

    @discord.ui.button(label="FDA Safety Reports", emoji="⚠️",
                       style=discord.ButtonStyle.secondary)
    async def fda_reports(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**FDA reporting data, not side-effect probabilities.** "
            "Select an FDA-approved cannabinoid medicine to see reported reaction terms. "
            "Reports can include other drugs, duplicates, and unverified information.",
            view=MemberMenu(self.bot, interaction.user.id, FDAProductSelect()), ephemeral=True)

    @discord.ui.button(label="Strain Name Reference", emoji="🌱",
                       style=discord.ButtonStyle.secondary)
    async def strain_names(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StrainQueryModal())

    @discord.ui.button(label="Advanced Evidence Search", emoji="🧪",
                       style=discord.ButtonStyle.secondary)
    async def advanced_papers(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "**Advanced PubMed:** filter by the study design indexed by PubMed. "
            "Design is not an evidence quality grade.",
            view=MemberMenu(self.bot, interaction.user.id, StudyDesignSelect()), ephemeral=True)

class LabPanelView(discord.ui.View):
    """Stable legacy component IDs keep posted panels functional across the rebrand."""
    def __init__(self, bot: LabBot):
        super().__init__(timeout=None)
        self.bot = bot
        self._refresh_pending: set[int] = set()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Preserve custom branding and quietly upgrade older posted panels."""
        message = interaction.message
        if (
            message is not None
            and self.bot.user is not None
            and message.author.id == self.bot.user.id
        ):
            rows = getattr(message, "components", ())
            controls = {
                getattr(child, "custom_id", None)
                for row in rows
                for child in getattr(row, "children", ())
            }
            missing_strain = "the420lab:panel:v1:strain" not in controls
            old_default = bool(
                message.embeds and message.embeds[0].title == "🌿 THE 420 LAB | Cannabis Science Desk"
            )
            if (missing_strain or old_default) and message.id not in self._refresh_pending:
                self._refresh_pending.add(message.id)
                # Do not delay Discord's interaction acknowledgement to edit the old post.
                asyncio.create_task(self._refresh_panel(message, old_default))
        return True

    async def _refresh_panel(self, message: discord.Message, old_default: bool) -> None:
        try:
            opts = {
                "view": self,
                "allowed_mentions": discord.AllowedMentions.none(),
            }
            if old_default:
                opts["embed"] = panel_embed()
            await message.edit(**opts)
        except discord.HTTPException:
            log.warning("Could not add strain button to an earlier Weed Doctor panel")
        finally:
            self._refresh_pending.discard(message.id)

    @discord.ui.button(label="Ask the Doctor", emoji="🧠", style=discord.ButtonStyle.primary,
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
            "**Research Library:** PubMed research, clinical trials, agency guides, FDA reports and historical strain names.",
            view=LibraryMenu(self.bot, interaction.user.id), ephemeral=True)
    @discord.ui.button(label="Find Strains", emoji="🌱", style=discord.ButtonStyle.success,
                       custom_id="the420lab:panel:v1:strain", row=1)
    async def find_strains(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StrainQueryModal())

    @discord.ui.button(label="Help & Safety", emoji="ℹ️", style=discord.ButtonStyle.secondary,
                       custom_id="the420lab:panel:v1:help", row=1)
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="The Weed Doctor • How to Use", color=discord.Color.from_rgb(18, 123, 82))
        embed.description = (
            "**Ask:** Type any science question.\n**Topics:** Choose a preset research question.\n"
            "**Cannabinoids:** Explore PubChem chemistry.\n**Find Strains:** Tap 🌱 Find Strains or enter `/strains` and a strain name, such as Northern Lights.\n"            "**Research:** Studies, advanced design filters, trials, guides, and FDA reports.\n\n"
            "Your responses are private. If enabled, Gemini receives your question and source excerpts; "
            "do not enter private health details. A paper or trial listing isn't proof of benefit. "
            "For severe symptoms, contact emergency services. This is an educational bot, not a physician.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        log.error("Lab panel failed: %s", type(error).__name__)
        if interaction.response.is_done():
            await interaction.followup.send("That action failed. Please try again.", ephemeral=True)
        else:
            await interaction.response.send_message("That action failed. Please try again.", ephemeral=True)
