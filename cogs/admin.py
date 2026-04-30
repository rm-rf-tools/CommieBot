"""admin.py"""

import discord
from discord import app_commands
from discord.ext import commands
import time
import datetime
import asyncio
import json
import os
from database import DatabaseController

STICKY_FILE = "./data/sticky.json"

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Sticky Messages State
        self.sticky_data = {}
        self.sticky_tasks = {}
        self.sticky_locks = {}
        self.moving_stickies = set()
        
        self.load_sticky_data()

    # ==========================================
    #             ERROR HANDLING
    # ==========================================

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Global error handler for the Admin cog."""
        if isinstance(error, app_commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await interaction.response.send_message(f"❌ **Permission Denied:** You need `{perms}` permissions to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await interaction.response.send_message(f"❌ **Bot Error:** I am missing `{perms}` permissions to execute this.", ephemeral=True)
        elif isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ **Access Denied:** You do not meet the requirements to run this command.", ephemeral=True)
        else:
            print(f"[Admin Cog Error] {error}")
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ An unexpected error occurred: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    # ==========================================
    #          STICKY MESSAGE SYSTEM
    # ==========================================

    def load_sticky_data(self):
        """Loads sticky messages from JSON on boot."""
        os.makedirs(os.path.dirname(STICKY_FILE), exist_ok=True)
        if os.path.exists(STICKY_FILE):
            with open(STICKY_FILE, "r") as f:
                self.sticky_data = json.load(f)
        else:
            self.sticky_data = {}

    def save_sticky_data(self):
        """Saves sticky messages to JSON."""
        with open(STICKY_FILE, "w") as f:
            json.dump(self.sticky_data, f, indent=4)

    def get_lock(self, channel_id: str):
        if channel_id not in self.sticky_locks:
            self.sticky_locks[channel_id] = asyncio.Lock()
        return self.sticky_locks[channel_id]

    async def _repost_sticky(self, channel: discord.TextChannel):
        """Handles deleting the old sticky message and posting a fresh one at the bottom."""
        channel_id = str(channel.id)
        
        async with self.get_lock(channel_id):
            if channel_id not in self.sticky_data:
                return

            data = self.sticky_data[channel_id]
            old_sticky_id = data.get("current_sticky_id")

            # Fetch or create the impersonation Webhook FIRST to save its ID
            try:
                webhooks = await channel.webhooks()
                webhook = discord.utils.get(webhooks, name="CommieBot Sticky")
                if not webhook:
                    webhook = await channel.create_webhook(name="CommieBot Sticky")
                
                # Save webhook ID so on_message can instantly ignore it
                self.sticky_data[channel_id]["webhook_id"] = webhook.id
                self.save_sticky_data()
            except discord.Forbidden:
                print(f"[Sticky] Missing 'Manage Webhooks' in #{channel.name}")
                return

            # Delete the old message so it doesn't duplicate
            if old_sticky_id:
                self.moving_stickies.add(old_sticky_id)
                try:
                    old_msg = channel.get_partial_message(old_sticky_id)
                    await old_msg.delete()
                except discord.HTTPException:
                    pass
                
                # Auto-cleanup moving_stickies set to prevent memory leaks
                async def cleanup_moving():
                    await asyncio.sleep(5)
                    self.moving_stickies.discard(old_sticky_id)
                asyncio.create_task(cleanup_moving())

            # Send the new message mimicking the original user
            try:
                embeds = [discord.Embed.from_dict(e) for e in data.get("embeds", [])]
                new_msg = await webhook.send(
                    content=data.get("content", ""),
                    username=data.get("author_name", "Unknown"),
                    avatar_url=data.get("author_avatar", None),
                    embeds=embeds,
                    wait=True,
                    allowed_mentions=discord.AllowedMentions.none() # Prevents pinging people when reposting
                )
                
                # Update database
                self.sticky_data[channel_id]["current_sticky_id"] = new_msg.id
                self.save_sticky_data()
            except discord.HTTPException as e:
                print(f"[Sticky] Failed to send webhook in #{channel.name}: {e}")

    async def _delayed_repost(self, channel: discord.TextChannel):
        """Slight debounce so we don't spam the API on rapid chat."""
        await asyncio.sleep(2.5)
        await self._repost_sticky(channel)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """If a normal message is sent, push the sticky down."""
        if not message.guild or message.channel.type != discord.ChannelType.text:
            return

        channel_id = str(message.channel.id)
        if channel_id in self.sticky_data:
            
            # 1) Loop Prevention: Ignore the message if it's sent by our sticky Webhook
            known_webhook_id = self.sticky_data[channel_id].get("webhook_id")
            if message.webhook_id and message.webhook_id == known_webhook_id:
                return

            # 2) Loop Prevention: Ignore if it's explicitly the registered sticky ID
            if message.id == self.sticky_data[channel_id].get("current_sticky_id"):
                return
            
            # Cancel any existing countdown and start a new one
            if channel_id in self.sticky_tasks and not self.sticky_tasks[channel_id].done():
                self.sticky_tasks[channel_id].cancel()
                
            self.sticky_tasks[channel_id] = asyncio.create_task(self._delayed_repost(message.channel))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """If a user manually deletes the sticky, immediately bring it back to the bottom."""
        channel_id = str(payload.channel_id)
        if channel_id in self.sticky_data:
            if payload.message_id == self.sticky_data[channel_id].get("current_sticky_id"):
                # If the bot deleted it to move it, ignore it.
                if payload.message_id in self.moving_stickies:
                    self.moving_stickies.discard(payload.message_id)
                else:
                    # It was manually deleted by an admin or user! Bring it back.
                    if channel_id in self.sticky_tasks and not self.sticky_tasks[channel_id].done():
                        self.sticky_tasks[channel_id].cancel()
                        
                    channel = self.bot.get_channel(payload.channel_id)
                    if channel:
                        await self._repost_sticky(channel)

    # --- STICKY COMMANDS ---
    sticky_group = app_commands.Group(name="sticky", description="Manage persistent sticky messages")

    @sticky_group.command(name="add", description="Clone an existing message and stick it to the bottom of the channel.")
    @app_commands.describe(message_id="The ID of the message you want to make sticky.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_webhooks=True, manage_messages=True)
    async def sticky_add(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel

        try:
            target_msg = await channel.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            return await interaction.followup.send("❌ Could not find a message with that ID in this channel.")
            
        if target_msg.attachments:
            await interaction.followup.send("⚠️ Note: Attachments are not supported for sticky messages and have been ignored.")

        # Save data necessary for impersonation
        self.sticky_data[str(channel.id)] = {
            "author_name": target_msg.author.display_name,
            "author_avatar": target_msg.author.display_avatar.url if target_msg.author.display_avatar else None,
            "content": target_msg.content,
            "embeds": [e.to_dict() for e in target_msg.embeds if e.type == 'rich'],
            "current_sticky_id": None,
            "webhook_id": None
        }
        self.save_sticky_data()

        # Delete the user's original message to prevent duplicates, then post the first sticky
        try:
            await target_msg.delete()
        except discord.Forbidden:
            pass

        await self._repost_sticky(channel)
        await interaction.followup.send("✅ Sticky message established!")

    @sticky_group.command(name="remove", description="Remove the sticky message from this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def sticky_remove(self, interaction: discord.Interaction):
        channel_id = str(interaction.channel.id)
        if channel_id not in self.sticky_data:
            return await interaction.response.send_message("❌ There is no sticky message in this channel.", ephemeral=True)

        data = self.sticky_data.pop(channel_id)
        self.save_sticky_data()

        # Cancel tasks
        if channel_id in self.sticky_tasks and not self.sticky_tasks[channel_id].done():
            self.sticky_tasks[channel_id].cancel()

        # Try to delete the active sticky
        if data.get("current_sticky_id"):
            try:
                msg = interaction.channel.get_partial_message(data["current_sticky_id"])
                await msg.delete()
            except discord.HTTPException:
                pass

        await interaction.response.send_message("✅ Sticky message removed.", ephemeral=True)



    # ==========================================
    #           MASS PURGING TOOLS
    # ==========================================

    @app_commands.command(name="clearsystem", description="Silently clear all system messages (like joins/pins) from this channel.")
    @app_commands.describe(limit="Max past messages to scan (default: 1000, enter 0 to scan entire channel)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def clearsystem(self, interaction: discord.Interaction, limit: int = 1000):
        await interaction.response.defer(ephemeral=True)
        scan_limit = None if limit <= 0 else limit
            
        try:
            deleted = await interaction.channel.purge(limit=scan_limit, check=lambda m: m.is_system())
            await interaction.followup.send(f"✅ Scanned and cleared {len(deleted)} system messages from {interaction.channel.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ I do not have permission to manage messages in this channel.", ephemeral=True)

    @app_commands.command(name="clearmedia", description="Delete all media (pics/vids) sent by specific users.")
    @app_commands.describe(
        user_ids="Comma-separated User IDs (e.g. 12345, 67890)",
        scope="Where to scan (Default: Current Channel)",
        limit="Max past messages to scan per channel (default: 1000, 0 for all)"
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="Current Channel", value="channel"),
        app_commands.Choice(name="Entire Server", value="server")
    ])
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def clearmedia(self, interaction: discord.Interaction, user_ids: str, scope: app_commands.Choice[str] = None, limit: int = 1000):
        await interaction.response.defer(ephemeral=True)

        try:
            target_ids = set(int(uid.strip()) for uid in user_ids.split(",") if uid.strip().isdigit())
        except ValueError:
            return await interaction.followup.send("❌ Invalid format. Please provide comma-separated User IDs (numbers only).", ephemeral=True)

        if not target_ids:
            return await interaction.followup.send("❌ No valid User IDs provided.", ephemeral=True)

        scan_scope = scope.value if scope else "channel"
        scan_limit = None if limit <= 0 else limit
        channels_to_scan = [interaction.channel] if scan_scope == "channel" else [
            c for c in interaction.guild.channels 
            if isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread))
        ]

        await interaction.followup.send(
            f"⏳ **Starting media purge for {len(target_ids)} user(s).**\n*Scanning {len(channels_to_scan)} channel(s)...*", 
            ephemeral=True
        )

        total_deleted = 0
        fourteen_days_ago = discord.utils.utcnow() - datetime.timedelta(days=14)

        for channel in channels_to_scan:
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.read_message_history or not perms.manage_messages:
                continue
                
            bulk_queue = []
            try:
                async for m in channel.history(limit=scan_limit):
                    if m.author.id not in target_ids:
                        continue
                    
                    has_media = any((a.content_type and (a.content_type.startswith('image/') or a.content_type.startswith('video/'))) for a in m.attachments)
                    has_media = has_media or any(em.type in ['image', 'video', 'gifv'] for em in m.embeds)
                                
                    if has_media:
                        if m.created_at >= fourteen_days_ago:
                            bulk_queue.append(m)
                            if len(bulk_queue) == 100:
                                await channel.delete_messages(bulk_queue)
                                total_deleted += 100
                                bulk_queue.clear()
                                await asyncio.sleep(2) 
                        else:
                            await m.delete()
                            total_deleted += 1
                            await asyncio.sleep(1.5) 

                if bulk_queue:
                    await channel.delete_messages(bulk_queue)
                    total_deleted += len(bulk_queue)
                    await asyncio.sleep(1.5)

            except discord.Forbidden:
                pass
            except discord.HTTPException:
                pass

        try:
            await interaction.user.send(f"✅ **Media Purge Complete!**\nDeleted a total of **{total_deleted}** media messages.")
        except discord.Forbidden:
            pass


    # ==========================================
    #             AUTOROLE SYSTEM 
    # ==========================================
    
    autorole_group = app_commands.Group(name="autorole", description="Manage autoroles assigned automatically to new members.")

    @autorole_group.command(name="set", description="Assign a default role to be applied automatically to new members.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_set(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_autorole(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ Autorole has been set to {role.mention}. Enable it with `/autorole toggle` if you haven't!", ephemeral=True)

    @autorole_group.command(name="toggle", description="Enable or disable the autorole feature.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole_toggle(self, interaction: discord.Interaction, enabled: bool):
        await DatabaseController.toggle_autorole(str(interaction.guild_id), enabled)
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ Autorole feature is now **{state}**.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        role_id, enabled = await DatabaseController.get_autorole_config(str(member.guild.id))
        if enabled and role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Autorole system active")
                except (discord.Forbidden, discord.HTTPException):
                    pass

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))