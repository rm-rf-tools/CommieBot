"""
filename: transcribe.py
description: Voice Note and audio file transcription using GPU-accelerated faster-whisper.
Views:
    - TranscribePromptView: Button interface sent in reply to voice notes allowing the creator to approve or dismiss transcription.
Commands:
    - /transcribe settings <mode>: Set your personal preference for how transcriptions are sent (chunked messages, txt file, or both). (User)
    - /transcribe file <audio_file>: Directly transcribe an uploaded audio or video file. (User)
    - Message Context Menu "Transcribe Audio": Right click any message with an audio attachment to instantly transcribe it. (User)
"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import io
import uuid
import asyncio
import logging
from faster_whisper import WhisperModel

from db import DatabaseController

logger = logging.getLogger("TranscribeCog")
logger.setLevel(logging.INFO)

TEMP_DIR = "./data/transcribe_temp"
os.makedirs(TEMP_DIR, exist_ok=True)

class TranscribePromptView(discord.ui.View):
    def __init__(self, cog, vn_message: discord.Message):
        super().__init__(timeout=300)
        self.cog = cog
        self.vn_message = vn_message
        self.prompt_msg = None

    async def on_timeout(self):
        if self.prompt_msg:
            try:
                await self.prompt_msg.delete()
            except discord.NotFound:
                pass

    @discord.ui.button(label="Transcribe", style=discord.ButtonStyle.primary, emoji="📝")
    async def transcribe_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.vn_message.author.id:
            return await interaction.response.send_message("❌ Only the creator of the Voice Note can authorize this.", ephemeral=True)
        
        await interaction.response.send_message("⏳ **Transcribing Voice Note...**", ephemeral=True)
        
        # Immediately clean up the prompt message
        if self.prompt_msg:
            try: await self.prompt_msg.delete()
            except: pass
            
        await self.cog.process_transcription(interaction, self.vn_message.attachments[0], original_msg=self.vn_message)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def dismiss_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.vn_message.author.id:
            return await interaction.response.send_message("❌ Only the creator of the Voice Note can dismiss this.", ephemeral=True)
        
        if self.prompt_msg:
            try: await self.prompt_msg.delete()
            except: pass
        await interaction.response.defer()


class TranscribeCog(commands.GroupCog, name="transcribe"):
    def __init__(self, bot):
        self.bot = bot
        # Loaded into VRAM on cog initialization. 
        # "medium" strikes a perfect balance of blazing speed and high accuracy for a 3090.
        logger.info("Loading Whisper Model into VRAM...")
        try:
            self.model = WhisperModel("medium", device="cuda", compute_type="float16")
            logger.info("Whisper Model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Whisper Model: {e}")
            self.model = None

        # Register Message Context Menu
        self.ctx_menu = app_commands.ContextMenu(
            name="Transcribe Audio",
            callback=self.transcribe_context
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        else:
            logger.error(f"Transcribe Error: {error}")
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    def _run_whisper_sync(self, file_path: str) -> str:
        """Blocking whisper transcription call."""
        if not self.model:
            raise RuntimeError("Whisper model is not loaded.")
        
        segments, _ = self.model.transcribe(file_path, beam_size=5)
        return "".join(segment.text for segment in segments)

    async def process_transcription(self, interaction: discord.Interaction, attachment: discord.Attachment, original_msg: discord.Message = None):
        """Core logic to download, transcribe, and distribute the text."""
        file_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}_{attachment.filename}")
        
        try:
            # 1. Download
            await attachment.save(file_path)
            
            # 2. Transcribe in executor to avoid blocking Discord bot loop
            loop = asyncio.get_running_loop()
            transcription = await loop.run_in_executor(None, self._run_whisper_sync, file_path)
            transcription = transcription.strip()
            
            if not transcription:
                return await interaction.followup.send("❌ No speech could be detected in this audio.", ephemeral=True)

            # 3. Fetch user settings
            mode = await DatabaseController.get_transcribe_setting(str(interaction.user.id))
            
            header = f"🎙️ **Transcription for {interaction.user.mention}:**\n"
            
            # 4. Chunk & Deliver based on settings
            if mode in ["chunk", "both"]:
                # 1900 chars to safely accommodate the header and formatting
                chunks = [transcription[i:i+1900] for i in range(0, len(transcription), 1900)]
                for i, chunk in enumerate(chunks):
                    # Reply directly to the original voice note if possible
                    prefix = header if i == 0 else ""
                    if original_msg:
                        await original_msg.reply(f"{prefix}> {chunk}", mention_author=False)
                    else:
                        await interaction.followup.send(f"{prefix}> {chunk}")

            if mode in ["file", "both"]:
                file = discord.File(io.BytesIO(transcription.encode("utf-8")), filename="transcription.txt")
                if original_msg and mode == "file":
                    await original_msg.reply(content=header, file=file, mention_author=False)
                else:
                    await interaction.followup.send(content=header if mode == "file" else None, file=file)

            if interaction.response.is_done() and mode != "file" and not original_msg:
                pass # Already handled via followup

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Transcription failed: `{e}`", ephemeral=True)
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Check if the message is a Voice Note (Discord specifically flags them)
        if message.flags.voice or (message.attachments and message.attachments[0].filename.endswith('.ogg') and message.attachments[0].is_voice_message()):
            
            # Send prompt
            view = TranscribePromptView(self, message)
            try:
                prompt_msg = await message.reply(
                    f"🎙️ {message.author.mention}, would you like to transcribe this Voice Note?", 
                    view=view,
                    mention_author=False
                )
                view.prompt_msg = prompt_msg
            except discord.HTTPException:
                pass

    @app_commands.command(name="settings", description="Configure how your transcriptions are returned.")
    @app_commands.describe(mode="How do you want to receive transcriptions?")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Chunked Text Messages (Default)", value="chunk"),
        app_commands.Choice(name="Text File (.txt)", value="file"),
        app_commands.Choice(name="Both", value="both")
    ])
    async def transcribe_settings(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        await DatabaseController.set_transcribe_setting(str(interaction.user.id), mode.value)
        await interaction.response.send_message(f"✅ Your transcription preference has been updated to: **{mode.name}**", ephemeral=True)

    @app_commands.command(name="file", description="Directly transcribe an audio or video file.")
    @app_commands.describe(audio_file="The audio or video file to transcribe")
    async def transcribe_file(self, interaction: discord.Interaction, audio_file: discord.Attachment):
        if not audio_file.content_type or not any(ext in audio_file.content_type for ext in ['audio', 'video']):
            return await interaction.response.send_message("❌ Please upload a valid audio or video file.", ephemeral=True)
            
        await interaction.response.send_message("⏳ **Processing uploaded file...**", ephemeral=True)
        await self.process_transcription(interaction, audio_file)

    async def transcribe_context(self, interaction: discord.Interaction, message: discord.Message):
        """Context menu command to transcribe an audio file on a message."""
        if not message.attachments:
            return await interaction.response.send_message("❌ This message has no attachments to transcribe.", ephemeral=True)
            
        attachment = message.attachments[0]
        if not attachment.content_type or not any(ext in attachment.content_type for ext in ['audio', 'video']):
            return await interaction.response.send_message("❌ This attachment is not a valid audio or video file.", ephemeral=True)

        await interaction.response.send_message("⏳ **Transcribing selected message...**", ephemeral=True)
        await self.process_transcription(interaction, attachment, original_msg=message)


async def setup(bot):
    await bot.add_cog(TranscribeCog(bot))