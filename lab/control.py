"""Ephemeral app-owner-only quota control UI. Does not manage Google billing."""
from __future__ import annotations
import sqlite3
import discord
from .quotas import QuotaExceeded

LIMITS = (
    ("gemini_daily", "Gemini per UTC day", "Maximum daily AI requests"),
    ("gemini_minute", "Gemini per minute", "Maximum minute AI requests"),
    ("member_10m", "Member per 10 minutes", "Per-member research allowance"),
    ("guild_hour", "Server per hour", "Per-server research allowance"),
    ("global_daily", "Bot per UTC day", "Maximum bot-wide research actions"),
    ("global_minute", "Bot per minute", "Maximum bot-wide research actions"),
    ("api_daily", "Research APIs per UTC day", "Combined public API requests"),
    ("api_minute", "Research APIs per minute", "Combined public API requests"),
)

def panel(bot) -> discord.Embed:
    quota = bot.quota
    values = []
    for key, title, _ in LIMITS:
        values.append(f"• {title}: **{quota.limit(key)}** (ceiling {getattr(quota, key)})")
    ai_ready = bool(bot.assistant and bot.assistant.ai)
    enabled = quota.ai_enabled() and ai_ready
    usage = quota.usage()
    summary = " • ".join(
        f"{name} {used}/{cap}" if used >= 0 else f"{name} unavailable"
        for name, (used, cap) in usage.items())
    embed = discord.Embed(
        title="🛡️ The 420 Lab | Owner Control Center",
        description=(
            f"**Gemini:** {'Enabled' if enabled else 'Paused / not configured'}\n"
            "**Edit limits or pause AI below.** Only the Discord application owner can make changes. "
            "Changes take effect immediately without a bot restart."
        ),
        color=0x127B52)
    embed.add_field(name="Current limits", value="\n".join(values), inline=False)
    embed.add_field(name="Current UTC-day usage", value=summary, inline=False)
    embed.add_field(name="Quota storage continuity",
                    value=quota.continuity_description(), inline=False)
    embed.add_field(name="Important boundary",
                    value=("These are **The 420 Lab's** limits, not Google's official "
                           "billing caps. Values cannot exceed the private hosting ceilings. "
                           "Settings remain saved only while the quota SQLite database is retained."),
                    inline=False)
    embed.set_footer(text="Private to the app owner • No keys, prompts or member identities displayed")
    return embed


class LimitModal(discord.ui.Modal):
    def __init__(self, bot, owner_id: int, setting: str):
        label = next(title for key, title, _ in LIMITS if key == setting)
        maximum = getattr(bot.quota, setting)
        super().__init__(title="Set " + label[:34], timeout=180)
        self.bot = bot
        self.owner_id = owner_id
        self.setting = setting
        self.value = discord.ui.TextInput(
            label=f"New limit (1 to {maximum})",
            placeholder=f"Current: {bot.quota.limit(setting)}",
            min_length=1, max_length=6, required=True)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id or not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Only the bot application owner can change limits.", ephemeral=True)
            return
        raw = str(self.value.value).strip()
        if not raw.isdecimal():
            await interaction.response.send_message("Enter a whole positive number.", ephemeral=True)
            return
        try:
            self.bot.quota.set_limit(self.setting, int(raw))
            new = panel(self.bot)
        except (ValueError, QuotaExceeded, sqlite3.Error):
            await interaction.response.send_message(
                "That limit is invalid or quota storage is unavailable; no change was applied.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            "New limit applied. Existing usage counters were not reset.",
            embed=new, ephemeral=True)


class LimitSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose a usage limit to edit…",
            options=[discord.SelectOption(label=title, value=name, description=hint)
                     for name, title, hint in LIMITS],
            min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            LimitModal(self.view.bot, self.view.owner_id, self.values[0]))


class OwnerControlView(discord.ui.View):
    def __init__(self, bot, owner_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.owner_id = owner_id
        self.add_item(LimitSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "Only the bot application owner can use this control panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pause / Resume Gemini", emoji="🛑", style=discord.ButtonStyle.danger)
    async def switch_ai(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            old = self.bot.quota.ai_enabled()
            self.bot.quota.set_ai_enabled(not old)
            view = panel(self.bot)
        except (ValueError, QuotaExceeded, sqlite3.Error):
            await interaction.response.send_message(
                "AI setting could not be changed. Hosting may prohibit AI or storage is unavailable.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            "Gemini is now " + ("paused." if old else "enabled."),
            embed=view, ephemeral=True)

    @discord.ui.button(label="Refresh usage", emoji="📊", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            details = panel(self.bot)
        except (QuotaExceeded, sqlite3.Error):
            await interaction.response.send_message(
                "Quota storage is unavailable. AI requests are blocked until it recovers.",
                ephemeral=True)
            return
        await interaction.response.send_message(embed=details, ephemeral=True)
