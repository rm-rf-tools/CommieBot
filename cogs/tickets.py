import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import uuid
import io
from database import DatabaseController

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

    # --- STAFF MANAGEMENT (Moved out of nested group) ---
    
    @ticket_group.command(name="staff_add", description="Add a role to the ticket staff list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staff_add(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.add_staff_role(str(interaction.guild.id), str(role.id))
        await interaction.response.send_message(f"✅ Added {role.mention} to ticket staff.", ephemeral=True)

    @ticket_group.command(name="staff_remove", description="Remove a role from the ticket staff list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def staff_remove(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.remove_staff_role(str(interaction.guild.id), str(role.id))
        await interaction.response.send_message(f"✅ Removed {role.mention} from ticket staff.", ephemeral=True)

    @ticket_group.command(name="staff_list", description="List all current ticket staff roles")
    async def staff_list(self, interaction: discord.Interaction):
        role_ids = await DatabaseController.get_staff_roles(str(interaction.guild.id))
        if not role_ids:
            return await interaction.response.send_message("No staff roles configured.", ephemeral=True)
        mentions = [interaction.guild.get_role(int(rid)).mention for rid in role_ids if interaction.guild.get_role(int(rid))]
        await interaction.response.send_message(f"**Ticket Staff Roles:**\n" + "\n".join(mentions), ephemeral=True)

    # --- TICKET COMMANDS ---

    @mod_group.command(name="ping", description="Open a ticket and ping moderators")
    async def mod_ping(self, interaction: discord.Interaction, description: str):
        await interaction.response.defer(ephemeral=True)
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
        await interaction.followup.send(f"✅ Ticket created: {ticket_channel.mention}")

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

    async def process_ticket_closure(self, interaction: discord.Interaction):
        role_ids = await DatabaseController.get_staff_roles(str(interaction.guild.id))
        user_role_ids = [str(r.id) for r in interaction.user.roles]
        is_staff = any(rid in user_role_ids for rid in role_ids)
        if not (is_staff or interaction.channel.topic == str(interaction.user.id) or interaction.user.guild_permissions.manage_channels):
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

async def setup(bot):
    await bot.add_cog(Tickets(bot))
    bot.add_view(TicketView())