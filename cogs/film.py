"""
filename: cogs/film.py
description: Search TMDB, view movie previews, and manage robust collaborative movie and series watchlists.
Views:
    - MoviePaginator: Handles pagination of movie search results with an easy "Add to List" drop down select.
    - AddToListSelectView: Ephemeral view for selecting which list to add a searched TMDB movie to.
    - ListShowPaginator: Handles pagination for displaying a high-level overview of a specific movie list.
    - ItemManagePaginator: An interactive per-item slide dashboard for editing, reordering, or removing specific items on a list.
Commands:
    - /film search <query>: Search for a movie and view a preview card. Contains easy button to Add to List. (User)
    - /movies list new <name> [description]: Create a new list. (User)
    - /movies list delete <name>: Delete a movie list entirely. (List Owner / Mod)
    - /movies list edit <name> [new_name] [new_description]: Edit the name or description of a list. (List Owner / Mod)
    - /movies list manage <name>: Open the slide dashboard to reorder, remove, or edit info/episodes for items on the list. (List Owner / Mod)
    - /movies list show <name>: Display all movies currently queued up on a specific list in a neat paginator. (User)
    - /movies list export <name>: Export the entire list to CSV format for download. (User)
    - /movies admin_repopulate: Repopulate the default list from the text file. (Mod)
"""

import csv
import io
import discord
from discord import app_commands
from discord.ext import commands
import logging

from db import DatabaseController
from db.movies_api import MoviesDBController

logger = logging.getLogger("FilmCog")
logger.setLevel(logging.INFO)

# ==========================================
#             HELPERS
# ==========================================

def expand_episodes(ep_str: str) -> str:
    if not ep_str:
        return ""
    parts = ep_str.split(',')
    res =[]
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                if start <= end:
                    res.extend(range(start, end + 1))
            except ValueError:
                pass
        else:
            try:
                res.append(int(part))
            except ValueError:
                pass
    if not res:
        return ep_str
    res = sorted(list(set(res)))
    return ", ".join(map(str, res))

# ==========================================
#             UI COMPONENTS
# ==========================================

class AddToListSelectView(discord.ui.View):
    def __init__(self, movie, user: discord.Member, lists: list):
        super().__init__(timeout=120)
        self.movie = movie
        
        options = [
            discord.SelectOption(label=lst.name[:100], description=(lst.description or "")[:50], value=str(lst.id))
            for lst in lists[:25]
        ]
        sel = discord.ui.Select(placeholder="Select a list...", options=options)
        
        async def cb(interaction: discord.Interaction):
            list_id = int(sel.values[0])
            await DatabaseController.add_movie_to_list(list_id, movie_id=self.movie.id)
            await interaction.response.edit_message(content=f"✅ Successfully added **{self.movie.title}** to your list!", view=None)
            
        sel.callback = cb
        self.add_item(sel)

class MoviePaginator(discord.ui.View):
    def __init__(self, movies: list):
        super().__init__(timeout=180)
        self.movies = movies
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        for child in self.children:
            if getattr(child, "custom_id", None) == "prev_btn":
                child.disabled = self.current_page == 0
            elif getattr(child, "custom_id", None) == "next_btn":
                child.disabled = self.current_page == len(self.movies) - 1

    def generate_embed(self) -> discord.Embed:
        movie = self.movies[self.current_page]
        year = movie.release_date[:4] if movie.release_date else "Unknown Year"
        title_str = f"🎬 {movie.title} ({year})"
        
        embed = discord.Embed(
            title=title_str,
            description=movie.overview or "*No description available.*",
            color=discord.Color.purple(),
            url=movie.homepage if movie.homepage else (f"https://www.imdb.com/title/{movie.imdb_id}/" if movie.imdb_id else None)
        )

        if movie.poster_path:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{movie.poster_path}")
        if movie.backdrop_path:
            embed.set_image(url=f"https://image.tmdb.org/t/p/original{movie.backdrop_path}")

        if movie.tagline:
            embed.add_field(name="Tagline", value=f"*{movie.tagline}*", inline=False)
        
        genres = movie.genres or "Unknown"
        embed.add_field(name="🎭 Genres", value=genres, inline=True)
        embed.add_field(name="⏱️ Runtime", value=f"{movie.runtime} mins", inline=True)
        
        rating = f"⭐ {movie.vote_average:.1f}/10 ({movie.vote_count} votes)" if movie.vote_average else "Not Rated"
        embed.add_field(name="📈 Rating", value=rating, inline=True)

        embed.set_footer(text=f"Result {self.current_page + 1} of {len(self.movies)} | TMDB Database")
        return embed

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, custom_id="prev_btn", row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="next_btn", row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="➕ Add to List", style=discord.ButtonStyle.success, row=1)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_lists = await DatabaseController.get_movie_lists(str(interaction.guild_id))
        if not interaction.user.guild_permissions.manage_messages:
            user_lists = [l for l in user_lists if l.user_id == str(interaction.user.id)]
            
        if not user_lists:
            return await interaction.response.send_message("❌ You don't have any lists available. Create one with `/movies list new`.", ephemeral=True)
            
        view = AddToListSelectView(self.movies[self.current_page], interaction.user, user_lists)
        await interaction.response.send_message(f"Add **{self.movies[self.current_page].title}** to which list?", view=view, ephemeral=True)

class ListShowPaginator(discord.ui.View):
    def __init__(self, list_obj, items: list):
        super().__init__(timeout=300)
        self.list_obj = list_obj
        self.items = items
        self.current_page = 0
        self.per_page = 5
        self.update_buttons()

    def update_buttons(self):
        max_pages = max(0, (len(self.items) - 1) // self.per_page)
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page >= max_pages

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🍿 Movie List: {self.list_obj.name}",
            description=self.list_obj.description or "No description.",
            color=discord.Color.gold()
        )
        
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.items[start:end]
        
        if not page_items:
            embed.add_field(name="Empty", value="This list has no items yet.")
            return embed

        for list_item, movie in page_items:
            title = movie.title if movie else list_item.custom_title
            year_str = list_item.custom_release_date or (movie.release_date[:4] if movie and movie.release_date else "")
            year_display = f" ({year_str})" if year_str else ""
            
            details =[]
            if list_item.film_type and list_item.film_type.lower() == "series":
                s_info = f"S{list_item.season_number}" if list_item.season_number else "Series"
                e_info = f"Eps: {list_item.episodes_list}" if list_item.episodes_list else ""
                details.append(f"📺 **{s_info}** {e_info}".strip())
                
            if list_item.watch_date: details.append(f"📅 **Date:** {list_item.watch_date}")
            if list_item.host_id: details.append(f"🎤 **Host:** {list_item.host_id}")
            if movie and movie.vote_average: details.append(f"⭐ {movie.vote_average:.1f}/10")
                
            val = " | ".join(details) if details else "*No schedule info*"
            embed.add_field(name=f"{list_item.order_index}. 🎬 {title}{year_display}", value=val, inline=False)

        max_pages = max(1, (len(self.items) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"Page {self.current_page + 1} of {max_pages} | Total: {len(self.items)} items")
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


class EditInfoModal(discord.ui.Modal):
    def __init__(self, item, paginator):
        super().__init__(title="Edit Schedule & Info")
        self.item = item
        self.paginator = paginator
        
        self.watch_date = discord.ui.TextInput(label="Watch Date", required=False, default=item.watch_date or "")
        self.host = discord.ui.TextInput(label="Host Name / @User", required=False, default=item.host_id or "")
        self.release_date = discord.ui.TextInput(label="Release Year", required=False, default=item.custom_release_date or "")
        
        self.add_item(self.watch_date)
        self.add_item(self.host)
        self.add_item(self.release_date)
        
    async def on_submit(self, interaction: discord.Interaction):
        await DatabaseController.update_movie_list_item(
            self.item.id, 
            watch_date=self.watch_date.value,
            host_id=self.host.value,
            custom_release_date=self.release_date.value
        )
        await self.paginator.reload_items()
        await interaction.response.edit_message(embed=self.paginator.generate_embed(), view=self.paginator)

class EditSeriesModal(discord.ui.Modal):
    def __init__(self, item, paginator):
        super().__init__(title="Edit Series Details")
        self.item = item
        self.paginator = paginator
        
        self.f_type = discord.ui.TextInput(label="Type (Movie or Series)", required=False, default=item.film_type or "")
        self.season = discord.ui.TextInput(label="Season Number", required=False, default=str(item.season_number) if item.season_number else "")
        self.eps = discord.ui.TextInput(label="Episodes (e.g. 1,3-5)", required=False, default=item.episodes_list or "")
        
        self.add_item(self.f_type)
        self.add_item(self.season)
        self.add_item(self.eps)
        
    async def on_submit(self, interaction: discord.Interaction):
        ep_list = expand_episodes(self.eps.value) if self.eps.value else None
        season_num = int(self.season.value) if self.season.value and self.season.value.isdigit() else None
        
        await DatabaseController.update_movie_list_item(
            self.item.id,
            film_type=self.f_type.value,
            season_number=season_num,
            episodes_list=ep_list
        )
        await self.paginator.reload_items()
        await interaction.response.edit_message(embed=self.paginator.generate_embed(), view=self.paginator)

class MoveItemModal(discord.ui.Modal):
    def __init__(self, item, total_items, paginator):
        super().__init__(title="Move Item Position")
        self.item = item
        self.paginator = paginator
        self.total_items = total_items
        
        self.new_pos = discord.ui.TextInput(label=f"New Position (1-{total_items})", required=True)
        self.add_item(self.new_pos)
        
    async def on_submit(self, interaction: discord.Interaction):
        try:
            pos = int(self.new_pos.value)
            await DatabaseController.reorder_movie_list_item(self.item.list_id, self.item.id, pos)
            await self.paginator.reload_items()
            self.paginator.current_page = max(0, min(pos - 1, self.total_items - 1))
            self.paginator.update_components()
            await interaction.response.edit_message(embed=self.paginator.generate_embed(), view=self.paginator)
        except ValueError:
            await interaction.response.send_message("❌ Invalid position number.", ephemeral=True)

class AddFilmModal(discord.ui.Modal):
    def __init__(self, list_id, paginator):
        super().__init__(title="Add Film")
        self.list_id = list_id
        self.paginator = paginator
        
        self.title_input = discord.ui.TextInput(label="Title", required=True)
        self.release_year_input = discord.ui.TextInput(label="Release Year (Optional)", required=False)
        self.add_item(self.title_input)
        self.add_item(self.release_year_input)
        
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await DatabaseController.add_movie_to_list(self.list_id, custom_title=self.title_input.value)
        
        if self.release_year_input.value:
            items = await DatabaseController.get_movie_list_items(self.list_id)
            if items:
                latest_item = items[-1][0]
                await DatabaseController.update_movie_list_item(latest_item.id, custom_release_date=self.release_year_input.value)
                
        await self.paginator.reload_items()
        self.paginator.current_page = len(self.paginator.items) - 1 
        self.paginator.update_components()
        await interaction.edit_original_response(embed=self.paginator.generate_embed(), view=self.paginator)

class ItemManagePaginator(discord.ui.View):
    def __init__(self, list_obj, items: list):
        super().__init__(timeout=600)
        self.list_obj = list_obj
        self.items = items
        self.current_page = 0
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        btn_first = discord.ui.Button(label="⏮ First", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0) or not self.items)
        btn_first.callback = self.go_first
        
        btn_prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0) or not self.items)
        btn_prev.callback = self.go_prev
        
        btn_next = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.current_page >= len(self.items) - 1) or not self.items)
        btn_next.callback = self.go_next
        
        btn_last = discord.ui.Button(label="Last ⏭", style=discord.ButtonStyle.primary, disabled=(self.current_page >= len(self.items) - 1) or not self.items)
        btn_last.callback = self.go_last
        
        btn_add = discord.ui.Button(label="➕ Add Film", style=discord.ButtonStyle.success)
        btn_add.callback = self.add_film
        
        self.add_item(btn_first)
        self.add_item(btn_prev)
        self.add_item(btn_next)
        self.add_item(btn_last)
        self.add_item(btn_add)
        
        if self.items:
            options =[
                discord.SelectOption(label="Edit Info (Date/Host/Release)", value="edit_info", emoji="📝"),
                discord.SelectOption(label="Edit Series Details (Season/Eps)", value="edit_series", emoji="📺"),
                discord.SelectOption(label="Move Position", value="move", emoji="↕️"),
                discord.SelectOption(label="Remove Item", value="remove", emoji="🗑️")
            ]
            sel = discord.ui.Select(placeholder="Manage this item...", options=options, row=1)
            sel.callback = self.action_callback
            self.add_item(sel)

    async def reload_items(self):
        self.items = await DatabaseController.get_movie_list_items(self.list_obj.id)
        self.current_page = max(0, min(self.current_page, len(self.items) - 1))
        self.update_components()

    def generate_embed(self) -> discord.Embed:
        if not self.items:
            return discord.Embed(title=f"Dashboard: {self.list_obj.name}", description="This list is currently empty. Add items!", color=discord.Color.red())
            
        list_item, movie = self.items[self.current_page]
        title = movie.title if movie else list_item.custom_title
        
        embed = discord.Embed(
            title=f"[{self.current_page + 1}/{len(self.items)}] {title}",
            color=discord.Color.blue()
        )
        
        if list_item.film_type is None:
            pass
        elif list_item.film_type and list_item.film_type.lower() == "series":
            season = f"Season {list_item.season_number}" if list_item.season_number else "Unknown Season"
            eps = f"Episodes: {list_item.episodes_list}" if list_item.episodes_list else "All Episodes"
            embed.add_field(name="📺 Series Details", value=f"{season}\n{eps}", inline=False)
            
        embed.add_field(name="📅 Watch Date", value=list_item.watch_date or "Not set", inline=True)
        embed.add_field(name="🎤 Host", value=list_item.host_id or "Not set", inline=True)
        
        release_val = list_item.custom_release_date or (movie.release_date[:4] if movie and movie.release_date else "Unknown")
        embed.add_field(name="🎞️ Release Year", value=release_val, inline=True)
        
        if movie and movie.poster_path:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w200{movie.poster_path}")
            
        return embed

    async def go_first(self, interaction):
        self.current_page = 0
        self.update_components()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def go_prev(self, interaction):
        self.current_page -= 1
        self.update_components()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        
    async def go_next(self, interaction):
        self.current_page += 1
        self.update_components()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        
    async def go_last(self, interaction):
        self.current_page = len(self.items) - 1
        self.update_components()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def add_film(self, interaction):
        modal = AddFilmModal(self.list_obj.id, self)
        await interaction.response.send_modal(modal)

    async def action_callback(self, interaction: discord.Interaction):
        val = interaction.data['values'][0]
        list_item, movie = self.items[self.current_page]
        
        if val == "edit_info":
            await interaction.response.send_modal(EditInfoModal(list_item, self))
        elif val == "edit_series":
            await interaction.response.send_modal(EditSeriesModal(list_item, self))
        elif val == "move":
            await interaction.response.send_modal(MoveItemModal(list_item, len(self.items), self))
        elif val == "remove":
            await DatabaseController.remove_movie_list_item(list_item.id)
            await self.reload_items()
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)

# ==========================================
#             COGS
# ==========================================

class FilmCog(commands.Cog, name="film"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Verifying default Movie Night lists for all connected servers...")
        for guild in self.bot.guilds:
            await DatabaseController.ensure_default_movie_list(str(guild.id), str(self.bot.user.id))

    film_group = app_commands.Group(name="film", description="Film search and tools")
    movies_group = app_commands.Group(name="movies", description="Manage and interact with movie lists")
    list_group = app_commands.Group(name="list", description="Manage the lists themselves", parent=movies_group)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        logger.error(f"Error caught in FilmCog by {interaction.user}: {error}")
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You do not have the right permissions.", ephemeral=True)
        else:
            await send(f"❌ An unexpected error occurred: {error}", ephemeral=True)

    # --- AUTOCOMPLETES ---
    async def movie_search_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not current:
            return[]
        movies = await DatabaseController.search_movies(current, limit=25)
        choices =[]
        for m in movies:
            year = f" ({m.release_date[:4]})" if m.release_date else ""
            display_name = f"{m.title}{year}"[:100]
            choices.append(app_commands.Choice(name=display_name, value=str(m.title)))
        return choices

    async def lists_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return[]
        
        await DatabaseController.ensure_default_movie_list(str(interaction.guild_id), str(self.bot.user.id))
        all_lists = await DatabaseController.get_movie_lists(str(interaction.guild_id))
        
        if interaction.user.guild_permissions.manage_messages:
            available = all_lists
        else:
            available = [l for l in all_lists if l.user_id == str(interaction.user.id) or l.is_default]

        return [
            app_commands.Choice(name=lst.name, value=lst.name)
            for lst in available if current.lower() in lst.name.lower()
        ][:25]

    # --- FILM SEARCH COMMAND ---
    @film_group.command(name="search", description="Search for a movie and view a beautiful preview card!")
    @app_commands.describe(query="Type to search for movies (auto-completes as you type)")
    @app_commands.autocomplete(query=movie_search_autocomplete)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True) 
    async def film_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        results = await MoviesDBController.search_and_cache(query, limit=10)

        if not results:
            return await interaction.followup.send(f"❌ No movies found matching **{query}** on TMDB or locally.")

        view = MoviePaginator(results)
        await interaction.followup.send(embed=view.generate_embed(), view=view)

    # --- MOVIES LIST COMMANDS ---
    @list_group.command(name="new", description="Create a new movie list.")
    async def list_new(self, interaction: discord.Interaction, name: str, description: str = None):
        list_id = await DatabaseController.create_movie_list(str(interaction.guild_id), str(interaction.user.id), name, description)
        if not list_id:
            return await interaction.response.send_message(f"❌ A list named **{name}** already exists in this server.", ephemeral=True)
        await interaction.response.send_message(f"✅ Created list **{name}**.", ephemeral=True)

    @list_group.command(name="edit", description="Edit the name or description of an existing movie list.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def list_edit(self, interaction: discord.Interaction, list_name: str, new_name: str = None, new_description: str = None):
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.response.send_message("❌ List not found.", ephemeral=True)
        
        if lst.is_default and not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Only server admins can edit the default Movie Night list.", ephemeral=True)
        if lst.user_id != str(interaction.user.id) and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ You do not own this list.", ephemeral=True)

        final_name = new_name if new_name else lst.name
        final_desc = new_description if new_description else lst.description
        await DatabaseController.edit_movie_list(lst.id, final_name, final_desc)
        await interaction.response.send_message(f"✅ List updated successfully.", ephemeral=True)

    @list_group.command(name="delete", description="Delete a movie list entirely.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def list_delete(self, interaction: discord.Interaction, list_name: str):
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.response.send_message("❌ List not found.", ephemeral=True)
            
        if lst.is_default:
            return await interaction.response.send_message("❌ The default Movie Night list cannot be deleted.", ephemeral=True)
            
        if lst.user_id != str(interaction.user.id) and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ You do not have permission to delete this list.", ephemeral=True)

        await DatabaseController.delete_movie_list(lst.id)
        await interaction.response.send_message(f"🗑️ Successfully deleted the list **{list_name}**.", ephemeral=True)

    @list_group.command(name="manage", description="Open an interactive dashboard to manage an individual movie list's items.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def list_manage(self, interaction: discord.Interaction, list_name: str):
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.response.send_message("❌ List not found.", ephemeral=True)
            
        if not lst.is_default and lst.user_id != str(interaction.user.id) and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ You do not have permission to manage items on this list.", ephemeral=True)

        items = await DatabaseController.get_movie_list_items(lst.id)
        view = ItemManagePaginator(lst, items)
        await interaction.response.send_message(embed=view.generate_embed(), view=view, ephemeral=True)

    @list_group.command(name="show", description="Display a read-only paginated overview of all items on a list.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def list_show(self, interaction: discord.Interaction, list_name: str):
        await interaction.response.defer()
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.followup.send("❌ List not found.")

        items = await DatabaseController.get_movie_list_items(lst.id)
        view = ListShowPaginator(lst, items)
        await interaction.followup.send(embed=view.generate_embed(), view=view)

    @list_group.command(name="export", description="Export a movie list to CSV.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def list_export(self, interaction: discord.Interaction, list_name: str):
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.response.send_message("❌ List not found.", ephemeral=True)
            
        items = await DatabaseController.get_movie_list_items(lst.id)
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Order", "Title", "TMDB_ID", "Film_Type", "Season", "Episodes", "Watch_Date", "Host", "Release_Date"])
        
        for list_item, movie in items:
            title = movie.title if movie else list_item.custom_title
            tmdb_id = movie.id if movie else ""
            rel_date = list_item.custom_release_date or (movie.release_date if movie else "")
            writer.writerow([
                list_item.order_index, title, tmdb_id, list_item.film_type or "", 
                list_item.season_number or "", list_item.episodes_list or "", 
                list_item.watch_date or "", list_item.host_id or "", rel_date
            ])
            
        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"{lst.name.replace(' ', '_')}_export.csv")
        await interaction.response.send_message(f"✅ Here is the export for **{lst.name}**:", file=file, ephemeral=True)

    @movies_group.command(name="admin_repopulate", description="Force re-populate the default Movie Night list from the text file.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def movies_admin_repopulate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        default_list = await DatabaseController.ensure_default_movie_list(str(interaction.guild_id), str(self.bot.user.id))
        
        if default_list.id in getattr(DatabaseController, "_populating_lists", set()):
            return await interaction.followup.send("⚠️ The bot is already populating this list in the background! Please wait a minute for it to finish.", ephemeral=True)
        
        import asyncio
        asyncio.create_task(DatabaseController._populate_default_list(default_list.id))
        await interaction.followup.send("⏳ Wiped existing list and started background task! The bot is now reading `movieslist.txt` and securely downloading TMDB info. Check the terminal logs!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FilmCog(bot))
    logger.info("FilmCog loaded successfully.")