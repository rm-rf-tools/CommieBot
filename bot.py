# bot.py
import os
import discord
from discord import app_commands
import aiosqlite
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DB_PATH = "./data/mutual_aid.db"

# Setup Discord Client with default intents
class MutualAidBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Initialize SQLite database
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            
            # 1. Create table for server-specific roles
            await db.execute('''
                CREATE TABLE IF NOT EXISTS server_configs (
                    guild_id TEXT PRIMARY KEY,
                    role_id TEXT
                )
            ''')

            # 2. Main aids table, now with guild_id included
            await db.execute('''
                CREATE TABLE IF NOT EXISTS aids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT,
                    amount_requested REAL,
                    amount_received REAL DEFAULT 0.0,
                    reason TEXT,
                    status TEXT DEFAULT 'active'
                )
            ''')

            # 3. Database Migration: Check if guild_id column exists (for older databases)
            async with db.execute("PRAGMA table_info(aids)") as cursor:
                columns = [col[1] for col in await cursor.fetchall()]
                if "guild_id" not in columns:
                    await db.execute("ALTER TABLE aids ADD COLUMN guild_id TEXT")
                    
            await db.commit()
        
        # Sync slash commands globally
        await self.tree.sync()
        print("Slash commands synced and database initialized.")

client = MutualAidBot()

# --- COMMANDS ---

@client.tree.command(name="aidrole", description="Set the role to ping for new mutual aid requests (Admins).")
@app_commands.describe(role="The server role to ping")
@app_commands.checks.has_permissions(manage_guild=True)
async def aidrole(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # INSERT OR REPLACE acts as an upsert (creates if new, updates if existing)
        await db.execute('''
            INSERT OR REPLACE INTO server_configs (guild_id, role_id)
            VALUES (?, ?)
        ''', (str(interaction.guild_id), str(role.id)))
        await db.commit()
    
    await interaction.response.send_message(f"✅ The mutual aid ping role has been successfully set to {role.mention}.", ephemeral=True)


@client.tree.command(name="requestaid", description="Create a new mutual aid request.")
@app_commands.describe(amount="The monetary goal you are requesting", reason="The reason for this request")
async def requestaid(interaction: discord.Interaction, amount: float, reason: str):
    if not interaction.guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # Fetch the server's configured role
        async with db.execute("SELECT role_id FROM server_configs WHERE guild_id = ?", (str(interaction.guild_id),)) as cursor:
            row = await cursor.fetchone()
            role_id = row[0] if row else None

        # Insert request with the guild_id
        cursor = await db.execute('''
            INSERT INTO aids (guild_id, user_id, amount_requested, reason)
            VALUES (?, ?, ?, ?)
        ''', (str(interaction.guild_id), str(interaction.user.id), amount, reason))
        await db.commit()
        aid_id = cursor.lastrowid

    # Ping the configured role or fallback to text if none is set
    role_ping = f"<@&{role_id}>" if role_id else "*(No ping role configured. Admins can use `/setrole`)*"
    
    embed = discord.Embed(title=f"New Mutual Aid Request (ID: {aid_id})", color=discord.Color.blue())
    embed.add_field(name="Requester", value=interaction.user.mention, inline=False)
    embed.add_field(name="Goal", value=f"${amount:.2f}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"Use /sendaid {aid_id} <amount> to contribute!")

    await interaction.response.send_message(content=role_ping, embed=embed)


@client.tree.command(name="sendaid", description="Log a contribution to an active aid request.")
@app_commands.describe(aid_id="The ID of the aid event", amount="The amount you sent")
async def sendaid(interaction: discord.Interaction, aid_id: int, amount: float):
    if not interaction.guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        # (guild_id IS NULL) allows older requests created before this update to still be processed
        async with db.execute('''
            SELECT amount_requested, amount_received, user_id 
            FROM aids 
            WHERE id = ? AND status = 'active' AND (guild_id = ? OR guild_id IS NULL)
        ''', (aid_id, str(interaction.guild_id))) as cursor:
            row = await cursor.fetchone()

        if not row:
            return await interaction.response.send_message(f"❌ No active aid request found with ID `{aid_id}` in this server.", ephemeral=True)

        req_amount, rec_amount, target_user_id = row
        new_total = rec_amount + amount

        if new_total >= req_amount:
            # Goal reached, mark as completed
            await db.execute("UPDATE aids SET amount_received = ?, status = 'completed' WHERE id = ?", (new_total, aid_id))
            await db.commit()
            await interaction.response.send_message(
                f"🎉 **GOAL REACHED!** Aid request **#{aid_id}** for <@{target_user_id}> has reached its goal of ${req_amount:.2f} and has been removed from the queue! (Total raised: ${new_total:.2f})"
            )
        else:
            # Goal not yet reached, update amount
            await db.execute("UPDATE aids SET amount_received = ? WHERE id = ?", (new_total, aid_id))
            await db.commit()
            await interaction.response.send_message(
                f"✅ Thank you! You logged a sent amount of ${amount:.2f} to aid **#{aid_id}**. Current progress: **${new_total:.2f} / ${req_amount:.2f}**."
            )


@client.tree.command(name="listaids", description="List all active mutual aid requests.")
async def listaids(interaction: discord.Interaction):
    if not interaction.guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT id, user_id, amount_requested, amount_received, reason 
            FROM aids 
            WHERE status = 'active' AND (guild_id = ? OR guild_id IS NULL)
        ''', (str(interaction.guild_id),)) as cursor:
            rows = await cursor.fetchall()

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


@client.tree.command(name="deleteaid", description="Delete a specific aid request (Requires Manage Messages).")
@app_commands.describe(aid_id="The ID of the aid request to delete")
@app_commands.checks.has_permissions(manage_messages=True)
async def deleteaid(interaction: discord.Interaction, aid_id: int):
    if not interaction.guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            SELECT id FROM aids 
            WHERE id = ? AND status = 'active' AND (guild_id = ? OR guild_id IS NULL)
        ''', (aid_id, str(interaction.guild_id)))
        if not await cursor.fetchone():
            return await interaction.response.send_message(f"❌ Aid request #{aid_id} not found in this server or is already inactive.", ephemeral=True)

        await db.execute("UPDATE aids SET status = 'deleted' WHERE id = ?", (aid_id,))
        await db.commit()

    await interaction.response.send_message(f"🗑️ Aid request **#{aid_id}** has been manually deleted.")


@client.tree.command(name="clearaids", description="Clear all active aid requests (Requires Manage Messages).")
@app_commands.checks.has_permissions(manage_messages=True)
async def clearaids(interaction: discord.Interaction):
    if not interaction.guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE aids SET status = 'deleted' 
            WHERE status = 'active' AND (guild_id = ? OR guild_id IS NULL)
        ''', (str(interaction.guild_id),))
        await db.commit()

    await interaction.response.send_message("🚨 All active aid requests in this server have been cleared from the queue.")

# Error handler for missing permissions
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        print(f"Error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')

if __name__ == '__main__':
    if not TOKEN:
        print("ERROR: DISCORD_TOKEN is not set in the .env file!")
    else:
        client.run(TOKEN)