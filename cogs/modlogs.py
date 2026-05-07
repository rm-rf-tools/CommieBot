"""
filename: modlogs.py
description: Server moderation logging system for channel events and keyword/regex tracking in messages.
Views:
    - TrackedWordsView: Interactive paginated view for managing tracked words/patterns.
    - AddWordModal: Modal for adding a new tracked word/pattern.
    - EditWordModal: Modal for editing an existing tracked word/pattern.
    - WordGroupView: Interactive paginated view for managing word groups.
Commands:
    - /modlogs channel <channel>: Set the channel to receive mod logs. (Admin: Manage Guild)
    - /modlogs toggle <event> <enabled>: Enable or disable specific logging events. (Admin: Manage Guild)
    - /modlogs words: Open the tracked words management panel. (Admin: Manage Guild)
    - /modlogs import <file> [action] [is_regex] [group_name]: Bulk import words from a text file. (Admin: Manage Guild)
    - /modlogs groups: Manage word groups (change action, delete). (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import re
import io
from db import DatabaseController

# --- Action Constants ---
ACTION_CHOICES = ["notify", "delete", "kick", "ban"]
ACTION_LABELS = {
    "notify": "📢 Notify Only",
    "delete": "🗑️ Delete Message",
    "kick": "👢 Kick User",
    "ban": "🔨 Ban User",
}
ACTION_COLORS = {
    "notify": discord.Color.orange(),
    "delete": discord.Color.yellow(),
    "kick": discord.Color.dark_orange(),
    "ban": discord.Color.red(),
}


# ─── Modals ───────────────────────────────────────────────

class AddWordModal(discord.ui.Modal, title="Add Tracked Word / Pattern"):
    name_input = discord.ui.TextInput(
        label="Rule Name (for display)",
        placeholder="e.g. Slur filter, Spam link pattern",
        required=True,
        max_length=100,
    )
    pattern_input = discord.ui.TextInput(
        label="Word or Regex Pattern",
        placeholder="e.g. badword or \\bb[a@]d\\b",
        required=True,
        max_length=3000,
    )
    is_regex_input = discord.ui.TextInput(
        label="Is this a regex pattern? (yes / no)",
        placeholder="no",
        required=False,
        default="no",
        max_length=3,
    )

    def __init__(self, parent_view: "TrackedWordsView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        pattern = self.pattern_input.value.strip()
        is_regex = self.is_regex_input.value.strip().lower() in ("yes", "y")

        if is_regex:
            try:
                re.compile(pattern)
            except re.error as e:
                return await interaction.response.send_message(
                    f"❌ Invalid regex: `{e}`", ephemeral=True
                )

        await DatabaseController.add_tracked_word(
            self.parent_view.guild_id, pattern, is_regex=is_regex, action="notify", name=name
        )
        await self.parent_view.refresh(interaction)


class EditWordModal(discord.ui.Modal, title="Edit Tracked Word / Pattern"):
    name_input = discord.ui.TextInput(
        label="Rule Name (for display)",
        required=True,
        max_length=100,
    )
    pattern_input = discord.ui.TextInput(
        label="Word or Regex Pattern",
        required=True,
        max_length=3000,
    )
    is_regex_input = discord.ui.TextInput(
        label="Is this a regex pattern? (yes / no)",
        required=False,
        max_length=3,
    )

    def __init__(self, parent_view: "TrackedWordsView", word):
        super().__init__()
        self.parent_view = parent_view
        self.word = word
        self.name_input.default = word.name or word.pattern[:100]
        self.pattern_input.default = word.pattern
        self.is_regex_input.default = "yes" if word.is_regex else "no"

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        pattern = self.pattern_input.value.strip()
        is_regex = self.is_regex_input.value.strip().lower() in ("yes", "y")

        if is_regex:
            try:
                re.compile(pattern)
            except re.error as e:
                return await interaction.response.send_message(
                    f"❌ Invalid regex: `{e}`", ephemeral=True
                )

        await DatabaseController.update_tracked_word(
            self.word.id, pattern=pattern, is_regex=is_regex, name=name
        )
        await self.parent_view.refresh(interaction)


# ─── Views ────────────────────────────────────────────────

class TrackedWordsView(discord.ui.View):
    PER_PAGE = 25

    def __init__(self, guild_id: str, author_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.author_id = author_id
        self.words = []
        self.page = 0
        self.selected_word = None

    async def fetch(self):
        self.words = await DatabaseController.get_tracked_words(self.guild_id)

    @property
    def max_page(self):
        return max(0, (len(self.words) - 1) // self.PER_PAGE)

    def current_page_words(self):
        start = self.page * self.PER_PAGE
        return self.words[start : start + self.PER_PAGE]

    # --- embeds ---
    def list_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🔍 Tracked Words Manager", color=discord.Color.blurple())
        if not self.words:
            embed.description = "No tracked words configured yet.\nClick **Add Word** to get started."
            return embed

        lines = []
        for i, w in enumerate(self.current_page_words(), start=self.page * self.PER_PAGE + 1):
            display = w.name or w.pattern[:60]
            regex_tag = " `[regex]`" if w.is_regex else ""
            lines.append(f"**{i}.** `{display}`{regex_tag} — {ACTION_LABELS.get(w.action, w.action)}")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_page + 1} • {len(self.words)} word(s)")
        return embed

    def detail_embed(self) -> discord.Embed:
        w = self.selected_word
        display = w.name or w.pattern[:60]
        embed = discord.Embed(
            title=f"⚙️ Configure: `{display}`",
            color=ACTION_COLORS.get(w.action, discord.Color.greyple()),
        )
        embed.add_field(name="Name", value=f"`{w.name}`" if w.name else "*unnamed*", inline=True)
        embed.add_field(name="Pattern", value=f"`{w.pattern[:1024]}`", inline=False)
        embed.add_field(name="Regex", value="Yes" if w.is_regex else "No", inline=True)
        embed.add_field(name="Action", value=ACTION_LABELS.get(w.action, w.action), inline=True)
        if w.group_id:
            embed.add_field(name="Group ID", value=str(w.group_id), inline=True)
        return embed

    # --- build UI ---
    def build_list_ui(self):
        self.clear_items()

        if self.words:
            page_words = self.current_page_words()
            options = [
                discord.SelectOption(
                    label=(w.name or w.pattern)[:100],
                    description=f"{ACTION_LABELS.get(w.action, w.action)} {'[regex]' if w.is_regex else ''}",
                    value=str(w.id),
                )
                for w in page_words
            ]
            select = discord.ui.Select(placeholder="Select a word to configure…", options=options, row=0)
            select.callback = self.on_select_word
            self.add_item(select)

        prev_btn = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=self.page <= 0)
        prev_btn.callback = self.on_prev
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.page >= self.max_page)
        next_btn.callback = self.on_next
        self.add_item(next_btn)

        add_btn = discord.ui.Button(label="Add Word", style=discord.ButtonStyle.success, emoji="➕", row=1)
        add_btn.callback = self.on_add
        self.add_item(add_btn)

    def build_detail_ui(self):
        self.clear_items()
        w = self.selected_word

        options = [
            discord.SelectOption(label=ACTION_LABELS[a], value=a, default=(a == w.action))
            for a in ACTION_CHOICES
        ]
        action_select = discord.ui.Select(placeholder="Change action…", options=options, row=0)
        action_select.callback = self.on_change_action
        self.add_item(action_select)

        edit_btn = discord.ui.Button(label="Edit Pattern", style=discord.ButtonStyle.primary, emoji="✏️", row=1)
        edit_btn.callback = self.on_edit
        self.add_item(edit_btn)

        delete_btn = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
        delete_btn.callback = self.on_delete
        self.add_item(delete_btn)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    # --- interaction guard ---
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This panel isn't yours.", ephemeral=True)
            return False
        return True

    # --- refresh helper ---
    async def refresh(self, interaction: discord.Interaction):
        await self.fetch()
        if self.selected_word:
            fresh = await DatabaseController.get_tracked_word_by_id(self.selected_word.id)
            if fresh:
                self.selected_word = fresh
                self.build_detail_ui()
                await interaction.response.edit_message(embed=self.detail_embed(), view=self)
            else:
                self.selected_word = None
                self.build_list_ui()
                await interaction.response.edit_message(embed=self.list_embed(), view=self)
        else:
            if self.page > self.max_page:
                self.page = self.max_page
            self.build_list_ui()
            await interaction.response.edit_message(embed=self.list_embed(), view=self)

    # --- callbacks ---
    async def on_select_word(self, interaction: discord.Interaction):
        word_id = int(interaction.data["values"][0])
        word = await DatabaseController.get_tracked_word_by_id(word_id)
        if not word:
            return await interaction.response.send_message("❌ Word not found.", ephemeral=True)
        self.selected_word = word
        self.build_detail_ui()
        await interaction.response.edit_message(embed=self.detail_embed(), view=self)

    async def on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self.build_list_ui()
        await interaction.response.edit_message(embed=self.list_embed(), view=self)

    async def on_next(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        self.build_list_ui()
        await interaction.response.edit_message(embed=self.list_embed(), view=self)

    async def on_add(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddWordModal(self))

    async def on_change_action(self, interaction: discord.Interaction):
        new_action = interaction.data["values"][0]
        await DatabaseController.update_tracked_word(self.selected_word.id, action=new_action)
        await self.refresh(interaction)

    async def on_edit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EditWordModal(self, self.selected_word))

    async def on_delete(self, interaction: discord.Interaction):
        await DatabaseController.delete_tracked_word(self.selected_word.id)
        self.selected_word = None
        await self.refresh(interaction)

    async def on_back(self, interaction: discord.Interaction):
        self.selected_word = None
        await self.refresh(interaction)


# ─── Word Group View ─────────────────────────────────────

class WordGroupView(discord.ui.View):
    PER_PAGE = 5

    def __init__(self, guild_id: str, author_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.author_id = author_id
        self.groups = []
        self.page = 0
        self.selected_group = None
        self.selected_group_words = []
        self.word_page = 0

    async def fetch(self):
        self.groups = await DatabaseController.get_word_groups(self.guild_id)

    @property
    def max_page(self):
        return max(0, (len(self.groups) - 1) // self.PER_PAGE)

    @property
    def word_max_page(self):
        return max(0, (len(self.selected_group_words) - 1) // 10)

    def current_page_groups(self):
        start = self.page * self.PER_PAGE
        return self.groups[start : start + self.PER_PAGE]

    def list_embed(self) -> discord.Embed:
        embed = discord.Embed(title="📁 Word Groups Manager", color=discord.Color.blurple())
        if not self.groups:
            embed.description = "No word groups yet.\nUse `/modlogs import` to bulk-import words into a group."
            return embed

        lines = []
        for i, g in enumerate(self.current_page_groups(), start=self.page * self.PER_PAGE + 1):
            lines.append(f"**{i}.** `{g.name}` — {ACTION_LABELS.get(g.action, g.action)}")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_page + 1} • {len(self.groups)} group(s)")
        return embed

    def detail_embed(self) -> discord.Embed:
        g = self.selected_group
        embed = discord.Embed(
            title=f"📁 Group: `{g.name}`",
            color=ACTION_COLORS.get(g.action, discord.Color.greyple()),
        )
        embed.add_field(name="Action", value=ACTION_LABELS.get(g.action, g.action), inline=True)
        embed.add_field(name="Words", value=str(len(self.selected_group_words)), inline=True)

        # Show a page of words
        start = self.word_page * 10
        page_words = self.selected_group_words[start : start + 10]
        if page_words:
            word_lines = [f"`{w.name or w.pattern[:50]}`{'  `[regex]`' if w.is_regex else ''}" for w in page_words]
            embed.add_field(
                name=f"Patterns (page {self.word_page + 1}/{self.word_max_page + 1})",
                value="\n".join(word_lines),
                inline=False,
            )
        else:
            embed.add_field(name="Patterns", value="*(empty)*", inline=False)
        return embed

    def build_list_ui(self):
        self.clear_items()

        if self.groups:
            page_groups = self.current_page_groups()
            options = [
                discord.SelectOption(
                    label=g.name[:100],
                    description=f"{ACTION_LABELS.get(g.action, g.action)}",
                    value=str(g.id),
                )
                for g in page_groups
            ]
            select = discord.ui.Select(placeholder="Select a group to manage…", options=options, row=0)
            select.callback = self.on_select_group
            self.add_item(select)

        prev_btn = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=self.page <= 0)
        prev_btn.callback = self.on_prev
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.page >= self.max_page)
        next_btn.callback = self.on_next
        self.add_item(next_btn)

    def build_detail_ui(self):
        self.clear_items()
        g = self.selected_group

        # Action selector
        options = [
            discord.SelectOption(label=ACTION_LABELS[a], value=a, default=(a == g.action))
            for a in ACTION_CHOICES
        ]
        action_select = discord.ui.Select(placeholder="Change action for entire group…", options=options, row=0)
        action_select.callback = self.on_change_action
        self.add_item(action_select)

        # Word pagination
        wprev = discord.ui.Button(label="◀ Words", style=discord.ButtonStyle.secondary, row=1, disabled=self.word_page <= 0)
        wprev.callback = self.on_word_prev
        self.add_item(wprev)

        wnext = discord.ui.Button(label="Words ▶", style=discord.ButtonStyle.secondary, row=1, disabled=self.word_page >= self.word_max_page)
        wnext.callback = self.on_word_next
        self.add_item(wnext)

        # Delete group + words
        delete_btn = discord.ui.Button(label="Delete Group + Words", style=discord.ButtonStyle.danger, emoji="🗑️", row=2)
        delete_btn.callback = self.on_delete
        self.add_item(delete_btn)

        # Ungroup (keep words, remove group)
        ungroup_btn = discord.ui.Button(label="Ungroup (keep words)", style=discord.ButtonStyle.secondary, emoji="📤", row=2)
        ungroup_btn.callback = self.on_ungroup
        self.add_item(ungroup_btn)

        back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, emoji="⬅️", row=2)
        back_btn.callback = self.on_back
        self.add_item(back_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This panel isn't yours.", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        await self.fetch()
        if self.selected_group:
            fresh = await DatabaseController.get_word_group_by_id(self.selected_group.id)
            if fresh:
                self.selected_group = fresh
                self.selected_group_words = await DatabaseController.get_words_by_group(fresh.id)
                if self.word_page > self.word_max_page:
                    self.word_page = self.word_max_page
                self.build_detail_ui()
                await interaction.response.edit_message(embed=self.detail_embed(), view=self)
            else:
                self.selected_group = None
                self.build_list_ui()
                await interaction.response.edit_message(embed=self.list_embed(), view=self)
        else:
            if self.page > self.max_page:
                self.page = self.max_page
            self.build_list_ui()
            await interaction.response.edit_message(embed=self.list_embed(), view=self)

    async def on_select_group(self, interaction: discord.Interaction):
        group_id = int(interaction.data["values"][0])
        group = await DatabaseController.get_word_group_by_id(group_id)
        if not group:
            return await interaction.response.send_message("❌ Group not found.", ephemeral=True)
        self.selected_group = group
        self.selected_group_words = await DatabaseController.get_words_by_group(group.id)
        self.word_page = 0
        self.build_detail_ui()
        await interaction.response.edit_message(embed=self.detail_embed(), view=self)

    async def on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self.build_list_ui()
        await interaction.response.edit_message(embed=self.list_embed(), view=self)

    async def on_next(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        self.build_list_ui()
        await interaction.response.edit_message(embed=self.list_embed(), view=self)

    async def on_word_prev(self, interaction: discord.Interaction):
        self.word_page = max(0, self.word_page - 1)
        self.build_detail_ui()
        await interaction.response.edit_message(embed=self.detail_embed(), view=self)

    async def on_word_next(self, interaction: discord.Interaction):
        self.word_page = min(self.word_max_page, self.word_page + 1)
        self.build_detail_ui()
        await interaction.response.edit_message(embed=self.detail_embed(), view=self)

    async def on_change_action(self, interaction: discord.Interaction):
        new_action = interaction.data["values"][0]
        await DatabaseController.update_word_group_action(self.selected_group.id, new_action)
        await self.refresh(interaction)

    async def on_delete(self, interaction: discord.Interaction):
        await DatabaseController.delete_word_group(self.selected_group.id, delete_words=True)
        self.selected_group = None
        self.selected_group_words = []
        await self.refresh(interaction)

    async def on_ungroup(self, interaction: discord.Interaction):
        await DatabaseController.delete_word_group(self.selected_group.id, delete_words=False)
        self.selected_group = None
        self.selected_group_words = []
        await self.refresh(interaction)

    async def on_back(self, interaction: discord.Interaction):
        self.selected_group = None
        self.selected_group_words = []
        self.word_page = 0
        await self.refresh(interaction)


# ─── Cog ──────────────────────────────────────────────────

class ModLogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_audit_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int) -> str:
        try:
            async for entry in guild.audit_logs(action=action, limit=3):
                if entry.target.id == target_id:
                    return str(entry.user.id)
        except discord.Forbidden:
            pass
        return None

    async def send_log(self, guild: discord.Guild, channel_id: str, embed: discord.Embed):
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
        perms = channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.embed_links:
            return
        await channel.send(embed=embed)

    # --- SETUP COMMANDS ---
    modlogs_group = app_commands.Group(name="modlogs", description="Configure server moderation logs")

    @modlogs_group.command(name="channel", description="Set the channel to receive mod logs")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        perms = channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            return await interaction.response.send_message(
                f"❌ Missing permissions (Send Messages, Embed Links) in {channel.mention}.", ephemeral=True
            )
        await DatabaseController.set_modlog_channel(str(interaction.guild.id), str(channel.id))
        await interaction.response.send_message(f"✅ Mod logs will now be sent to {channel.mention}.", ephemeral=True)

    @modlogs_group.command(name="toggle", description="Enable or disable specific logging events")
    @app_commands.choices(event=[
        app_commands.Choice(name="Channel Created", value="log_channel_create"),
        app_commands.Choice(name="Channel Deleted", value="log_channel_delete"),
        app_commands.Choice(name="Channel Renamed", value="log_channel_rename"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle_event(self, interaction: discord.Interaction, event: app_commands.Choice[str], enabled: bool):
        await DatabaseController.toggle_modlog_event(str(interaction.guild.id), event.value, enabled)
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ {event.name} tracking {state}.", ephemeral=True)

    # --- WORD TRACKING (View-based) ---
    @modlogs_group.command(name="words", description="Manage tracked words and their actions")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def words_manage(self, interaction: discord.Interaction):
        view = TrackedWordsView(str(interaction.guild.id), interaction.user.id)
        await view.fetch()
        view.build_list_ui()
        await interaction.response.send_message(embed=view.list_embed(), view=view, ephemeral=True)

    # --- BULK IMPORT ---
    @modlogs_group.command(name="import", description="Bulk import tracked words from a text file (one word/pattern per line)")
    @app_commands.describe(
        file="A .txt file with one word or pattern per line",
        action="Action to take when matched (default: notify)",
        is_regex="Treat all patterns as regex? (default: False)",
        group_name="Name for this import group (for bulk management)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="📢 Notify Only", value="notify"),
        app_commands.Choice(name="🗑️ Delete Message", value="delete"),
        app_commands.Choice(name="👢 Kick User", value="kick"),
        app_commands.Choice(name="🔨 Ban User", value="ban"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def import_words(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        group_name: str,
        action: app_commands.Choice[str] = None,
        is_regex: bool = False,
    ):
        chosen_action = action.value if action else "notify"

        # Validate file
        if not file.filename.endswith(".txt"):
            return await interaction.response.send_message("❌ Please upload a `.txt` file.", ephemeral=True)
        if file.size > 512_000:  # 512KB limit
            return await interaction.response.send_message("❌ File too large (max 512KB).", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Read and parse
        raw = (await file.read()).decode("utf-8", errors="ignore")
        # Support both newline and comma separation
        raw = raw.replace(",", "\n")
        patterns = [line.strip() for line in raw.splitlines() if line.strip()]

        if not patterns:
            return await interaction.followup.send("❌ No patterns found in the file.", ephemeral=True)

        # Validate regex patterns if needed
        if is_regex:
            invalid = []
            for p in patterns:
                try:
                    re.compile(p)
                except re.error as e:
                    invalid.append(f"`{p}` — {e}")
            if invalid:
                preview = "\n".join(invalid[:10])
                suffix = f"\n…and {len(invalid) - 10} more" if len(invalid) > 10 else ""
                return await interaction.followup.send(
                    f"❌ Found {len(invalid)} invalid regex pattern(s):\n{preview}{suffix}",
                    ephemeral=True,
                )

        # Auto-generate names from patterns (truncated for display)
        names = [p[:100] for p in patterns]

        # Create group and bulk add
        guild_id = str(interaction.guild.id)
        group_id = await DatabaseController.create_word_group(guild_id, group_name, chosen_action)
        added = await DatabaseController.bulk_add_tracked_words(
            guild_id, patterns, is_regex=is_regex, action=chosen_action, group_id=group_id, names=names
        )

        await interaction.followup.send(
            f"✅ Imported **{added}** pattern(s) into group `{group_name}` with action **{ACTION_LABELS[chosen_action]}**.",
            ephemeral=True,
        )

    # --- GROUP MANAGEMENT ---
    @modlogs_group.command(name="groups", description="Manage word groups (bulk change action, delete)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def groups_manage(self, interaction: discord.Interaction):
        view = WordGroupView(str(interaction.guild.id), interaction.user.id)
        await view.fetch()
        view.build_list_ui()
        await interaction.response.send_message(embed=view.list_embed(), view=view, ephemeral=True)

    # --- MESSAGE LISTENER ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        config = await DatabaseController.get_modlog_config(str(message.guild.id))
        if not config.log_channel_id:
            return

        if str(message.channel.id) == config.log_channel_id:
            return

        tracked = await DatabaseController.get_tracked_words(str(message.guild.id))
        if not tracked:
            return

        msg_content = message.content
        msg_lower = msg_content.lower()

        severity_order = {"ban": 3, "kick": 2, "delete": 1, "notify": 0}
        matches = []

        for tw in tracked:
            matched = False
            if tw.is_regex:
                try:
                    if re.search(tw.pattern, msg_content, re.IGNORECASE):
                        matched = True
                except re.error:
                    pass
            else:
                if tw.pattern.lower() in msg_lower:
                    matched = True
            if matched:
                matches.append(tw)

        if not matches:
            return

        matches.sort(key=lambda w: severity_order.get(w.action, 0), reverse=True)
        most_severe = matches[0].action
        matched_patterns = [f"`{m.pattern}`" for m in matches]

        log_channel = message.guild.get_channel(int(config.log_channel_id))
        if log_channel:
            perms = log_channel.permissions_for(message.guild.me)
            if perms.send_messages and perms.embed_links:
                embed = discord.Embed(
                    title="🚨 Tracked Word Detected",
                    description=(
                        f"**User:** {message.author.mention}\n"
                        f"**Channel:** {message.channel.mention}\n"
                        f"**Matched:** {', '.join(matched_patterns)}\n"
                        f"**Action Taken:** {ACTION_LABELS.get(most_severe, most_severe)}"
                    ),
                    color=ACTION_COLORS.get(most_severe, discord.Color.orange()),
                )
                embed.add_field(
                    name="Message",
                    value=msg_content[:1024] or "[No Content]",
                    inline=False,
                )
                if most_severe == "notify":
                    embed.add_field(name="Jump", value=f"[Go to Message]({message.jump_url})", inline=False)
                await log_channel.send(embed=embed)

        member = message.guild.get_member(message.author.id)

        if most_severe in ("delete", "kick", "ban"):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

        if most_severe == "kick" and member:
            try:
                await member.kick(reason=f"Tracked word auto-kick: {matches[0].pattern}")
            except discord.Forbidden:
                pass
        elif most_severe == "ban" and member:
            try:
                await member.ban(reason=f"Tracked word auto-ban: {matches[0].pattern}", delete_message_days=0)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        config = await DatabaseController.get_modlog_config(str(channel.guild.id))
        if not config.log_channel_id or not config.log_channel_create:
            return
            
        user_id = await self.get_audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        actor = f"<@{user_id}>" if user_id else "Unknown"
        
        embed = discord.Embed(title="🟢 Channel Created", color=discord.Color.green())
        embed.add_field(name="Name", value=channel.name)
        embed.add_field(name="Type", value=str(channel.type))
        embed.add_field(name="Created By", value=actor)
        
        await self.send_log(channel.guild, config.log_channel_id, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        config = await DatabaseController.get_modlog_config(str(channel.guild.id))
        if not config.log_channel_id or not config.log_channel_delete:
            return
            
        user_id = await self.get_audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        actor = f"<@{user_id}>" if user_id else "Unknown"
        
        embed = discord.Embed(title="🔴 Channel Deleted", color=discord.Color.red())
        embed.add_field(name="Name", value=channel.name)
        embed.add_field(name="Deleted By", value=actor)
        
        await self.send_log(channel.guild, config.log_channel_id, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        if before.name == after.name:
            return
            
        config = await DatabaseController.get_modlog_config(str(after.guild.id))
        if not config.log_channel_id or not config.log_channel_rename:
            return
            
        user_id = await self.get_audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
        actor = f"<@{user_id}>" if user_id else "Unknown"
        
        embed = discord.Embed(title="🟡 Channel Renamed", color=discord.Color.yellow())
        embed.add_field(name="Before", value=before.name)
        embed.add_field(name="After", value=after.name)
        embed.add_field(name="Renamed By", value=actor)
        
        await self.send_log(after.guild, config.log_channel_id, embed)

async def setup(bot):
    await bot.add_cog(ModLogs(bot))
