import discord
from discord.ext import commands, tasks
from database import DatabaseController

class RemindersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(minutes=30)  # Check for due reminders every 30 minutes
    async def check_reminders(self):
        # Wait until bot is fully loaded
        await self.bot.wait_until_ready()
        
        due_aids = await DatabaseController.get_due_reminders()
        for aid in due_aids:
            aid_id, guild_id, channel_id, user_id, req_amount, rec_amount, reason = aid
            
            # Fetch the channel
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                # Fetch role ping
                role_id = await DatabaseController.get_role(guild_id)
                role_ping = f"<@&{role_id}>" if role_id else ""
                
                # Build reminder embed
                embed = discord.Embed(
                    title=f"⏳ 24h Reminder: Aid Request #{aid_id} still active!", 
                    color=discord.Color.orange()
                )
                embed.add_field(name="Requester", value=f"<@{user_id}>", inline=False)
                embed.add_field(name="Progress", value=f"${rec_amount:.2f} / ${req_amount:.2f}", inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.set_footer(text=f"Use /sendaid {aid_id} <amount> to contribute!")
                
                try:
                    await channel.send(content=f"{role_ping} A community member is still looking for mutual aid!", embed=embed)
                except discord.Forbidden:
                    # Bot lacks permissions to send in this channel
                    pass
            
            # Reset the reminder timer for another 24 hours regardless of whether the send succeeded
            await DatabaseController.reset_reminder(aid_id)

async def setup(bot):
    await bot.add_cog(RemindersCog(bot))