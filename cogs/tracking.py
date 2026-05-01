"""
filename: tracking.py
description: Server activity tracking system that monitors member participation and identifies inactive users.
Views:
    - None
Commands:
    - /lastseen <member>: Check the relative timestamp of a user's last message. (User)
    - /server scan_history [days]: Retroactively scan message history to backfill activity data. (Admin: Manage Guild)
    - /server active count [days]: Get the number of members active within a timeframe. (Admin: Manage Guild)
    - /server active list [days]: Generate a list of all active members. (Admin: Manage Guild)
    - /server inactive count [days]: Get the number of members inactive within a timeframe. (Admin: Manage Guild)
    - /server inactive list [days]: Generate a list of all inactive members. (Admin: Manage Guild)
    - /server list_no_pfp: List all members using a default Discord avatar. (Admin: Manage Guild)
"""

import time
import io
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from db import DatabaseController, engine
from models import UserLastSeen

class TrackingCog(commands.Cog, name="tracking"):
    def __init__(self, bot):
        self.bot = bot

    # Base groups for the new server activity commands
    server_group = app_commands.Group(
        name="server", 
        description="Server activity tracking", 
        default_permissions=discord.Permissions(manage_guild=True)
    )
    active_group = app_commands.Group(name="active", description="Active members", parent=server_group)
    inactive_group = app_commands.Group(name="inactive", description="Inactive members", parent=server_group)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        # Log the latest message interaction time for this user
        current_time = int(time.time())
        await DatabaseController.update_last_seen(str(message.guild.id), str(message.author.id), current_time)

    @app_commands.command(name="lastseen", description="Check the last time a user sent a message in this server.")
    @app_commands.describe(user="The user to check")
    async def last_seen(self, interaction: discord.Interaction, user: discord.Member):
        timestamp = await DatabaseController.get_last_seen(str(interaction.guild_id), str(user.id))
        
        if timestamp:
            # Using Discord's dynamic timestamp tag `<t:...:R>` which formats it as "X minutes/days ago" for the end user automatically
            await interaction.response.send_message(f"👀 {user.mention} was last seen sending a message **<t:{timestamp}:R>**.", ephemeral=False)
        else:
            await interaction.response.send_message(f"🔍 I haven't seen {user.mention} send any messages since I started tracking.", ephemeral=False)

    @server_group.command(name="scan_history", description="Search past message history to backfill activity data.")
    @app_commands.describe(days="Number of days to search back (default 30)")
    async def scan_history(self, interaction: discord.Interaction, days: int = 30):
        """Retroactively scrape the server to find the last time users spoke."""
        if days <= 0:
            return await interaction.response.send_message("❌ Timeframe must be at least 1 day.", ephemeral=True)
            
        await interaction.response.send_message(f"⏳ **Starting history scan for the last {days} days.**\n*This may take several minutes depending on server size...*", ephemeral=True)
        
        cutoff = discord.utils.utcnow() - datetime.timedelta(days=days)
        scanned_msgs = 0
        user_latest = {}

        # Gather all channels that can contain messages (Text, Voice with text, and Threads)
        channels = [c for c in interaction.guild.channels if isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel))]
        channels.extend(interaction.guild.threads)

        for channel in channels:
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.read_message_history or not perms.view_channel:
                continue
                
            try:
                async for msg in channel.history(after=cutoff, limit=None):
                    scanned_msgs += 1
                    if msg.author.bot:
                        continue
                        
                    uid = str(msg.author.id)
                    msg_time = int(msg.created_at.timestamp())
                    
                    # Store only the newest message timestamp for each user
                    if uid not in user_latest or msg_time > user_latest[uid]:
                        user_latest[uid] = msg_time
            except (discord.Forbidden, discord.HTTPException):
                continue
                
        # Update Database
        updated_users = 0
        for uid, ts in user_latest.items():
            current_ts = await DatabaseController.get_last_seen(str(interaction.guild_id), uid)
            # Only update if the scraped message is newer than what's in the DB, or if they aren't in the DB at all
            if current_ts is None or ts > current_ts:
                await DatabaseController.update_last_seen(str(interaction.guild_id), uid, ts)
                updated_users += 1
                
        await interaction.followup.send(
            f"✅ **Scan Complete!**\n"
            f"Scanned **{scanned_msgs}** messages over the last {days} days.\n"
            f"Updated activity records for **{updated_users}** members.\n"
            f"*(You can now use `/server inactive list` to see accurate results!)*"
        )

    # --- HELPER METHODS ---

    async def get_active_user_ids(self, guild_id: str, days: int) -> set[str]:
        """Fetches a set of user IDs who have sent a message in the last X days."""
        cutoff_time = int(time.time()) - (days * 86400)
        async with AsyncSession(engine) as session:
            stmt = select(UserLastSeen.user_id).where(
                UserLastSeen.guild_id == guild_id,
                UserLastSeen.last_seen_at >= cutoff_time
            )
            result = await session.execute(stmt)
            return set(result.scalars().all())

    async def send_list(self, interaction: discord.Interaction, title: str, members: list[discord.Member]):
        """Sends list as embed, but switches to file if character limits are approached."""
        if not members:
            return await interaction.followup.send(f"🔍 No members found for: {title}")

        # Total character budget for all embeds in one message is 6000.
        # We target 5000 to be safe with titles and mentions.
        total_chars = 0
        embeds = []
        current_desc = ""
        
        force_file = False
        
        for m in members:
            m_text = f"{m.mention} "
            total_chars += len(m_text)
            
            # If total character volume is getting dangerous, force a text file
            if total_chars > 5500:
                force_file = True
                break

            if len(current_desc) + len(m_text) > 4000:
                embeds.append(discord.Embed(title=f"{title} (cont.)", description=current_desc.strip(), color=discord.Color.blue()))
                current_desc = ""
            
            current_desc += m_text
            
        if current_desc and not force_file:
            embeds.append(discord.Embed(title=title if not embeds else f"{title} (cont.)", description=current_desc.strip(), color=discord.Color.blue()))

        if force_file or len(embeds) > 10:
            # Fallback to text file if the list is massive
            content = f"--- {title} ---\n\n"
            content += "\n".join([f"{m.display_name} | @{m.name} | {m.id}" for m in members])
            file = discord.File(fp=io.BytesIO(content.encode("utf-8")), filename="member_list.txt")
            await interaction.followup.send(f"📄 The list is too large for Discord to display ({len(members)} users). Sending as a file:", file=file)
        else:
            await interaction.followup.send(embeds=embeds)


    @active_group.command(name="count", description="Count members who have sent a message within the last X days.")
    @app_commands.describe(days="Timeframe in days")
    async def active_count(self, interaction: discord.Interaction, days: int = 30):
        if days <= 0:
            return await interaction.response.send_message("❌ Timeframe must be at least 1 day.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        active_ids = await self.get_active_user_ids(str(interaction.guild_id), days)
        
        # Filter against current members (excludes bots and users who left the server)
        active_members = [m for m in interaction.guild.members if not m.bot and str(m.id) in active_ids]
        
        await interaction.followup.send(f"📊 **Active Member Count:** {len(active_members)} members have sent a message in the last {days} days.")

    @active_group.command(name="list", description="List members who have sent a message within the last X days.")
    @app_commands.describe(days="Timeframe in days")
    async def active_list(self, interaction: discord.Interaction, days: int = 30):
        if days <= 0:
            return await interaction.response.send_message("❌ Timeframe must be at least 1 day.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        active_ids = await self.get_active_user_ids(str(interaction.guild_id), days)
        
        active_members = [m for m in interaction.guild.members if not m.bot and str(m.id) in active_ids]
        
        if not active_members:
            return await interaction.followup.send(f"🔍 No active members found in the last {days} days.")

        await self.send_list(interaction, f"Active Members ({days} days)", active_members)

    # --- INACTIVE COMMANDS ---

    @inactive_group.command(name="count", description="Count members who have NOT sent a message within the last X days.")
    @app_commands.describe(days="Timeframe in days")
    async def inactive_count(self, interaction: discord.Interaction, days: int = 30):
        if days <= 0:
            return await interaction.response.send_message("❌ Timeframe must be at least 1 day.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        active_ids = await self.get_active_user_ids(str(interaction.guild_id), days)
        
        # Anyone in the server who isn't in the active DB query is inactive
        inactive_members = [m for m in interaction.guild.members if not m.bot and str(m.id) not in active_ids]
        
        await interaction.followup.send(f"💤 **Inactive Member Count:** {len(inactive_members)} members have not sent a message in the last {days} days (or ever).")

    @inactive_group.command(name="list", description="List members who have NOT sent a message within the last X days.")
    @app_commands.describe(days="Timeframe in days")
    async def inactive_list(self, interaction: discord.Interaction, days: int = 30):
        if days <= 0:
            return await interaction.response.send_message("❌ Timeframe must be at least 1 day.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        active_ids = await self.get_active_user_ids(str(interaction.guild_id), days)
        
        inactive_members = [m for m in interaction.guild.members if not m.bot and str(m.id) not in active_ids]
        
        if not inactive_members:
            return await interaction.followup.send(f"🔍 No inactive members found in the last {days} days. Everyone is active!")

        await self.send_list(interaction, f"Inactive Members ({days} days)", inactive_members)
    
    @server_group.command(name="list_no_pfp", description="List all members who do not have a custom profile picture.")
    async def list_no_pfp(self, interaction: discord.Interaction):
        """Finds all users currently using a default Discord avatar."""
        await interaction.response.defer(ephemeral=True)
        
        # In Discord.py, 'avatar' is None if the user hasn't uploaded a custom pfp.
        # 'display_avatar' would return the default one, so we check 'avatar' specifically.
        no_pfp_members = [
            m for m in interaction.guild.members 
            if not m.bot and m.avatar is None
        ]
        
        if not no_pfp_members:
            return await interaction.followup.send("✨ Everyone in the server has a custom profile picture!")

        # Re-using your existing send_list helper for chunking/file fallback
        await self.send_list(interaction, "Members with No Profile Picture", no_pfp_members)

async def setup(bot):
    await bot.add_cog(TrackingCog(bot))
