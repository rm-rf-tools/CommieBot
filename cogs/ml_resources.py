"""
filename: ml_resources.py
Views:
    - TheoryPaginator: Standard pagination for search results with First/Prev/Next/Last buttons. Includes clickable resource links.
    - TheoryFixView: Slide-based management for resolving dead links identified by the scanner.
    - TheoryEditModal: Modal for updating resource title, URL, description, and tags.
Commands:
    - /theory search [query] [tag]: Search resources with advanced pagination and clickable links.
    - /theory download <resource>: Download attached files directly.
    - /theory resource add: Add a new resource (Admin).
    - /theory resource edit: Edit an existing resource (Admin).
    - /theory resource delete: Remove a resource from the library (Admin).
    - /theory resource export: Export library as JSON (Admin).
    - /theory admin deadlinks: Automated scan for 403/404/500 errors.
    - /theory admin fix: Interactive UI to repair or delete dead links.
    - /theory admin clear: Wipe the entire library (Admin).
Required Permissions:
    - Manage Messages: Required for adding, editing, and fixing resources.
    - Manage Guild: Required for bulk export and clearing the library.
"""

import discord
from discord import app_commands
from discord.ext import commands
import io
import json
import aiohttp
from typing import Optional, List
from db import DatabaseController

class TheoryEditModal(discord.ui.Modal):
    def __init__(self, resource, view_to_refresh=None):
        super().__init__(title=f"Edit: {resource.title[:30]}")
        self.resource = resource
        self.view_to_refresh = view_to_refresh

        self.r_title = discord.ui.TextInput(label="Title", default=resource.title, required=True, max_length=200)
        self.r_url = discord.ui.TextInput(label="URL", default=resource.url or "", required=False)
        self.r_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, default=resource.description or "", required=False)
        self.r_tags = discord.ui.TextInput(label="Tags (Comma separated)", default=resource.tags or "", required=False)

        self.add_item(self.r_title)
        self.add_item(self.r_url)
        self.add_item(self.r_desc)
        self.add_item(self.r_tags)

    async def on_submit(self, interaction: discord.Interaction):
        await DatabaseController.edit_theory_resource(
            resource_id=self.resource.id,
            title=self.r_title.value.strip(),
            url=self.r_url.value.strip() if self.r_url.value.strip() else None,
            description=self.r_desc.value.strip() if self.r_desc.value.strip() else None,
            tags=self.r_tags.value.strip().lower() if self.r_tags.value.strip() else None
        )
        await DatabaseController.set_theory_resource_dead_status(self.resource.id, False)
        
        if self.view_to_refresh:
            await self.view_to_refresh.refresh_data()
            await interaction.response.edit_message(embed=self.view_to_refresh.generate_embed(), view=self.view_to_refresh)
        else:
            await interaction.response.send_message(f"✅ Updated **{self.r_title.value}**", ephemeral=True)

class TheoryPaginator(discord.ui.View):
    def __init__(self, resources: list, search_ctx: str = ""):
        super().__init__(timeout=300)
        self.resources = resources
        self.current_page = 0
        self.per_page = 10
        self.search_ctx = search_ctx
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.resources) - 1) // self.per_page)
        self.first_btn.disabled = self.prev_btn.disabled = self.current_page == 0
        self.last_btn.disabled = self.next_btn.disabled = self.current_page >= max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="📚 Theory Library", color=discord.Color.red())
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_res = self.resources[start:end]
        
        if not page_res:
            embed.description = "No resources found."
            return embed
            
        desc = ""
        for r in page_res:
            icon = "💀" if r.is_dead else ("💾" if r.file_data else "🔗")
            title_display = f"[{r.title}]({r.url})" if r.url else r.title
            desc += f"**{r.id}. {title_display}** {icon}\n"
            if r.tags:
                desc += f"> `{r.tags.replace(',', '`, `')}`\n"
        
        embed.description = desc
        max_pages = max(1, (len(self.resources) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"{self.search_ctx}Page {self.current_page + 1} of {max_pages} ({len(self.resources)} total)")
        return embed

    @discord.ui.button(label="First", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Last", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, (len(self.resources) - 1) // self.per_page)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

class TheoryFixView(discord.ui.View):
    def __init__(self, resources: list):
        super().__init__(timeout=600)
        self.resources = resources
        self.index = 0
        self.update_buttons()

    def update_buttons(self):
        self.first_btn.disabled = self.prev_btn.disabled = self.index == 0
        self.last_btn.disabled = self.next_btn.disabled = self.index >= len(self.resources) - 1
        if not self.resources:
            for btn in self.children:
                btn.disabled = True

    async def refresh_data(self):
        self.resources = await DatabaseController.get_dead_theory_resources()
        if self.index >= len(self.resources):
            self.index = max(0, len(self.resources) - 1)
        self.update_buttons()

    def generate_embed(self) -> discord.Embed:
        if not self.resources:
            return discord.Embed(title="✅ All clear!", description="No dead links currently need fixing.", color=discord.Color.green())
        
        r = self.resources[self.index]
        embed = discord.Embed(title=f"Repairing: {r.title}", color=discord.Color.orange())
        embed.add_field(name="Current URL", value=f"[{r.url}]({r.url})" if r.url else "None", inline=False)
        embed.add_field(name="ID", value=str(r.id), inline=True)
        embed.add_field(name="Type", value=r.resource_type, inline=True)
        embed.set_footer(text=f"Resource {self.index + 1} of {len(self.resources)}")
        return embed

    @discord.ui.button(label="First", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Update Link", style=discord.ButtonStyle.primary, emoji="✏️")
    async def fix_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TheoryEditModal(self.resources[self.index], self))

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def del_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        r = self.resources[self.index]
        await DatabaseController.delete_theory_resource(r.id)
        await self.refresh_data()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Last", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = len(self.resources) - 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

class TheoryCog(commands.GroupCog, name="theory"):
    def __init__(self, bot):
        self.bot = bot

    async def resource_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        resources = await DatabaseController.search_theory_resources(current, limit=25)
        return [app_commands.Choice(name=f"{r.title[:80]}", value=str(r.id)) for r in resources]

    async def tag_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        all_tags = await DatabaseController.get_all_theory_tags()
        filtered = [t for t in all_tags if current.lower() in t.lower()][:25]
        return [app_commands.Choice(name=t, value=t) for t in filtered]

    @app_commands.command(name="search", description="Search for theory resources.")
    @app_commands.autocomplete(query=resource_autocomplete, tag=tag_autocomplete)
    async def theory_search(self, interaction: discord.Interaction, query: str = None, tag: str = None):
        await interaction.response.defer()
        if query and query.isdigit():
            res = await DatabaseController.get_theory_resource_by_id(int(query))
            results = [res] if res else []
        else:
            results = await DatabaseController.search_theory_resources(query or "")
            if tag:
                results = [r for r in results if r.tags and tag.lower() in r.tags.lower()]

        if not results:
            return await interaction.followup.send("❌ No resources found.", ephemeral=True)
        
        view = TheoryPaginator(results, f"Search: {query or 'All'} | " if query else "")
        await interaction.followup.send(embed=view.generate_embed(), view=view)

    @app_commands.command(name="download", description="Download a resource file.")
    @app_commands.autocomplete(resource=resource_autocomplete)
    async def theory_download(self, interaction: discord.Interaction, resource: str):
        await interaction.response.defer()
        res = await DatabaseController.get_theory_resource_by_id(int(resource))
        if not res or not res.file_data:
            return await interaction.followup.send("❌ Resource file not found.", ephemeral=True)
        file = discord.File(io.BytesIO(res.file_data), filename=res.file_name or "theory.pdf")
        await interaction.followup.send(file=file)

    admin_group = app_commands.Group(name="admin", description="Library maintenance")

    @admin_group.command(name="deadlinks", description="Scan for 403/404/500 errors in the library.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def admin_deadlinks(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔍 Running deadlink scan... please wait.", ephemeral=True)
        
        resources = await DatabaseController.get_all_resources_with_urls()
        dead_count = 0
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            for r in resources:
                try:
                    async with session.get(r.url, allow_redirects=True) as resp:
                        is_dead = resp.status in [403, 404, 500, 502, 503, 504]
                        if is_dead:
                            dead_count += 1
                        await DatabaseController.set_theory_resource_dead_status(r.id, is_dead)
                except:
                    dead_count += 1
                    await DatabaseController.set_theory_resource_dead_status(r.id, True)

        await interaction.edit_original_response(content=f"✅ Scan complete! Found **{dead_count}** inaccessible links. Use `/theory admin fix` to resolve them.")

    @admin_group.command(name="fix", description="Resolve dead links one by one.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def admin_fix(self, interaction: discord.Interaction):
        dead_resources = await DatabaseController.get_dead_theory_resources()
        if not dead_resources:
            return await interaction.response.send_message("✅ No dead links found! Run `/theory admin deadlinks` if you haven't recently.", ephemeral=True)
        
        view = TheoryFixView(dead_resources)
        await interaction.response.send_message(embed=view.generate_embed(), view=view, ephemeral=True)

    resource_group = app_commands.Group(name="resource", description="Add/Edit resources")

    @resource_group.command(name="add")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def resource_add(self, interaction: discord.Interaction, title: str, resource_type: str, url: str = None, file: discord.Attachment = None, tags: str = ""):
        await interaction.response.defer(ephemeral=True)
        fb = await file.read() if file else None
        fn = file.filename if file else None
        await DatabaseController.add_theory_resource(title, resource_type, url, fb, fn, tags=tags)
        await interaction.followup.send("✅ Added resource.")

    @resource_group.command(name="edit")
    @app_commands.autocomplete(resource_id=resource_autocomplete)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def resource_edit(self, interaction: discord.Interaction, resource_id: str):
        res = await DatabaseController.get_theory_resource_by_id(int(resource_id))
        if not res:
            return await interaction.response.send_message("❌ Resource not found.", ephemeral=True)
        await interaction.response.send_modal(TheoryEditModal(res))

    @resource_group.command(name="delete")
    @app_commands.autocomplete(resource_id=resource_autocomplete)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def resource_delete(self, interaction: discord.Interaction, resource_id: str):
        await DatabaseController.delete_theory_resource(int(resource_id))
        await interaction.response.send_message("🗑️ Deleted resource.", ephemeral=True)

    @resource_group.command(name="export")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def resource_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        resources = await DatabaseController.get_all_theory_resources()
        data = [{"title": r.title, "url": r.url, "tags": r.tags, "type": r.resource_type, "description": r.description} for r in resources]
        file = discord.File(io.BytesIO(json.dumps(data, indent=4).encode()), filename="theory_export.json")
        await interaction.followup.send(file=file)

    @admin_group.command(name="clear")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def admin_clear(self, interaction: discord.Interaction):
        await DatabaseController.clear_all_theory_resources()
        await interaction.response.send_message("💣 Library cleared.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TheoryCog(bot))