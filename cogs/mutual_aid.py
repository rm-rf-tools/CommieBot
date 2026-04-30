"""
filename: mutual_aid.py
description: Manages mutual aid requests, donations, and role pinging via name-based requests.
Views:
    - ContributionView: Persistent view with a 'Donate' button to log contributions. Extracts name from the embed.
    - AidPaginator: Handles pagination for listing aid requests cleanly.
    - ContributeModal: Modal for logging a contribution, passed the aid name and original message.
Commands:
    - /aid create <name> <amount> <description>: Create a new mutual aid request. (User)
    - /aid edit <aid_name> [new_name] [amount] [description]: Upsert/edit an existing aid without losing history. (User/Mod)
    - /aid donate <aid_name> <amount> [anonymous]: Log a monetary contribution directly. (User)
    - /aid delete <aid_name>: Manually delete a specific aid request. (Mod)
    - /aid clearall: Clear all active aid requests in the server. (Mod)
    - /aid stats: View total money raised locally and globally. (User)
    - /aid list active: Paginated list of active mutual aid requests. (User)
    - /aid list completed: Paginated list of completed mutual aid requests. (User)
    - /aid list all: Paginated list of all mutual aid requests. (User)
    - /aid list export: Generate and download a CSV backup of all server aid records. (Mod)
    - /aid role set <role>: Set the role to ping for new mutual aid requests. (Admin)
    - /aid role delete: Remove the ping role configuration entirely. (Admin)
"""

import discord
from discord import app_commands
from discord.ext import commands
import re
import io
import csv
import datetime
from database import DatabaseController

class ContributeModal(discord.ui.Modal, title='Log Contribution'):
    amount_input = discord.ui.TextInput(
        label='Amount Sent ($)',
        placeholder='e.g. 15.50',
        style=discord.TextStyle.short,
        required=True
    )

    anon_input = discord.ui.TextInput(
        label='Log Anonymously? (Optional)',
        placeholder='Type "yes" to hide your name',
        style=discord.TextStyle.short,
        required=False,
        max_length=3
    )

    def __init__(self, aid_name: str, origin_message: discord.Message = None):
        super().__init__()
        self.aid_name = aid_name
        self.origin_message = origin_message

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_amount = self.amount_input.value.strip().replace('$', '')
            amount = float(clean_amount)
        except ValueError:
            return await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)

        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        is_anonymous = self.anon_input.value.lower().strip() in ["yes", "y", "true"]
        contributor_display = "An anonymous donor" if is_anonymous else interaction.user.mention

        row = await DatabaseController.get_aid_by_name(str(interaction.guild_id), self.aid_name)
        if not row or row[5] == 'deleted':
            return await interaction.response.send_message(f"❌ No valid aid request found named `{self.aid_name}`.", ephemeral=True)

        name, target_user_id, req_amount, rec_amount, reason, status = row
        new_total = rec_amount + amount
        was_already_completed = (status == 'completed')
        is_now_completed = (new_total >= req_amount) or was_already_completed

        # DB Updates
        await DatabaseController.update_aid_progress_by_name(
            str(interaction.guild_id), 
            self.aid_name, 
            new_total, 
            status='completed' if is_now_completed else 'active'
        )

        # Message Embed UI Update
        if self.origin_message and self.origin_message.embeds:
            embed = self.origin_message.embeds[0]
            
            # Update the progress text live
            for i, field in enumerate(embed.fields):
                if field.name in ["Goal", "Progress"]:
                    embed.set_field_at(i, name="Progress", value=f"${new_total:.2f} / ${req_amount:.2f}", inline=field.inline)
                    break
            
            # If it's done, turn the embed green, alter the title, and remove the button
            if is_now_completed:
                embed.color = discord.Color.brand_green()
                if not embed.title.startswith("🎉 GOAL REACHED"):
                    clean_title = embed.title.replace("Aid Request: ", "").replace("**", "")
                    embed.title = f"🎉 GOAL REACHED: {clean_title}"
                embed.set_footer(text="This request has been fully funded!")
                
                try:
                    await self.origin_message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass
            else:
                try:
                    await self.origin_message.edit(embed=embed)
                except discord.HTTPException:
                    pass

        # Reply Logic
        if was_already_completed:
            await interaction.response.send_message(
                f"✅ (This goal has already been reached but we logged your contribution of ${amount:.2f}, thank you!)"
            )
        elif is_now_completed:
            await interaction.response.send_message(
                f"🎉 **GOAL REACHED!** {contributor_display} logged ${amount:.2f}. "
                f"Aid request **{self.aid_name}** for <@{target_user_id}> is complete! (Total: ${new_total:.2f})"
            )
        else:
            await interaction.response.send_message(
                f"✅ Thank you! {contributor_display} logged a contribution of ${amount:.2f} to aid **{self.aid_name}**. "
                f"Current progress: **${new_total:.2f} / ${req_amount:.2f}**."
            )

class ContributionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(label="💸 Log Contribution", style=discord.ButtonStyle.success, custom_id="persistent_contribute_btn")
    async def contribute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        
        # Determine the name. Fallback handles older unmigrated embeds that still use ID
        match_name = re.search(r'Aid Request:\s*\*\*(.+)\*\*', embed.title)
        match_id = re.search(r'(?:ID:\s*|#)(\d+)', embed.title)
        
        aid_name = None
        
        if match_name:
            aid_name = match_name.group(1)
        elif match_id:
            aid_id = int(match_id.group(1))
            aid_name = await DatabaseController.get_aid_name_by_id(aid_id)

        if not aid_name:
            return await interaction.response.send_message("❌ Could not resolve the aid request name from this message.", ephemeral=True)
        
        await interaction.response.send_modal(ContributeModal(aid_name=aid_name, origin_message=interaction.message))

class AidPaginator(discord.ui.View):
    def __init__(self, aids: list, list_type: str):
        super().__init__(timeout=300)
        self.aids = aids
        self.list_type = list_type
        self.current_page = 0
        self.per_page = 5
        self.max_pages = (len(aids) - 1) // self.per_page
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= self.max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"📋 Mutual Aid Registry ({self.list_type.title()})", color=discord.Color.blue())
        
        start = self.current_page * self.per_page
        end = start + self.per_page
        
        for row in self.aids[start:end]:
            name, user_id, req_amount, rec_amount, reason, status, created_at = row
            status_emoji = "🟢" if status == 'active' else "🔴" if status == 'deleted' else "✅"
            
            val = f"**User:** <@{user_id}>\n**Progress:** ${rec_amount:.2f} / ${req_amount:.2f}\n**Status:** {status_emoji} {status.title()}\n**Details:** {reason}"
            embed.add_field(name=f"Request: {name}", value=val, inline=False)
            
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages + 1} | Total Records: {len(self.aids)}")
        return embed

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, custom_id="aid_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="aid_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)


class MutualAidCommands(commands.GroupCog, name="aid"):
    def __init__(self, bot):
        self.bot = bot

    role_group = app_commands.Group(name="role", description="Admin configurations for aid pings")
    list_group = app_commands.Group(name="list", description="List and export mutual aid requests")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send(f"❌ **Permission Denied:** {error}", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def aid_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        names = await DatabaseController.search_aid_names(str(interaction.guild_id), current)
        return [app_commands.Choice(name=n, value=n) for n in names][:25]

    # ==========================================
    #            USER COMMANDS
    # ==========================================

    @app_commands.command(name="create", description="Create a new mutual aid request.")
    @app_commands.describe(name="Unique identifier name for this request", amount="The monetary goal", description="Explain your need and add payment tags")
    async def aid_create(self, interaction: discord.Interaction, name: str, amount: float, description: str):
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        exists = await DatabaseController.check_aid_name_exists(str(interaction.guild_id), name)
        if exists:
            return await interaction.response.send_message(f"❌ An active aid request named **{name}** already exists! Use `/aid edit` if you want to update it.", ephemeral=True)

        await DatabaseController.create_aid(str(interaction.guild_id), str(interaction.channel_id), str(interaction.user.id), name, amount, description)
        
        role_id = await DatabaseController.get_role(str(interaction.guild_id))
        role_ping = f"<@&{role_id}>" if role_id else "*(No ping role configured. Admins can use `/aid role set`)*"

        embed = discord.Embed(title=f"Aid Request: **{name}**", color=discord.Color.blue())
        embed.add_field(name="Requester", value=interaction.user.mention, inline=False)
        embed.add_field(name="Progress", value=f"$0.00 / ${amount:.2f}", inline=True)
        embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"Click the button below or use /aid donate <name> <amount> to contribute!")
        
        await interaction.response.send_message(
            content=role_ping, 
            embed=embed, 
            view=ContributionView(),
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

    @app_commands.command(name="edit", description="Update an existing mutual aid request's details without losing log history.")
    @app_commands.autocomplete(aid_name=aid_name_autocomplete)
    @app_commands.describe(aid_name="The existing request to edit", new_name="Optional new name", amount="Optional new goal", description="Optional new description")
    async def aid_edit(self, interaction: discord.Interaction, aid_name: str, new_name: str = None, amount: float = None, description: str = None):
        if not new_name and not amount and not description:
            return await interaction.response.send_message("❌ You must provide at least one field to edit.", ephemeral=True)

        success = await DatabaseController.edit_aid(str(interaction.guild_id), aid_name, new_name, amount, description)
        if success:
            display_name = new_name if new_name else aid_name
            await interaction.response.send_message(f"✅ Successfully updated the aid request: **{display_name}**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Aid request **{aid_name}** not found.", ephemeral=True)

    @app_commands.command(name="donate", description="Log a contribution to an active aid request directly via command.")
    @app_commands.autocomplete(aid_name=aid_name_autocomplete)
    @app_commands.describe(aid_name="The name of the aid event", amount="The amount you sent", anonymous="Hide your name from the progress message?")
    async def aid_donate(self, interaction: discord.Interaction, aid_name: str, amount: float, anonymous: bool = False):
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        row = await DatabaseController.get_aid_by_name(str(interaction.guild_id), aid_name)
        if not row or row[5] == 'deleted':
            return await interaction.response.send_message(f"❌ No valid aid request found named `{aid_name}`.", ephemeral=True)

        name, target_user_id, req_amount, rec_amount, _, status = row
        new_total = rec_amount + amount
        contributor_display = "An anonymous donor" if anonymous else interaction.user.mention
        
        was_already_completed = (status == 'completed')
        is_now_completed = (new_total >= req_amount) or was_already_completed

        await DatabaseController.update_aid_progress_by_name(
            str(interaction.guild_id), 
            aid_name, 
            new_total, 
            status='completed' if is_now_completed else 'active'
        )

        if was_already_completed:
            await interaction.response.send_message(
                f"✅ (This goal has already been reached but we logged your contribution of ${amount:.2f}, thank you!)"
            )
        elif is_now_completed:
            await interaction.response.send_message(
                f"🎉 **GOAL REACHED!** {contributor_display} logged ${amount:.2f}. "
                f"Aid request **{aid_name}** for <@{target_user_id}> is complete! (Total: ${new_total:.2f})"
            )
        else:
            await interaction.response.send_message(
                f"✅ Thank you! {contributor_display} logged a contribution of ${amount:.2f} to aid **{aid_name}**. "
                f"Progress: **${new_total:.2f} / ${req_amount:.2f}**."
            )

    @app_commands.command(name="stats", description="View total money raised through mutual aid.")
    async def aid_stats(self, interaction: discord.Interaction):
        local_total = await DatabaseController.get_total_raised(str(interaction.guild_id))
        global_total = await DatabaseController.get_total_raised()

        embed = discord.Embed(title="📊 Mutual Aid Statistics", color=discord.Color.gold())
        embed.add_field(name="This Server", value=f"${local_total:,.2f}", inline=True)
        embed.add_field(name="Bot Total (All Servers)", value=f"${global_total:,.2f}", inline=True)
        
        await interaction.response.send_message(embed=embed)


    # ==========================================
    #            LIST COMMANDS
    # ==========================================

    async def _send_list_response(self, interaction: discord.Interaction, status: str = None):
        rows = await DatabaseController.get_aids_by_status(str(interaction.guild_id), status)
        list_type = status if status else "all"
        
        if not rows:
            return await interaction.response.send_message(f"🔍 No requests found matching filter: `{list_type}`", ephemeral=True)

        view = AidPaginator(rows, list_type)
        await interaction.response.send_message(embed=view.generate_embed(), view=view)

    @list_group.command(name="active", description="List all currently active mutual aid requests.")
    async def list_active(self, interaction: discord.Interaction):
        await self._send_list_response(interaction, status="active")

    @list_group.command(name="completed", description="List all completed mutual aid requests.")
    async def list_completed(self, interaction: discord.Interaction):
        await self._send_list_response(interaction, status="completed")

    @list_group.command(name="all", description="List all historical and active mutual aid requests.")
    async def list_all(self, interaction: discord.Interaction):
        await self._send_list_response(interaction, status=None)

    @list_group.command(name="export", description="Export a CSV file of all mutual aid requests in this server.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def list_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        rows = await DatabaseController.get_aids_by_status(str(interaction.guild_id), status=None)
        if not rows:
            return await interaction.followup.send("No records found to export.")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "User ID", "Amount Requested", "Amount Received", "Reason", "Status", "Created At Timestamp"])
        
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])

        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"mutual_aid_export_{datetime.date.today()}.csv")
        await interaction.followup.send("✅ Export generated.", file=file)

    # ==========================================
    #            MODERATION COMMANDS
    # ==========================================

    @app_commands.command(name="delete", description="Manually delete a specific aid request.")
    @app_commands.autocomplete(aid_name=aid_name_autocomplete)
    @app_commands.describe(aid_name="The name of the aid request to delete")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def aid_delete(self, interaction: discord.Interaction, aid_name: str):
        success = await DatabaseController.delete_aid_by_name(str(interaction.guild_id), aid_name)
        if not success:
            return await interaction.response.send_message(f"❌ Aid request **{aid_name}** not found or is already inactive.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ Aid request **{aid_name}** has been manually deleted.")

    @app_commands.command(name="clearall", description="Clear all active aid requests in the server.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def aid_clearall(self, interaction: discord.Interaction):
        await DatabaseController.clear_all(str(interaction.guild_id))
        await interaction.response.send_message("🚨 All active aid requests in this server have been cleared from the queue.")


    # ==========================================
    #            ROLE CONFIGURATION
    # ==========================================

    @role_group.command(name="set", description="Set or upsert the role to ping for new mutual aid requests.")
    @app_commands.describe(role="The server role to ping")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aid_role_set(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ The mutual aid ping role has been successfully set to {role.mention}.", ephemeral=True)

    @role_group.command(name="delete", description="Remove the mutual aid ping role configuration.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aid_role_delete(self, interaction: discord.Interaction):
        await DatabaseController.set_role(str(interaction.guild_id), None)
        await interaction.response.send_message("🗑️ The mutual aid ping role configuration has been removed.", ephemeral=True)

async def setup(bot):
    bot.add_view(ContributionView())
    await bot.add_cog(MutualAidCommands(bot))