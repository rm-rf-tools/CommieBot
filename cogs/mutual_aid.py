import discord
from discord import app_commands
from discord.ext import commands
import re
from database import DatabaseController

class ContributeModal(discord.ui.Modal, title='Log Contribution'):
    # Input popup
    amount_input = discord.ui.TextInput(
        label='Amount Sent ($)',
        placeholder='e.g. 15.50',
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(self, aid_id: int):
        super().__init__()
        self.aid_id = aid_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_amount = self.amount_input.value.strip().replace('$', '')
            amount = float(clean_amount)
        except ValueError:
            return await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)

        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        row = await DatabaseController.get_active_aid(self.aid_id, str(interaction.guild_id))
        if not row:
            return await interaction.response.send_message(f"❌ No active aid request found with ID `{self.aid_id}`.", ephemeral=True)

        req_amount, rec_amount, target_user_id = row
        new_total = rec_amount + amount

        if new_total >= req_amount:
            await DatabaseController.update_aid_progress(self.aid_id, new_total, status='completed')
            await interaction.response.send_message(
                f"🎉 **GOAL REACHED!** Aid request **#{self.aid_id}** for <@{target_user_id}> has reached its goal of ${req_amount:.2f} and has been removed from the queue! (Total raised: ${new_total:.2f})"
            )
        else:
            await DatabaseController.update_aid_progress(self.aid_id, new_total)
            await interaction.response.send_message(
                f"✅ Thank you! You logged a sent amount of ${amount:.2f} to aid **#{self.aid_id}**. Current progress: **${new_total:.2f} / ${req_amount:.2f}**."
            )

class ContributionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # timeout=None makes the button persistent across bot restarts!

    @discord.ui.button(label="💸 Log Contribution", style=discord.ButtonStyle.success, custom_id="persistent_contribute_btn")
    async def contribute_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Read the Aid ID directly from the text of the embed they clicked on
        embed = interaction.message.embeds[0]
        match = re.search(r'(?:ID:\s*|#)(\d+)', embed.title)
        
        if not match:
            return await interaction.response.send_message("❌ Could not determine the Aid ID from this message.", ephemeral=True)
        
        aid_id = int(match.group(1))
        # Launch the popup modal
        await interaction.response.send_modal(ContributeModal(aid_id=aid_id))

class MutualAidCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="requestaid", description="Create a new mutual aid request.")
    @app_commands.describe(amount="The monetary goal", description="Explain your need and add payment tags (Venmo, CashApp, etc.)")
    async def requestaid(self, interaction: discord.Interaction, amount: float, description: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

        aid_id = await DatabaseController.create_aid(str(interaction.guild_id), str(interaction.channel_id), str(interaction.user.id), amount, description)
        
        role_id = await DatabaseController.get_role(str(interaction.guild_id))
        role_ping = f"<@&{role_id}>" if role_id else "*(No ping role configured. Admins can use `/aidrole`)*"

        embed = discord.Embed(title=f"New Mutual Aid Request (ID: {aid_id})", color=discord.Color.blue())
        embed.add_field(name="Requester", value=interaction.user.mention, inline=False)
        embed.add_field(name="Goal", value=f"${amount:.2f}", inline=True)
        embed.add_field(name="Description", value=description, inline=False)
        embed.set_footer(text=f"Click the button below or use /sendaid {aid_id} <amount> to contribute!")
        # Attach the persistent view (the button) AND force the role ping
        await interaction.response.send_message(
            content=role_ping, 
            embed=embed, 
            view=ContributionView(),
            allowed_mentions=discord.AllowedMentions(roles=True)
        )

    @app_commands.command(name="sendaid", description="Log a contribution to an active aid request.")
    @app_commands.describe(aid_id="The ID of the aid event", amount="The amount you sent")
    async def sendaid(self, interaction: discord.Interaction, aid_id: int, amount: float):
        modal = ContributeModal(aid_id=aid_id)
        modal.amount_input.value = str(amount)
        await modal.on_submit(interaction)

    @app_commands.command(name="listaids", description="List all active mutual aid requests.")
    async def listaids(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        rows = await DatabaseController.get_all_active(str(interaction.guild_id))
        if not rows:
            return await interaction.response.send_message("There are currently no active aid requests in this server.", ephemeral=True)

        embed = discord.Embed(title="Active Mutual Aid Requests", color=discord.Color.green())
        for row in rows:
            aid_id, user_id, req_amount, rec_amount, description = row
            embed.add_field(
                name=f"ID: {aid_id} | User: <@{user_id}>",
                value=f"**Progress**: ${rec_amount:.2f} / ${req_amount:.2f}\n**Description**: {description}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    bot.add_view(ContributionView())
    await bot.add_cog(MutualAidCommands(bot))