"""
filename: cogs/dl.py
description: Download videos and photos from various platforms using yt-dlp and gallery-dl. Features host-based fallbacks (like instaloader for Instagram) and automatically shrinks videos over 10MB using an FFmpeg subprocess implementation to safely fit within Discord's upload limits, optimized for iOS compatibility. Logs all history for administration.
Views:
    - DLHistoryPaginator: Handles pagination for displaying a guild's media download history.
Commands:
    - /dl video <url>: Download a video from a URL. Prioritizes file size and mobile compatibility over raw quality. (User)
    - /dl photos <url>: Download photos from a URL. (User)
    - /dl history: View a paginated history of all downloaded URLs in the server. (User)
    - /dl cookies <file>: Upload a cookies.txt file for yt-dlp/gallery-dl to bypass login walls. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import shutil
import uuid
import yt_dlp
import re
import traceback
import logging
from urllib.parse import urlparse
from db import DatabaseController

logger = logging.getLogger("cogs.dl")

TEMP_DIR = "./data/dl_temp"
COOKIES_FILE = "./data/cookies.txt"

os.makedirs(TEMP_DIR, exist_ok=True)

def get_hostname(url: str) -> str:
    try:
        return urlparse(url).hostname.replace('www.', '')
    except Exception:
        return ""

async def get_video_duration(file_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", file_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return float(stdout.decode('utf-8').strip())
        else:
            logger.warning(f"ffprobe failed: {stderr.decode('utf-8', errors='replace')}")
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
    return 0.0

async def process_video_ffmpeg(input_path: str, output_path: str, target_mb: float = 9.0, shrink: bool = False) -> tuple[bool, str]:
    duration = await get_video_duration(input_path)
    logger.info(f"Processing video. Target: {target_mb}MB, Duration: {duration}s, Shrink: {shrink}")
    
    # Scale to max 720p to save bitrate, ensure dimensions are even (required by x264 iOS)
    # Enforce profile and format to strictly support all iPhones
    base_video_opts = [
        "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v", "libx264", 
        "-profile:v", "main", 
        "-pix_fmt", "yuv420p",
        "-preset", "faster"
    ]
    
    # Ensure faststart is applied for iOS streaming compatibility
    base_audio_opts = [
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-f", "mp4"
    ]

    if shrink and duration > 0:
        # Strict bitrate targeting using 90% margin to prevent overshooting 10MB
        safe_target_kb = (target_mb * 8192) * 0.90
        total_bitrate_kbps = safe_target_kb / duration
        
        audio_bitrate = 64
        video_bitrate = max(50, int(total_bitrate_kbps - audio_bitrate))
        
        logger.info(f"Calculated Bitrates - Video: {video_bitrate}k, Audio: {audio_bitrate}k")
        
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            *base_video_opts,
            "-b:v", f"{video_bitrate}k",
            "-maxrate", f"{int(video_bitrate * 1.5)}k", 
            "-bufsize", f"{video_bitrate * 2}k",
            *base_audio_opts,
            "-b:a", f"{audio_bitrate}k",
            output_path
        ]
    else:
        logger.info("Using CRF-based encoding for iOS formatting.")
        # If it doesn't need to shrink severely, just convert it to standard format with a cap
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            *base_video_opts,
            "-crf", "28" if shrink else "24",
            "-maxrate", "2000k", # cap bitrate to prevent it artificially inflating tiny files
            "-bufsize", "4000k",
            *base_audio_opts,
            "-b:a", "64k" if shrink else "128k",
            output_path
        ]
        
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            err_msg = stderr.decode('utf-8', errors='replace')
            logger.error(f"FFmpeg compression failed: {err_msg}")
            return False, err_msg
        return True, ""
    except Exception as e:
        logger.error(f"Exception during FFmpeg execution: {e}", exc_info=True)
        return False, str(e)


class DLHistoryPaginator(discord.ui.View):
    def __init__(self, history: list, bot: commands.Bot):
        super().__init__(timeout=300)
        self.history = history
        self.bot = bot
        self.current_page = 0
        self.per_page = 5
        self.user_cache = {}  # Cache to prevent fetching the same user multiple times
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.history) - 1) // self.per_page)
        for child in self.children:
            if getattr(child, "custom_id", None) in ["first_btn", "prev_btn"]:
                child.disabled = self.current_page == 0
            elif getattr(child, "custom_id", None) in ["next_btn", "last_btn"]:
                child.disabled = self.current_page >= max_pages

    async def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📥 Download History",
            color=discord.Color.blue()
        )
        
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.history[start:end]
        
        if not page_items:
            embed.description = "No history found."
            return embed

        for idx, record in enumerate(page_items, start=start+1):
            dt = f"<t:{record.timestamp}:R>"
            m_type = "🎬 Video" if record.media_type == "video" else "📸 Photo"
            
            # Safely get or fetch the user's name so we don't display a raw <@id>
            user_id = int(record.user_id)
            if user_id in self.user_cache:
                username = self.user_cache[user_id]
            else:
                user = self.bot.get_user(user_id)
                if not user:
                    try:
                        user = await self.bot.fetch_user(user_id)
                    except discord.NotFound:
                        pass
                username = f"@{user.name}" if user else f"User {user_id}"
                self.user_cache[user_id] = username

            embed.add_field(
                name=f"{idx}. {m_type} by {username}",
                value=f"**URL:** {record.url}\n**Time:** {dt}",
                inline=False
            )

        max_pages = max(1, (len(self.history) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"Page {self.current_page + 1} of {max_pages} | Total: {len(self.history)} records")
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
        max_pages = max(0, (len(self.history) - 1) // self.per_page)
        self.current_page = max_pages
        self.update_buttons()
        await interaction.response.edit_message(embed=await self.generate_embed(), view=self)


class DLCog(commands.GroupCog, name="dl"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await send(f"❌ **Bot Error:** I am missing permissions to run this: `{perms}`. I need `Attach Files` and `Send Messages`.", ephemeral=True)
        else:
            logger.error(f"Unhandled app command error: {error}", exc_info=error)
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def fallback_instaloader(self, url: str, dest_dir: str) -> tuple[bool, str]:
        match = re.search(r"(?:instagram\.com|instagr\.am)/(?:p|reel|tv)/([^/?#&]+)", url)
        if not match:
            return False, "Could not extract shortcode for instaloader."
            
        shortcode = match.group(1)
        cmd = ["instaloader", "--quiet", "--dirname-pattern", dest_dir, "--", f"-{shortcode}"]
        logger.info(f"Triggering instaloader fallback for shortcode: {shortcode}")
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            if process.returncode == 0:
                return True, ""
            err_msg = stderr.decode('utf-8', errors='replace')
            logger.warning(f"Instaloader failed: {err_msg}")
            return False, err_msg
        except Exception as e:
            logger.error(f"Instaloader exception: {e}", exc_info=True)
            return False, str(e)

    @app_commands.command(name="video", description="Download a video from a URL.")
    @app_commands.describe(url="The URL of the video to download")
    @app_commands.checks.bot_has_permissions(send_messages=True, attach_files=True)
    async def dl_video(self, interaction: discord.Interaction, url: str):
        await interaction.response.send_message(f"⏳ Starting background download...", ephemeral=True)
        
        req_id = f"temp_{uuid.uuid4().hex[:12]}"
        req_dir = os.path.join(TEMP_DIR, req_id)
        os.makedirs(req_dir, exist_ok=True)
        logger.info(f"Starting video download for {url} in {req_dir}")
        
        # Hard limits strictly locking to 10MB to avoid Discord 413 Payload Errors
        server_limit_mb = 10.0
        target_compression_mb = 9.0 
        
        ydl_opts = {
            'outtmpl': os.path.join(req_dir, f"{req_id}.%(ext)s"),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'restrictfilenames': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            
        host = get_hostname(url)
        success = False
        error_msgs = []
        
        try:
            loop = asyncio.get_running_loop()
            def extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
                    
            await loop.run_in_executor(None, extract)
            
            if any(f.lower().endswith(('.mp4', '.webm', '.mkv', '.mov')) for f in os.listdir(req_dir)):
                success = True
            else:
                msg = "yt-dlp: No media files were produced in the download directory."
                error_msgs.append(msg)
                logger.warning(msg)
        except Exception as e:
            msg = f"yt-dlp error: {str(e)}"
            error_msgs.append(msg)
            logger.error(msg, exc_info=True)
            
        if not success:
            if host in ['instagram.com', 'instagr.am']:
                success, err = await self.fallback_instaloader(url, req_dir)
                if not success:
                    error_msgs.append(f"Instaloader fallback error: {err}")
                
        try:
            if not success:
                err_text = "\n".join(error_msgs)[:1800]
                return await interaction.edit_original_response(content=f"❌ Failed to download the video.\n**Logs:**\n```\n{err_text}\n```")
                
            media_files = [
                os.path.join(req_dir, f) for f in os.listdir(req_dir) 
                if f.lower().endswith(('.mp4', '.webm', '.mkv', '.mov', '.avi'))
            ]
            
            if not media_files:
                return await interaction.edit_original_response(content="❌ No valid video file found after a successful download execution.")
                
            media_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
            original_file = media_files[0]
            
            file_size_mb = os.path.getsize(original_file) / (1024 * 1024)
            logger.info(f"Original file downloaded: {file_size_mb:.2f}MB")
            
            # We enforce processing on EVERY video to guarantee iOS streaming compatibility (+faststart & strict h264)
            needs_shrink = file_size_mb > target_compression_mb
            
            if needs_shrink:
                await interaction.edit_original_response(content=f"⏳ Video is {file_size_mb:.1f}MB. Compressing to fit 10.0MB upload limit...")
            else:
                await interaction.edit_original_response(content=f"⏳ Processing video encoding...")
                
            processed_file = os.path.join(req_dir, f"processed_{req_id}.mp4")
            shrink_success, shrink_err = await process_video_ffmpeg(original_file, processed_file, target_mb=target_compression_mb, shrink=needs_shrink)
            
            if not shrink_success:
                err_trim = shrink_err[-1800:] if shrink_err else "Unknown FFmpeg error."
                logger.error(f"Compression failed completely: {err_trim}")
                return await interaction.edit_original_response(content=f"❌ Failed to process the video.\n**FFmpeg Error:**\n```\n{err_trim}\n```")
            
            if not os.path.exists(processed_file):
                logger.error("Compression reported success but output file missing.")
                return await interaction.edit_original_response(content="❌ Video compression succeeded but the output file is missing.")
                
            final_file = processed_file
                
            # Pre-upload check: Verify we are actually under the strict 10MB server limit
            final_file_size_mb = os.path.getsize(final_file) / (1024 * 1024)
            logger.info(f"Final file ready for upload: {final_file_size_mb:.2f}MB")

            if final_file_size_mb >= server_limit_mb:
                logger.error(f"Video compression insufficient. Final: {final_file_size_mb:.2f}MB, Limit: {server_limit_mb:.2f}MB")
                return await interaction.edit_original_response(
                    content=f"❌ The resulting video ({final_file_size_mb:.2f}MB) is still too large for this server's limit ({server_limit_mb:.2f}MB) after compression."
                )
                
            file = discord.File(final_file)
            try:
                # Log success history
                await DatabaseController.log_dl_history(str(interaction.guild_id), str(interaction.user.id), url, "video")
                
                # Send the final video out to the public channel (doesn't trigger a "reply")
                await interaction.channel.send(content=f"✅ {interaction.user.mention} Downloaded a video:", file=file)
                # Confirm cleanly in the original ephemeral message
                await interaction.edit_original_response(content="✅ Video uploaded successfully!")
                logger.info(f"Successfully uploaded video for {url}")
            except discord.errors.HTTPException as e:
                if e.status == 413:
                    logger.error(f"Discord rejected the file payload (413). Size: {final_file_size_mb:.2f}MB")
                    await interaction.edit_original_response(
                        content=f"❌ Discord rejected the file (413 Payload Too Large). The compression didn't shrink it enough.\n"
                        f"Final Size: {final_file_size_mb:.2f}MB | Server Limit: {server_limit_mb:.2f}MB"
                    )
                else:
                    raise

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"Unexpected error in dl_video: {err_trace}")
            await interaction.edit_original_response(content=f"❌ An unexpected error occurred while processing:\n```\n{str(e)}\n```")
        finally:
            shutil.rmtree(req_dir, ignore_errors=True)

    @app_commands.command(name="photos", description="Download photos from a URL.")
    @app_commands.describe(url="The URL of the photos to download")
    @app_commands.checks.bot_has_permissions(send_messages=True, attach_files=True)
    async def dl_photos(self, interaction: discord.Interaction, url: str):
        # We start by sending a completely ephemeral message so we don't spam the chat with "Bot is thinking"
        await interaction.response.send_message(f"⏳ Starting background download...", ephemeral=True)
        
        req_id = f"temp_{uuid.uuid4().hex[:12]}"
        req_dir = os.path.join(TEMP_DIR, req_id)
        os.makedirs(req_dir, exist_ok=True)
        
        host = get_hostname(url)
        success = False
        error_msgs = []
        
        cmd = ["gallery-dl", "-d", req_dir, url]
        if os.path.exists(COOKIES_FILE):
            cmd.extend(["--cookies", COOKIES_FILE])
            
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, err = await process.communicate()
            if process.returncode == 0:
                success = True
            else:
                error_msgs.append(f"gallery-dl error: {err.decode('utf-8', errors='replace')}")
        except Exception as e:
            error_msgs.append(f"gallery-dl exception: {str(e)}")
            logger.error(f"gallery-dl execution failed: {e}", exc_info=True)
            
        if not success:
            if host in ['instagram.com', 'instagr.am']:
                success, err = await self.fallback_instaloader(url, req_dir)
                if not success:
                    error_msgs.append(f"Instaloader fallback error: {err}")
                    
        try:
            downloaded_photos = []
            for root, _, files in os.walk(req_dir):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        downloaded_photos.append(os.path.join(root, file))
                        
            if not downloaded_photos:
                err_text = "\n".join(error_msgs)[:1800] if error_msgs else "No supported images located after download."
                return await interaction.edit_original_response(content=f"❌ No photos were found or downloaded.\n**Logs:**\n```\n{err_text}\n```")
                
            # Log success history
            await DatabaseController.log_dl_history(str(interaction.guild_id), str(interaction.user.id), url, "photo")

            batch_size = 10
            for i in range(0, len(downloaded_photos), batch_size):
                batch_files = downloaded_photos[i:i+batch_size]
                discord_files = [discord.File(f) for f in batch_files]
                if i == 0:
                    # Send public channel notification
                    await interaction.channel.send(content=f"✅ {interaction.user.mention} Downloaded {len(downloaded_photos)} photo(s):", files=discord_files)
                    # Complete ephemeral
                    await interaction.edit_original_response(content="✅ Photos uploaded successfully!")
                else:
                    await interaction.channel.send(files=discord_files)
                
        except Exception as e:
            logger.error(f"Error serving photos: {e}", exc_info=True)
            await interaction.edit_original_response(content=f"❌ An error occurred: `{str(e)}`")
        finally:
            shutil.rmtree(req_dir, ignore_errors=True)

    @app_commands.command(name="history", description="View a paginated history of all downloaded URLs in the server.")
    async def dl_history(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        history = await DatabaseController.get_dl_history(str(interaction.guild_id))
        
        if not history:
            return await interaction.followup.send("No download history found in this server yet.")
            
        view = DLHistoryPaginator(history, self.bot)
        await interaction.followup.send(embed=await view.generate_embed(), view=view)

    @app_commands.command(name="cookies", description="Upload a cookies.txt file for yt-dlp/gallery-dl.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def dl_cookies(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith('.txt'):
            return await interaction.response.send_message("❌ Please upload a valid `.txt` file.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            await file.save(COOKIES_FILE)
            logger.info(f"Cookies file updated by {interaction.user}")
            await interaction.followup.send("✅ Cookies file successfully updated.", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Failed to save cookies: `{str(e)}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(DLCog(bot))