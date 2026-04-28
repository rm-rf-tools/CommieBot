import discord
from discord import app_commands
from discord.ext import commands

class EmojiCog(commands.GroupCog, name="emoji"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    # ==========================================
    #             ADMIN COMMANDS
    # ==========================================

    @app_commands.command(name="pfp", description="Turns a user's profile picture into a server emoji")
    @app_commands.describe(
        member="The user whose avatar you want to steal (defaults to you)",
        emoji_name="Optional custom name for the new emoji"
    )
    @app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
    @app_commands.checks.bot_has_permissions(manage_emojis_and_stickers=True)
    async def emoji_pfp(self, interaction: discord.Interaction, member: discord.Member = None, emoji_name: str = None):
        # Defer because downloading/uploading images can take longer than the 3-second interaction limit
        await interaction.response.defer()

        target = member or interaction.user

        if not target.display_avatar:
            return await interaction.followup.send("❌ This user doesn't have an avatar.", ephemeral=True)

        # Sanitize the emoji name (Discord emojis can only contain alphanumeric chars and underscores)
        if not emoji_name:
            emoji_name = "".join(c for c in target.name if c.isalnum() or c == "_")
            if not emoji_name:
                emoji_name = "user_avatar"

        # Discord requires emoji names to be between 2 and 32 characters
        emoji_name = emoji_name[:32].ljust(2, "_")

        try:
            # Resize to 128x128 to guarantee it stays under Discord's 256kb file limit
            avatar_asset = target.display_avatar.replace(size=128)
            image_bytes = await avatar_asset.read()
            
            # Upload to the guild
            new_emoji = await interaction.guild.create_custom_emoji(name=emoji_name, image=image_bytes)
            
            await interaction.followup.send(f"✅ Successfully added {target.display_name}'s pfp as {new_emoji} (`:{new_emoji.name}:`)")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to manage emojis here.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed to create emoji. You may be out of emoji slots. (Error: {e.text})", ephemeral=True)

    # ==========================================
    #             ERROR HANDLING
    # ==========================================

    @emoji_pfp.error
    async def emoji_pfp_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need `Manage Emojis and Stickers` permission to use this.", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            await interaction.response.send_message("❌ I need the `Manage Emojis and Stickers` permission to do this.", ephemeral=True)
        else:
            # Log other errors or handle them accordingly
            pass

async def setup(bot):
    await bot.add_cog(EmojiCog(bot))