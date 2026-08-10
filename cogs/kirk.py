"""
filename: cogs/kirk.py
description: Deepfake integration using FaceFusion for headless face swapping (kirkifying) media.
Views:
    - KirkListPaginator: Handles pagination for displaying available source faces with First/Prev/Next/Last navigation.
Commands:
    - /kirkify media <source_face> <target_media>: Run FaceFusion headless to face swap a source face onto the target media. (User)
    - /kirkify roster add <name> <photo>: Add a new source face to the roster. (Admin: Manage Guild)
    - /kirkify roster delete <name>: Delete a source face from the roster. (Admin: Manage Guild)
    - /kirkify roster view: View all available source faces in a paginated list. (User)
    - /kirkify roster export: Export a CSV list of all available source faces. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import io
import csv
import uuid
import asyncio
import logging
import time

# --- Setup Logging ---
logger = logging.getLogger("Kirkify")
logger.setLevel(logging.INFO)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)

# Absolute paths internal to the Docker container
BASE_DIR = os.path.abspath("./data/kirk")
KIRK_IMAGES_DIR = os.path.join(BASE_DIR, "images")
KIRK_TEMP_DIR = os.path.join(BASE_DIR, "temp")

os.makedirs(KIRK_IMAGES_DIR, exist_ok=True)
os.makedirs(KIRK_TEMP_DIR, exist_ok=True)

async def read_stream_and_log(stream: asyncio.StreamReader, prefix: str, is_error: bool = False) -> str:
    """Reads an asyncio stream line by line, logs it, and returns the full text."""
    output = []
    while True:
        line = await stream.readline()
        if not line:
            break
        decoded_line = line.decode('utf-8', errors='replace').strip()
        if decoded_line:
            output.append(decoded_line)
            if is_error:
                logger.error(f"[{prefix}] {decoded_line}")
            else:
                logger.info(f"[{prefix}] {decoded_line}")
    return "\n".join(output)

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
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return float(stdout.decode('utf-8').strip())
    except Exception as e:
        logger.error(f"[FFprobe] Failed to get duration: {e}")
    return 0.0

async def shrink_video_ffmpeg(input_path: str, output_path: str, target_mb: float = 24.0) -> tuple[bool, str]:
    logger.info(f"Starting video compression to target {target_mb}MB...")
    duration = await get_video_duration(input_path)
    
    if duration <= 0:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-crf", "28", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k", "-f", "mp4", output_path
        ]
    else:
        total_bitrate_kbps = (target_mb * 8192) / duration
        audio_bitrate = 128
        video_bitrate = max(100, int(total_bitrate_kbps - audio_bitrate))
        
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-b:v", f"{video_bitrate}k",
            "-maxrate", f"{int(video_bitrate * 1.5)}k", "-bufsize", f"{video_bitrate * 2}k",
            "-preset", "fast",
            "-c:a", "aac", "-b:a", f"{audio_bitrate}k",
            "-f", "mp4", output_path
        ]
        
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        # Stream FFmpeg logs to prevent deadlocks
        _, stderr_text = await asyncio.gather(
            read_stream_and_log(proc.stdout, "FFmpeg"),
            read_stream_and_log(proc.stderr, "FFmpeg", is_error=True)
        )
        await proc.wait()
        
        if proc.returncode != 0:
            return False, stderr_text
        return True, ""
    except Exception as e:
        return False, str(e)

class KirkListPaginator(discord.ui.View):
    def __init__(self, items: list):
        super().__init__(timeout=300)
        self.items = items
        self.current_page = 0
        self.per_page = 15
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.items) - 1) // self.per_page)
        for child in self.children:
            if child.custom_id in ("first_btn", "prev_btn"):
                child.disabled = self.current_page == 0
            elif child.custom_id in ("next_btn", "last_btn"):
                child.disabled = self.current_page >= max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🎭 Available Source Faces", color=discord.Color.purple())
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.items[start:end]
        
        if not page_items:
            embed.description = "No source faces uploaded yet."
            return embed

        desc = ""
        for item in page_items:
            desc += f"• **{item}**\n"
        
        embed.description = desc
        max_pages = max(1, (len(self.items) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"Page {self.current_page + 1} of {max_pages} | Total: {len(self.items)}")
        return embed

    @discord.ui.button(label="⏮ First", style=discord.ButtonStyle.secondary, custom_id="first_btn")
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="next_btn")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Last ⏭", style=discord.ButtonStyle.primary, custom_id="last_btn")
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, (len(self.items) - 1) // self.per_page)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

class KirkifyCog(commands.GroupCog, name="kirkify"):
    def __init__(self, bot):
        self.bot = bot

    roster_group = app_commands.Group(name="roster", description="Manage the source face roster")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def face_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not os.path.exists(KIRK_IMAGES_DIR):
            return []
        files = os.listdir(KIRK_IMAGES_DIR)
        names = [f[:-4] for f in files if f.endswith(".png")]
        return [
            app_commands.Choice(name=n, value=n) 
            for n in names if current.lower() in n.lower()
        ][:25]

    async def send_or_fallback(self, interaction: discord.Interaction, status_message: discord.Message, content: str, file: discord.File = None):
        """Safely sends the final result, falling back to a channel message if the interaction timed out."""
        try:
            # Try to edit the original "Processing..." message
            if file:
                await interaction.followup.send(content=content, file=file)
                await status_message.delete()
            else:
                await status_message.edit(content=content)
        except (discord.NotFound, discord.HTTPException):
            logger.warning("Interaction token expired. Falling back to channel send.")
            # If the 15-minute token expired, fallback to sending it as a new message to the channel
            try:
                fallback_content = f"{interaction.user.mention} {content}"
                if file:
                    await interaction.channel.send(content=fallback_content, file=file)
                else:
                    await interaction.channel.send(content=fallback_content)
            except Exception as e:
                logger.error(f"Fallback send also failed: {e}")

    @app_commands.command(name="media", description="Face swap a source face onto the target media.")
    @app_commands.describe(source_face="The name of the source face to apply", target_media="The image or video to alter")
    @app_commands.autocomplete(source_face=face_autocomplete)
    async def kirkify_media(self, interaction: discord.Interaction, source_face: str, target_media: discord.Attachment):
        source_path = os.path.join(KIRK_IMAGES_DIR, f"{source_face}.png")
        if not os.path.exists(source_path):
            return await interaction.response.send_message(f"❌ Source face **{source_face}** not found.", ephemeral=True)

        await interaction.response.defer()
        
        status_message = await interaction.followup.send(
            "⏳ **Processing media...**\n"
            "This may take a while for videos", 
            wait=True
        )

        req_id = uuid.uuid4().hex[:8]
        ext = os.path.splitext(target_media.filename)[1].lower()
        target_path = os.path.join(KIRK_TEMP_DIR, f"{req_id}_target{ext}")
        output_path = os.path.join(KIRK_TEMP_DIR, f"{req_id}_output{ext}")
        shrunk_path = os.path.join(KIRK_TEMP_DIR, f"{req_id}_shrunk.mp4")

        start_time = time.time()

        try:
            logger.info(f"[{req_id}] Downloading target media: {target_media.filename}")
            await target_media.save(target_path)

            facefusion_script = "/app/facefusion/facefusion.py"
            if not os.path.exists(facefusion_script):
                return await self.send_or_fallback(interaction, status_message, "❌ Internal Path Error: The FaceFusion core script was not found in the container at `/app/facefusion/facefusion.py`.")

            cmd = [
                "python", facefusion_script, "headless-run",
                "--execution-providers", "cuda",
                "--processors", "face_swapper",
                "--face-swapper-model", "inswapper_128",
                "-s", source_path,
                "-t", target_path,
                "-o", output_path
            ]

            logger.info(f"[{req_id}] Starting FaceFusion Subprocess...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd="/app/facefusion",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Stream logs in real time to prevent deadlocks and allow developer monitoring
            _, stderr_text = await asyncio.gather(
                read_stream_and_log(process.stdout, "FaceFusion"),
                read_stream_and_log(process.stderr, "FaceFusion", is_error=True)
            )
            await process.wait()

            process_time = round(time.time() - start_time, 2)
            logger.info(f"[{req_id}] FaceFusion finished in {process_time}s with return code {process.returncode}")

            if process.returncode != 0:
                err_text = stderr_text[-1800:] if stderr_text else "No output provided."
                return await self.send_or_fallback(interaction, status_message, f"❌ FaceFusion encountered an error:\n```\n{err_text}\n```")

            if not os.path.exists(output_path):
                return await self.send_or_fallback(interaction, status_message, "❌ Output file was not generated by FaceFusion.")

            final_file = output_path
            is_video = ext in ('.mp4', '.webm', '.mov', '.avi', '.mkv')
            
            # Compress if needed
            if is_video and (os.path.getsize(output_path) / (1024 * 1024)) > 24.0:
                try:
                    await status_message.edit(content="⏳ Resulting video is large. Compressing to fit Discord upload limits...")
                except discord.NotFound:
                    pass # Message interaction expired, just continue
                    
                shrink_success, shrink_err = await shrink_video_ffmpeg(output_path, shrunk_path, target_mb=24.0)
                
                if shrink_success and os.path.exists(shrunk_path):
                    final_file = shrunk_path
                    logger.info(f"[{req_id}] Video shrunk successfully.")
                else:
                    return await self.send_or_fallback(interaction, status_message, f"❌ Video compression failed: {shrink_err}")

            if (os.path.getsize(final_file) / (1024 * 1024)) > 25.0:
                return await self.send_or_fallback(interaction, status_message, "❌ The resulting media is still over 25MB and cannot be uploaded to Discord.")

            logger.info(f"[{req_id}] Sending final payload to Discord...")
            file = discord.File(final_file, filename=f"kirkified_{source_face}{ext}")
            await self.send_or_fallback(interaction, status_message, f"✅ Successfully kirkified with **{source_face}**!", file)

        except Exception as e:
            logger.exception(f"[{req_id}] Unhandled Exception during kirkify_media:")
            await self.send_or_fallback(interaction, status_message, f"❌ An unexpected error occurred: `{e}`")
        finally:
            logger.info(f"[{req_id}] Cleaning up temporary files...")
            for p in [target_path, output_path, shrunk_path]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass

    @roster_group.command(name="add", description="Add a new source face to the roster.")
    @app_commands.describe(name="Name to save the face under", photo="Clear, front-facing image of the face")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def roster_add(self, interaction: discord.Interaction, name: str, photo: discord.Attachment):
        if not photo.content_type or not photo.content_type.startswith('image/'):
            return await interaction.response.send_message("❌ Please upload a valid image file.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            safe_name = name.strip().replace(" ", "_").lower()
            save_path = os.path.join(KIRK_IMAGES_DIR, f"{safe_name}.png")
            await photo.save(save_path)
            await interaction.followup.send(f"✅ Successfully saved source face **{safe_name}**.")
            logger.info(f"Added new source face: {safe_name}")
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to save image: {e}")

    @roster_group.command(name="delete", description="Delete a source face from the roster.")
    @app_commands.describe(name="The face to delete")
    @app_commands.autocomplete(name=face_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def roster_delete(self, interaction: discord.Interaction, name: str):
        safe_name = name.strip().replace(" ", "_").lower()
        file_path = os.path.join(KIRK_IMAGES_DIR, f"{safe_name}.png")

        if not os.path.exists(file_path):
            return await interaction.response.send_message(f"❌ Face **{name}** not found.", ephemeral=True)

        try:
            os.remove(file_path)
            await interaction.response.send_message(f"🗑️ Deleted source face **{name}**.", ephemeral=True)
            logger.info(f"Deleted source face: {safe_name}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to delete image: {e}", ephemeral=True)

    @roster_group.command(name="view", description="View all available source faces.")
    async def roster_view(self, interaction: discord.Interaction):
        await interaction.response.defer()
        files = os.listdir(KIRK_IMAGES_DIR)
        names = sorted([f[:-4] for f in files if f.endswith(".png")])
        
        if not names:
            return await interaction.followup.send("❌ No source faces have been uploaded yet.")

        view = KirkListPaginator(names)
        await interaction.followup.send(embed=view.generate_embed(), view=view)

    @roster_group.command(name="export", description="Export a CSV list of all available source faces.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def roster_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        files = os.listdir(KIRK_IMAGES_DIR)
        names = sorted([f[:-4] for f in files if f.endswith(".png")])
        
        if not names:
            return await interaction.followup.send("No faces found to export.")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "File Path"])
        
        for n in names:
            writer.writerow([n, f"{n}.png"])

        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename="kirk_faces_export.csv")
        await interaction.followup.send("✅ Export generated.", file=file)

async def setup(bot):
    await bot.add_cog(KirkifyCog(bot))