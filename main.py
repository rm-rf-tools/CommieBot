"""main.py"""

import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from db import DatabaseController

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class MutualAidBot(commands.Bot):
    def __init__(self):

        intents = discord.Intents.default()
        intents.message_content = True 
        intents.members = True 
        
        super().__init__(command_prefix="!", intents=intents)
        
    async def setup_hook(self):
        await DatabaseController.setup()
        
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.mutual_aid")
        await self.load_extension("cogs.reminders")
        await self.load_extension("cogs.test")
        await self.load_extension("cogs.quotemaker")
        await self.load_extension("cogs.attendance")
        await self.load_extension("cogs.crp")
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.skills") 
        await self.load_extension("cogs.aipac")
        await self.load_extension("cogs.forms")
        await self.load_extension("cogs.modlogs")
        await self.load_extension("cogs.focus")
        await self.load_extension("cogs.grok")
        await self.load_extension("cogs.tracking")
        await self.load_extension("cogs.emoji")
        await self.load_extension("cogs.clone")
        await self.load_extension("cogs.film")
        await self.load_extension("cogs.roles")
        await self.load_extension("cogs.ml_resources")
        await self.load_extension("cogs.dl") 
        await self.load_extension("cogs.kirk") 
        await self.load_extension("cogs.music") 
        await self.load_extension("cogs.mock_reddit")
        # await self.load_extension("cogs.gamba")
        await self.load_extension("cogs.transcribe")
        await self.load_extension("cogs.image")
        await self.load_extension("cogs.qotd")

        # await self.load_extension("cogs.facts") 

        
        await self.tree.sync()
        print("Slash commands synced and database initialized.")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

client = MutualAidBot()
        
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        return await interaction.response.send_message("❌ You do not have the required role to use this command.", ephemeral=True)


    if isinstance(error, app_commands.MissingPermissions):
        return await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)

    print(f"Error: {error}")
    if not interaction.response.is_done():
        try:
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)
        except:
            pass

if __name__ == '__main__':
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN is not set in the .env file!")
    else:
        client.run(TOKEN)