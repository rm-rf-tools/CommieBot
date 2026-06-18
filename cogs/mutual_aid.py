"""
filename: mutual_aid.py
description: Manages mutual aid requests with automated recurring reminders based on custom intervals.
Views:
    - ContributionView: Persistent view for logging donations via buttons.
    - AidPaginator: Pagination handler for registry listings.
    - ContributeModal: UI for submitting donation amounts.
    - AidDashboardView: Main control panel for users to manage their own requests.
    - AidCreateModal: Form for initiating new aid requests with interval settings.
    - AidEditModal: Form for updating existing aid requests including reminder timing.
Commands:
    - /aid create <name> <amount> <description> [interval] [for_user]: Create a new request.
    - /aid edit <aid_name> [new_name] [amount] [description] [interval]: Update request details.
    - /aid menu: Open the interactive dashboard.
    - /aid donate <aid_name> <amount> [anonymous]: Command-line donation logging.
    - /aid list <active|completed|all|export>: View or download aid data.
    - /aid stats: View financial statistics.
    - /aid delete <aid_name>: Deactivate a request (Staff).
    - /aid clearall: Deactivate all guild requests (Staff).
    - /aid role <set|delete>: Configure the notification ping role.
"""

import discord
from discord import app_commands
from discord.ext import commands
import re
import io
import csv
import datetime
import time
from db import DatabaseController

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
            return await interaction.response.send_message(f"❌ No valid active aid request found named `{self.aid_name}`.", ephemeral=True)

        name, target_user_id, req_amount, rec_amount, reason, status = row
        new_total = rec_amount + amount
        was_already_completed = (status == 'completed')
        is_now_completed = (new_total >= req_amount) or was_already_completed

        await DatabaseController.update_aid_progress_by_name(
            str(interaction.guild_id), 
            self.aid_name, 
            new_total, 
            status='completed' if is_now_completed else 'active'
        )

        if self.origin_message and self.origin_message.embeds:
            embed = self.origin_message.embeds[0]
            for i, field in enumerate(embed.fields):
                if field.name in ["Goal", "Progress"]:
                    embed.set_field_at(i, name="Progress", value=f"${new_total:.2f} / ${req_amount:.2f}", inline=field.inline)
                    break
            
            old_footer = embed.footer.text if embed.footer else f"Click the button below to contribute!"
            if is_now_completed:
                embed.color = discord.Color.brand_green()
                if not embed.title.startswith("🎉 GOAL REACHED"):
                    clean_title = embed.title.replace("Aid Request: ", "").replace("**", "")
                    embed.title = f"🎉 GOAL REACHED: {clean_title}"
                embed.set_footer(text=f"{old_footer}\nStatus: Fully Funded!")
                try:
                    await self.origin_message.edit(embed=embed, view=None)
                except: pass
            else:
                try:
                    await self.origin_message.edit(embed=embed)
                except: pass

        allowed_mentions = discord.AllowedMentions(users=[discord.Object(id=target_user_id)])
        if was_already_completed:
            await interaction.response.send_message(f"✅ Goal already reached. Logged ${amount:.2f} to <@{target_user_id}>.", allowed_mentions=allowed_mentions)
        elif is_now_completed:
            await interaction.response.send_message(f"🎉 **GOAL REACHED!** {contributor_display} logged ${amount:.2f}. Request **{self.aid_name}** is complete!", allowed_mentions=allowed_mentions)
        else:
            await interaction.response.send_message(f"✅ {contributor_display} logged ${amount:.2f} for **{self.aid_name}**. Progress: **${new_total:.2f} / ${req_amount:.2f}**.", allowed_mentions=allowed_mentions)

class ContributionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(label="💸 Log Contribution", style=discord.ButtonStyle.success, custom_id="persistent_contribute_btn")
    async def contribute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        aid_name = None
        if embed.footer and embed.footer.text:
            match_id = re.search(r'Aid ID:\s*(\d+)', embed.footer.text)
            if match_id:
                aid_id = int(match_id.group(1))
                aid_name = await DatabaseController.get_aid_name_by_id(aid_id)

        if not aid_name:
            match_name = re.search(r'Aid Request:\s*\*\*(.+)\*\*', embed.title)
            if match_name: aid_name = match_name.group(1).strip()

        if not aid_name:
            return await interaction.response.send_message("❌ Could not resolve aid request.", ephemeral=True)
        
        await interaction.response.send_modal(ContributeModal(aid_name=aid_name, origin_message=interaction.message))

class AidCreateModal(discord.ui.Modal, title="Create Aid Request"):
    aid_name = discord.ui.TextInput(label="Request Name", placeholder="Unique identifier", required=True)
    amount = discord.ui.TextInput(label="Amount Needed ($)", placeholder="e.g. 500", required=True)
    interval = discord.ui.TextInput(label="Reminder Interval (Days)", placeholder="e.g. 7 (0 for no reminders)", default="1", required=True)
    description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Explain your need and payment methods", required=True)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = float(self.amount.value.strip().replace('$', ''))
            days = int(self.interval.value.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Amount and Interval must be valid numbers.", ephemeral=True)
            
        exists = await DatabaseController.check_aid_name_exists(str(interaction.guild_id), self.aid_name.value.strip())
        if exists:
            return await interaction.response.send_message("❌ An active request with that name already exists.", ephemeral=True)
            
        aid_id = await DatabaseController.create_aid(str(interaction.guild_id), str(interaction.channel_id), str(interaction.user.id), self.aid_name.value.strip(), amt, self.description.value.strip(), days)
        
        role_id = await DatabaseController.get_role(str(interaction.guild_id))
        role_ping = f"<@&{role_id}>" if role_id else ""

        embed = discord.Embed(title=f"Aid Request: **{self.aid_name.value}**", color=discord.Color.blue())
        embed.add_field(name="Requester", value=interaction.user.mention, inline=False)
        embed.add_field(name="Progress", value=f"$0.00 / ${amt:.2f}", inline=True)
        embed.add_field(name="Reminder", value=f"Every {days} days" if days > 0 else "No recurring reminders", inline=True)
        embed.add_field(name="Description", value=self.description.value, inline=False)
        embed.set_footer(text=f"Aid ID: {aid_id} | Click the button below to contribute!")
        
        await interaction.channel.send(content=role_ping, embed=embed, view=ContributionView())
        
        await self.parent_view.fetch_data()
        self.parent_view.build_main_menu()
        await interaction.response.edit_message(embed=self.parent_view.generate_main_embed(), view=self.parent_view)

class AidEditModal(discord.ui.Modal):
    def __init__(self, parent_view, aid_data):
        super().__init__(title=f"Edit: {aid_data[1][:30]}")
        self.parent_view = parent_view
        self.aid_id = aid_data[0]
        self.old_name = aid_data[1]
        
        self.new_name = discord.ui.TextInput(label="New Name (Optional)", default=aid_data[1], required=False)
        self.amount = discord.ui.TextInput(label="New Goal ($)", default=str(aid_data[2]), required=False)
        self.interval = discord.ui.TextInput(label="Reminder Interval (Days)", default=str(aid_data[5]), required=False)
        self.description = discord.ui.TextInput(label="New Description", style=discord.TextStyle.paragraph, default=aid_data[4], required=False)
        
        for item in [self.new_name, self.amount, self.interval, self.description]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = float(self.amount.value.strip().replace('$', '')) if self.amount.value else None
            days = int(self.interval.value.strip()) if self.interval.value else None
        except ValueError:
            return await interaction.response.send_message("❌ Invalid numeric input.", ephemeral=True)
                
        await DatabaseController.edit_aid(str(interaction.guild_id), self.old_name, self.new_name.value.strip() or None, amt, self.description.value.strip() or None, days)
        
        await self.parent_view.fetch_data()
        self.parent_view.selected_aid = None
        self.parent_view.build_main_menu()
        await interaction.response.edit_message(content="✅ Request updated!", embed=self.parent_view.generate_main_embed(), view=self.parent_view)

class AidDashboardView(discord.ui.View):
    def __init__(self, user: discord.Member, guild_id: str):
        super().__init__(timeout=600)
        self.user = user
        self.guild_id = guild_id
        self.user_aids =[]
        self.selected_aid = None
    
    async def fetch_data(self):
        self.user_aids = await DatabaseController.get_user_aids(self.guild_id, str(self.user.id))
        
    def build_main_menu(self):
        self.clear_items()
        if self.user_aids:
            options = [discord.SelectOption(label=a[1][:100], description=f"${a[3]:.2f}/${a[2]:.2f} - Int: {a[5]}d", value=str(a[0])) for a in self.user_aids[:25]]
            select = discord.ui.Select(placeholder="Select a request to manage...", options=options)
            async def select_callback(interaction: discord.Interaction):
                aid_id = int(interaction.data["values"][0])
                self.selected_aid = next((a for a in self.user_aids if a[0] == aid_id), None)
                self.build_manage_menu()
                await interaction.response.edit_message(embed=self.generate_manage_embed(), view=self)
            select.callback = select_callback
            self.add_item(select)
            
        create_btn = discord.ui.Button(label="➕ Create New Request", style=discord.ButtonStyle.success)
        create_btn.callback = lambda i: i.response.send_modal(AidCreateModal(self))
        self.add_item(create_btn)

    def build_manage_menu(self):
        self.clear_items()
        edit_btn = discord.ui.Button(label="✏️ Edit Request", style=discord.ButtonStyle.primary)
        edit_btn.callback = lambda i: i.response.send_modal(AidEditModal(self, self.selected_aid))
        self.add_item(edit_btn)
        
        delete_btn = discord.ui.Button(label="🗑️ Delete Request", style=discord.ButtonStyle.danger)
        async def del_cb(interaction: discord.Interaction):
            await DatabaseController.delete_aid(self.selected_aid[0], self.guild_id)
            await self.fetch_data()
            self.selected_aid = None
            self.build_main_menu()
            await interaction.response.edit_message(embed=self.generate_main_embed(), view=self)
        delete_btn.callback = del_cb
        self.add_item(delete_btn)
        
        back_btn = discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            self.selected_aid = None
            self.build_main_menu()
            await interaction.response.edit_message(embed=self.generate_main_embed(), view=self)
        back_btn.callback = back_cb
        self.add_item(back_btn)

    def generate_main_embed(self):
        embed = discord.Embed(title="🏥 Mutual Aid Dashboard", color=discord.Color.blue())
        if not self.user_aids:
            embed.description = "You have no active requests."
        else:
            for _, name, req, rec, reason, interval in self.user_aids[:10]:
                embed.add_field(name=name, value=f"Progress: ${rec:.2f} / ${req:.2f}\nInterval: {interval} days\n{reason[:100]}", inline=False)
        return embed

    def generate_manage_embed(self):
        _, name, req, rec, reason, interval = self.selected_aid
        embed = discord.Embed(title=f"🛠️ Managing: {name}", color=discord.Color.orange())
        embed.add_field(name="Goal", value=f"${req:.2f}", inline=True)
        embed.add_field(name="Raised", value=f"${rec:.2f}", inline=True)
        embed.add_field(name="Interval", value=f"{interval} days", inline=True)
        embed.add_field(name="Description", value=reason, inline=False)
        return embed

class AidPaginator(discord.ui.View):
    def __init__(self, aids: list, list_type: str):
        super().__init__(timeout=300)
        self.aids = sorted(aids, key=lambda r: r[6], reverse=True)
        self.list_type = list_type
        self.current_page = 0
        self.per_page = 5
        self.max_pages = max(0, (len(aids) - 1) // self.per_page)
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= self.max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"📋 Mutual Aid Registry ({self.list_type})", color=discord.Color.blue())
        start = self.current_page * self.per_page
        for row in self.aids[start:start+self.per_page]:
            embed.add_field(name=f"Request: {row[0]}", value=f"User: <@{row[1]}>\nProgress: ${row[3]:.2f}/${row[2]:.2f}\nStatus: {row[5]}", inline=False)
        embed.set_footer(text=f"Page {self.current_page+1}/{self.max_pages+1}")
        return embed

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

class MutualAidCommands(commands.GroupCog, name="aid"):
    def __init__(self, bot):
        self.bot = bot

    role_group = app_commands.Group(name="role", description="Aid role configs")
    list_group = app_commands.Group(name="list", description="List/Export aid data")

    async def aid_name_autocomplete(self, i: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        names = await DatabaseController.search_aid_names(str(i.guild_id), current)
        return[app_commands.Choice(name=n, value=n) for n in names][:25]

    @app_commands.command(name="create", description="Start a new aid request.")
    @app_commands.describe(interval="Days between reminders (default 1, 0 for none)")
    async def aid_create(self, interaction: discord.Interaction, name: str, amount: float, description: str, interval: int = 1, for_user: discord.Member = None):
        if amount <= 0: return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        if await DatabaseController.check_aid_name_exists(str(interaction.guild_id), name):
            return await interaction.response.send_message("❌ Name taken.", ephemeral=True)

        target = for_user or interaction.user
        aid_id = await DatabaseController.create_aid(str(interaction.guild_id), str(interaction.channel_id), str(target.id), name, amount, description, interval)
        
        role_id = await DatabaseController.get_role(str(interaction.guild_id))
        embed = discord.Embed(title=f"Aid Request: **{name}**", color=discord.Color.blue())
        embed.add_field(name="Requester", value=target.mention, inline=False)
        embed.add_field(name="Progress", value=f"$0.00 / ${amount:.2f}", inline=True)
        embed.add_field(name="Reminder", value=f"Every {interval} days" if interval > 0 else "None", inline=True)
        embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"Aid ID: {aid_id} | Click the button below to contribute!")
        
        await interaction.response.send_message(content=f"<@&{role_id}>" if role_id else "", embed=embed, view=ContributionView())

    @app_commands.command(name="edit", description="Update an existing request.")
    @app_commands.autocomplete(aid_name=aid_name_autocomplete)
    async def aid_edit(self, interaction: discord.Interaction, aid_name: str, new_name: str = None, amount: float = None, description: str = None, interval: int = None):
        if await DatabaseController.edit_aid(str(interaction.guild_id), aid_name, new_name, amount, description, interval):
            await interaction.response.send_message(f"✅ Updated **{new_name or aid_name}**.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Request not found.", ephemeral=True)

    @app_commands.command(name="menu", description="Manage your requests.")
    async def aid_menu(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = AidDashboardView(interaction.user, str(interaction.guild_id))
        await view.fetch_data()
        view.build_main_menu()
        await interaction.followup.send(embed=view.generate_main_embed(), view=view)

    @app_commands.command(name="donate", description="Log a contribution.")
    @app_commands.autocomplete(aid_name=aid_name_autocomplete)
    async def aid_donate(self, interaction: discord.Interaction, aid_name: str, amount: float, anonymous: bool = False):
        row = await DatabaseController.get_aid_by_name(str(interaction.guild_id), aid_name)
        if not row or row[5] == 'deleted': return await interaction.response.send_message("❌ Invalid aid.", ephemeral=True)

        new_total = row[3] + amount
        await DatabaseController.update_aid_progress_by_name(str(interaction.guild_id), aid_name, new_total, status='completed' if new_total >= row[2] else 'active')
        await interaction.response.send_message(f"✅ Logged ${amount:.2f} for **{aid_name}**.")

    @app_commands.command(name="stats", description="View aid stats.")
    async def aid_stats(self, interaction: discord.Interaction):
        local = await DatabaseController.get_total_raised(str(interaction.guild_id))
        glob = await DatabaseController.get_total_raised()
        embed = discord.Embed(title="📊 Mutual Aid Stats", color=discord.Color.gold())
        embed.add_field(name="Server", value=f"${local:,.2f}"); embed.add_field(name="Global", value=f"${glob:,.2f}")
        await interaction.response.send_message(embed=embed)

    @list_group.command(name="active")
    async def list_active(self, i: discord.Interaction):
        rows = await DatabaseController.get_aids_by_status(str(i.guild_id), "active")
        if not rows: return await i.response.send_message("No active requests.", ephemeral=True)
        view = AidPaginator(rows, "Active")
        await i.response.send_message(embed=view.generate_embed(), view=view)

    @list_group.command(name="export")
    async def list_export(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        rows = await DatabaseController.get_aids_by_status(str(i.guild_id))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "User", "Goal", "Raised", "Reason", "Status", "Created", "Interval"])
        for r in rows: writer.writerow(r)
        output.seek(0)
        await i.followup.send(file=discord.File(fp=io.BytesIO(output.getvalue().encode()), filename="aid_export.csv"))

    @app_commands.command(name="delete")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def aid_delete(self, i: discord.Interaction, aid_name: str):
        if await DatabaseController.delete_aid_by_name(str(i.guild_id), aid_name):
            await i.response.send_message(f"🗑️ Deleted **{aid_name}**.")
        else: await i.response.send_message("❌ Not found.", ephemeral=True)

    @role_group.command(name="set")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def role_set(self, i: discord.Interaction, role: discord.Role):
        role_mentioned = role.mention
        await DatabaseController.set_role(str(i.guild_id), str(role.id))
        await i.response.send_message(f"✅ Set to {role_mentioned}", ephemeral=True)

async def setup(bot):
    bot.add_view(ContributionView())
    await bot.add_cog(MutualAidCommands(bot))