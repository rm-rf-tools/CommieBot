"""
filename: cogs/dl.py
description: Download videos and photos from various platforms using yt-dlp and gallery-dl. Features host-based fallbacks (like instaloader for Instagram) and automatically shrinks videos over 10MB using an FFmpeg subprocess implementation to safely fit within Discord's upload limits, optimized for iOS compatibility. Includes detailed error logging and strictly targets 10MB limits.
Views:
    - None
Commands:
    - /dl video <url>: Download a video from a URL. Prioritizes file size and mobile compatibility over raw quality. (User)
    - /dl photos <url>: Download photos from a URL. (User)
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
        await interaction.response.defer()
        
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
                return await interaction.followup.send(f"❌ Failed to download the video.\n**Logs:**\n```\n{err_text}\n```", ephemeral=True)
                
            media_files = [
                os.path.join(req_dir, f) for f in os.listdir(req_dir) 
                if f.lower().endswith(('.mp4', '.webm', '.mkv', '.mov', '.avi'))
            ]
            
            if not media_files:
                return await interaction.followup.send("❌ No valid video file found after a successful download execution.", ephemeral=True)
                
            media_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
            original_file = media_files[0]
            
            file_size_mb = os.path.getsize(original_file) / (1024 * 1024)
            logger.info(f"Original file downloaded: {file_size_mb:.2f}MB")
            
            # We enforce processing on EVERY video to guarantee iOS streaming compatibility (+faststart & strict h264)
            needs_shrink = file_size_mb > target_compression_mb
            
            if needs_shrink:
                await interaction.followup.send(f"⏳ Video is {file_size_mb:.1f}MB. Compressing to fit 10.0MB upload limit...", ephemeral=True)
            else:
                await interaction.followup.send(f"⏳ Processing video encoding...", ephemeral=True)
                
            processed_file = os.path.join(req_dir, f"processed_{req_id}.mp4")
            shrink_success, shrink_err = await process_video_ffmpeg(original_file, processed_file, target_mb=target_compression_mb, shrink=needs_shrink)
            
            if not shrink_success:
                err_trim = shrink_err[-1800:] if shrink_err else "Unknown FFmpeg error."
                logger.error(f"Compression failed completely: {err_trim}")
                return await interaction.followup.send(f"❌ Failed to process the video.\n**FFmpeg Error:**\n```\n{err_trim}\n```", ephemeral=True)
            
            if not os.path.exists(processed_file):
                logger.error("Compression reported success but output file missing.")
                return await interaction.followup.send("❌ Video compression succeeded but the output file is missing.", ephemeral=True)
                
            final_file = processed_file
                
            # Pre-upload check: Verify we are actually under the strict 10MB server limit
            final_file_size_mb = os.path.getsize(final_file) / (1024 * 1024)
            logger.info(f"Final file ready for upload: {final_file_size_mb:.2f}MB")

            if final_file_size_mb >= server_limit_mb:
                logger.error(f"Video compression insufficient. Final: {final_file_size_mb:.2f}MB, Limit: {server_limit_mb:.2f}MB")
                return await interaction.followup.send(
                    f"❌ The resulting video ({final_file_size_mb:.2f}MB) is still too large for this server's limit ({server_limit_mb:.2f}MB) after compression.", 
                    ephemeral=True
                )
                
            file = discord.File(final_file)
            try:
                await interaction.followup.send(content="✅ Here is your video:", file=file)
                logger.info(f"Successfully uploaded video for {url}")
            except discord.errors.HTTPException as e:
                if e.status == 413:
                    logger.error(f"Discord rejected the file payload (413). Size: {final_file_size_mb:.2f}MB")
                    await interaction.followup.send(
                        f"❌ Discord rejected the file (413 Payload Too Large). The compression didn't shrink it enough.\n"
                        f"Final Size: {final_file_size_mb:.2f}MB | Server Limit: {server_limit_mb:.2f}MB", 
                        ephemeral=True
                    )
                else:
                    raise

        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"Unexpected error in dl_video: {err_trace}")
            await interaction.followup.send(
                f"❌ An unexpected error occurred while processing:\n```\n{str(e)}\n```", 
                ephemeral=True
            )
        finally:
            shutil.rmtree(req_dir, ignore_errors=True)

    @app_commands.command(name="photos", description="Download photos from a URL.")
    @app_commands.describe(url="The URL of the photos to download")
    @app_commands.checks.bot_has_permissions(send_messages=True, attach_files=True)
    async def dl_photos(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        
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
                return await interaction.followup.send(f"❌ No photos were found or downloaded.\n**Logs:**\n```\n{err_text}\n```", ephemeral=True)
                
            batch_size = 10
            for i in range(0, len(downloaded_photos), batch_size):
                batch_files = downloaded_photos[i:i+batch_size]
                discord_files = [discord.File(f) for f in batch_files]
                if i == 0:
                    await interaction.followup.send(content=f"✅ Downloaded {len(downloaded_photos)} photo(s).", files=discord_files)
                else:
                    await interaction.channel.send(files=discord_files)
                
        except Exception as e:
            logger.error(f"Error serving photos: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred: `{str(e)}`", ephemeral=True)
        finally:
            shutil.rmtree(req_dir, ignore_errors=True)

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