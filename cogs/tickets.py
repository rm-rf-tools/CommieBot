"""
filename: tickets.py
description: Complete ticketing and mod-watch system for user support and internal moderation tracking.
Views:
    - TicketCreateModal: Modal for users to describe their reason for opening a ticket.
    - TicketCreateView: Persistent view containing the 'Open Ticket' trigger button.
    - TicketView: View inside ticket channels for staff/users to close the ticket.
    - TicketListView: Admin interface for listing active tickets and mass-clearing channels.
Commands:
    - /mod ping <description>: Immediately open a support ticket. (User)
    - /mod ticketbutton: Deploy the persistent 'Open Ticket' button to a channel. (Staff / Admin: Manage Guild)
    - /mod staff add <role>: Grant a role permission to see and manage tickets. (Admin: Manage Guild)
    - /mod staff remove <role>: Revoke ticket management permissions from a role. (Admin: Manage Guild)
    - /mod staff list: List all roles configured as ticket staff. (User)
    - /mod ticket list: View all currently active tickets. (User)
    - /mod ticket add <user>: Add a specific user to an active ticket channel. (User/Staff)
    - /mod ticket close: Close the current ticket and generate a transcript. (User/Staff)
    - /mod watch add <user> <reason>: Add a user to the internal mod watch list. (Staff)
    - /mod watch list: View the list of users on the mod watch list. (Staff)
    - /mod watch remove <user>: Remove a user from the mod watch list. (Staff)
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import uuid
import io
from database import DatabaseController

class TicketCreateModal(discord.ui.Modal, title="Open a Ticket"):
    description = discord.ui.TextInput(
        label="Reason for ticket",
        style=discord.TextStyle.paragraph,
        placeholder="Please describe why you are opening this ticket...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.get_cog("Tickets")
        if cog and hasattr(cog, "create_ticket_channel"):
            ticket_channel = await cog.create_ticket_channel(interaction, self.description.value)
            await interaction.followup.send(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)
        else:
            await interaction.followup.send("❌ Internal Error: Could not find ticket creation logic.", ephemeral=True)

class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Open Ticket", style=discord.ButtonStyle.primary, custom_id="persistent_ticket_create_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketCreateModal())

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="ticket_close_button")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("Tickets")
        await cog.process_ticket_closure(interaction)

class TicketListView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Clear All Tickets", style=discord.ButtonStyle.danger, custom_id="clear_all_tickets")
    async def clear_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Permissions denied.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        category = discord.utils.get(interaction.guild.categories, name="Tickets")
        if not category:
            return await interaction.followup.send("No ticket category found.")

        channels_to_delete = [c for c in category.text_channels if c.name.startswith("ticket-")]
        if not channels_to_delete:
            return await interaction.followup.send("No active tickets to clear.")

        await DatabaseController.close_all_active_tickets_db(str(interaction.guild.id))
        for channel in channels_to_delete:
            try: await channel.delete()
            except: pass

        await interaction.followup.send(f"✅ Successfully cleared {len(channels_to_delete)} ticket channels.")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    mod_group = app_commands.Group(name="mod", description="Moderation and ticketing")
    ticket_group = app_commands.Group(name="ticket", description="Ticket management", parent=mod_group)
    staff_group = app_commands.Group(name="staff", description="Ticket staff management", parent=mod_group)
    watch_group = app_commands.Group(name="watch", description="Mod watch list management", parent=mod_group)

    async def is_mod(self, interaction: discord.Interaction) -> bool:
        role_ids = await DatabaseController.get_staff_roles(str(interaction.guild.id))
        user_role_ids = [str(r.id) for r in interaction.user.roles]
        return any(rid in user_role_ids for rid in role_ids) or interaction.user.guild_permissions.manage_messages

    # --- TICKET HELPER ---
    
    async def create_ticket_channel(self, interaction: discord.Interaction, description: str):
        role_ids = await DatabaseController.get_staff_roles(str(interaction.guild.id))
        
        category = discord.utils.get(interaction.guild.categories, name="Tickets")
        if not category:
            category = await interaction.guild.create_category("Tickets")

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        ping_list = []
        for rid in role_ids:
            role = interaction.guild.get_role(int(rid))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, manage_messages=True)
                ping_list.append(role.mention)

        ticket_id = uuid.uuid4().hex[:6]
        ticket_channel = await interaction.guild.create_text_channel(
            name=f"ticket-{ticket_id}",
            category=category,
            overwrites=overwrites,
            topic=str(interaction.user.id)
        )

        await DatabaseController.create_ticket(ticket_id, str(interaction.guild.id), str(interaction.user.id), str(ticket_channel.id))
        embed = discord.Embed(title=f"Ticket: {ticket_id}", description=f"**Reason:**\n{description}", color=discord.Color.red())
        content = f"{interaction.user.mention} Ticket created. {' '.join(ping_list)}"
        await ticket_channel.send(content=content, embed=embed, view=TicketView())
        
        return ticket_channel

    async def process_ticket_closure(self, interaction: discord.Interaction):
        if not await self.is_mod(interaction) and interaction.channel.topic != str(interaction.user.id):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        if not interaction.response.is_done(): await interaction.response.defer()
        
        transcript = []
        async for m in interaction.channel.history(limit=None, oldest_first=True):
            transcript.append(f"[{m.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {m.author}: {m.content}")
        
        await DatabaseController.close_ticket_db(str(interaction.channel.id))
        log_channel = discord.utils.get(interaction.guild.text_channels, name="ticket-logs")
        if log_channel:
            file = discord.File(fp=io.BytesIO("\n".join(transcript).encode("utf-8")), filename=f"log-{interaction.channel.name}.txt")
            await log_channel.send(content=f"Ticket {interaction.channel.name} closed by {interaction.user}", file=file)
        
        await interaction.followup.send("🔒 Deleting...")
        await asyncio.sleep(3)
        await interaction.channel.delete()

    # --- GENERAL MOD COMMANDS ---

    @mod_group.command(name="ping", description="Open a ticket and ping moderators")
    async def mod_ping(self, interaction: discord.Interaction, description: str):
        await interaction.response.defer(ephemeral=True)
        ticket_channel = await self.create_ticket_channel(interaction, description)
        await interaction.followup.send(f"✅ Ticket created: {ticket_channel.mention}")

    @mod_group.command(name="ticketbutton", description="Create a permanent button for users to open tickets")
    async def ticketbutton(self, interaction: discord.Interaction):
        if not await self.is_mod(interaction) and not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ You do not have permission to create a ticket button.", ephemeral=True)
            
        embed = discord.Embed(
            title="🎫 Contact Support", 
            description="Click the button below to open a ticket and contact our staff team.", 
            color=discord.Color.blue()
        )
        await interaction.channel.send(embed=embed, view=TicketCreateView())
        await interaction.response.send_message("✅ Ticket button generated successfully.", ephemeral=True)

    # --- STAFF MANAGEMENT COMMANDS ---

    @staff_group.command(name="add", description="Add a role to the ticket staff list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staff_add(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.add_staff_role(str(interaction.guild.id), str(role.id))
        await interaction.response.send_message(f"✅ Added {role.mention} to ticket staff.", ephemeral=True)

    @staff_group.command(name="remove", description="Remove a role from the ticket staff list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staff_remove(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.remove_staff_role(str(interaction.guild.id), str(role.id))
        await interaction.response.send_message(f"✅ Removed {role.mention} from ticket staff.", ephemeral=True)

    @staff_group.command(name="list", description="List all current ticket staff roles")
    async def staff_list(self, interaction: discord.Interaction):
        role_ids = await DatabaseController.get_staff_roles(str(interaction.guild.id))
        if not role_ids:
            return await interaction.response.send_message("No staff roles configured.", ephemeral=True)
        mentions = [interaction.guild.get_role(int(rid)).mention for rid in role_ids if interaction.guild.get_role(int(rid))]
        await interaction.response.send_message(f"**Ticket Staff Roles:**\n" + "\n".join(mentions), ephemeral=True)

    # --- TICKET MANAGEMENT COMMANDS ---

    @ticket_group.command(name="list", description="List active tickets")
    async def ticket_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        category = discord.utils.get(interaction.guild.categories, name="Tickets")
        if not category: return await interaction.followup.send("No tickets.")
        links = [c.mention for c in category.text_channels if c.name.startswith("ticket-")]
        embed = discord.Embed(title="Active Tickets", description="\n".join(links) if links else "None", color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=TicketListView(self))

    @ticket_group.command(name="add", description="Add user to ticket")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.channel.name.startswith("ticket-"):
            return await interaction.response.send_message("❌ Not a ticket.", ephemeral=True)
        await interaction.channel.set_permissions(user, read_messages=True, send_messages=True, attach_files=True)
        await interaction.response.send_message(f"✅ {user.mention} added.")

    @ticket_group.command(name="close", description="Close ticket")
    async def ticket_close_cmd(self, interaction: discord.Interaction):
        await self.process_ticket_closure(interaction)

    # --- WATCH COMMANDS ---

    @watch_group.command(name="add", description="Add a user to the mod watch list")
    @app_commands.describe(user="The user to add", reason="Reason for watching")
    async def watch_add(self, interaction: discord.Interaction, user: discord.User, reason: str):
        if not await self.is_mod(interaction):
            return await interaction.response.send_message("❌ You do not have permission to use the watch list.", ephemeral=True)
            
        await DatabaseController.add_to_watch_list(str(interaction.guild.id), str(user.id), reason)
        await interaction.response.send_message(f"✅ Added {user.mention} to the watch list.\n**Reason:** {reason}", ephemeral=True)

    @watch_group.command(name="list", description="List users currently on the mod watch list")
    async def watch_list(self, interaction: discord.Interaction):
        if not await self.is_mod(interaction):
            return await interaction.response.send_message("❌ You do not have permission to use the watch list.", ephemeral=True)
        
        records = await DatabaseController.get_watch_list(str(interaction.guild.id))
        if not records:
            return await interaction.response.send_message("The watch list is currently empty.", ephemeral=True)
        
        embed = discord.Embed(title="👀 Mod Watch List", color=discord.Color.orange())
        
        count = 0
        for record in records:
            if count >= 25:
                embed.set_footer(text=f"Showing 25 out of {len(records)} watched users.")
                break
                
            reason = record.reason[:1000] + "..." if len(record.reason) > 1000 else record.reason
            embed.add_field(name=f"User ID: {record.user_id}", value=f"<@{record.user_id}> - **Reason:** {reason}", inline=False)
            count += 1
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @watch_group.command(name="remove", description="Remove a user from the mod watch list")
    @app_commands.describe(user="The user to remove")
    async def watch_remove(self, interaction: discord.Interaction, user: discord.User):
        if not await self.is_mod(interaction):
            return await interaction.response.send_message("❌ You do not have permission to use the watch list.", ephemeral=True)
        
        success = await DatabaseController.remove_from_watch_list(str(interaction.guild.id), str(user.id))
        if success:
            await interaction.response.send_message(f"✅ Removed {user.mention} from the watch list.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {user.mention} is not currently on the watch list.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Tickets(bot))
    bot.add_view(TicketView())
    bot.add_view(TicketCreateView())
