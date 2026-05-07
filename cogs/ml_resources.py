"""
filename: ml_resources.py
description: Marxist-Leninist Educational Theory Library supporting links, articles, videos, and direct file uploads.
Views:
    - TheoryPaginator: Handles pagination (10/page) and interactive tag filtering for theory resources.
    - TheoryManageView: Interactive GUI for admins to select, edit, and delete theory resources.
    - TheoryEditModal: Modal popup for editing a selected theory resource.
Commands:
    - /theory search [query]: Search for theory resources. Lists 10 at a time with a tag filter dropdown. (User)
    - /theory download <id>: Download a file directly attached to a theory resource. (User)
    - /theory random [resource_type]: Get a random theory resource, optionally filtered by type. (User)
    - /theory manage [query]: Open the interactive GUI to select, edit, or delete resources. (Admin: Manage Messages)
    - /theory resource add <title> <resource_type> [url] [file] [description] [tags]: Add a new theory resource. (Admin: Manage Messages)
    - /theory resource edit <resource_id>: Edit an existing theory resource via text command. (Admin: Manage Messages)
    - /theory resource delete <resource_id>: Delete a theory resource via text command. (Admin: Manage Messages)
    - /theory resource import <file>: Bulk import theory resources from a JSON file. (Admin: Manage Guild)
    - /theory resource export: Export the entire theory library as a JSON file. (Admin: Manage Guild)
    - /theory admin clear: DELETE ALL theory resources in the server database. (Admin: Manage Guild)
"""

import discord
from discord import app_commands
from discord.ext import commands
import io
import os
import json
import random
import logging
from typing import Optional, List
from collections import Counter

from db import DatabaseController

logger = logging.getLogger("TheoryCog")
logger.setLevel(logging.INFO)


# ==========================================
#             MODALS & VIEWS
# ==========================================

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
        
        if self.view_to_refresh:
            await self.view_to_refresh.refresh()
            await interaction.response.edit_message(embed=self.view_to_refresh.generate_embed(), view=self.view_to_refresh)
        else:
            await interaction.response.send_message(f"✅ Updated **{self.r_title.value}**", ephemeral=True)


class TheorySingleManageView(discord.ui.View):
    """View for managing ONE specific resource (Edit/Delete). Scalable."""
    def __init__(self, resource):
        super().__init__(timeout=300)
        self.resource = resource

    async def refresh(self):
        self.resource = await DatabaseController.get_theory_resource_by_id(self.resource.id)

    def generate_embed(self) -> discord.Embed:
        r = self.resource
        embed = discord.Embed(title=f"⚙️ Managing: {r.title}", color=discord.Color.blurple())
        embed.description = (
            f"**Type:** {r.resource_type}\n"
            f"**URL:** {r.url or 'None'}\n"
            f"**Tags:** {r.tags or 'None'}\n"
            f"**File:** {'Attached' if r.file_data else 'None'}\n\n"
            f"**Description:**\n{r.description or 'No description provided.'}"
        )
        return embed

    @discord.ui.button(label="Edit Details", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TheoryEditModal(self.resource, self))

    @discord.ui.button(label="Delete Resource", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await DatabaseController.delete_theory_resource(self.resource.id)
        await interaction.response.edit_message(content=f"✅ Deleted **{self.resource.title}**", embed=None, view=None)


class TheoryPaginator(discord.ui.View):
    """View for browsing search results."""
    def __init__(self, resources: list, search_ctx: str = ""):
        super().__init__(timeout=300)
        self.resources = resources
        self.current_page = 0
        self.per_page = 5
        self.search_ctx = search_ctx
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.resources) - 1) // self.per_page)
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="📚 Theory Library Results", color=discord.Color.red())
        
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_res = self.resources[start:end]
        
        if not page_res:
            embed.description = "No resources found."
            return embed
            
        desc = ""
        for r in page_res:
            file_indicator = "💾" if r.file_data else "🔗"
            desc += f"**{r.id}. {r.title}** `[{r.resource_type.upper()}]` {file_indicator}\n"
            if r.tags:
                desc += f"> 🏷️ `{r.tags.replace(',', '`, `')}`\n"
            desc += "\n"
            
        embed.description = desc
        max_pages = max(1, (len(self.resources) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"{self.search_ctx}Page {self.current_page + 1} of {max_pages} | Total: {len(self.resources)}")
        return embed

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)


# ==========================================
#             DISCORD COG
# ==========================================

class TheoryCog(commands.GroupCog, name="theory"):
    def __init__(self, bot):
        self.bot = bot

    # --- AUTOCOMPLETES ---

    async def resource_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Scalable search for titles."""
        resources = await DatabaseController.search_theory_resources(current, limit=25)
        return [
            app_commands.Choice(name=f"{r.title[:80]} [{r.resource_type.upper()}]", value=str(r.id))
            for r in resources
        ]

    async def tag_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Scalable search for tags."""
        all_tags = await DatabaseController.get_all_theory_tags()
        # Filter tags by what the user is typing
        filtered = [t for t in all_tags if current.lower() in t.lower()][:25]
        return [app_commands.Choice(name=f"🏷️ {t}", value=t) for t in filtered]

    # --- COMMANDS ---  
    resource_group = app_commands.Group(name="resource", description="Theory resource management commands")
    admin_group = app_commands.Group(name="admin", description="Dangerous admin commands")


    @app_commands.command(name="search", description="Search by title or filter by tag.")
    @app_commands.describe(query="Search text for titles", tag="Filter by a specific tag")
    @app_commands.autocomplete(query=resource_autocomplete, tag=tag_autocomplete)
    async def theory_search(self, interaction: discord.Interaction, query: str = None, tag: str = None):
        await interaction.response.defer()
        
        # 1. If they picked a specific resource from autocomplete query
        if query and query.isdigit():
            res = await DatabaseController.get_theory_resource_by_id(int(query))
            results = [res] if res else []
        else:
            # 2. General search
            results = await DatabaseController.search_theory_resources(query or "")
            
            # 3. Apply tag filter if provided
            if tag:
                results = [r for r in results if r.tags and tag.lower() in r.tags.lower()]

        if not results:
            return await interaction.followup.send("❌ No resources found matching those criteria.")

        ctx_msg = f"Searching: '{query}' " if query else ""
        ctx_msg += f"Tag: '{tag}' " if tag else ""
        
        view = TheoryPaginator(results, ctx_msg)
        await interaction.followup.send(embed=view.generate_embed(), view=view)

    @app_commands.command(name="manage", description="Edit or delete a specific resource.")
    @app_commands.describe(resource="Search and select a resource to manage")
    @app_commands.autocomplete(resource=resource_autocomplete)
    async def theory_manage(self, interaction: discord.Interaction, resource: str):
        """Management command that uses autocomplete instead of a broken dropdown."""
        if not resource.isdigit():
            return await interaction.response.send_message("❌ Please select a resource from the list.", ephemeral=True)
            
        res_obj = await DatabaseController.get_theory_resource_by_id(int(resource))
        if not res_obj:
            return await interaction.response.send_message("❌ Resource not found.", ephemeral=True)
            
        view = TheorySingleManageView(res_obj)
        await interaction.response.send_message(embed=view.generate_embed(), view=view, ephemeral=True)

    @app_commands.command(name="download", description="Get the file for a resource.")
    @app_commands.describe(resource="Search and select resource")
    @app_commands.autocomplete(resource=resource_autocomplete)
    async def theory_download(self, interaction: discord.Interaction, resource: str):
        await interaction.response.defer()
        if not resource.isdigit():
            return await interaction.followup.send("❌ Invalid selection.")
            
        res = await DatabaseController.get_theory_resource_by_id(int(resource))
        if not res or not res.file_data:
            return await interaction.followup.send("❌ This resource has no file attached.")
            
        file = discord.File(io.BytesIO(res.file_data), filename=res.file_name or "document.pdf")
        await interaction.followup.send(f"📥 **{res.title}**", file=file)

    @resource_group.command(name="add", description="Manually add a new resource to the library.")
    @app_commands.describe(
        title="Title of the resource",
        resource_type="e.g. link, video, pdf, article",
        url="Link to the resource",
        file="Attach a file directly to the DB (max 8MB recommended)",
        description="A short summary",
        tags="Comma-separated list of tags (e.g. theory, history)"
    )
    @app_commands.choices(resource_type=[
        app_commands.Choice(name="Link / Webpage", value="link"),
        app_commands.Choice(name="PDF / Document", value="pdf"),
        app_commands.Choice(name="Video", value="video"),
        app_commands.Choice(name="Article / Essay", value="article"),
        app_commands.Choice(name="Book", value="book")
    ])
    async def resource_add(
        self, interaction: discord.Interaction, 
        title: str, resource_type: app_commands.Choice[str], 
        url: str = None, file: discord.Attachment = None, 
        description: str = None, tags: str = ""
    ):
        await interaction.response.defer(ephemeral=True)
        
        file_bytes = None
        file_name = None
        if file:
            # Prevent excessive memory bloat in SQLite
            if file.size > 8 * 1024 * 1024:
                return await interaction.followup.send("❌ File is too large. Please keep database uploads under 8MB.")
            file_bytes = await file.read()
            file_name = file.filename
            
        resource = await DatabaseController.add_theory_resource(
            title=title, 
            resource_type=resource_type.value, 
            url=url, 
            file_data=file_bytes, 
            file_name=file_name, 
            description=description, 
            tags=tags.lower()
        )
        
        await interaction.followup.send(f"✅ Successfully added **{resource.title}** to the library!")

    @resource_group.command(name="edit", description="Edit an existing theory resource via text modal.")
    @app_commands.autocomplete(resource_id=resource_autocomplete) 
    async def resource_edit(self, interaction: discord.Interaction, resource_id: str):
        try:
            r_id = int(resource_id)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid resource selected.", ephemeral=True)
            
        resource = await DatabaseController.get_theory_resource_by_id(r_id)
        if not resource:
            return await interaction.response.send_message("❌ Resource not found.", ephemeral=True)
            
        await interaction.response.send_modal(TheoryEditModal(resource))

    @resource_group.command(name="delete", description="Delete a theory resource via text command.")
    @app_commands.autocomplete(resource_id=resource_autocomplete) 
    async def resource_delete(self, interaction: discord.Interaction, resource_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            r_id = int(resource_id)
        except ValueError:
            return await interaction.followup.send("❌ Invalid resource selected.")

        resource = await DatabaseController.get_theory_resource_by_id(r_id)
        if not resource:
            return await interaction.followup.send("❌ Resource not found.")

        success = await DatabaseController.delete_theory_resource(r_id)
        if success:
            await interaction.followup.send(f"🗑️ Successfully deleted **{resource.title}**.")
        else:
            await interaction.followup.send("❌ Failed to delete resource.")

    # ==========================================
    #           DATA MIGRATION
    # ==========================================

    @resource_group.command(name="import", description="Bulk import theory resources from a JSON file.")
    async def resource_import(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.filename.endswith('.json'):
            return await interaction.response.send_message("❌ Must be a `.json` file.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        try:
            content = await file.read()
            data = json.loads(content.decode('utf-8'))

            # Handle both formats: raw array or nested in "resources" key
            if isinstance(data, dict) and "resources" in data:
                resources_list = data["resources"]
            elif isinstance(data, list):
                resources_list = data
            else:
                return await interaction.followup.send("❌ Unrecognized JSON structure. Provide an array of objects.")

            db_payload =[]
            for item in resources_list:
                tags_raw = item.get("tags", "")
                tags_str = ",".join(tags_raw) if isinstance(tags_raw, list) else tags_raw
                
                db_payload.append({
                    "title": item.get("title", "Unknown Title"),
                    "resource_type": item.get("resource_type", "link"),
                    "url": item.get("url") or item.get("href"),
                    "description": item.get("description", None),
                    "tags": tags_str.lower()
                })

            added_count = await DatabaseController.bulk_add_theory_resources(db_payload)
            await interaction.followup.send(f"✅ Successfully imported **{added_count}** new resources into the library!")
            
        except json.JSONDecodeError as e:
            await interaction.followup.send(f"❌ Failed to parse JSON file: {e}")
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred during import: {e}")

    @resource_group.command(name="export", description="Export the entire theory library as a JSON file.")
    async def resource_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        resources = await DatabaseController.get_all_theory_resources()
        
        if not resources:
            await interaction.followup.send("❌ The library is currently empty. Nothing to export.")
            return
            
        # Using a safer dict and list initialization
        export_data = {"resources": list()}
        
        for r in resources:
            # Parse tags safely without inline list comprehensions
            tags_parsed = list()
            if r.tags:
                for t in r.tags.split(","):
                    if t.strip():
                        tags_parsed.append(t.strip())
            
            # Note: We omit file_data bytes to prevent massive JSON files. 
            # We just note whether a file is attached.
            item_dict = {
                "id": r.id,
                "title": r.title,
                "resource_type": r.resource_type,
                "url": r.url,
                "description": r.description,
                "tags": tags_parsed,
                "has_file": bool(r.file_data)
            }
            export_data.get("resources").append(item_dict)
            
        # Convert dictionary to nicely formatted JSON string
        json_string = json.dumps(export_data, indent=4)
        
        # Create an in-memory file for Discord to upload
        file_io = io.BytesIO(json_string.encode('utf-8'))
        discord_file = discord.File(fp=file_io, filename="theory_library_export.json")
        
        await interaction.followup.send("✅ Here is the current library export:", file=discord_file)

    @admin_group.command(name="clear", description="DELETE ALL theory resources in the server database.")
    async def admin_clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Executes the text("DELETE FROM theory_resources") command
        await DatabaseController.clear_all_theory_resources()
        
        await interaction.followup.send("⚠️ **WARNING:** All theory resources have been completely wiped from the database.")

async def setup(bot):
    await bot.add_cog(TheoryCog(bot))
