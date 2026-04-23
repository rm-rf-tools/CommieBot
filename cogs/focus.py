import discord
from discord import app_commands
from discord.ext import commands
from typing import Union
from database import DatabaseController

class FocusCog(commands.GroupCog, name="focus"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    role_group = app_commands.Group(name="role", description="Focus role configuration")
    channel_group = app_commands.Group(name="channel", description="Focus channel configuration")

    # ==========================================
    #             USER COMMANDS
    # ==========================================

    @app_commands.command(name="toggle", description="Enable or disable Focus Mode")
    @app_commands.describe(enable="True to enter Focus Mode, False to leave")
    async def focus_toggle(self, interaction: discord.Interaction, enable: bool):
        guild_id = str(interaction.guild_id)
        role_id = await DatabaseController.get_focus_role(guild_id)

        if not role_id:
            return await interaction.response.send_message("❌ Focus Mode has not been configured by an admin yet.", ephemeral=True)

        focus_role = interaction.guild.get_role(int(role_id))
        if not focus_role:
            return await interaction.response.send_message("❌ The configured Focus Role could not be found. Let a moderator know.", ephemeral=True)

        # Check if the user is a server admin (focus mode won't work properly for admins because Discord bypasses restrictions)
        if interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⚠️ You are an Administrator! Focus mode cannot hide channels from you due to Discord limitations.", ephemeral=True)

        try:
            if enable:
                if focus_role in interaction.user.roles:
                    return await interaction.response.send_message("You are already in Focus Mode.", ephemeral=True)
                await interaction.user.add_roles(focus_role, reason="User toggled Focus Mode ON")
                await interaction.response.send_message("🧘 **Focus Mode Enabled.** Distractions hidden.", ephemeral=True)
            else:
                if focus_role not in interaction.user.roles:
                    return await interaction.response.send_message("You are not currently in Focus Mode.", ephemeral=True)
                await interaction.user.remove_roles(focus_role, reason="User toggled Focus Mode OFF")
                await interaction.response.send_message("👋 **Focus Mode Disabled.** Welcome back.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles. Ensure my bot role is higher than the Focus role.", ephemeral=True)

    # ==========================================
    #             ADMIN COMMANDS
    # ==========================================

    @role_group.command(name="set", description="Set the Focus Mode role")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def focus_role_set(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_focus_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ Focus role set to {role.mention}.", ephemeral=True)

    @role_group.command(name="remove", description="Remove the Focus Mode role configuration")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def focus_role_remove(self, interaction: discord.Interaction):
        await DatabaseController.set_focus_role(str(interaction.guild_id), None)
        await interaction.response.send_message("✅ Focus role configuration removed.", ephemeral=True)

    @channel_group.command(name="add", description="Add a channel to the allowed Focus Mode list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def focus_channel_add(self, interaction: discord.Interaction, channel: Union[discord.abc.GuildChannel, discord.Thread]):
        guild_id = str(interaction.guild_id)
        role_id = await DatabaseController.get_focus_role(guild_id)

        # Handle threads by targeting their parent channel
        if isinstance(channel, discord.Thread):
            target_channel = channel.parent
            msg = f"⚠️ Discord doesn't allow permissions directly on threads. I added its parent channel {target_channel.mention} instead."
        else:
            target_channel = channel
            msg = f"✅ Added {target_channel.mention} to focus channels."

        await DatabaseController.add_focus_channel(guild_id, str(target_channel.id))
        
        # If the role is configured, apply the explicit allow overwrite
        if role_id:
            focus_role = interaction.guild.get_role(int(role_id))
            if focus_role:
                try:
                    await target_channel.set_permissions(focus_role, view_channel=True)
                except discord.Forbidden:
                    msg += "\n*(Warning: I lack permissions to edit this channel's settings!)*"

        await interaction.response.send_message(msg, ephemeral=True)

    @channel_group.command(name="remove", description="Remove a channel from the allowed Focus Mode list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def focus_channel_remove(self, interaction: discord.Interaction, channel: Union[discord.abc.GuildChannel, discord.Thread]):
        guild_id = str(interaction.guild_id)
        role_id = await DatabaseController.get_focus_role(guild_id)

        if isinstance(channel, discord.Thread):
            target_channel = channel.parent
            msg = f"⚠️ Threads inherit permissions. I removed its parent channel {target_channel.mention} instead."
        else:
            target_channel = channel
            msg = f"✅ Removed {target_channel.mention} from focus channels."

        await DatabaseController.remove_focus_channel(guild_id, str(target_channel.id))

        # If the role is configured, apply the explicit deny overwrite
        if role_id:
            focus_role = interaction.guild.get_role(int(role_id))
            if focus_role:
                try:
                    await target_channel.set_permissions(focus_role, view_channel=False)
                except discord.Forbidden:
                    msg += "\n*(Warning: I lack permissions to edit this channel's settings!)*"

        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="sync", description="Automatically configure all server channel permissions for Focus Mode")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def focus_sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild_id = str(interaction.guild_id)
        role_id = await DatabaseController.get_focus_role(guild_id)

        if not role_id:
            return await interaction.followup.send("❌ You need to set the Focus Role first using `/focus role set`.")

        focus_role = interaction.guild.get_role(int(role_id))
        if not focus_role:
            return await interaction.followup.send("❌ Focus role not found in server.")

        focus_channels = await DatabaseController.get_focus_channels(guild_id)
        updates = 0

        # Loop through all categories, text, voice, and forum channels
        for channel in interaction.guild.channels:
            try:
                if str(channel.id) in focus_channels:
                    # Allow explicitly
                    await channel.set_permissions(focus_role, view_channel=True)
                else:
                    # Deny explicitly - This overrides the @everyone view permission!
                    await channel.set_permissions(focus_role, view_channel=False)
                updates += 1
            except discord.Forbidden:
                pass # Bot lacks permission to edit this specific channel

        await interaction.followup.send(f"✅ Sync complete! Evaluated and updated overrides on {updates} channels/categories.")

async def setup(bot):
    await bot.add_cog(FocusCog(bot))