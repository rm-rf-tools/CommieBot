"""
filename: attendance.py
description: Logs attendance for members currently in a voice or stage channel for a specific event.
Views:
    - None
Commands:
    - /attendance <event_name>: Log attendance for everyone currently in your voice channel. (User)
"""

import discord
from discord import app_commands
from discord.ext import commands
from db import DatabaseController

class AttendanceCog(commands.Cog, name="attendance"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="attendance", description="Log attendance for everyone currently in your voice channel.")
    @app_commands.describe(event_name="Name of the event or meeting to log")
    async def take_attendance(self, interaction: discord.Interaction, event_name: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        # Check if user is in a voice/stage channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ You need to be in a voice channel or stage to take attendance!", ephemeral=True)

        voice_channel = interaction.user.voice.channel
        vc_mention = voice_channel.mention
        # We don't need to connect. We can just sweep the 'members' property.
        # This prevents the WebSocket 4006 error and is instantaneous.
        attendees = [m for m in voice_channel.members if not m.bot]

        if not attendees:
            return await interaction.response.send_message(f"❌ No humans found in {vc_mention}!", ephemeral=True)

        # Defer because database operations might take a second
        await interaction.response.defer()

        try:
            # 1. Get or create the event ID
            event_id = await DatabaseController.get_or_create_event(str(interaction.guild_id), event_name)
            
            # 2. Log the user IDs
            user_ids = [str(m.id) for m in attendees]
            newly_added = await DatabaseController.log_attendance(event_id, user_ids)

            # 3. Build the response
            embed = discord.Embed(
                title="✅ Attendance Logged",
                description=f"Sweep completed for **{event_name}**.",
                color=discord.Color.green()
            )
            embed.add_field(name="Channel", value=voice_channel.mention, inline=True)
            embed.add_field(name="Total Found", value=str(len(attendees)), inline=True)
            embed.add_field(name="New Logins", value=str(newly_added), inline=True)

            # Mention attendees
            attendee_mentions = [m.mention for m in attendees]
            mentions_str = ", ".join(attendee_mentions)
            
            # Handle potential embed field limit (1024 chars)
            if len(mentions_str) > 1024:
                mentions_str = mentions_str[:1000] + "... (and more)"
                
            embed.add_field(name="Attendees Swept", value=mentions_str, inline=False)
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Attendance Error: {e}")
            await interaction.followup.send(f"❌ An error occurred while logging attendance: {e}")

async def setup(bot):
    await bot.add_cog(AttendanceCog(bot))
