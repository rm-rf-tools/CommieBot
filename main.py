# main.py
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database import DatabaseController

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class MutualAidBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

        await DatabaseController.setup()
        
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.mutual_aid")
        await self.load_extension("cogs.reminders")
        await self.load_extension("cogs.test")
        await self.load_extension("cogs.quotemaker")

        
        # 3. Sync Slash Commands
        await self.tree.sync()
        print("Slash commands synced and database initialized.")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

client = MutualAidBot()

@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        print(f"Error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

if __name__ == '__main__':
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN is not set in the .env file!")
    else:
        client.run(TOKEN)