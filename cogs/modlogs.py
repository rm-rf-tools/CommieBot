import discord
from discord import app_commands
from discord.ext import commands
import re
from database import DatabaseController

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
            return await interaction.response.send_message(f"❌ Missing permissions (Send Messages, Embed Links) in {channel.mention}.", ephemeral=True)
            
        await DatabaseController.set_modlog_channel(str(interaction.guild.id), str(channel.id))
        await interaction.response.send_message(f"✅ Mod logs will now be sent to {channel.mention}.", ephemeral=True)

    @modlogs_group.command(name="toggle", description="Enable or disable specific logging events")
    @app_commands.choices(event=[
        app_commands.Choice(name="Channel Created", value="log_channel_create"),
        app_commands.Choice(name="Channel Deleted", value="log_channel_delete"),
        app_commands.Choice(name="Channel Renamed", value="log_channel_rename")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle_event(self, interaction: discord.Interaction, event: app_commands.Choice[str], enabled: bool):
        await DatabaseController.toggle_modlog_event(str(interaction.guild.id), event.value, enabled)
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ {event.name} tracking {state}.", ephemeral=True)

    # --- WORD TRACKING ---
    words_group = app_commands.Group(name="words", description="Manage tracked words", parent=modlogs_group)

    @words_group.command(name="add", description="Add a word to track in messages")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def word_add(self, interaction: discord.Interaction, word: str):
        config = await DatabaseController.get_modlog_config(str(interaction.guild.id))
        current = [w.strip() for w in config.tracked_words.split(",")] if config.tracked_words else []
        word = word.lower().strip()
        
        if word in current:
            return await interaction.response.send_message("❌ Word is already tracked.", ephemeral=True)
            
        current.append(word)
        await DatabaseController.update_tracked_words(str(interaction.guild.id), ",".join(current))
        await interaction.response.send_message(f"✅ Added `{word}` to tracked words.", ephemeral=True)

    @words_group.command(name="remove", description="Remove a tracked word")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def word_remove(self, interaction: discord.Interaction, word: str):
        config = await DatabaseController.get_modlog_config(str(interaction.guild.id))
        current = [w.strip() for w in config.tracked_words.split(",")] if config.tracked_words else []
        word = word.lower().strip()
        
        if word not in current:
            return await interaction.response.send_message("❌ Word is not being tracked.", ephemeral=True)
            
        current.remove(word)
        await DatabaseController.update_tracked_words(str(interaction.guild.id), ",".join(current))
        await interaction.response.send_message(f"✅ Removed `{word}` from tracked words.", ephemeral=True)

    @words_group.command(name="list", description="List all tracked words")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def word_list(self, interaction: discord.Interaction):
        config = await DatabaseController.get_modlog_config(str(interaction.guild.id))
        if not config.tracked_words:
            return await interaction.response.send_message("ℹ️ No words are currently tracked.", ephemeral=True)
            
        words = config.tracked_words.replace(",", ", ")
        await interaction.response.send_message(f"**Tracked Words:** {words}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. Basic Filters
        if message.author.bot or not message.guild:
            return
            
        # 2. Get Config
        config = await DatabaseController.get_modlog_config(str(message.guild.id))
        if not config.log_channel_id or not config.tracked_words:
            return

        # 3. Ignore the log channel itself
        if str(message.channel.id) == config.log_channel_id:
            return

        # 4. Check for words (Simple 'in' check, no regex)
        words = [w.strip().lower() for w in config.tracked_words.split(",") if w.strip()]
        msg_lower = message.content.lower()
        found_words = [w for w in words if w in msg_lower]

        if found_words:
            log_channel = message.guild.get_channel(int(config.log_channel_id))
            
            # 5. Permission/Channel Check
            if not log_channel:
                print(f"DEBUG: Log channel {config.log_channel_id} not found.")
                return
                
            perms = log_channel.permissions_for(message.guild.me)
            if not perms.send_messages or not perms.embed_links:
                print(f"DEBUG: Missing perms in log channel {log_channel.name}")
                return

            # 6. Send Log
            embed = discord.Embed(
                title="🚨 Tracked Word Detected",
                description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Words:** {', '.join(found_words)}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Message", value=message.content[:1024] or "[No Content - Likely Attachment]", inline=False)
            embed.add_field(name="Jump", value=f"[Go to Message]({message.jump_url})", inline=False)
            
            await log_channel.send(embed=embed)

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