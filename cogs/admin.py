import discord
from discord import app_commands
from discord.ext import commands
from database import DatabaseController

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="aidrole", description="Set the role to ping for new mutual aid requests (Admins).")
    @app_commands.describe(role="The server role to ping")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def aidrole(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        await DatabaseController.set_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ The mutual aid ping role has been successfully set to {role.mention}.", ephemeral=True)

    @app_commands.command(name="deleteaid", description="Delete a specific aid request (Requires Manage Messages).")
    @app_commands.describe(aid_id="The ID of the aid request to delete")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def deleteaid(self, interaction: discord.Interaction, aid_id: int):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        success = await DatabaseController.delete_aid(aid_id, str(interaction.guild_id))
        if not success:
            return await interaction.response.send_message(f"❌ Aid request #{aid_id} not found or is already inactive.", ephemeral=True)

        await interaction.response.send_message(f"🗑️ Aid request **#{aid_id}** has been manually deleted.")

    @app_commands.command(name="clearaids", description="Clear all active aid requests (Requires Manage Messages).")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearaids(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        await DatabaseController.clear_all(str(interaction.guild_id))
        await interaction.response.send_message("🚨 All active aid requests in this server have been cleared from the queue.")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))