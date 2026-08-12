"""
filename: qotd.py
description: Question of the Day system that allows user submissions and automatically asks a random question at noon.
Views:
    - QOTDListView: Handles pagination for viewing pending questions.
    - QOTDSubmitView: Persistent view containing the 'Submit Question' trigger button.
    - QOTDSubmitModal: Modal for users to type and submit their question.
Commands:
    - /qotd submit <question>: Submit a new question for the QOTD rotation. (User)
    - /qotd button: Deploy the persistent 'Submit Question' button to a channel. (Admin: Manage Guild)
    - /qotd channel <channel>: Set the channel where the QOTD will be posted. (Admin: Manage Guild)
    - /qotd list view: View a paginated list of all pending QOTD submissions. (Admin: Manage Guild)
    - /qotd list export: Export all pending QOTD submissions to a CSV file. (Admin: Manage Guild)
    - /qotd delete <question>: Delete a pending question from the queue. (Admin: Manage Guild)
    - /qotd force_spawn: Instantly post a random QOTD ignoring the schedule. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import csv
import io
from db import DatabaseController


class QOTDSubmitModal(discord.ui.Modal, title="Submit Question of the Day"):
    question_text = discord.ui.TextInput(
        label="Your Question",
        style=discord.TextStyle.paragraph,
        placeholder="Type your question here...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await DatabaseController.add_qotd_question(
            str(interaction.guild_id), 
            str(interaction.user.id), 
            self.question_text.value.strip()
        )
        await interaction.followup.send("✅ Your question has been added to the queue!", ephemeral=True)


class QOTDSubmitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Submit Question", style=discord.ButtonStyle.primary, custom_id="persistent_qotd_submit_btn")
    async def submit_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QOTDSubmitModal())


class QOTDListView(discord.ui.View):
    def __init__(self, questions: list):
        super().__init__(timeout=300)
        self.questions = questions
        self.current_page = 0
        self.per_page = 10
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.questions) - 1) // self.per_page)
        for child in self.children:
            if getattr(child, "custom_id", None) in ["first_btn", "prev_btn"]:
                child.disabled = self.current_page == 0
            elif getattr(child, "custom_id", None) in ["next_btn", "last_btn"]:
                child.disabled = self.current_page >= max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="❓ Pending QOTD Submissions", color=discord.Color.purple())
        
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.questions[start:end]
        
        if not page_items:
            embed.description = "The queue is completely empty."
            return embed

        for q in page_items:
            dt = f"<t:{q.submitted_at}:d>"
            val = f"**Submitted by:** <@{q.user_id}> | {dt}\n**ID:** `{q.id}`"
            embed.add_field(name=q.question_text[:256], value=val, inline=False)
            
        max_pages = max(1, (len(self.questions) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"Page {self.current_page + 1} of {max_pages} | Total: {len(self.questions)}")
        return embed

    @discord.ui.button(label="⏮ First", style=discord.ButtonStyle.secondary, custom_id="first_btn")
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="next_btn")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Last ⏭", style=discord.ButtonStyle.primary, custom_id="last_btn")
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, (len(self.questions) - 1) // self.per_page)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)


class QOTDCog(commands.GroupCog, name="qotd"):
    def __init__(self, bot):
        self.bot = bot
        # 19:00 UTC == 12:00 PM PDT (Noon in Los Angeles)
        self.daily_qotd.start()

    def cog_unload(self):
        self.daily_qotd.cancel()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    list_group = app_commands.Group(name="list", description="List or export pending QOTD submissions")

    async def qotd_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        questions = await DatabaseController.search_pending_qotd(str(interaction.guild_id), current)
        return [
            app_commands.Choice(name=f"{q.question_text[:95]}...", value=str(q.id))
            for q in questions
        ][:25]

    async def _trigger_qotd(self, guild: discord.Guild):
        channel_id = await DatabaseController.get_qotd_channel(str(guild.id))
        if not channel_id:
            return
            
        channel = guild.get_channel(int(channel_id))
        if not channel:
            return
            
        qotd = await DatabaseController.get_random_pending_qotd(str(guild.id))
        if not qotd:
            return
            
        embed = discord.Embed(
            title="❓ Question of the Day",
            description=f"**{qotd.question_text}**",
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Submitted by: {guild.get_member(int(qotd.user_id)).display_name if guild.get_member(int(qotd.user_id)) else 'Unknown User'}")

        try:
            await channel.send(
                content="@everyone", 
                embed=embed, 
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )
            await DatabaseController.mark_qotd_asked(qotd.id)
        except discord.Forbidden:
            pass

    @tasks.loop(time=datetime.time(hour=19, minute=0, tzinfo=datetime.timezone.utc))
    async def daily_qotd(self):
        """Task loop running at 19:00 UTC (12:00 PM Pacific)."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._trigger_qotd(guild)

    @app_commands.command(name="submit", description="Submit a new question for the QOTD rotation.")
    @app_commands.describe(question="The question you want to ask the server")
    async def qotd_submit(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=True)
        await DatabaseController.add_qotd_question(str(interaction.guild_id), str(interaction.user.id), question.strip())
        await interaction.followup.send("✅ Your question has been added to the queue!")

    @app_commands.command(name="button", description="Create a permanent button for users to submit QOTD.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def qotd_button(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="❓ Submit a Question of the Day", 
            description="Click the button below to submit a question to the server's QOTD queue!", 
            color=discord.Color.purple()
        )
        await interaction.channel.send(embed=embed, view=QOTDSubmitView())
        await interaction.response.send_message("✅ QOTD submission button generated successfully.", ephemeral=True)

    @app_commands.command(name="channel", description="Set the channel where the QOTD will be posted.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def qotd_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await DatabaseController.set_qotd_channel(str(interaction.guild_id), str(channel.id))
        await interaction.response.send_message(f"✅ QOTD will now be automatically posted in {channel.mention} at noon.", ephemeral=True)

    @app_commands.command(name="delete", description="Delete a pending question from the queue.")
    @app_commands.autocomplete(question_id=qotd_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def qotd_delete(self, interaction: discord.Interaction, question_id: str):
        try:
            q_id = int(question_id)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid question ID.", ephemeral=True)
            
        success = await DatabaseController.delete_qotd(q_id)
        if success:
            await interaction.response.send_message("🗑️ Question successfully deleted from the queue.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Question not found or already asked.", ephemeral=True)

    @app_commands.command(name="force_spawn", description="Instantly post a random QOTD ignoring the schedule.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def qotd_force(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        channel_id = await DatabaseController.get_qotd_channel(str(interaction.guild_id))
        if not channel_id:
            return await interaction.followup.send("❌ You must configure a QOTD channel first with `/qotd channel`.")
            
        qotd = await DatabaseController.get_random_pending_qotd(str(interaction.guild_id))
        if not qotd:
            return await interaction.followup.send("❌ The queue is empty!")
            
        await self._trigger_qotd(interaction.guild)
        await interaction.followup.send("✅ Forced QOTD spawn successful.")

    @list_group.command(name="view", description="View a paginated list of all pending QOTD submissions.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def qotd_list_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        questions = await DatabaseController.get_all_pending_qotd(str(interaction.guild_id))
        
        if not questions:
            return await interaction.followup.send("The queue is completely empty.")
            
        view = QOTDListView(questions)
        await interaction.followup.send(embed=view.generate_embed(), view=view)

    @list_group.command(name="export", description="Export all pending QOTD submissions to a CSV file.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def qotd_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        questions = await DatabaseController.get_all_pending_qotd(str(interaction.guild_id))
        
        if not questions:
            return await interaction.followup.send("The queue is completely empty.")
            
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "User ID", "Question", "Submitted At"])
        
        for q in questions:
            dt = datetime.datetime.fromtimestamp(q.submitted_at, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            writer.writerow([q.id, q.user_id, q.question_text, dt])
            
        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename="qotd_pending_export.csv")
        await interaction.followup.send("✅ Here is the current queue:", file=file)

async def setup(bot):
    bot.add_view(QOTDSubmitView())
    await bot.add_cog(QOTDCog(bot))