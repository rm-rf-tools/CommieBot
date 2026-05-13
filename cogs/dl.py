"""
filename: dl.py
description: Download videos and photos from various platforms using yt-dlp and gallery-dl. Features host-based fallbacks (like instaloader for Instagram) and automatically shrinks videos over 10MB using a custom shrinker binary.
Views:
    - None
Commands:
    - /dl video <url>: Download a video from a URL. (User)
    - /dl photos <url>: Download photos from a URL. (User)
    - /dl cookies <file>: Upload a cookies.txt file for yt-dlp/gallery-dl to bypass login walls. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import shutil
import glob
import uuid
import yt_dlp
import re
from urllib.parse import urlparse

TEMP_DIR = "./data/dl_temp"
VIDEOS_DIR = "./videos"
COOKIES_FILE = "./data/cookies.txt"
SHRINKER_PATH = "./static/shrinker"

# Ensure directories exist
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)

def get_hostname(url: str) -> str:
    """Helper to extract the base domain name for fallback routing."""
    try:
        return urlparse(url).hostname.replace('www.', '')
    except:
        return ""

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
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def fallback_instaloader(self, url: str, dest_dir: str) -> tuple[bool, str]:
        """Fallback specifically for fetching Instagram content via instaloader."""
        match = re.search(r"(?:instagram\.com|instagr\.am)/(?:p|reel|tv)/([^/?#&]+)", url)
        if not match:
            return False, "Could not extract shortcode for instaloader."
            
        shortcode = match.group(1)
        
        # NOTE: Instaloader does not natively take standard Netscape cookie.txt files in CLI easily
        # So we run it unauthenticated as a pure fallback for public posts
        cmd =["instaloader", "--quiet", "--dirname-pattern", dest_dir, "--", f"-{shortcode}"]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                return True, ""
            return False, stderr.decode('utf-8')[:500]
        except Exception as e:
            return False, str(e)

    @app_commands.command(name="video", description="Download a video from a URL.")
    @app_commands.describe(url="The URL of the video to download")
    @app_commands.checks.bot_has_permissions(send_messages=True, attach_files=True)
    async def dl_video(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        
        req_id = uuid.uuid4().hex[:8]
        req_dir = os.path.join(TEMP_DIR, req_id)
        os.makedirs(req_dir, exist_ok=True)
        
        ydl_opts = {
            'outtmpl': os.path.join(req_dir, '%(title)s.%(ext)s'),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'restrictfilenames': True,  # Ensures yt-dlp normalizes output names heavily
            'quiet': True,
            'no_warnings': True,
        }
        
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            
        # ==========================================
        # DOWNLOAD FLOW ROUTING
        # ==========================================
        host = get_hostname(url)
        success = False
        error_msgs =[]
        
        try:
            # ATTEMPT 1: Primary Downloader (yt-dlp)
            loop = asyncio.get_running_loop()
            def extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
                    
            await loop.run_in_executor(None, extract)
            
            # Check if files actually downloaded
            if any(f.lower().endswith(('.mp4', '.webm', '.mkv', '.mov')) for f in os.listdir(req_dir)):
                success = True
            else:
                error_msgs.append("yt-dlp: No video files downloaded.")
        except Exception as e:
            error_msgs.append(f"yt-dlp: {str(e)[:200]}")
            
        # ATTEMPT 2: Fallbacks based on host
        if not success:
            if host in ['instagram.com', 'instagr.am']:
                await interaction.followup.send("⏳ yt-dlp failed, falling back to Instaloader for Instagram...", ephemeral=True)
                success, err = await self.fallback_instaloader(url, req_dir)
                if not success:
                    error_msgs.append(f"instaloader: {err}")
                
        # ==========================================
        
        try:
            if not success:
                return await interaction.followup.send(f"❌ Failed to download the video.\nErrors:\n" + "\n".join(error_msgs))
                
            # Locate the video file downloaded
            downloaded_videos =[os.path.join(req_dir, f) for f in os.listdir(req_dir) if f.lower().endswith(('.mp4', '.webm', '.mkv', '.mov'))]
            if not downloaded_videos:
                return await interaction.followup.send("❌ No video file found after successful download step.")
                
            orig_file = downloaded_videos[0]
            
            # Strip extension completely to ensure it's normalized to a-zA-Z0-9
            raw_ext = os.path.splitext(orig_file)[1].lower()
            clean_ext = re.sub(r'[^a-z0-9]', '', raw_ext) 
            
            # req_id is a hex UUID (strictly alphanumeric), fulfilling the strict naming constraint
            actual_file = os.path.join(req_dir, f"{req_id}.{clean_ext}")
            os.rename(orig_file, actual_file)
            
            file_size_mb = os.path.getsize(actual_file) / (1024 * 1024)
            final_file = actual_file
            
            # Auto-shrink if > 10MB
            if file_size_mb > 10:
                await interaction.followup.send(f"⏳ Video is {file_size_mb:.1f}MB, shrinking down to 9MB...", ephemeral=True)
                
                if not os.path.exists(SHRINKER_PATH):
                    return await interaction.followup.send(f"❌ Shrinker binary not found at `{SHRINKER_PATH}`.")
                    
                os.chmod(SHRINKER_PATH, 0o755)
                
                process = await asyncio.create_subprocess_exec(
                    SHRINKER_PATH, "-m", "9", actual_file,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    # FIX: Safely replace invalid encoding characters rather than throwing an Exception
                    error_msg = stderr.decode('utf-8', errors='replace')[:500] if stderr else "Unknown failure from shrinker."
                    return await interaction.followup.send(f"❌ Shrinker failed: ```\n{error_msg}\n```")
                
                # Verify the shrunk file was placed in ./videos/shrunk_<req_id>...
                possible_files = glob.glob(os.path.join(VIDEOS_DIR, f"shrunk_{req_id}.*"))
                if possible_files:
                    final_file = possible_files[0]
                else:
                    return await interaction.followup.send("❌ Could not locate the shrunk video output.")
                
            # Ensure it's under Discord's final 25MB limit just in case shrinker underperformed
            if os.path.getsize(final_file) > 25 * 1024 * 1024:
                return await interaction.followup.send("❌ Video is still too large for Discord even after shrinking.")
                
            file = discord.File(final_file)
            await interaction.followup.send(content=f"✅ Here is your video:", file=file)
            
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred while processing: {e}")
        finally:
            # Cleanup all temp files and shrunk files to prevent server bloat
            shutil.rmtree(req_dir, ignore_errors=True)
            for f in glob.glob(os.path.join(VIDEOS_DIR, f"shrunk_{req_id}.*")):
                try: os.remove(f)
                except: pass

    @app_commands.command(name="photos", description="Download photos from a URL.")
    @app_commands.describe(url="The URL of the photos to download")
    @app_commands.checks.bot_has_permissions(send_messages=True, attach_files=True)
    async def dl_photos(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        
        req_id = uuid.uuid4().hex[:8]
        req_dir = os.path.join(TEMP_DIR, req_id)
        os.makedirs(req_dir, exist_ok=True)
        
        # ==========================================
        # DOWNLOAD FLOW ROUTING
        # ==========================================
        host = get_hostname(url)
        success = False
        error_msgs =[]
        
        cmd = ["gallery-dl", "-d", req_dir, url]
        if os.path.exists(COOKIES_FILE):
            cmd.extend(["--cookies", COOKIES_FILE])
            
        # ATTEMPT 1: Primary Downloader (gallery-dl)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            out, err = await process.communicate()
            if process.returncode == 0:
                success = True
            else:
                error_msgs.append(f"gallery-dl: {err.decode('utf-8')[:200]}")
        except Exception as e:
            error_msgs.append(f"gallery-dl: {str(e)[:200]}")
            
        # ATTEMPT 2: Fallbacks based on host
        if not success:
            if host in ['instagram.com', 'instagr.am']:
                await interaction.followup.send("⏳ gallery-dl failed, falling back to Instaloader for Instagram...", ephemeral=True)
                success, err = await self.fallback_instaloader(url, req_dir)
                if not success:
                    error_msgs.append(f"instaloader: {err}")
        # ==========================================
        
        try:
            # Recursively find all photo files in the output directory regardless of success 
            # (sometimes gallery-dl throws errors but still downloads partial images)
            downloaded_photos =[]
            for root, _, files in os.walk(req_dir):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        downloaded_photos.append(os.path.join(root, file))
                        
            if not downloaded_photos:
                err_text = "\n".join(error_msgs) if error_msgs else "Unknown error."
                return await interaction.followup.send(f"❌ No photos were found/downloaded.\nErrors:\n```{err_text}```")
                
            # Batch send up to 10 at a time (Discord's attachment limit per message)
            batch_size = 10
            for i in range(0, len(downloaded_photos), batch_size):
                batch_files = downloaded_photos[i:i+batch_size]
                discord_files = [discord.File(f) for f in batch_files]
                if i == 0:
                    await interaction.followup.send(content=f"✅ Downloaded {len(downloaded_photos)} photo(s).", files=discord_files)
                else:
                    await interaction.channel.send(files=discord_files)
                
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred: {e}")
        finally:
            shutil.rmtree(req_dir, ignore_errors=True)

    @app_commands.command(name="cookies", description="Upload a cookies.txt file for yt-dlp/gallery-dl.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def dl_cookies(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith('.txt'):
            return await interaction.response.send_message("❌ Please upload a valid .txt file.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            await file.save(COOKIES_FILE)
            await interaction.followup.send("✅ Cookies file successfully updated.")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to save cookies: {e}")

async def setup(bot):
    await bot.add_cog(DLCog(bot))