import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import io
import time
import random
import os
import re

class CloneCog(commands.GroupCog, name="clone"):
    def __init__(self, bot):
        self.bot = bot

    def _map_overwrites(self, old_overwrites, role_map, target_guild):
        """Translates permission overwrites from the old server to the new one."""
        new_overwrites = {}
        for target, overwrite in old_overwrites.items():
            # We only copy Role overwrites, not individual Member overwrites
            if isinstance(target, discord.Role):
                if target.is_default():
                    new_overwrites[target_guild.default_role] = overwrite
                elif target.id in role_map:
                    new_overwrites[role_map[target.id]] = overwrite
                    
        # SELF-PRESERVATION: Ensure the bot explicitly grants itself access to the new channel.
        # This prevents Discord Error 50013 (locking oneself out of a newly created private channel).
        bot_member = target_guild.me
        bot_overwrite = new_overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.update(view_channel=True, manage_channels=True, manage_roles=True, manage_webhooks=True)
        new_overwrites[bot_member] = bot_overwrite
        
        return new_overwrites

    # ==========================================
    #             DIAGNOSTICS
    # ==========================================

    @app_commands.command(name="diagnose", description="Check if the bot has the correct permissions to clone servers/messages.")
    @app_commands.describe(source_guild_id="The ID of the server you want to copy FROM")
    @app_commands.checks.has_permissions(administrator=True)
    async def clone_diagnose(self, interaction: discord.Interaction, source_guild_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            source_guild_id = int(source_guild_id)
        except ValueError:
            return await interaction.followup.send("❌ Invalid Server ID provided.")

        source_guild = self.bot.get_guild(source_guild_id)
        target_guild = interaction.guild

        embed = discord.Embed(title="🔍 Clone Diagnostic Report", color=discord.Color.blue())

        # 1. Check Target Server (Where the bot is typing)
        target_admin = target_guild.me.guild_permissions.administrator
        target_status = "✅ YES" if target_admin else "❌ NO (Crucial for Server Cloning)"
        embed.add_field(
            name="Target Server (Here)", 
            value=f"**Administrator:** {target_status}\n*The bot MUST have Administrator here to successfully clone private channels and roles without throwing 50013 errors.*", 
            inline=False
        )

        # 2. Check Source Server
        if not source_guild:
            embed.add_field(name="Source Server", value="❌ Bot is NOT in the source server, or ID is wrong.", inline=False)
        else:
            source_perms = source_guild.me.guild_permissions
            read_perms = source_perms.view_channel and source_perms.read_message_history
            source_status = "✅ YES" if read_perms else "❌ NO (Cannot read history/channels)"
            
            # Count how many channels the bot can actually see
            visible_channels = len([c for c in source_guild.channels if c.permissions_for(source_guild.me).view_channel])
            total_channels = len(source_guild.channels)
            
            embed.add_field(
                name=f"Source Server: {source_guild.name}", 
                value=f"**Read Permissions:** {source_status}\n**Channels Visible:** {visible_channels} / {total_channels}\n*If Channels Visible is lower than the total, give the bot an Admin role in the source server so it can see private channels to clone them.*", 
                inline=False
            )

        await interaction.followup.send(embed=embed)

    # ==========================================
    #             SERVER INFRASTRUCTURE
    # ==========================================

    @app_commands.command(name="server", description="Sync and clone roles, categories, and channels from another server.")
    @app_commands.describe(
        source_guild_id="The ID of the server you want to copy FROM",
        clear_server="Set to True to DELETE ALL existing roles and channels in this server first"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def clone_server(self, interaction: discord.Interaction, source_guild_id: str, clear_server: bool = False):
        # Strict Pre-flight Check
        if not interaction.guild.me.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ **Critical Error:** I require the `Administrator` permission in this target server to clone private channels and roles. Please go to Server Settings -> Roles, grant my bot role Administrator, and try again.", 
                ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        try:
            source_guild_id = int(source_guild_id)
        except ValueError:
            return await interaction.followup.send("❌ Invalid Server ID provided.")

        source_guild = self.bot.get_guild(source_guild_id)
        target_guild = interaction.guild

        if not source_guild:
            return await interaction.followup.send("❌ I cannot find the source server. Make sure I am invited to it!")

        if source_guild.id == target_guild.id:
            return await interaction.followup.send("❌ Source and target servers cannot be the same.")

        status_msg = f"⏳ Starting server clone/sync from **{source_guild.name}**...\n*This might take a few minutes to respect Discord rate limits.*"
        await interaction.followup.send(status_msg)

        error_log = []

        # --- 0. WIPE TARGET SERVER (IF REQUESTED) ---
        if clear_server:
            save_channel = interaction.channel.parent if isinstance(interaction.channel, discord.Thread) else interaction.channel
            for channel in target_guild.channels:
                if channel.id != save_channel.id:
                    try: 
                        await channel.delete()
                        await asyncio.sleep(0.5) # Rate limit pacing
                    except Exception as e: 
                        error_log.append(f"[Clear] Failed to delete channel {channel.name}: {e}")
            
            for role in target_guild.roles:
                if not role.is_default() and not role.managed and role < target_guild.me.top_role:
                    try: 
                        await role.delete()
                        await asyncio.sleep(0.3) # Rate limit pacing
                    except Exception as e: 
                        error_log.append(f"[Clear] Failed to delete role {role.name}: {e}")

        # --- 1. CLONE / SYNC ROLES ---
        role_map = {} 
        roles_to_copy = [r for r in reversed(source_guild.roles) if not r.is_default() and not r.managed]
        
        for src_role in roles_to_copy:
            existing_role = discord.utils.get(target_guild.roles, name=src_role.name)
            try:
                if existing_role:
                    await existing_role.edit(
                        permissions=src_role.permissions, color=src_role.color, 
                        hoist=src_role.hoist, mentionable=src_role.mentionable,
                        reason=f"Synced from {source_guild.name}"
                    )
                    role_map[src_role.id] = existing_role
                else:
                    new_role = await target_guild.create_role(
                        name=src_role.name, permissions=src_role.permissions,
                        color=src_role.color, hoist=src_role.hoist, mentionable=src_role.mentionable,
                        reason=f"Cloned from {source_guild.name}"
                    )
                    role_map[src_role.id] = new_role
                await asyncio.sleep(0.4) # Rate limit pacing
            except Exception as e:
                error_log.append(f"[Roles] Failed to clone/sync role '{src_role.name}': {e}")

        # --- 2. CLONE / SYNC CATEGORIES ---
        category_map = {} 

        for src_cat in source_guild.categories:
            existing_cat = discord.utils.get(target_guild.categories, name=src_cat.name)
            new_overwrites = self._map_overwrites(src_cat.overwrites, role_map, target_guild)
            
            try:
                if existing_cat:
                    await existing_cat.edit(overwrites=new_overwrites, position=src_cat.position)
                    category_map[src_cat.id] = existing_cat
                else:
                    new_category = await target_guild.create_category(
                        name=src_cat.name, overwrites=new_overwrites, position=src_cat.position
                    )
                    category_map[src_cat.id] = new_category
                await asyncio.sleep(0.5) # Rate limit pacing
            except Exception as e:
                error_log.append(f"[Categories] Failed to clone/sync category '{src_cat.name}': {e}")

        # --- 3. CLONE / SYNC CHANNELS ---
        for src_chan in source_guild.channels:
            if isinstance(src_chan, discord.CategoryChannel):
                continue

            target_cat = category_map.get(src_chan.category_id)
            new_overwrites = self._map_overwrites(src_chan.overwrites, role_map, target_guild)
            existing_chan = discord.utils.get(target_guild.channels, name=src_chan.name, type=src_chan.type)

            try:
                if existing_chan:
                    kwargs = {'category': target_cat, 'overwrites': new_overwrites, 'position': src_chan.position}
                    if hasattr(src_chan, 'topic'): kwargs['topic'] = src_chan.topic
                    if hasattr(src_chan, 'nsfw'): kwargs['nsfw'] = src_chan.nsfw
                    if hasattr(src_chan, 'slowmode_delay'): kwargs['slowmode_delay'] = src_chan.slowmode_delay
                    if hasattr(src_chan, 'user_limit'): kwargs['user_limit'] = src_chan.user_limit
                    if hasattr(src_chan, 'bitrate'): kwargs['bitrate'] = src_chan.bitrate
                    
                    await existing_chan.edit(**kwargs)
                else:
                    if isinstance(src_chan, discord.TextChannel):
                        await target_guild.create_text_channel(
                            name=src_chan.name, category=target_cat, overwrites=new_overwrites,
                            position=src_chan.position, topic=src_chan.topic, slowmode_delay=src_chan.slowmode_delay, nsfw=src_chan.nsfw
                        )
                    elif isinstance(src_chan, discord.VoiceChannel):
                        await target_guild.create_voice_channel(
                            name=src_chan.name, category=target_cat, overwrites=new_overwrites,
                            position=src_chan.position, user_limit=src_chan.user_limit, bitrate=src_chan.bitrate
                        )
                    elif isinstance(src_chan, discord.ForumChannel):
                        await target_guild.create_forum(
                            name=src_chan.name, category=target_cat, overwrites=new_overwrites,
                            position=src_chan.position, topic=src_chan.topic
                        )
                await asyncio.sleep(0.6) # Channel endpoints are heavily rate limited, pace slower
            except Exception as e:
                error_log.append(f"[Channels] Failed to clone/sync channel '{src_chan.name}': {e}")

        # --- 4. FINAL REPORTING ---
        final_msg = f"✅ **Sync Complete!** Roles, categories, and channels match **{source_guild.name}**."
        
        if error_log:
            final_msg += f"\n⚠️ Encountered {len(error_log)} errors during the process. See the attached log."
            report_text = "\n".join(error_log)
            file = discord.File(io.BytesIO(report_text.encode('utf-8')), filename="clone_errors.txt")
            await interaction.edit_original_response(content=final_msg, attachments=[file])
        else:
            await interaction.edit_original_response(content=final_msg)

    # ==========================================
    #             MESSAGE CLONING
    # ==========================================

    @app_commands.command(name="messages", description="Clone messages, pins, images, or files from another server.")
    @app_commands.describe(
        source_guild_id="The ID of the server you want to copy FROM",
        scope="Copy just this channel, or entire server?",
        filter_type="What kind of messages to clone?",
        limit="Max amount of messages to copy per channel (0 for unlimited)",
        create_backup="Download the channel history into a markdown/media backup as well?"
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Current Channel Only", value="channel"),
            app_commands.Choice(name="Entire Server", value="server")
        ],
        filter_type=[
            app_commands.Choice(name="All Messages", value="all"),
            app_commands.Choice(name="Pinned Messages Only", value="pins"),
            app_commands.Choice(name="Images Only", value="images"),
            app_commands.Choice(name="Files/Attachments Only", value="files")
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def clone_messages(self, interaction: discord.Interaction, source_guild_id: str, scope: app_commands.Choice[str], filter_type: app_commands.Choice[str], limit: int = 50, create_backup: bool = False):
        await interaction.response.defer(thinking=True)

        try:
            source_guild_id = int(source_guild_id)
        except ValueError:
            return await interaction.followup.send("❌ Invalid Server ID provided.")

        source_guild = self.bot.get_guild(source_guild_id)
        if not source_guild:
            return await interaction.followup.send("❌ I cannot find the source server. Make sure I am invited to it!")

        # 1. Determine channels to process
        channels_to_process = []
        if scope.value == "channel":
            src_chan = discord.utils.get(source_guild.text_channels, name=interaction.channel.name)
            if not src_chan:
                return await interaction.followup.send(f"❌ Could not find a channel named `{interaction.channel.name}` in the source server.")
            channels_to_process.append((src_chan, interaction.channel))
        else:
            for tgt_chan in interaction.guild.text_channels:
                src_chan = discord.utils.get(source_guild.text_channels, name=tgt_chan.name)
                if src_chan:
                    channels_to_process.append((src_chan, tgt_chan))

        if not channels_to_process:
            return await interaction.followup.send("❌ No matching channels found to clone messages into.")

        await interaction.followup.send(f"⏳ **Message cloning started!**\nScope: `{scope.name}` | Filter: `{filter_type.name}`\nCheck below for live updates.")
        fetch_limit = None if limit <= 0 else limit

        # 2. Process each channel
        for src_chan, tgt_chan in channels_to_process:
            try:
                # Fetch messages based on filter
                if filter_type.value == "pins":
                    messages = await src_chan.pins()
                    messages.reverse() # Discord returns newest pins first, we want chronological
                else:
                    raw_messages = [m async for m in src_chan.history(limit=fetch_limit, oldest_first=False)]
                    raw_messages.reverse()

                    if filter_type.value == "images":
                        messages = [m for m in raw_messages if m.attachments and any(a.content_type and a.content_type.startswith('image/') for a in m.attachments)]
                    elif filter_type.value == "files":
                        messages = [m for m in raw_messages if m.attachments]
                    else:
                        messages = raw_messages

                if not messages:
                    continue

                # Prepare Backup Environment if requested
                md_file_path = None
                media_dir = None
                if create_backup:
                    safe_chan_name = re.sub(r'[\\/*?:"<>|]', "", src_chan.name)
                    backup_dir = os.path.join("data", "backups", str(source_guild.id), safe_chan_name)
                    media_dir = os.path.join(backup_dir, "media")
                    os.makedirs(media_dir, exist_ok=True)
                    md_file_path = os.path.join(backup_dir, "chatlog.md")
                    
                    with open(md_file_path, "w", encoding="utf-8") as f:
                        f.write(f"# Backup of {src_chan.name} from {source_guild.name}\n\n")

                # Prepare Webhook for impersonation
                webhook = None
                if tgt_chan.permissions_for(interaction.guild.me).manage_webhooks:
                    webhooks = await tgt_chan.webhooks()
                    webhook = discord.utils.get(webhooks, name="CloneHook")
                    if not webhook:
                        webhook = await tgt_chan.create_webhook(name="CloneHook")

                copied_count = 0
                base_delay = 1.0 # Starting delay

                for msg in messages:
                    if not msg.content and not msg.attachments and not msg.embeds:
                        continue

                    # Read bytes into memory so we can recreate the File object upon retries / save locally
                    file_data = []
                    for att in msg.attachments:
                        if att.size <= 25 * 1024 * 1024:
                            try:
                                file_bytes = await att.read()
                                file_data.append((file_bytes, att.filename, att.id))
                            except: pass

                    # Local Markdown Formatting / Save File
                    if create_backup and md_file_path and media_dir:
                        with open(md_file_path, 'a', encoding='utf-8') as f:
                            dt = msg.created_at
                            timestamp = f"{dt.month}/{dt.day}/{dt.strftime('%y')}, {dt.strftime('%I:%M %p').lstrip('0')}"
                            
                            f.write(f"## {msg.author.display_name} — {timestamp}\n")
                            if msg.content:
                                f.write(f"{msg.content}\n\n")
                            
                            # Embed and Download Files
                            for att_bytes, att_filename, att_id in file_data:
                                safe_filename = f"{msg.id}_{att_id}_{att_filename}"
                                media_filepath = os.path.join(media_dir, safe_filename)
                                with open(media_filepath, "wb") as img_file:
                                    img_file.write(att_bytes)
                                
                                lower_name = att_filename.lower()
                                if lower_name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                    f.write(f"![{att_filename}](media/{safe_filename})\n\n")
                                else:
                                    f.write(f"[{att_filename}](media/{safe_filename})\n\n")
                                    
                            # Note missing attachments
                            for att in msg.attachments:
                                if att.size > 25 * 1024 * 1024:
                                    f.write(f"*[Attachment too large to backup: {att.filename}]({att.url})*\n\n")
                            
                            # Rip Embeds
                            for em in msg.embeds:
                                if em.description:
                                    f.write(f"> {em.description}\n\n")
                                if em.image and em.image.url:
                                    f.write(f"*[Embed Image: {em.image.url}]*\n\n")
                            
                            f.write("\n")

                    safe_mentions = discord.AllowedMentions.none()
                    
                    # --- EXPONENTIAL BACKOFF RETRY LOOP ---
                    max_retries = 7
                    for attempt in range(max_retries):
                        
                        # Re-instantiate discord.File objects so they aren't consumed in previous failed attempts
                        files = [discord.File(io.BytesIO(b), filename=fn) for b, fn, _id in file_data]

                        try:
                            start_time = time.time()
                            
                            if webhook:
                                target_msg = await webhook.send(
                                    content=msg.content,
                                    username=msg.author.display_name,
                                    avatar_url=msg.author.display_avatar.url if msg.author.display_avatar else None,
                                    embeds=msg.embeds[:10],
                                    files=files,
                                    wait=True,
                                    allowed_mentions=safe_mentions
                                )
                            else:
                                content = f"**{msg.author.display_name}**: {msg.content}"
                                target_msg = await tgt_chan.send(
                                    content=content,
                                    embeds=msg.embeds[:10],
                                    files=files,
                                    allowed_mentions=safe_mentions
                                )

                            if filter_type.value == "pins" or msg.pinned:
                                try: await target_msg.pin(reason="Cloned Pin")
                                except: pass

                            copied_count += 1
                            
                            # Adaptive Pacing: If sending took unusually long, discord.py hit a rate limit internally.
                            # We proactively slow down to stop spamming the console with warnings.
                            elapsed = time.time() - start_time
                            if elapsed > 1.5:
                                base_delay = min(base_delay * 1.5, 10.0) 
                            else:
                                base_delay = max(1.0, base_delay * 0.9) 

                            await asyncio.sleep(base_delay)
                            
                            # Bucket Evasion: Forcefully clear the webhook limit bucket (usually 30 per 60s)
                            if copied_count % 25 == 0:
                                await asyncio.sleep(20.0)

                            break # Success, break the retry loop
                            
                        except discord.HTTPException as e:
                            if e.status == 429: # Explicit Rate Limit
                                # Softer exponential backoff: 1.5^attempt instead of 2^attempt
                                backoff_time = (1.5 ** attempt) + random.uniform(1.0, 3.0)
                                print(f"[Clone] Explicit 429 Rate Limit. Soft exponential backoff: sleeping {backoff_time:.2f}s")
                                await asyncio.sleep(backoff_time)
                            else:
                                print(f"[Clone] Failed to clone message {msg.id}: {e}")
                                break # Other HTTP error, do not retry
                        except Exception as e:
                            print(f"[Clone] Unknown error on msg {msg.id}: {e}")
                            break

                if webhook:
                    await webhook.delete()

                if copied_count > 0:
                    status = f"✅ Successfully cloned **{copied_count}** messages in {tgt_chan.mention}."
                    if create_backup:
                        status += f"\n📁 *Backup successfully saved locally to `data/backups/`*"
                    await interaction.channel.send(status)

            except discord.Forbidden:
                await interaction.channel.send(f"⚠️ Missing permissions to read {src_chan.name} or write to {tgt_chan.mention}.")
            except Exception as e:
                await interaction.channel.send(f"⚠️ Error processing {tgt_chan.mention}: {e}")

        await interaction.channel.send("🎉 **Message Clone Sequence Complete!**")

async def setup(bot):
    await bot.add_cog(CloneCog(bot))