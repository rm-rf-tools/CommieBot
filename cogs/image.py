"""
filename: image.py
description: General image manipulation utilities including background removal.
Views:
    - None
Commands:
    - /image remove_bg <image>: Removes the background from the provided image. (User)
"""

import discord
from discord import app_commands
from discord.ext import commands
import io
import asyncio
from typing import Optional

def remove_background(image_bytes: bytes) -> bytes:
    try:
        from rembg import remove
        return remove(image_bytes)
    except ImportError:
        pass
        
    try:
        import withoutbg
        return withoutbg.remove(image_bytes)
    except Exception:
        raise RuntimeError("Background removal failed. No valid backend found.")

class ImageCog(commands.GroupCog, name="image"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    @app_commands.command(name="remove_bg", description="Remove the background from an image.")
    @app_commands.describe(image="The image you want to process")
    async def remove_bg(self, interaction: discord.Interaction, image: discord.Attachment):
        if not image.content_type or not image.content_type.startswith('image/'):
            return await interaction.response.send_message("❌ Please upload a valid image file.", ephemeral=True)

        await interaction.response.defer()

        try:
            input_bytes = await image.read()
            loop = asyncio.get_running_loop()
            
            bg_removed_bytes = await loop.run_in_executor(None, remove_background, input_bytes)
            
            output_file = discord.File(fp=io.BytesIO(bg_removed_bytes), filename="bg_removed.png")
            await interaction.followup.send(file=output_file)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to process the image: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ImageCog(bot))