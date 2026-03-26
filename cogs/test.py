
import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal
from database import DatabaseController
from cogs.mutual_aid import ContributionView 

class TestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="testaid", description="Admin testing utilities for the mutual aid bot.")
    @app_commands.describe(action="The test function to run", aid_id="The ID of the aid event")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testaid(self, interaction: discord.Interaction, action: Literal["reminder"], aid_id: int):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        # --- ACTION: REMINDER ---
        if action == "reminder":
            # Fetch full details of the specific aid request
            aid = await DatabaseController.get_aid_by_id(aid_id, str(interaction.guild_id))
            
            if not aid:
                return await interaction.response.send_message(f"❌ Could not find an active aid request with ID `{aid_id}`.", ephemeral=True)
            
            
            fetched_id, guild_id, channel_id, user_id, req_amount, rec_amount, description = aid
            
            role_id = await DatabaseController.get_role(guild_id)
            role_ping = f"<@&{role_id}>" if role_id else ""
            
            embed = discord.Embed(
                title=f"🧪 TEST 24h Reminder: Aid Request #{aid_id}", 
                color=discord.Color.purple()
            )
            embed.add_field(name="Requester", value=f"<@{user_id}>", inline=False)
            embed.add_field(name="Progress", value=f"${rec_amount:.2f} / ${req_amount:.2f}", inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            embed.set_footer(text=f"Click the button below or use /sendaid {aid_id} <amount> to contribute!")

            await interaction.response.send_message(
                content=f"*(Test Mode)* {role_ping} A community member is still looking for mutual aid!",
                embed=embed,
                view=ContributionView()
            )

async def setup(bot):
    await bot.add_cog(TestCog(bot))