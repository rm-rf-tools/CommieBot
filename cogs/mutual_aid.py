import discord
from discord import app_commands
from discord.ext import commands
from database import DatabaseController

class MutualAidCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="requestaid", description="Create a new mutual aid request.")
    @app_commands.describe(amount="The monetary goal you are requesting", reason="The reason for this request")
    async def requestaid(self, interaction: discord.Interaction, amount: float, reason: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        # Create Aid in DB (with channel_id for reminders)
        aid_id = await DatabaseController.create_aid(str(interaction.guild_id), str(interaction.channel_id), str(interaction.user.id), amount, reason)
        
        # Determine Role Ping
        role_id = await DatabaseController.get_role(str(interaction.guild_id))
        role_ping = f"<@&{role_id}>" if role_id else "*(No ping role configured. Admins can use `/aidrole`)*"

        embed = discord.Embed(title=f"New Mutual Aid Request (ID: {aid_id})", color=discord.Color.blue())
        embed.add_field(name="Requester", value=interaction.user.mention, inline=False)
        embed.add_field(name="Goal", value=f"${amount:.2f}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Use /sendaid {aid_id} <amount> to contribute!")

        await interaction.response.send_message(content=role_ping, embed=embed)

    @app_commands.command(name="sendaid", description="Log a contribution to an active aid request.")
    @app_commands.describe(aid_id="The ID of the aid event", amount="The amount you sent")
    async def sendaid(self, interaction: discord.Interaction, aid_id: int, amount: float):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        row = await DatabaseController.get_active_aid(aid_id, str(interaction.guild_id))
        if not row:
            return await interaction.response.send_message(f"❌ No active aid request found with ID `{aid_id}` in this server.", ephemeral=True)

        req_amount, rec_amount, target_user_id = row
        new_total = rec_amount + amount

        if new_total >= req_amount:
            await DatabaseController.update_aid_progress(aid_id, new_total, status='completed')
            await interaction.response.send_message(
                f"🎉 **GOAL REACHED!** Aid request **#{aid_id}** for <@{target_user_id}> has reached its goal of ${req_amount:.2f} and has been removed from the queue! (Total raised: ${new_total:.2f})"
            )
        else:
            await DatabaseController.update_aid_progress(aid_id, new_total)
            await interaction.response.send_message(
                f"✅ Thank you! You logged a sent amount of ${amount:.2f} to aid **#{aid_id}**. Current progress: **${new_total:.2f} / ${req_amount:.2f}**."
            )

    @app_commands.command(name="listaids", description="List all active mutual aid requests.")
    async def listaids(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        rows = await DatabaseController.get_all_active(str(interaction.guild_id))
        if not rows:
            return await interaction.response.send_message("There are currently no active aid requests in this server.", ephemeral=True)

        embed = discord.Embed(title="Active Mutual Aid Requests", color=discord.Color.green())
        for row in rows:
            aid_id, user_id, req_amount, rec_amount, reason = row
            embed.add_field(
                name=f"ID: {aid_id} | User: <@{user_id}>",
                value=f"**Progress**: ${rec_amount:.2f} / ${req_amount:.2f}\n**Reason**: {reason}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MutualAidCommands(bot))