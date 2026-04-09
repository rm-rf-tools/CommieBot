import discord
from discord.ext import commands
import aiosqlite
import datetime

class AttendanceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "org_database.db" # Point this to your SQLite file

    @commands.command(name="attendance", help="Takes attendance for your current voice channel. Usage: !attendance <event_id>")
    async def take_attendance(self, ctx, event_id: int):
        # 1. Ensure the person running the command is actually in a Voice Channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ You need to be in a voice channel to take attendance!")
            return

        voice_channel = ctx.author.voice.channel
        members_in_vc = voice_channel.members

        if not members_in_vc:
            await ctx.send("The voice channel is empty!")
            return

        # 2. Connect to the database and log attendance
        checked_in_count = 0
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        async with aiosqlite.connect(self.db_path) as db:
            # Optional: Check if the event actually exists first
            async with db.execute("SELECT id FROM events WHERE id = ?", (event_id,)) as cursor:
                if not await cursor.fetchone():
                    await ctx.send(f"❌ Event ID `{event_id}` does not exist in the database.")
                    return

            for member in members_in_vc:
                if member.bot:
                    continue  # We don't track bot attendance

                # Use INSERT OR REPLACE (SQLite) or UPSERT (Postgres) to avoid crashing if they already RSVP'd
                # This updates their status to 'Attended' and stamps the check-in time
                await db.execute("""
                    INSERT INTO event_attendance (event_id, member_id, attendance_status, check_in_time)
                    VALUES (?, ?, 'Attended', ?)
                    ON CONFLICT(event_id, member_id) 
                    DO UPDATE SET attendance_status = 'Attended', check_in_time = ?;
                """, (event_id, member.id, now, now))
                
                checked_in_count += 1

            await db.commit()

        await ctx.send(f"✅ **Attendance Logged!**\nChecked in **{checked_in_count}** members from `{voice_channel.name}` into Event #{event_id}.")
async def setup(bot):
    await bot.add_cog(AttendanceCog(bot))