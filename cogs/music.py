"""
filename: cogs/music.py
description: A straightforward music bot cog that uses yt-dlp to grab audio from URLs, saves MP3s locally to avoid redownloads, and handles VC playback with a queue system.
Views:
    - MusicQueuePaginator: Handles pagination for displaying the current music queue.
Commands:
    - /music play <url>: Join your voice channel and play audio from a URL.
    - /music test: Play data/musicbot/test.mp3 to verify voice connectivity.
    - /music pause: Pause the currently playing audio.
    - /music resume: Resume the paused audio.
    - /music skip: Skip the current track in the queue.
    - /music stop: Stop playback and completely clear the queue.
    - /music queue: View the paginated current queue of tracks.
    - /music leave: Disconnect the bot from the voice channel.
    - /music export: Export the current music queue to a JSON file.
    - /music load: Load a previously exported JSON queue.
"""

import os
import io
import json
import asyncio
import logging
import yt_dlp
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("cogs.music")

MUSIC_DIR = "./data/musicbot"
COOKIES_FILE = "./data/cookies.txt"

os.makedirs(MUSIC_DIR, exist_ok=True)


class MusicQueuePaginator(discord.ui.View):
    def __init__(self, queue: list, bot: commands.Bot, current: dict = None):
        super().__init__(timeout=300)
        self.queue = queue
        self.bot = bot
        self.current = current
        self.current_page = 0
        self.per_page = 10
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.queue) - 1) // self.per_page) if self.queue else 0
        for child in self.children:
            if getattr(child, "custom_id", None) in ["first_btn", "prev_btn"]:
                child.disabled = self.current_page == 0
            elif getattr(child, "custom_id", None) in ["next_btn", "last_btn"]:
                child.disabled = self.current_page >= max_pages

    async def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎶 Music Queue", color=discord.Color.blue())
        
        if self.current:
            embed.add_field(name="Now Playing", value=f"[{self.current['title']}]({self.current['url']})", inline=False)
            
        if not self.queue and not self.current:
            embed.description = "The queue is completely empty."
            return embed

        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.queue[start:end]
        
        q_text = ""
        for idx, track in enumerate(page_items, start=start+1):
            q_text += f"**{idx}.** [{track['title']}]({track['url']})\n"
            
        if q_text:
            embed.add_field(name="Up Next", value=q_text, inline=False)
        else:
            embed.add_field(name="Up Next", value="No upcoming tracks.", inline=False)
        
        total_tracks = len(self.queue)
        max_pages = max(1, (total_tracks + self.per_page - 1) // self.per_page) if total_tracks else 1
        embed.set_footer(text=f"Page {self.current_page + 1} of {max_pages} | Total: {total_tracks} tracks")
        return embed

    @discord.ui.button(label="⏮ First", style=discord.ButtonStyle.secondary, custom_id="first_btn")
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="next_btn")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)

    @discord.ui.button(label="Last ⏭", style=discord.ButtonStyle.primary, custom_id="last_btn")
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_pages = max(0, (len(self.queue) - 1) // self.per_page) if self.queue else 0
        self.current_page = max_pages
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)


@app_commands.guild_only()
class MusicCog(commands.GroupCog, name="music"):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.current = {}

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await send(f"❌ **Bot Error:** I am missing permissions to run this: `{perms}`. I need `Connect` and `Speak`.", ephemeral=True)
        else:
            logger.error(f"Unhandled app command error in Music: {error}", exc_info=error)
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def dl_audio(self, url: str) -> dict:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(MUSIC_DIR, '%(extractor)s_%(id)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'restrictfilenames': True,
            'noplaylist': True, 
        }
        
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            
        loop = asyncio.get_running_loop()
        
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("Could not extract info from the provided URL.")
                
                if 'entries' in info:
                    if not info['entries']:
                        raise Exception("The URL points to an empty playlist.")
                    info = info['entries'][0]

                expected_filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(expected_filename)
                mp3_file = f"{base}.mp3"
                
                if not os.path.exists(mp3_file):
                    video_url = info.get('webpage_url', url)
                    ydl.download([video_url])
                    
                if not os.path.exists(mp3_file):
                    raise Exception("Download succeeded but the MP3 file was not found locally.")
                    
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'url': info.get('webpage_url', url),
                    'file': mp3_file
                }
                
        return await loop.run_in_executor(None, extract)

    def play_next(self, guild, vc):
        if guild.id in self.queues and len(self.queues[guild.id]) > 0:
            track = self.queues[guild.id].pop(0)
            
            if not os.path.exists(track['file']):
                async def re_dl_and_play():
                    try:
                        new_track = await self.dl_audio(track['url'])
                        self.current[guild.id] = new_track
                        if vc.is_connected():
                            audio = discord.FFmpegPCMAudio(new_track['file'])
                            vc.play(audio, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, guild, vc))
                        else:
                            self.current.pop(guild.id, None)
                    except Exception as e:
                        logger.error(f"Failed to cleanly re-download missing track {track['url']}: {e}")
                        self.play_next(guild, vc)
                asyncio.run_coroutine_threadsafe(re_dl_and_play(), self.bot.loop)
                return
                
            self.current[guild.id] = track
            try:
                if vc.is_connected():
                    audio = discord.FFmpegPCMAudio(track['file'])
                    vc.play(audio, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, guild, vc))
                else:
                    self.current.pop(guild.id, None)
            except Exception as e:
                logger.error(f"Failed to play audio in queue sequence: {e}", exc_info=True)
                self.play_next(guild, vc)
        else:
            self.current.pop(guild.id, None)

    @app_commands.command(name="play", description="Join your voice channel and play audio from a URL.")
    @app_commands.describe(url="The URL of the song or video to play")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ You must be in a voice channel to use this command.", ephemeral=True)
            
        # Acknowledge immediately to prevent Discord command timeout
        await interaction.response.send_message("⏳ Fetching track info and downloading audio...")
        
        # STEP 1: Download the audio BEFORE joining VC to prevent 4006 socket timeout errors
        try:
            track_info = await self.dl_audio(url)
            track_title = track_info['title']
        except Exception as e:
            logger.error(f"Failed to process URL {url}: {e}", exc_info=True)
            return await interaction.edit_original_response(content=f"❌ Failed to download or process the URL:\n```\n{e}\n```")
            
        await interaction.edit_original_response(content="⏳ Audio ready! Connecting to voice channel...")
        
        # STEP 2: Connect to VC
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                vc = await interaction.user.voice.channel.connect(timeout=20.0)
            else:
                if not vc.is_connected():
                    logger.info("Voice client found but disconnected. Forcing cleanup and reconnect.")
                    await vc.disconnect(force=True)
                    vc = await interaction.user.voice.channel.connect(timeout=20.0)
                elif vc.channel != interaction.user.voice.channel:
                    await vc.move_to(interaction.user.voice.channel)
        except Exception as e:
            logger.error(f"Voice connection error: {e}", exc_info=True)
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect(force=True)
            return await interaction.edit_original_response(
                content=f"❌ Failed to connect to voice channel. (If using Docker, ensure UDP ports are open!)\n```\n{e}\n```"
            )
            
        # STEP 3: Play or Queue
        if vc.is_playing() or vc.is_paused():
            if interaction.guild.id not in self.queues:
                self.queues[interaction.guild.id] = []
            self.queues[interaction.guild.id].append(track_info)
            await interaction.edit_original_response(content=f"✅ Added to queue: **{track_title}**")
        else:
            self.current[interaction.guild.id] = track_info
            try:
                if not vc.is_connected():
                    raise Exception("Voice client disconnected unexpectedly right before playback.")
                audio = discord.FFmpegPCMAudio(track_info['file'])
                vc.play(audio, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, interaction.guild, vc))
                
                await interaction.edit_original_response(content=f"🎶 Now playing: **{track_title}**")
            except Exception as e:
                logger.error(f"Failed to play audio: {e}", exc_info=True)
                await interaction.edit_original_response(content=f"❌ Failed to begin playback:\n```\n{e}\n```")

    @app_commands.command(name="test", description="Play a local test.mp3 file to verify voice connectivity.")
    async def test_audio(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ You must be in a voice channel.", ephemeral=True)
            
        test_file = os.path.join(MUSIC_DIR, "test.mp3")
        if not os.path.exists(test_file):
            return await interaction.response.send_message(f"❌ Test file not found. Please place an MP3 file at `{test_file}`.", ephemeral=True)
            
        await interaction.response.send_message("⏳ Connecting to voice to play test file...")
        
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                vc = await interaction.user.voice.channel.connect(timeout=20.0)
            else:
                if not vc.is_connected():
                    await vc.disconnect(force=True)
                    vc = await interaction.user.voice.channel.connect(timeout=20.0)
                elif vc.channel != interaction.user.voice.channel:
                    await vc.move_to(interaction.user.voice.channel)
        except Exception as e:
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect(force=True)
            return await interaction.edit_original_response(content=f"❌ Failed to connect to voice:\n```\n{e}\n```")
            
        track_info = {
            'title': 'Test Audio',
            'url': 'Local File',
            'file': test_file
        }
        
        if vc.is_playing() or vc.is_paused():
            if interaction.guild.id not in self.queues:
                self.queues[interaction.guild.id] = []
            self.queues[interaction.guild.id].append(track_info)
            await interaction.edit_original_response(content=f"✅ Added to queue: **Test Audio**")
        else:
            self.current[interaction.guild.id] = track_info
            try:
                audio = discord.FFmpegPCMAudio(test_file)
                vc.play(audio, after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, interaction.guild, vc))
                await interaction.edit_original_response(content=f"🎶 Now playing: **Test Audio**")
            except Exception as e:
                await interaction.edit_original_response(content=f"❌ Playback failed:\n```\n{e}\n```")

    @app_commands.command(name="pause", description="Pause the currently playing audio.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Paused the music.")
        else:
            await interaction.response.send_message("❌ Nothing is currently playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume the paused audio.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed the music.")
        else:
            await interaction.response.send_message("❌ Music is not paused.", ephemeral=True)

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop() 
            await interaction.response.send_message("⏭ Skipped the current track.")
        else:
            await interaction.response.send_message("❌ Nothing is currently playing.", ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and completely clear the queue.")
    async def stop(self, interaction: discord.Interaction):
        self.queues[interaction.guild.id] = []
        self.current.pop(interaction.guild.id, None)
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await interaction.response.send_message("⏹ Stopped playback and wiped the queue.")
        else:
            await interaction.response.send_message("❌ Not connected to a voice channel.", ephemeral=True)

    @app_commands.command(name="leave", description="Disconnect the bot from the voice channel.")
    async def leave(self, interaction: discord.Interaction):
        self.queues[interaction.guild.id] = []
        self.current.pop(interaction.guild.id, None)
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect(force=True)
            await interaction.response.send_message("👋 Disconnected from the voice channel.")
        else:
            await interaction.response.send_message("❌ Not connected to a voice channel.", ephemeral=True)

    @app_commands.command(name="queue", description="View the current paginated queue of tracks.")
    async def queue(self, interaction: discord.Interaction):
        q = self.queues.get(interaction.guild.id, [])
        curr = self.current.get(interaction.guild.id)
        if not q and not curr:
            return await interaction.response.send_message("❌ The queue is currently empty.", ephemeral=True)
            
        view = MusicQueuePaginator(q, self.bot, current=curr)
        await interaction.response.send_message(embed=await view.generate_embed(), view=view)

    @app_commands.command(name="export", description="Export the current music queue to a JSON file.")
    async def export_queue(self, interaction: discord.Interaction):
        q = self.queues.get(interaction.guild.id, [])
        if not q:
            return await interaction.response.send_message("❌ The queue is empty. Nothing to export.", ephemeral=True)
        
        data = json.dumps(q, indent=4)
        file = discord.File(io.BytesIO(data.encode('utf-8')), filename="music_queue.json")
        await interaction.response.send_message("✅ Exported current queue:", file=file)

    @app_commands.command(name="load", description="Load a previously exported JSON queue.")
    @app_commands.describe(file="The JSON file containing the exported queue.")
    async def load_queue(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith('.json'):
            return await interaction.response.send_message("❌ Please upload a valid `.json` file.", ephemeral=True)
            
        await interaction.response.defer()
        
        try:
            content = await file.read()
            loaded_q = json.loads(content.decode('utf-8'))
            
            if not isinstance(loaded_q, list):
                raise ValueError("JSON must contain a list of tracks.")
                
            for item in loaded_q:
                if not isinstance(item, dict) or 'title' not in item or 'url' not in item or 'file' not in item:
                    raise ValueError("JSON file is improperly formatted or corrupted.")
                
            if interaction.guild.id not in self.queues:
                self.queues[interaction.guild.id] = []
                
            self.queues[interaction.guild.id].extend(loaded_q)
            len_loaded_q = len(loaded_q)
            await interaction.followup.send(f"✅ Successfully loaded **{len_loaded_q}** tracks into the queue.\nUse `/music queue` to view it!")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to parse or load the queue:\n```\n{e}\n```", ephemeral=True)


async def setup(bot):
    await bot.add_cog(MusicCog(bot))