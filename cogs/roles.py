"""
filename: roles.py
description: Advanced role management system for creating, importing, and deploying complex role-reaction menus (Role Plans).
Views:
    - RoleItemModal: Modal for configuring individual role item details (name, color, emoji, description).
    - PlanManageView: Interactive dashboard for adding, editing, or removing roles within a specific plan.
Commands:
    - /roles plan create <name>: Create a new empty role plan. (Admin: Manage Roles)
    - /roles plan manage <name>: Open the management UI for a specific plan. (Admin: Manage Roles)
    - /roles plan import <file>: Bulk import a role plan from a JSON file. (Admin: Manage Roles)
    - /roles plan export <name>: Export a role plan configuration to a JSON file. (Admin: Manage Roles)
    - /roles plan delete <name>: Permanently delete a role plan and its configuration. (Admin: Manage Roles)
    - /roles plan debug_ghosts: Clean up orphaned role items in the database. (Admin: Manage Roles)
    - /roles deploy <name> [channel] [clear_previous]: Create roles and deploy the reaction UI to a channel. (Admin: Manage Roles)
"""

# cogs/roles.py
import discord
from discord import app_commands
from discord.ext import commands
import json
import io
import asyncio
from typing import Optional

from database import DatabaseController

# ==========================================
#             INTERACTIVE UI
# ==========================================

class RoleItemModal(discord.ui.Modal):
    def __init__(self, view, plan_id: int, item=None):
        title = "Edit Role Configuration" if item else "Add Role to Plan"
        super().__init__(title=title)
        self.parent_view = view
        self.plan_id = plan_id
        self.item = item

        self.role_name = discord.ui.TextInput(
            label="Role Name (Must match existing if linking)",
            default=item.role_name if item else "",
            required=True
        )
        self.category = discord.ui.TextInput(
            label="Category Header",
            default=item.category if item else "General",
            required=True
        )
        self.emoji = discord.ui.TextInput(
            label="Emoji (Unicode or Custom ID)",
            default=item.emoji if item else "",
            required=False,
            max_length=50
        )
        self.color_hex = discord.ui.TextInput(
            label="Role Color Hex (e.g. #FF0000)",
            default=f"#{hex(item.role_color)[2:].zfill(6)}" if (item and item.role_color) else "",
            required=False,
            max_length=7
        )
        self.description = discord.ui.TextInput(
            label="Description",
            default=item.description if item else "",
            required=False,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.role_name)
        self.add_item(self.category)
        self.add_item(self.emoji)
        self.add_item(self.color_hex)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        color_int = 0
        hex_val = self.color_hex.value.strip().lstrip('#')
        if hex_val:
            try:
                color_int = int(hex_val, 16)
            except ValueError:
                color_int = 0

        if self.item:
            await DatabaseController.update_role_plan_item(
                item_id=self.item.id,
                role_name=self.role_name.value.strip(),
                category=self.category.value.strip(),
                color=color_int,
                emoji=self.emoji.value.strip(),
                description=self.description.value.strip()
            )
        else:
            await DatabaseController.add_role_plan_item(
                plan_id=self.plan_id,
                role_name=self.role_name.value.strip(),
                category=self.category.value.strip(),
                color=color_int,
                emoji=self.emoji.value.strip(),
                description=self.description.value.strip()
            )

        await self.parent_view.refresh_data()
        await interaction.response.edit_message(embed=self.parent_view.generate_embed(), view=self.parent_view)


class PlanManageView(discord.ui.View):
    def __init__(self, plan):
        super().__init__(timeout=600)
        self.plan = plan
        self.items = []
        self.selected_item = None

    async def refresh_data(self):
        self.items = await DatabaseController.get_role_plan_items(self.plan.id)
        self.selected_item = None
        self.build_ui()

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🛠️ Managing Role Plan: {self.plan.name}",
            description="Add, edit, or remove roles from this plan.\n*(Note: Removing a role here does NOT delete the actual Discord role)*",
            color=discord.Color.blue()
        )
        if not self.items:
            embed.add_field(name="Roles in Plan", value="*This plan is currently empty.*")
        else:
            categories = {}
            for item in self.items:
                cat = item.category or "General"
                if cat not in categories:
                    categories[cat] = []
                emoji = item.emoji + " " if item.emoji else ""
                categories[cat].append(f"{emoji}**{item.role_name}**")

            for cat, roles in categories.items():
                roles_str = "\n".join(roles)
                if len(roles_str) > 1024:
                    roles_str = roles_str[:1000] + "...\n*(and more)*"
                embed.add_field(name=cat, value=roles_str, inline=True)
        return embed

    def build_ui(self):
        self.clear_items()

        if self.items:
            options = []
            for item in self.items[:25]:
                options.append(discord.SelectOption(
                    label=item.role_name,
                    description=item.category[:50],
                    value=str(item.id),
                    emoji=item.emoji if item.emoji else None
                ))
            
            select = discord.ui.Select(placeholder="Select a role to edit or remove...", options=options, row=0)

            async def select_callback(interaction: discord.Interaction):
                item_id = int(interaction.data['values'][0])
                self.selected_item = next((i for i in self.items if i.id == item_id), None)
                self.build_ui()
                await interaction.response.edit_message(view=self)
            
            select.callback = select_callback
            self.add_item(select)

        btn_add = discord.ui.Button(label="➕ Add Role", style=discord.ButtonStyle.success, row=1)
        async def add_cb(interaction: discord.Interaction):
            await interaction.response.send_modal(RoleItemModal(self, self.plan.id))
        btn_add.callback = add_cb
        self.add_item(btn_add)

        btn_edit = discord.ui.Button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary, row=1, disabled=self.selected_item is None)
        async def edit_cb(interaction: discord.Interaction):
            await interaction.response.send_modal(RoleItemModal(self, self.plan.id, self.selected_item))
        btn_edit.callback = edit_cb
        self.add_item(btn_edit)

        btn_remove = discord.ui.Button(label="🗑️ Remove Selected", style=discord.ButtonStyle.danger, row=1, disabled=self.selected_item is None)
        async def remove_cb(interaction: discord.Interaction):
            if self.selected_item:
                await DatabaseController.delete_role_plan_item(self.selected_item.id)
                await self.refresh_data()
                await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        btn_remove.callback = remove_cb
        self.add_item(btn_remove)


# ==========================================
#             DISCORD COG
# ==========================================

class RolesCog(commands.GroupCog, name="roles"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message

        if isinstance(error, app_commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await send(f"❌ **Permission Denied:** You need `{perms}` to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            await send(f"❌ **Bot Error:** I am missing `{perms}` permissions.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    plan_group = app_commands.Group(name="plan", description="Manage Role Plans")

    async def plan_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        plans = await DatabaseController.get_all_role_plans(str(interaction.guild_id))
        return [
            app_commands.Choice(name=p.name, value=p.name)
            for p in plans if current.lower() in p.name.lower()
        ][:25]

    @plan_group.command(name="create", description="Create a new, empty Role Plan manually.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def plan_create(self, interaction: discord.Interaction, plan_name: str):
        guild_id = str(interaction.guild_id)
        plan_id = await DatabaseController.create_role_plan(guild_id, plan_name)
        if not plan_id:
            return await interaction.response.send_message(f"❌ A plan named **{plan_name}** already exists.", ephemeral=True)
        await interaction.response.send_message(f"✅ Created empty plan **{plan_name}**. Use `/roles plan manage` to add roles to it!", ephemeral=True)

    @plan_group.command(name="manage", description="Open the interactive UI to edit roles inside a plan.")
    @app_commands.autocomplete(plan_name=plan_autocomplete)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def plan_manage(self, interaction: discord.Interaction, plan_name: str):
        guild_id = str(interaction.guild_id)
        plan = await DatabaseController.get_role_plan_by_name(guild_id, plan_name)
        if not plan:
            return await interaction.response.send_message(f"❌ Plan **{plan_name}** not found.", ephemeral=True)

        view = PlanManageView(plan)
        await view.refresh_data()
        await interaction.response.send_message(embed=view.generate_embed(), view=view, ephemeral=True)

    @plan_group.command(name="import", description="Bulk import a Role Plan from a JSON file.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def plan_import(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith('.json'):
            return await interaction.response.send_message("❌ Must be a .json file.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            content = await file.read()
            data = json.loads(content.decode('utf-8'))

            plan_name = data.get("name", "Imported Plan")
            items = data.get("items", [])

            if not items:
                return await interaction.followup.send("❌ JSON file has no items array.")

            plan_id = await DatabaseController.create_role_plan(str(interaction.guild_id), plan_name)
            if not plan_id:
                return await interaction.followup.send(f"❌ A plan named **{plan_name}** already exists. If it's corrupted, use `/roles plan debug_ghosts` to wipe it.")

            count = 0
            for item in items:
                role_name = item.get("role_name")
                if not role_name:
                    continue
                
                await DatabaseController.add_role_plan_item(
                    plan_id=plan_id, role_name=role_name, category=item.get("category", "General"),
                    color=item.get("color", 0), emoji=item.get("emoji", ""), description=item.get("description", "")
                )
                count += 1

            await interaction.followup.send(f"✅ Successfully imported **{plan_name}** with {count} roles!")
        except Exception as e:
            await interaction.followup.send(f"❌ Error during import: {e}")

    @plan_group.command(name="export", description="Backup a Role Plan to a JSON file.")
    @app_commands.autocomplete(plan_name=plan_autocomplete)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def plan_export(self, interaction: discord.Interaction, plan_name: str):
        plan = await DatabaseController.get_role_plan_by_name(str(interaction.guild_id), plan_name)
        if not plan:
            return await interaction.response.send_message("❌ Plan not found.", ephemeral=True)

        items = await DatabaseController.get_role_plan_items(plan.id)
        export_data = {"name": plan.name, "items": []}
        for i in items:
            export_data["items"].append({
                "role_name": i.role_name, "color": i.role_color, "emoji": i.emoji,
                "category": i.category, "description": i.description
            })

        json_string = json.dumps(export_data, indent=2)
        file = discord.File(fp=io.BytesIO(json_string.encode('utf-8')), filename=f"{plan.name.replace(' ', '_')}.json")
        await interaction.response.send_message(f"✅ Exported **{plan.name}**", file=file, ephemeral=True)

    @plan_group.command(name="delete", description="Delete an entire Role Plan from the database.")
    @app_commands.autocomplete(plan_name=plan_autocomplete)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def plan_delete(self, interaction: discord.Interaction, plan_name: str):
        plan = await DatabaseController.get_role_plan_by_name(str(interaction.guild_id), plan_name)
        if not plan:
            return await interaction.response.send_message("❌ Plan not found.", ephemeral=True)

        await DatabaseController.delete_role_plan(plan.id)
        await interaction.response.send_message(f"🗑️ Deleted Role Plan **{plan_name}**. All configuration items wiped.", ephemeral=True)

    @plan_group.command(name="debug_ghosts", description="Cleans up orphaned role items in the database that crash the UI.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def debug_ghosts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        count = await DatabaseController.cleanup_orphaned_role_items()
        await interaction.followup.send(f"🧹 Vacuumed up **{count} ghost roles** from the database that had no valid plan assigned. Your deployments should now be fixed!")

    # --- DEPLOY COMMAND ---

    @app_commands.command(name="deploy", description="Deploy a Role Plan (Creates missing roles and sends the React UI).")
    @app_commands.autocomplete(plan_name=plan_autocomplete)
    @app_commands.describe(
        plan_name="The plan to deploy.",
        target_channel="The channel to post the menus in.",
        clear_previous="If True, it will delete old role menus in the channel first."
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True, send_messages=True, read_message_history=True)
    async def deploy_roles(self, interaction: discord.Interaction, plan_name: str, target_channel: discord.TextChannel = None, clear_previous: bool = False):
        channel = target_channel or interaction.channel
        guild = interaction.guild

        await interaction.response.defer(ephemeral=True)

        # 1. Sweep the channel for old React Role messages and delete them
        if clear_previous:
            try:
                async for msg in channel.history(limit=100):
                    if msg.author == guild.me and msg.components:
                        is_role_menu = False
                        for action_row in msg.components:
                            for component in action_row.children:
                                if hasattr(component, "custom_id") and component.custom_id and component.custom_id.startswith('rr_btn_'):
                                    is_role_menu = True
                                    break
                            if is_role_menu:
                                break
                        
                        if is_role_menu:
                            await msg.delete()
                            await asyncio.sleep(0.5) 
            except discord.Forbidden:
                pass 

        # 2. Fetch Plan
        plan = await DatabaseController.get_role_plan_by_name(str(guild.id), plan_name)
        if not plan:
            return await interaction.followup.send(f"❌ Role plan **{plan_name}** not found.")

        items = await DatabaseController.get_role_plan_items(plan.id)
        if not items:
            return await interaction.followup.send("❌ This role plan is empty.")

        # 3. Group items by category and safely filter out exact duplicate roles in the same category
        categories = {}
        for item in items:
            role = discord.utils.get(guild.roles, name=item.role_name)
            if not role:
                try:
                    role = await guild.create_role(
                        name=item.role_name,
                        color=discord.Color(item.role_color) if item.role_color else discord.Color.default(),
                        reason=f"Deployed via React Roles plan '{plan_name}'"
                    )
                    await asyncio.sleep(0.5)
                except discord.Forbidden:
                    return await interaction.followup.send("❌ Cannot create roles! Ensure my bot role is higher in the hierarchy.")

            cat = item.category or "General"
            if cat not in categories:
                categories[cat] = []
                
            if not any(r.id == role.id for i, r in categories[cat]):
                categories[cat].append((item, role))

        # 4. Build Embeds and Views for each category
        for cat_name, pairs in categories.items():
            embed = discord.Embed(
                title=f"🎭 {cat_name}",
                description="Click the buttons below to toggle your roles!",
                color=discord.Color.blurple()
            )

            chunks = [pairs[i:i + 25] for i in range(0, len(pairs), 25)]

            for chunk_idx, chunk in enumerate(chunks):
                view = discord.ui.View(timeout=None)
                desc_lines = []
                
                for item, role in chunk:
                    desc_text = item.description if item.description else ""
                    emoji_str = item.emoji + " " if item.emoji else ""
                    if desc_text:
                        desc_lines.append(f"{emoji_str}{role.mention} - {desc_text}")
                    
                    # Appends item.id to guarantee Discord uniqueness even if two items have the same role_id
                    try:
                        btn = discord.ui.Button(
                            label=item.role_name,
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"rr_btn_{role.id}_{item.id}",
                            emoji=item.emoji if item.emoji else None
                        )
                    except Exception:
                        btn = discord.ui.Button(
                            label=item.role_name,
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"rr_btn_{role.id}_{item.id}"
                        )
                    view.add_item(btn)

                if desc_lines:
                    embed.description = "\n".join(desc_lines)
                if chunk_idx > 0:
                    embed.title = f"🎭 {cat_name} (Cont.)"

                await channel.send(embed=embed, view=view)

        await interaction.followup.send(f"✅ Successfully deployed **{plan_name}** to {channel.mention}.")


    # --- GLOBAL BUTTON LISTENER ---
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        
        custom_id = interaction.data.get('custom_id', '')
        
        if custom_id.startswith('rr_btn_'):
            try:
                # Safely grabs the role_id from rr_btn_{role_id}_{item_id}
                parts = custom_id.split('_')
                role_id = int(parts[2])
            except (ValueError, IndexError):
                return
            
            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.response.send_message("❌ This role no longer exists in the server.", ephemeral=True)

            if interaction.guild.me.top_role <= role:
                return await interaction.response.send_message("❌ My bot role is beneath this role! An Admin needs to drag my role higher up the list in server settings.", ephemeral=True)

            try:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role, reason="React Role Toggle")
                    await interaction.response.send_message(f"➖ Removed **{role.name}**", ephemeral=True)
                else:
                    await interaction.user.add_roles(role, reason="React Role Toggle")
                    await interaction.response.send_message(f"➕ Added **{role.name}**", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ I do not have permission to manage roles. Please contact an admin.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(RolesCog(bot))
