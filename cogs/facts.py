"""
filename: facts.py
description: Facts of the Day system for sharing and managing daily facts.
Views:
    - None
Commands:
    - /facts add <text>: Add a new fact of the day to the server. (Anyone)
    - /facts spawn: Randomly select and spawn a fact of the day in the configured channel. (Facts Role or Admin)
    - /facts delete <fact_id>: Delete a fact from the database. (Facts Role or Admin)
    - /facts set role <role>: Set the role that is allowed to edit facts and choose the channel. (Admin: Manage Guild)
    - /facts set channel <channel>: Set the channel where facts will be spawned. (Admin: Manage Guild)
    - /facts list export: Export all facts in the server to a CSV file. (Anyone)
    - /facts seed: Seed the database with 20 starting facts. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import csv
import io
import datetime
from db import DatabaseController

async def has_facts_permissions(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.manage_guild:
        return True
    
    role_id = await DatabaseController.get_facts_role(str(interaction.guild_id))
    if role_id and any(str(r.id) == role_id for r in interaction.user.roles):
        return True
    return False

def is_facts_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await has_facts_permissions(interaction):
            return True
        raise app_commands.CheckFailure("You do not have the required role to manage facts.")
    return app_commands.check(predicate)


class FactsCog(commands.GroupCog, name="facts"):
    def __init__(self, bot):
        self.bot = bot

    set_group = app_commands.Group(name="set", description="Configure facts system")
    list_group = app_commands.Group(name="list", description="List and export facts")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You need specific permissions to run this command.", ephemeral=True)
        elif isinstance(error, app_commands.CheckFailure):
            await send(f"❌ {error}", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    async def fact_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        facts = await DatabaseController.search_facts(str(interaction.guild_id), current)
        return [
            app_commands.Choice(name=f.content[:100], value=str(f.id))
            for f in facts
        ][:25]

    @app_commands.command(name="add", description="Add a new fact of the day to the server.")
    @app_commands.describe(text="The fact to add")
    async def facts_add(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        fact_id = await DatabaseController.add_fact(str(interaction.guild_id), text, str(interaction.user.id))
        await interaction.followup.send(f"✅ Added fact #{fact_id} to the database!")

    @app_commands.command(name="spawn", description="Randomly select and spawn a fact of the day.")
    @is_facts_admin()
    async def facts_spawn(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        channel_id = await DatabaseController.get_facts_channel(str(interaction.guild_id))
        if channel_id:
            channel = interaction.guild.get_channel(int(channel_id))
            if not channel:
                return await interaction.followup.send("❌ The configured facts channel no longer exists. Please update it.", ephemeral=True)
        else:
            channel = interaction.channel

        fact = await DatabaseController.get_random_fact(str(interaction.guild_id))
        if not fact:
            return await interaction.followup.send("❌ No facts found in the database. Use `/facts add` or `/facts seed`.", ephemeral=True)

        embed = discord.Embed(
            title="📚 Fact of the Day",
            description=fact.content,
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Fact #{fact.id}")

        if channel != interaction.channel:
            await channel.send(embed=embed)
            await interaction.followup.send(f"✅ Spawned a fact in {channel.mention}.", ephemeral=True)
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="delete", description="Delete a fact from the database.")
    @app_commands.describe(fact_id="The fact to delete")
    @app_commands.autocomplete(fact_id=fact_autocomplete)
    @is_facts_admin()
    async def facts_delete(self, interaction: discord.Interaction, fact_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            fid = int(fact_id)
        except ValueError:
            return await interaction.followup.send("❌ Invalid fact selected.")
            
        success = await DatabaseController.delete_fact(fid)
        if success:
            await interaction.followup.send("✅ Fact deleted successfully.")
        else:
            await interaction.followup.send("❌ Fact not found.")

    @set_group.command(name="role", description="Set the role allowed to edit facts and choose the channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_role(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_facts_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ Facts management role set to {role.mention}.", ephemeral=True)

    @set_group.command(name="channel", description="Set the channel where facts will be spawned.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await DatabaseController.set_facts_channel(str(interaction.guild_id), str(channel.id))
        await interaction.response.send_message(f"✅ Facts channel set to {channel.mention}.", ephemeral=True)

    @list_group.command(name="export", description="Export all facts in the server to a CSV file.")
    async def list_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        facts = await DatabaseController.get_all_facts(str(interaction.guild_id))
        
        if not facts:
            return await interaction.followup.send("No facts found to export.")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Content", "Added By"])
        
        for f in facts:
            writer.writerow([f.id, f.content, f.added_by])

        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"facts_export_{datetime.date.today()}.csv")
        await interaction.followup.send("✅ Export generated.", file=file)

    @app_commands.command(name="seed", description="Seed the database with 20 starting facts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def facts_seed(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        facts_list =[
            "The Paris Commune of 1871 was one of the first major examples of the working class taking power.",
            "Thomas Sankara, often called 'Africa's Che Guevara', vaccinated 2.5 million children in Burkina Faso.",
            "The USSR was the first country to launch a human, Yuri Gagarin, into space in 1961.",
            "The eight-hour workday was achieved after decades of struggle by labor unions and socialist organizers.",
            "Helen Keller was a radical socialist and a member of the Industrial Workers of the World (IWW).",
            "Albert Einstein wrote an essay titled 'Why Socialism?' advocating for a planned economy.",
            "The Black Panther Party created the Free Breakfast for School Children Program.",
            "Cuba has a higher life expectancy and lower infant mortality rate than the United States.",
            "May Day (International Workers' Day) commemorates the Haymarket affair in Chicago.",
            "Rosa Luxemburg was a prominent Marxist theorist and anti-war activist.",
            "During the Spanish Civil War, the anarcho-syndicalist CNT-FAI organized vast worker-controlled areas.",
            "Salvador Allende, democratically elected socialist president of Chile, was overthrown in a CIA-backed coup in 1973.",
            "Women in the Soviet Union were the first to win equal pay for equal work.",
            "The Zapatista Army of National Liberation (EZLN) has maintained autonomous indigenous control in Chiapas, Mexico since 1994.",
            "Fidel Castro survived over 600 assassination attempts orchestrated by the CIA.",
            "Vladimir Lenin led the October Revolution in 1917, establishing the first socialist state.",
            "Eugene V. Debs ran for President of the United States five times as a socialist, once from prison.",
            "In 1917, the Soviet Union became the first country to legalize abortion.",
            "Che Guevara was a key figure of the Cuban Revolution and fought against imperialism worldwide.",
            "The Kerala model in India demonstrates how communist-led state governments can achieve high human development indicators."
        ]
        
        count = 0
        bot_id = str(self.bot.user.id)
        guild_id = str(interaction.guild_id)
        
        for content in facts_list:
            await DatabaseController.add_fact(guild_id, content, bot_id)
            count += 1
            
        await interaction.followup.send(f"✅ Successfully seeded {count} facts into the database.")

async def setup(bot):
    await bot.add_cog(FactsCog(bot))