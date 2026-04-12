# cogs/skills.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import List
from database import DatabaseController

class ManageSkillsView(discord.ui.View):
    def __init__(self, user: discord.Member, guild_id: str):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = guild_id
        self.all_skills = []
        self.user_skills = {}
        self.pending_skill_id = None
        self.pending_skill_name = None

    async def fetch_data(self):
        """Pulls fresh state from the database"""
        skills = await DatabaseController.get_all_server_skills(self.guild_id)
        
        self.all_skills = [{"id": s[0], "name": s[1], "desc": s[2], "wanted": s[3]} for s in skills]
        
        user_s = await DatabaseController.get_user_skills(self.guild_id, str(self.user.id))
        self.user_skills = {name: prof for name, prof in user_s}

    def build_main_menu(self):
        """Builds the main dashboard of current skills and an add dropdown"""
        self.clear_items()
        
        # Danger
        added_buttons = 0
        for name, prof in self.user_skills.items():
            if added_buttons >= 15: # Safety cap for Discord's View limits
                break
                
            btn = discord.ui.Button(
                label=f"✖ {name}",
                style=discord.ButtonStyle.danger,
                custom_id=f"rem_{name[:50]}",
                row=added_buttons // 5
            )
            
            def make_remove_callback(skill_name):
                async def callback(interaction: discord.Interaction):
                    skill_id = next((s["id"] for s in self.all_skills if s["name"] == skill_name), None)
                    if skill_id:
                        await DatabaseController.remove_profile_skill(self.guild_id, str(self.user.id), skill_id)
                    
                    await self.fetch_data()
                    self.build_main_menu()
                    await interaction.response.edit_message(embed=self.generate_embed(), view=self)
                return callback
                
            btn.callback = make_remove_callback(name)
            self.add_item(btn)
            added_buttons += 1

    
        missing_skills = [s for s in self.all_skills if s["name"] not in self.user_skills]
        if missing_skills:
            options = []
            for s in missing_skills[:25]: # Discord max 25 options
                desc = s["desc"][:50] + "..." if len(s["desc"]) > 50 else s["desc"]
                options.append(discord.SelectOption(label=s["name"], description=desc))
                
            placeholder = "➕ Select a skill to add..." if len(missing_skills) <= 25 else "➕ Select a skill (Showing first 25)"
            select = discord.ui.Select(placeholder=placeholder, options=options, row=3)
            
            async def select_callback(interaction: discord.Interaction):
                selected_name = interaction.data["values"][0]
                self.pending_skill_name = selected_name
                self.pending_skill_id = next((s["id"] for s in self.all_skills if s["name"] == selected_name), None)
                
                self.build_proficiency_menu()
                embed = discord.Embed(
                    title=f"Level of experience: {selected_name}",
                    description="How proficient are you with this skill?",
                    color=discord.Color.orange()
                )
                await interaction.response.edit_message(embed=embed, view=self)
                
            select.callback = select_callback
            self.add_item(select)

        # 3. Done button
        done_btn = discord.ui.Button(label="Done", style=discord.ButtonStyle.success, row=4)
        async def done_callback(interaction: discord.Interaction):
            self.stop()
            self.clear_items()
            await interaction.response.edit_message(content="✅ **Profile updated successfully!**", embed=self.generate_embed(), view=None)
        done_btn.callback = done_callback
        self.add_item(done_btn)

    def build_proficiency_menu(self):
        """Replaces the view with proficiency selection buttons"""
        self.clear_items()
        profs = ["1 - Beginner", "2 - Intermediate", "3 - Advanced", "4 - Expert", "Willing to learn"]
        
        for i, p in enumerate(profs):
            btn = discord.ui.Button(label=p, style=discord.ButtonStyle.primary, row=i//3)
            
            def make_prof_callback(prof):
                async def callback(interaction: discord.Interaction):
                    if self.pending_skill_id:
                        await DatabaseController.set_profile_skill(
                            self.guild_id, str(self.user.id), self.pending_skill_id, prof
                        )
                    self.pending_skill_id = None
                    self.pending_skill_name = None
                    await self.fetch_data()
                    self.build_main_menu()
                    await interaction.response.edit_message(embed=self.generate_embed(), view=self)
                return callback
                
            btn.callback = make_prof_callback(p)
            self.add_item(btn)
            
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
        async def cancel_callback(interaction: discord.Interaction):
            self.pending_skill_id = None
            self.pending_skill_name = None
            self.build_main_menu()
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        cancel.callback = cancel_callback
        self.add_item(cancel)

    def generate_embed(self):
        embed = discord.Embed(title=f"🛠️ Edit Skills: {self.user.display_name}", color=discord.Color.blue())
        if not self.user_skills:
            embed.description = "You haven't logged any skills yet.\n**Use the dropdown below to add some!**"
        else:
            text = ""
            for name, prof in self.user_skills.items():
                text += f"• **{name}** - {prof}\n"
            embed.add_field(name="Current Skills", value=text)
            embed.set_footer(text="Click a red button to remove a skill, or use the dropdown to add more.")
        return embed

# --- NEW ADMIN UI CLASSES ---

class SkillCreateModal(discord.ui.Modal, title="Create New Skill"):
    skill_name = discord.ui.TextInput(label="Skill Name", placeholder="e.g. Graphic Design", required=True)
    skill_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)
    is_wanted = discord.ui.TextInput(label="Is this actively wanted? (yes/no)", default="no", max_length=3, required=True)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        wanted = self.is_wanted.value.strip().lower() in ['yes', 'y', 'true']
        success = await DatabaseController.create_skill(
            self.parent_view.guild_id, 
            self.skill_name.value.strip(), 
            self.skill_desc.value.strip(), 
            wanted
        )
        
        if not success:
            return await interaction.response.send_message("❌ A skill with that name already exists!", ephemeral=True)
            
        await self.parent_view.fetch_data()
        self.parent_view.build_main_menu()
        await interaction.response.edit_message(content=f"✅ Created **{self.skill_name.value}**!", embed=self.parent_view.generate_main_embed(), view=self.parent_view)

class SkillEditModal(discord.ui.Modal):
    def __init__(self, parent_view, skill_data: dict):
        super().__init__(title=f"Edit: {skill_data['name'][:30]}")
        self.parent_view = parent_view
        self.skill_id = skill_data["id"]
        
        self.skill_name = discord.ui.TextInput(label="Skill Name", default=skill_data["name"], required=True)
        self.skill_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, default=skill_data["desc"], required=True)
        self.is_wanted = discord.ui.TextInput(label="Is this actively wanted? (yes/no)", default="yes" if skill_data["wanted"] else "no", max_length=3, required=True)
        
        self.add_item(self.skill_name)
        self.add_item(self.skill_desc)
        self.add_item(self.is_wanted)

    async def on_submit(self, interaction: discord.Interaction):
        wanted = self.is_wanted.value.strip().lower() in ['yes', 'y', 'true']
        success = await DatabaseController.update_skill_by_id(
            self.parent_view.guild_id,
            self.skill_id,
            self.skill_name.value.strip(),
            self.skill_desc.value.strip(),
            wanted
        )
        
        if not success:
            return await interaction.response.send_message("❌ Failed to update. (That name might already be taken by another skill).", ephemeral=True)
            
        await self.parent_view.fetch_data()
        self.parent_view.current_skill = next((s for s in self.parent_view.skills if s["id"] == self.skill_id), None)
        
        self.parent_view.build_detail_menu()
        await interaction.response.edit_message(content="✅ Skill updated!", embed=self.parent_view.generate_detail_embed(), view=self.parent_view)

class AdminSkillsView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.skills = []
        self.current_skill = None 

    async def fetch_data(self):
        skills = await DatabaseController.get_all_server_skills(self.guild_id)
        self.skills = [{"id": s[0], "name": s[1], "desc": s[2], "wanted": s[3]} for s in skills]

    def build_main_menu(self):
        self.clear_items()

        # 1. Create Button
        create_btn = discord.ui.Button(label="➕ Create New Skill", style=discord.ButtonStyle.success, row=0)
        async def create_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(SkillCreateModal(self))
        create_btn.callback = create_callback
        self.add_item(create_btn)

        # 2. Select Menu (Max 25 options per Discord limitations)
        if self.skills:
            options = []
            for s in self.skills[:25]:
                desc = s["desc"][:50] + "..." if len(s["desc"]) > 50 else s["desc"]
                options.append(discord.SelectOption(label=s["name"], description=desc, value=str(s["id"])))
            
            placeholder = "⚙️ Select a skill to manage..." if len(self.skills) <= 25 else "⚙️ Select a skill (Showing first 25)"
            select = discord.ui.Select(placeholder=placeholder, options=options, row=1)
            async def select_callback(interaction: discord.Interaction):
                skill_id = int(interaction.data["values"][0])
                self.current_skill = next((s for s in self.skills if s["id"] == skill_id), None)
                self.build_detail_menu()
                await interaction.response.edit_message(embed=self.generate_detail_embed(), view=self)
            select.callback = select_callback
            self.add_item(select)

    def build_detail_menu(self):
        self.clear_items()
        
        edit_btn = discord.ui.Button(label="✏️ Edit", style=discord.ButtonStyle.primary, row=0)
        async def edit_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(SkillEditModal(self, self.current_skill))
        edit_btn.callback = edit_callback
        self.add_item(edit_btn)

        delete_btn = discord.ui.Button(label="🗑️ Delete", style=discord.ButtonStyle.danger, row=0)
        async def delete_callback(interaction: discord.Interaction):
            await self.build_delete_confirm_menu(interaction)
        delete_btn.callback = delete_callback
        self.add_item(delete_btn)

        back_btn = discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction):
            self.current_skill = None
            self.build_main_menu()
            await interaction.response.edit_message(content="", embed=self.generate_main_embed(), view=self)
        back_btn.callback = back_callback
        self.add_item(back_btn)

    async def build_delete_confirm_menu(self, interaction: discord.Interaction):
        self.clear_items()
        
        # Pull everyone actively holding this skill to show the warning
        users = await DatabaseController.get_users_by_skill(self.guild_id, self.current_skill["id"])
        
        embed = discord.Embed(
            title=f"⚠️ Confirm Deletion: {self.current_skill['name']}",
            description="Are you sure you want to delete this skill? **It will be permanently removed from the catalog and from all user profiles.**",
            color=discord.Color.red()
        )
        
        if users:
            user_list = "\n".join([f"<@{uid}> - {prof}" for uid, prof in users])
            if len(user_list) > 1024:
                user_list = user_list[:1000] + "...\n*(And more)*"
            embed.add_field(name="Users losing this skill:", value=user_list)
        else:
            embed.add_field(name="Users affected:", value="*No users currently have this skill.*")

        confirm_btn = discord.ui.Button(label="🚨 Confirm Delete", style=discord.ButtonStyle.danger, row=0)
        async def confirm_callback(interaction: discord.Interaction):
            await DatabaseController.delete_skill_by_id(self.guild_id, self.current_skill["id"])
            deleted_name = self.current_skill['name']
            self.current_skill = None
            await self.fetch_data()
            self.build_main_menu()
            await interaction.response.edit_message(content=f"🗑️ **{deleted_name}** has been completely deleted.", embed=self.generate_main_embed(), view=self)
        confirm_btn.callback = confirm_callback
        self.add_item(confirm_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
        async def cancel_callback(interaction: discord.Interaction):
            self.build_detail_menu()
            await interaction.response.edit_message(embed=self.generate_detail_embed(), view=self)
        cancel_btn.callback = cancel_callback
        self.add_item(cancel_btn)

        await interaction.response.edit_message(embed=embed, view=self)

    def generate_main_embed(self):
        embed = discord.Embed(title="⚙️ Skill Administration", description="Manage the server's skill catalog.", color=discord.Color.purple())
        if not self.skills:
            embed.add_field(name="Catalog Empty", value="Click **➕ Create New Skill** to get started.")
        else:
            embed.set_footer(text=f"Total Skills Logged: {len(self.skills)}")
        return embed

    def generate_detail_embed(self):
        embed = discord.Embed(title=f"🛠️ Manage Skill: {self.current_skill['name']}", color=discord.Color.blue())
        wanted_text = "Yes 🚨" if self.current_skill["wanted"] else "No"
        embed.add_field(name="Description", value=self.current_skill['desc'], inline=False)
        embed.add_field(name="Actively Wanted?", value=wanted_text, inline=False)
        return embed


class SkillsCog(commands.GroupCog, name="skills"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    user_group = app_commands.Group(name="user", description="Manage skills tied to a specific user's profile.")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild_id:
            await interaction.response.send_message("❌ Must be used in a server.", ephemeral=True)
            return False

        is_member = await DatabaseController.is_crp_member(str(interaction.guild_id), str(interaction.user.id))
        if not is_member:
            await interaction.response.send_message("❌ You must be assigned to at least one CRP committee to use the skills matrix.", ephemeral=True)
            return False
            
        return True

    async def skill_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        skills = await DatabaseController.get_all_server_skills(str(interaction.guild_id))
        return [
            app_commands.Choice(name=s[1], value=s[1]) 
            for s in skills if current.lower() in s[1].lower()
        ][:25]

    # ==========================================
    #        GLOBAL SKILL MANAGEMENT
    # ==========================================

    @app_commands.command(name="create", description="Create a new skill in the server catalog.")
    @app_commands.describe(name="Name of the skill", description="What this skill entails", is_wanted="Are we actively looking for people with this skill?")
    async def skill_create(self, interaction: discord.Interaction, name: str, description: str, is_wanted: bool = False):
        await interaction.response.defer()
        guild_id = str(interaction.guild_id)
        
        success = await DatabaseController.create_skill(guild_id, name, description, is_wanted)
        if not success:
            return await interaction.followup.send(f"❌ The skill **{name}** already exists in the catalog!")

        wanted_text = "🚨 **(WANTED)**" if is_wanted else ""
        await interaction.followup.send(f"✅ Added **{name}** to the skill catalog! {wanted_text}\n*\"{description}\"*")

    @app_commands.command(name="delete", description="Delete a skill from the catalog entirely.")
    @app_commands.autocomplete(name=skill_autocomplete)
    async def skill_delete(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        
        success = await DatabaseController.delete_skill(str(interaction.guild_id), name)
        if not success:
            return await interaction.followup.send(f"❌ Could not find a skill named **{name}**.")

        await interaction.followup.send(f"🗑️ Permanently deleted **{name}** from the catalog and all user profiles.")

    @app_commands.command(name="list", description="List all available skills in the catalog.")
    async def skill_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        skills = await DatabaseController.get_all_server_skills(str(interaction.guild_id))
        
        if not skills:
            return await interaction.followup.send("📋 The skill catalog is currently empty. Use `/skills create` to add some!")

        embed = discord.Embed(title="📋 Server Skill Catalog", color=discord.Color.blue())
        for _, name, desc, is_wanted in skills:
            title = f"⭐ {name} (WANTED)" if is_wanted else name
            embed.add_field(name=title, value=desc, inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="find", description="Find organization members with a specific skill.")
    @app_commands.autocomplete(skill_name=skill_autocomplete)
    async def skill_find(self, interaction: discord.Interaction, skill_name: str):
        await interaction.response.defer()
        guild_id = str(interaction.guild_id)

        skills = await DatabaseController.get_all_server_skills(guild_id)
        skill_id = next((s[0] for s in skills if s[1].lower() == skill_name.lower()), None)
        
        if not skill_id:
            return await interaction.followup.send(f"🔍 Skill **{skill_name}** does not exist in the catalog.")

        users = await DatabaseController.get_users_by_skill(guild_id, skill_id)
        
        if not users:
            return await interaction.followup.send(f"🔍 No active members found with the skill: **{skill_name}**.")

        prof_map = {"4 - Expert": [], "3 - Advanced": [], "2 - Intermediate": [], "1 - Beginner": [], "Willing to learn": []}
        for uid, prof in users:
            if prof in prof_map:
                prof_map[prof].append(f"<@{uid}>")
            else:
                prof_map.setdefault(prof, []).append(f"<@{uid}>")

        embed = discord.Embed(title=f"🔎 Skill Search: {skill_name.title()}", color=discord.Color.green())
        for level, members in prof_map.items():
            if members:
                embed.add_field(name=level, value="\n".join(members), inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="profile", description="View a user's skill profile.")
    async def skill_profile(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        guild_id = str(interaction.guild_id)

        is_member = await DatabaseController.is_crp_member(guild_id, str(target.id))
        if not is_member:
            return await interaction.response.send_message(f"❌ {target.display_name} is not currently an active member of the org.", ephemeral=True)

        skills = await DatabaseController.get_user_skills(guild_id, str(target.id))
        
        embed = discord.Embed(title=f"🛠️ Profile: {target.display_name}", color=discord.Color.blue())
        if not skills:
            embed.description = "No skills logged yet."
        else:
            skills_text = ""
            for name, prof in skills:
                skills_text += f"• **{name}** - {prof}\n"
            embed.add_field(name="Skills Matrix", value=skills_text)

        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="edit", description="Edit an existing skill's description or wanted status.")
    @app_commands.autocomplete(name=skill_autocomplete)
    @app_commands.describe(name="Name of the skill to edit", description="The new description", is_wanted="Are we actively looking for this skill?")
    async def skill_edit(self, interaction: discord.Interaction, name: str, description: str, is_wanted: bool = False):
        await interaction.response.defer()
        
        success = await DatabaseController.edit_skill(str(interaction.guild_id), name, description, is_wanted)
        if not success:
            return await interaction.followup.send(f"❌ Could not find a skill named **{name}** in the catalog.")

        wanted_text = "🚨 **(WANTED)**" if is_wanted else ""
        await interaction.followup.send(f"✅ Successfully updated **{name}**! {wanted_text}\n*\"{description}\"*")
        
    @app_commands.command(name="tree", description="View the full organization skill tree.")
    async def skill_tree(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        rows = await DatabaseController.get_skill_tree(str(interaction.guild_id))
        if not rows:
            return await interaction.followup.send("🔍 The skill catalog is currently empty.")

        tree_data = {}
        for skill_name, is_wanted, uid, prof in rows:
            if skill_name not in tree_data:
                tree_data[skill_name] = {"is_wanted": is_wanted, "members": []}
            if uid:
                tree_data[skill_name]["members"].append(f"<@{uid}> ({prof})")

        embeds = []
        current_embed = discord.Embed(title="🌳 Organization Skill Tree", color=discord.Color.dark_teal())
        
        for skill, data in tree_data.items():
            if len(current_embed.fields) >= 25:
                embeds.append(current_embed)
                current_embed = discord.Embed(color=discord.Color.dark_teal())
                
            header = f"⭐ {skill} (WANTED)" if data["is_wanted"] else skill
            members_text = "\n".join(data["members"]) if data["members"] else "*No members logged.*"
            current_embed.add_field(name=header, value=members_text, inline=False)
            
        embeds.append(current_embed)
        await interaction.followup.send(embeds=embeds)

    # ==========================================
    #        USER PROFILE MANAGEMENT
    # ==========================================

    @app_commands.command(name="manage", description="Interactive UI to easily toggle your skills on and off.")
    async def skill_manage(self, interaction: discord.Interaction):
        
        await interaction.response.defer(ephemeral=True)
        
        view = ManageSkillsView(interaction.user, str(interaction.guild_id))
        await view.fetch_data()
        view.build_main_menu()
        
        embed = view.generate_embed()
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="admin", description="Admin UI to manage, create, edit, or delete the skill catalog.")
    async def skill_admin(self, interaction: discord.Interaction):
    
        await interaction.response.defer(ephemeral=True)
        
        view = AdminSkillsView(str(interaction.guild_id))
        await view.fetch_data()
        view.build_main_menu()
        
        await interaction.followup.send(embed=view.generate_main_embed(), view=view)

    @user_group.command(name="add", description="Add a catalog skill to a user's profile manually.")
    @app_commands.autocomplete(skill_name=skill_autocomplete)
    @app_commands.choices(proficiency=[
        app_commands.Choice(name="1 - Beginner", value="1 - Beginner"),
        app_commands.Choice(name="2 - Intermediate", value="2 - Intermediate"),
        app_commands.Choice(name="3 - Advanced", value="3 - Advanced"),
        app_commands.Choice(name="4 - Expert", value="4 - Expert"),
        app_commands.Choice(name="Willing to learn", value="Willing to learn")
    ])
    async def user_add(self, interaction: discord.Interaction, skill_name: str, proficiency: app_commands.Choice[str], member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        guild_id = str(interaction.guild_id)
        
        skills = await DatabaseController.get_all_server_skills(guild_id)
        skill_id = next((s[0] for s in skills if s[1].lower() == skill_name.lower()), None)
        
        if not skill_id:
            return await interaction.followup.send(f"❌ **{skill_name}** is not in the catalog. Ask an admin to `/skills create` it first.")
        
        await DatabaseController.set_profile_skill(guild_id, str(target.id), skill_id, proficiency.value)
        
        target_name = "your" if target == interaction.user else f"{target.display_name}'s"
        await interaction.followup.send(f"✅ Logged **{skill_name}** at level **{proficiency.value}** on {target_name} profile.")

    @user_group.command(name="remove", description="Remove a skill from a user's profile manually.")
    @app_commands.autocomplete(skill_name=skill_autocomplete)
    async def user_remove(self, interaction: discord.Interaction, skill_name: str, member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        guild_id = str(interaction.guild_id)
        
        skills = await DatabaseController.get_all_server_skills(guild_id)
        skill_id = next((s[0] for s in skills if s[1].lower() == skill_name.lower()), None)
        
        if not skill_id:
            return await interaction.followup.send("❌ Skill not found in the server registry.")

        await DatabaseController.remove_profile_skill(guild_id, str(target.id), skill_id)
        
        target_name = "your" if target == interaction.user else f"{target.display_name}'s"
        await interaction.followup.send(f"🗑️ Removed **{skill_name}** from {target_name} profile.")

async def setup(bot):
    await bot.add_cog(SkillsCog(bot))