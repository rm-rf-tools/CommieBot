"""
filename: secret.py
description: Secret messaging system allowing users to post completely hidden messages to a configured channel via a persistent UI button.
Views:
    - SecretSubmitView: Persistent view containing the 'Send Secret Message' trigger button.
    - SecretSubmitModal: Modal for users to type and submit their secret text.
Commands:
    - /secret button: Deploy the persistent 'Send Secret Message' button to a channel. (Admin: Manage Guild)
    - /secret channel <channel>: Set the channel where secret messages will be posted. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
from db import DatabaseController


class SecretSubmitModal(discord.ui.Modal, title="Secret Message"):
    message_text = discord.ui.TextInput(
        label="Your Message",
        style=discord.TextStyle.paragraph,
        placeholder="Type your secret message here. Nobody will know it was you...",
        required=True,
        max_length=3000
    )

    async def on_submit(self, interaction: discord.Interaction):
        channel_id = await DatabaseController.get_secret_channel(str(interaction.guild_id))
        
        if not channel_id:
            return await interaction.response.send_message(
                "❌ The secret channel hasn't been set up yet. An admin needs to run `/secret channel` first.", 
                ephemeral=True
            )
        
        target_channel = interaction.guild.get_channel(int(channel_id))
        if not target_channel:
            return await interaction.response.send_message(
                "❌ The configured secret message channel could not be found. It may have been deleted.", 
                ephemeral=True
            )
        
        embed = discord.Embed(
            title="Secret Message",
            description=self.message_text.value.strip(),
            color=discord.Color.dark_grey(),
            timestamp=discord.utils.utcnow()
        )
        
        try:
            await target_channel.send(embed=embed)
            await interaction.response.send_message("Secret message sent!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I do not have permission to post messages or embeds in the configured secret channel.", 
                ephemeral=True
            )


class SecretSubmitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🕵️ Send Secret Message", style=discord.ButtonStyle.secondary, custom_id="persistent_secret_submit_btn")
    async def submit_secret(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SecretSubmitModal())


class SecretCog(commands.GroupCog, name="secret"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    @app_commands.command(name="button", description="Create a permanent button for users to submit secret messages.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def secret_button(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Send Secret Message", 
            description="Send a secret message\n", 
            color=discord.Color.dark_grey()
        )
        await interaction.channel.send(embed=embed, view=SecretSubmitView())
        await interaction.response.send_message("Button generated successfully.", ephemeral=True)

    @app_commands.command(name="channel", description="Set the secret message channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def secret_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await DatabaseController.set_secret_channel(str(interaction.guild_id), str(channel.id))
        await interaction.response.send_message(f"✅ Secret messages will now be posted in {channel.mention}.", ephemeral=True)


async def setup(bot):
    bot.add_view(SecretSubmitView())
    await bot.add_cog(SecretCog(bot))