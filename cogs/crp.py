# cogs/crp.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import List
from pydantic import BaseModel, field_validator, ValidationError
from enum import Enum

from database import DatabaseController

# ==========================================
# 1. PYDANTIC MODELS (Logic & Validation)
# ==========================================

class RoleType(str, Enum):
    OFFICER = "officer"
    DIRECTOR = "director"
    CHAIRMAN = "chairman"
    ADVISOR = "advisor"
    EXECUTOR = "executor"

class CommitteeAssignment(BaseModel):
    committee_name: str
    role: RoleType

class MemberRoles(BaseModel):
    """Used strictly to validate limits before saving to DB"""
    user_id: str
    assignments: List[CommitteeAssignment] = []

    @field_validator('assignments')
    @classmethod
    def validate_role_limits(cls, v: List[CommitteeAssignment]):
        officer_count = len([a for a in v if a.role == RoleType.OFFICER])
        director_count = len([a for a in v if a.role == RoleType.DIRECTOR])

        # Enforce your custom limits!
        if officer_count > 3:
            raise ValueError('A member cannot be an officer of more than 3 committees.')
        if director_count > 2:
            raise ValueError('A member cannot be a director of more than 2 committees.')
        
        # Check for exact duplicate assignments (e.g. Officer of Finance twice)
        seen = set()
        for a in v:
            identifier = f"{a.committee_name.lower()}_{a.role}"
            if identifier in seen:
                raise ValueError(f"Member is already a {a.role.value.title()} for {a.committee_name}.")
            seen.add(identifier)
            
        return v

# ==========================================
# 2. DISCORD COG
# ==========================================

class CRPCog(commands.GroupCog, name="crp"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__() # Initializes the command group

    @app_commands.command(name="assign", description="Assign a committee role to a member.")
    @app_commands.describe(
        target_user="The member to assign", 
        committee_name="Name of the committee",
        role="The role (officer, director, etc.)"
    )
    @app_commands.choices(role=[
        app_commands.Choice(name="Officer", value="officer"),
        app_commands.Choice(name="Director", value="director"),
        app_commands.Choice(name="Chairman", value="chairman"),
        app_commands.Choice(name="Advisor", value="advisor"),
        app_commands.Choice(name="Executor", value="executor")
    ])
    async def assign_role(self, interaction: discord.Interaction, target_user: discord.Member, committee_name: str, role: app_commands.Choice[str]):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        guild_id = str(interaction.guild_id)
        user_id = str(target_user.id)

        # 1. Fetch current roles from the SQLite Database
        current_rows = await DatabaseController.get_user_committee_roles(guild_id, user_id)
        
        # 2. Build the list for Pydantic validation
        assignments = [{"committee_name": row[0], "role": row[1]} for row in current_rows]
        
        # Add the NEW proposed role
        assignments.append({"committee_name": committee_name, "role": role.value})

        # 3. Pass through Pydantic to validate the limits
        try:
            MemberRoles(user_id=user_id, assignments=assignments)
        except ValidationError as e:
            # If Pydantic throws an error (e.g. 4th officer), catch it and warn user!
            error_msg = e.errors()[0]['msg']
            return await interaction.response.send_message(f"⚠️ **Cannot assign role:** {error_msg}", ephemeral=True)

        # 4. If Pydantic passed, it's safe. Save to Database!
        await DatabaseController.assign_committee_role(guild_id, user_id, committee_name, role.value)
        
        await interaction.response.send_message(
            f"✅ Successfully assigned {target_user.mention} as **{role.name}** for the **{committee_name}** committee."
        )

    @app_commands.command(name="view", description="View a member's committee roles.")
    async def view_roles(self, interaction: discord.Interaction, target_user: discord.Member = None):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        target_user = target_user or interaction.user
        rows = await DatabaseController.get_user_committee_roles(str(interaction.guild_id), str(target_user.id))

        if not rows:
            return await interaction.response.send_message(f"🔍 {target_user.display_name} has no committee roles.", ephemeral=True)

        embed = discord.Embed(title=f"Roles for {target_user.display_name}", color=discord.Color.blue())
        for committee_name, role_type in rows:
            embed.add_field(name=committee_name, value=role_type.title(), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list", description="List everyone in a specific committee.")
    async def list_committee(self, interaction: discord.Interaction, committee_name: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)

        rows = await DatabaseController.get_committee_members(str(interaction.guild_id), committee_name)

        if not rows:
            return await interaction.response.send_message(f"🔍 No members found for the **{committee_name}** committee.", ephemeral=True)

        embed = discord.Embed(title=f"Members of {committee_name.title()}", color=discord.Color.green())
        
        # Group members by their role type for a cleaner Discord embed display
        roles_dict = {}
        for user_id, role_type in rows:
            if role_type not in roles_dict:
                roles_dict[role_type] = []
            roles_dict[role_type].append(f"<@{user_id}>")

        # Display roles in the embed
        for role_type, members in roles_dict.items():
            embed.add_field(name=f"**{role_type.title()}s**", value="\n".join(members), inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(CRPCog(bot))