"""
filename: grok.py
description: Automated reply system (Grok) that responds to mentions and keywords based on relevance scoring.
Views:
    - None
Commands:
    - /grok reply add <text> [category] [keywords] [intent]: Add a new automated reply. (Admin: Manage Messages)
    - /grok reply clear <confirm>: DELETE ALL Grok replies for this server. (Admin: Manage Guild)
    - /grok reply list: List all configured replies. (Admin: Manage Messages)
    - /grok reply delete <reply_id>: Delete a specific reply. (Admin: Manage Messages)
    - /grok json import <file>: Bulk import replies from a JSON file. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import random
import re
import json
from typing import Optional
from database import DatabaseController

class GrokCog(commands.GroupCog, name="grok"):
    def __init__(self, bot):
        self.bot = bot

    reply_group = app_commands.Group(name="reply", description="Manage Grok automated replies")
    json_group = app_commands.Group(name="json", description="Manage Grok JSON imports")

    def _score_reply(self, message_content: str, reply) -> int:
        """Calculates relevance based on keyword matches."""
        score = 0
        if not reply.keywords:
            return 0
            
        words_in_msg = set(re.findall(r'\w+', message_content.lower()))
        trigger_keywords = [kw.strip().lower() for kw in reply.keywords.split(',')]
        
        for kw in trigger_keywords:
            if kw in words_in_msg:
                score += 2  # Exact word match
            elif kw in message_content.lower():
                score += 1  # Partial phrase match
                
        return score

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Triggers: Mentions or specific names
        triggers = ["@grok", "@marx", "peoples ai", "people's ai", "commiebot"]
        msg_lower = message.content.lower()
        
        if any(trigger in msg_lower for trigger in triggers) or (self.bot.user in message.mentions):
            replies = await DatabaseController.get_grok_replies(str(message.guild.id))
            if not replies:
                return

            scored_replies = [(reply, self._score_reply(message.content, reply)) for reply in replies]
            max_score = max(score for _, score in scored_replies)
            
            if max_score > 0:
                best_candidates = [reply for reply, score in scored_replies if score == max_score]
            else:
                # Fallback to general category or random
                best_candidates = [r for r in replies if r.category.lower() == "general"] or replies

            chosen = random.choice(best_candidates)
            try:
                async with message.channel.typing():
                    await message.reply(chosen.reply_text)
            except discord.HTTPException:
                pass

    # --- AUTOCOMPLETE ---
    async def reply_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        replies = await DatabaseController.get_grok_replies(str(interaction.guild_id))
        return [
            app_commands.Choice(name=f"[{r.category}] {r.reply_text}"[:100], value=str(r.id))
            for r in replies if current.lower() in r.reply_text.lower()
        ][:25]

    # --- COMMANDS ---

    @reply_group.command(name="add", description="Add a new automated reply")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def reply_add(self, interaction: discord.Interaction, text: str, category: str = "general", keywords: Optional[str] = None, intent: str = "neutral"):
        await DatabaseController.add_grok_reply(str(interaction.guild_id), text, category, keywords, intent)
        await interaction.response.send_message(f"✅ Added reply to **{category}**.", ephemeral=True)

    @reply_group.command(name="clear", description="⚠️ DELETE ALL Grok replies for this server")
    @app_commands.describe(confirm="Must type 'CONFIRM' to wipe the database")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reply_clear(self, interaction: discord.Interaction, confirm: str):
        if confirm != "CONFIRM":
            return await interaction.response.send_message("❌ Action cancelled. You must type `CONFIRM` exactly.", ephemeral=True)
        
        await DatabaseController.clear_all_grok_replies(str(interaction.guild_id))
        await interaction.response.send_message("🗑️ **All Grok replies have been deleted.** The AI is now silent.", ephemeral=True)

    @reply_group.command(name="list", description="List all configured replies")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def reply_list(self, interaction: discord.Interaction):
        replies = await DatabaseController.get_grok_replies(str(interaction.guild_id))
        if not replies:
            return await interaction.response.send_message("No replies configured.", ephemeral=True)
            
        embed = discord.Embed(title="🤖 Grok Response Catalog", color=discord.Color.blue())
        for r in replies[:25]:
            embed.add_field(name=f"ID: {r.id} [{r.category}]", value=f"\"{r.reply_text[:100]}\"\nKeywords: `{r.keywords}`", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reply_group.command(name="delete", description="Delete a specific reply")
    @app_commands.autocomplete(reply_id=reply_autocomplete)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def reply_delete(self, interaction: discord.Interaction, reply_id: str):
        if await DatabaseController.delete_grok_reply(int(reply_id)):
            await interaction.response.send_message("✅ Reply deleted.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Reply not found.", ephemeral=True)

    @json_group.command(name="import", description="Bulk import replies from a JSON file")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def json_import(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith('.json'):
            return await interaction.response.send_message("❌ Must be a .json file.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            data = json.loads(await file.read())
            count = 0
            for item in data:
                if "text" in item:
                    await DatabaseController.add_grok_reply(
                        str(interaction.guild_id), 
                        item["text"], 
                        item.get("category", "general"), 
                        item.get("keywords"), 
                        item.get("intent", "neutral")
                    )
                    count += 1
            await interaction.followup.send(f"✅ Imported {count} replies.")
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

async def setup(bot):
    await bot.add_cog(GrokCog(bot))
