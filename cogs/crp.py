"""
filename: crp.py
description: Committee Role Management (CRP) for managing organizational hierarchies and committee assignments.
Views:
    - None
Commands:
    - /crp setup setup <role>: Set the role allowed to manage CRP. (Admin: Manage Guild)
    - /crp committee create <name> [description]: Create a new committee. (CRP Management)
    - /crp committee edit <old_name> <new_name>: Rename an existing committee. (CRP Management)
    - /crp committee remove <name>: Delete a committee. (CRP Management)
    - /crp committee list: List all committees. (CRP Management)
    - /crp role assign <target> <role> [committee_name]: Assign a role to a member. (CRP Management)
    - /crp role remove <target> <role> [committee_name]: Remove a specific role. (CRP Management)
    - /crp role view [target]: View a member's current roles. (CRP Management)
    - /crp role list <committee_name>: List members in a committee. (CRP Management)
    - /crp role listall: Full Org Hierarchy. (CRP Management)
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from pydantic import BaseModel, field_validator, ValidationError
from enum import Enum

from db import DatabaseController


class RoleType(str, Enum):
    CHAIRMAN = "chairman"
    EXECUTOR = "executor"
    DIRECTOR = "director"
    ADVISOR = "advisor"
    OFFICER = "officer"
    MEMBER = "member"
    ASSISTANT = "assistant"

ROLE_WEIGHT = {
    "chairman": 1, "executor": 2, "director": 3, 
    "advisor": 4, "officer": 5, "member": 6, "assistant": 7
}

# Roles that REQUIRE a committee selection
COMMITTEE_ROLES = [RoleType.DIRECTOR, RoleType.ADVISOR, RoleType.OFFICER, RoleType.ASSISTANT]

class CommitteeAssignment(BaseModel):
    committee_name: str 
    role: RoleType

class MemberRoles(BaseModel):
    user_id: str
    assignments: List[CommitteeAssignment] = []

    @field_validator('assignments')
    @classmethod
    def validate_role_limits(cls, v: List[CommitteeAssignment]):
        officer_count = len([a for a in v if a.role == RoleType.OFFICER])
        director_count = len([a for a in v if a.role == RoleType.DIRECTOR])

        if officer_count > 3:
            raise ValueError('A member cannot be an officer of more than 3 committees.')
        if director_count > 2:
            raise ValueError('A member cannot be a director of more than 2 committees.')
        
        seen = set()
        for a in v:
            identifier = f"{a.committee_name.lower()}_{a.role}"
            if identifier in seen:
                raise ValueError(f"Member is already a {a.role.value.title()} for {a.committee_name}.")
            seen.add(identifier)
        return v


async def has_crp_permissions(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    
    role_id = await DatabaseController.get_crp_role(str(interaction.guild_id))
    if not role_id:

        return False
        
    user_role_ids = [str(r.id) for r in interaction.user.roles]
    return role_id in user_role_ids


class CRPCog(commands.GroupCog, name="crp"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await has_crp_permissions(interaction):
            raise app_commands.CheckFailure()
        await interaction.response.defer(ephemeral=True)
        return True
    
    async def committee_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        committees = await DatabaseController.get_all_committees(str(interaction.guild_id))
        return [
            app_commands.Choice(name=c[1], value=c[1]) 
            for c in committees if current.lower() in c[1].lower()
        ][:25]

    # Subgroups
    committee_group = app_commands.Group(name="committee", description="Committee management commands")
    role_group = app_commands.Group(name="role", description="Role management commands")
    setup_group = app_commands.Group(name="setup", description="Discord setup commands")

    # --- CONFIG COMMANDS
    @setup_group.command(name="setup", description="Set the role allowed to manage CRP")
    @app_commands.describe(role="The role allowed to use CRP commands")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_role(self, interaction: discord.Interaction, role: discord.Role):
        await DatabaseController.set_crp_role(str(interaction.guild_id), str(role.id))
        await interaction.response.send_message(f"✅ CRP Management role set to {role.mention}.", ephemeral=True)
    # --- COMMITTEE COMMANDS 

    @committee_group.command(name="create", description="Create a new committee.")
    async def comm_create(self, interaction: discord.Interaction, name: str, description: str = "No description"):
        cid = await DatabaseController.create_committee(str(interaction.guild_id), name, description)
        if not cid:
            return await interaction.followup.send(f"⚠️ A committee named **{name}** already exists!")
        await interaction.followup.send(f"✅ Created the **{name}** committee!")

    @committee_group.command(name="edit", description="Rename an existing committee.")
    @app_commands.autocomplete(old_name=committee_autocomplete)
    async def comm_edit(self, interaction: discord.Interaction, old_name: str, new_name: str):
        c = await DatabaseController.get_committee_by_name(str(interaction.guild_id), old_name)
        if not c:
            return await interaction.followup.send("❌ Committee not found.")
        await DatabaseController.update_committee_name(str(interaction.guild_id), c[0], new_name)
        await interaction.followup.send(f"✅ Renamed **{old_name}** to **{new_name}**.")

    @committee_group.command(name="remove", description="Delete a committee.")
    @app_commands.autocomplete(name=committee_autocomplete)
    async def comm_remove(self, interaction: discord.Interaction, name: str):
        c = await DatabaseController.get_committee_by_name(str(interaction.guild_id), name)
        if not c:
            return await interaction.followup.send("❌ Committee not found.")
        await DatabaseController.delete_committee(str(interaction.guild_id), c[0])
        await interaction.followup.send(f"🗑️ Deleted **{name}**.")

    @committee_group.command(name="list", description="List all committees.")
    async def comm_list(self, interaction: discord.Interaction):
        comms = await DatabaseController.get_all_committees(str(interaction.guild_id))
        if not comms:
            return await interaction.followup.send("🔍 No committees found.")
        
        embed = discord.Embed(title="Server Committees", color=discord.Color.blue())
        for _, name, desc in comms:
            embed.add_field(name=name, value=desc[:50]+"...", inline=False)
        await interaction.followup.send(embed=embed)

    # --- ROLE COMMANDS


    @role_group.command(name="assign", description="Assign a role to a member.")
    @app_commands.autocomplete(committee_name=committee_autocomplete)
    @app_commands.choices(role=[app_commands.Choice(name=r.title(), value=r) for r in ROLE_WEIGHT.keys()])
    async def role_assign(self, interaction: discord.Interaction, target: discord.Member, role: app_commands.Choice[str], committee_name: Optional[str] = None):
        guild_id, user_id = str(interaction.guild_id), str(target.id)
        rtype = RoleType(role.value)
        cid, final_name = None, "Global"

        if rtype in COMMITTEE_ROLES:
            if not committee_name:
                return await interaction.followup.send(f"❌ Role **{role.name}** requires a committee!")
            c = await DatabaseController.get_committee_by_name(guild_id, committee_name)
            if not c:
                return await interaction.followup.send(f"❌ Committee **{committee_name}** does not exist.")
            cid, final_name = c[0], c[1]
        elif committee_name:
            return await interaction.followup.send(f"ℹ️ **{role.name}** is a Global role. Leave committee blank.")

        cur_rows = await DatabaseController.get_user_committee_roles(guild_id, user_id)
        assigns = [{"committee_name": r[0], "role": r[1]} for r in cur_rows]
        assigns.append({"committee_name": final_name, "role": rtype})
        
        try:
            MemberRoles(user_id=user_id, assignments=assigns)
        except ValidationError as e:
            return await interaction.followup.send(f"⚠️ {e.errors()[0]['msg']}")

        await DatabaseController.assign_committee_role(guild_id, user_id, cid, rtype.value)
        await interaction.followup.send(f"✅ Assigned {target.mention} as **{role.name}** ({final_name}).")

    @role_group.command(name="remove", description="Yoink a specific role.")
    @app_commands.autocomplete(committee_name=committee_autocomplete)
    @app_commands.choices(role=[app_commands.Choice(name=r.title(), value=r) for r in ROLE_WEIGHT.keys()])
    async def role_remove(self, interaction: discord.Interaction, target: discord.Member, role: app_commands.Choice[str], committee_name: Optional[str] = None):
        cid = None
        if committee_name:
            c = await DatabaseController.get_committee_by_name(str(interaction.guild_id), committee_name)
            if c: cid = c[0]
        await DatabaseController.remove_assignment(str(interaction.guild_id), str(target.id), cid, role.value)
        await interaction.followup.send(f"✅ Yoinked **{role.name}** from {target.mention}.")

    @role_group.command(name="view", description="View a member's current roles.")
    async def role_view(self, interaction: discord.Interaction, target: discord.Member = None):
        target = target or interaction.user
        rows = await DatabaseController.get_user_committee_roles(str(interaction.guild_id), str(target.id))
        if not rows:
            return await interaction.followup.send(f"🔍 {target.display_name} has no roles.")

        embed = discord.Embed(title=f"Roles: {target.display_name}", color=discord.Color.blue())
        for cname, rtype in rows:
            embed.add_field(name=cname, value=rtype.title(), inline=False)
        await interaction.followup.send(embed=embed)

    @role_group.command(name="list", description="List members in a committee.")
    @app_commands.autocomplete(committee_name=committee_autocomplete)
    async def role_list(self, interaction: discord.Interaction, committee_name: str):
        c = await DatabaseController.get_committee_by_name(str(interaction.guild_id), committee_name)
        if not c:
            return await interaction.followup.send("❌ Committee not found.")
        
        rows = await DatabaseController.get_committee_members(str(interaction.guild_id), c[0])
        if not rows:
            return await interaction.followup.send(f"🔍 No members in **{committee_name}**.")

        sorted_rows = sorted(rows, key=lambda x: ROLE_WEIGHT.get(x[1].lower(), 99))
        embed = discord.Embed(title=f"🏛️ {committee_name.title()} Members", color=discord.Color.gold())
        rd = {}
        for uid, rt in sorted_rows: rd.setdefault(rt, []).append(f"<@{uid}>")
        for rt, mems in rd.items(): embed.add_field(name=rt.title(), value="\n".join(mems), inline=False)
        await interaction.followup.send(embed=embed)

    @role_group.command(name="listall", description="Full Org Hierarchy (Silent).")
    async def role_listall(self, interaction: discord.Interaction):
        
        rows = await DatabaseController.get_all_org_members(str(interaction.guild_id))
        if not rows:
            return await interaction.followup.send("🔍 Org is empty.")

        sorted_rows = sorted(rows, key=lambda x: ROLE_WEIGHT.get(x[1].lower(), 99))
        embed = discord.Embed(title="🏛️ Full Org Hierarchy", color=discord.Color.purple())
        rd = {}
        for uid, rt, cn in sorted_rows:
            loc = f"({cn})" if cn != "Global" else "🌐"
            rd.setdefault(rt, []).append(f"<@{uid}> {loc}")
        for rt, mems in rd.items(): embed.add_field(name=rt.title(), value="\n".join(mems), inline=False)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(CRPCog(bot))
