"""
filename: film.py
description: Search TMDB, view movie previews, and manage collaborative movie lists.
Views:
    - MoviePaginator: Handles pagination of movie search results with previous/next buttons.
    - MovieListManageView: Interactive dashboard for managing user-owned movie lists.
    - MovieListFormModal: Modal for creating or editing movie list details.
    - MovieAddModal: Modal to input movie title, watch date, and host name.
    - MovieSearchSelectionView: Dropdown menu allowing a user to finalize their movie choice from a TMDB search query.
    - ListShowPaginator: Handles pagination for displaying movies stored in a specific list.
Commands:
    - /film search <query>: Search for a movie and view a beautiful preview card. Uses TMDB fallback. (User)
    - /movies manage: Open an interactive dashboard to create, edit, or delete your movie lists. (User)
    - /movies add <list_name>: Add a new movie to a list with optional watch dates and host info. (User)
    - /movies list show <list_name>: Display all movies currently queued up on a specific list. (User)
    - /movies list delete <list_name>: Delete a movie list entirely. (Mod/Owner)
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging

from db import DatabaseController
from db.movies_api import MoviesDBController

logger = logging.getLogger("FilmCog")
logger.setLevel(logging.INFO)

# ==========================================
#             UI COMPONENTS
# ==========================================

class MoviePaginator(discord.ui.View):
    def __init__(self, movies: list):
        super().__init__(timeout=180)
        self.movies = movies
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == len(self.movies) - 1

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

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="next_btn")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)


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
            embed.add_field(name="Empty", value="This list has no movies yet.")
            return embed

        for list_item, movie in page_items:
            title = movie.title if movie else list_item.custom_title
            year = f" ({movie.release_date[:4]})" if (movie and movie.release_date) else ""
            
            details =[]
            if list_item.watch_date:
                details.append(f"📅 **Date:** {list_item.watch_date}")
            if list_item.host_id:
                # We just print the string exactly as they typed it in the modal
                details.append(f"🎤 **Host:** {list_item.host_id}")
            if movie and movie.vote_average:
                details.append(f"⭐ {movie.vote_average:.1f}/10")
                
            val = " | ".join(details) if details else "*No schedule info*"
            embed.add_field(name=f"🎬 {title}{year}", value=val, inline=False)

        max_pages = max(1, (len(self.items) + self.per_page - 1) // self.per_page)
        embed.set_footer(text=f"Page {self.current_page + 1} of {max_pages} | Total: {len(self.items)} movies")
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


class MovieListFormModal(discord.ui.Modal):
    def __init__(self, guild_id: str, user_id: str, existing_list=None):
        title = "Edit Movie List" if existing_list else "Create Movie List"
        super().__init__(title=title)
        self.guild_id = guild_id
        self.user_id = user_id
        self.existing_list = existing_list

        self.list_name = discord.ui.TextInput(
            label="List Name",
            default=existing_list.name if existing_list else "",
            required=True
        )
        self.list_desc = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=existing_list.description if existing_list else "",
            required=False
        )

        self.add_item(self.list_name)
        self.add_item(self.list_desc)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.list_name.value.strip()
        desc = self.list_desc.value.strip()

        if self.existing_list:
            await DatabaseController.edit_movie_list(self.existing_list.id, name, desc)
            await interaction.response.send_message(f"✅ Updated list **{name}**.", ephemeral=True)
        else:
            list_id = await DatabaseController.create_movie_list(self.guild_id, self.user_id, name, desc)
            if not list_id:
                await interaction.response.send_message(f"❌ A list named **{name}** already exists.", ephemeral=True)
            else:
                await interaction.response.send_message(f"✅ Created list **{name}**.", ephemeral=True)


class MovieListManageView(discord.ui.View):
    def __init__(self, guild_id: str, user: discord.Member):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.user = user
        self.lists =[]
        self.selected_list = None

    async def fetch_data(self):
        all_lists = await DatabaseController.get_movie_lists(self.guild_id)
        if self.user.guild_permissions.manage_messages:
            self.lists = all_lists
        else:
            self.lists = [lst for lst in all_lists if lst.user_id == str(self.user.id)]

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(title="⚙️ Movie List Management", color=discord.Color.dark_purple())
        if not self.lists:
            embed.description = "You do not own any movie lists. Click Create below!"
        else:
            embed.description = f"You have access to manage **{len(self.lists)}** list(s)."
        return embed

    async def build_ui(self):
        self.clear_items()
        
        if self.lists:
            options = [
                discord.SelectOption(label=lst.name, description=lst.description[:50] if lst.description else "No description", value=str(lst.id))
                for lst in self.lists[:25]
            ]
            sel = discord.ui.Select(placeholder="Select a list to edit/delete...", options=options, row=0)
            
            async def sel_cb(interaction: discord.Interaction):
                list_id = int(interaction.data['values'][0])
                self.selected_list = next((l for l in self.lists if l.id == list_id), None)
                await self.build_ui()
                await interaction.response.edit_message(view=self)
            
            sel.callback = sel_cb
            self.add_item(sel)

        btn_create = discord.ui.Button(label="➕ Create New List", style=discord.ButtonStyle.success, row=1)
        async def create_cb(interaction: discord.Interaction):
            await interaction.response.send_modal(MovieListFormModal(self.guild_id, str(self.user.id)))
        btn_create.callback = create_cb
        self.add_item(btn_create)

        btn_edit = discord.ui.Button(label="✏️ Edit Selected", style=discord.ButtonStyle.primary, row=1, disabled=self.selected_list is None)
        async def edit_cb(interaction: discord.Interaction):
            if self.selected_list.is_default and not self.user.guild_permissions.manage_guild:
                return await interaction.response.send_message("❌ Only server admins can edit the default Movie Night list.", ephemeral=True)
            await interaction.response.send_modal(MovieListFormModal(self.guild_id, str(self.user.id), self.selected_list))
        btn_edit.callback = edit_cb
        self.add_item(btn_edit)

        btn_delete = discord.ui.Button(label="🗑️ Delete Selected", style=discord.ButtonStyle.danger, row=1, disabled=self.selected_list is None)
        async def delete_cb(interaction: discord.Interaction):
            if self.selected_list.is_default:
                return await interaction.response.send_message("❌ The default Movie Night list cannot be deleted.", ephemeral=True)
            await DatabaseController.delete_movie_list(self.selected_list.id)
            self.selected_list = None
            await self.fetch_data()
            await self.build_ui()
            await interaction.response.edit_message(content="✅ List deleted.", embed=self.generate_embed(), view=self)
        btn_delete.callback = delete_cb
        self.add_item(btn_delete)


class MovieSearchSelectionView(discord.ui.View):
    def __init__(self, list_id: int, movies: list, custom_title: str, watch_date: str, host_info: str):
        super().__init__(timeout=120)
        self.list_id = list_id
        self.movies = movies
        self.custom_title = custom_title
        self.watch_date = watch_date
        self.host_info = host_info

        options =[]
        for m in movies[:25]:
            year = f" ({m.release_date[:4]})" if m.release_date else ""
            options.append(discord.SelectOption(label=f"{m.title}{year}"[:100], description=(m.overview or "")[:50], value=str(m.id)))
        
        options.append(discord.SelectOption(label="Use Custom Title Only (No Metadata)", value="manual_fallback", emoji="📝"))

        sel = discord.ui.Select(placeholder="Select the correct movie...", options=options)
        
        async def sel_cb(interaction: discord.Interaction):
            val = interaction.data['values'][0]
            if val == "manual_fallback":
                await DatabaseController.add_movie_to_list(self.list_id, None, self.custom_title, self.watch_date, self.host_info)
                await interaction.response.edit_message(content=f"✅ Added **{self.custom_title}** manually without metadata.", view=None)
            else:
                movie_id = int(val)
                selected_m = next((m for m in self.movies if m.id == movie_id), None)
                await DatabaseController.add_movie_to_list(self.list_id, movie_id, None, self.watch_date, self.host_info)
                await interaction.response.edit_message(content=f"✅ Successfully added **{selected_m.title if selected_m else 'Movie'}** to the list!", view=None)
                
        sel.callback = sel_cb
        self.add_item(sel)


class MovieAddModal(discord.ui.Modal, title="Add Movie to List"):
    movie_title = discord.ui.TextInput(label="Movie Title to Search", required=True)
    watch_date = discord.ui.TextInput(label="Watch Date / Schedule (Optional)", required=False, placeholder="e.g. Friday 8PM EST")
    
    # Renamed the label to imply it accepts plain names or raw pings alike.
    host_name = discord.ui.TextInput(label="Host Name or @User (Optional)", required=False, placeholder="e.g. Alice or @Alice")

    def __init__(self, list_id: int):
        super().__init__()
        self.list_id = list_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        query = self.movie_title.value.strip()
        w_date = self.watch_date.value.strip() if self.watch_date.value.strip() else None
        h_info = self.host_name.value.strip() if self.host_name.value.strip() else None

        results = await MoviesDBController.search_and_cache(query, limit=10)
        
        if not results:
            await DatabaseController.add_movie_to_list(self.list_id, None, query, w_date, h_info)
            await interaction.followup.send(f"⚠️ No TMDB results found. Added **{query}** manually as a text entry.", ephemeral=True)
        else:
            view = MovieSearchSelectionView(self.list_id, results, query, w_date, h_info)
            await interaction.followup.send(f"🔍 Found {len(results)} matches for **{query}**. Please select the correct one:", view=view, ephemeral=True)


class FilmCog(commands.Cog, name="film"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Verifying default Movie Night lists for all connected servers...")
        for guild in self.bot.guilds:
            await DatabaseController.ensure_default_movie_list(str(guild.id), str(self.bot.user.id))

    # Declare the top-level groups
    film_group = app_commands.Group(name="film", description="Film search and tools")
    movies_group = app_commands.Group(name="movies", description="Manage and interact with movie lists")
    list_group = app_commands.Group(name="list", description="View and delete lists", parent=movies_group)

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
            return []
        movies = await DatabaseController.search_movies(current, limit=25)
        choices = []
        for m in movies:
            year = f" ({m.release_date[:4]})" if m.release_date else ""
            display_name = f"{m.title}{year}"[:100]
            choices.append(app_commands.Choice(name=display_name, value=str(m.title)))
        return choices

    async def lists_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        
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

    # --- MOVIES COMMANDS ---
    @movies_group.command(name="manage", description="Open an interactive dashboard to create, edit, or delete your movie lists.")
    async def movies_manage(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await DatabaseController.ensure_default_movie_list(str(interaction.guild_id), str(self.bot.user.id))
        
        view = MovieListManageView(str(interaction.guild_id), interaction.user)
        await view.fetch_data()
        await view.build_ui()
        await interaction.followup.send(embed=view.generate_embed(), view=view, ephemeral=True)

    @movies_group.command(name="add", description="Add a new movie to a list.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def movies_add(self, interaction: discord.Interaction, list_name: str):
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.response.send_message("❌ List not found.", ephemeral=True)
            
        if not lst.is_default and lst.user_id != str(interaction.user.id) and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ You do not have permission to add movies to this list.", ephemeral=True)

        await interaction.response.send_modal(MovieAddModal(lst.id))

    # --- MOVIES LIST COMMANDS ---
    @list_group.command(name="show", description="Display all movies currently queued up on a specific list.")
    @app_commands.autocomplete(list_name=lists_autocomplete)
    async def list_show(self, interaction: discord.Interaction, list_name: str):
        await interaction.response.defer()
        lst = await DatabaseController.get_movie_list_by_name(str(interaction.guild_id), list_name)
        if not lst:
            return await interaction.followup.send("❌ List not found.")

        items = await DatabaseController.get_movie_list_items(lst.id)
        view = ListShowPaginator(lst, items)
        await interaction.followup.send(embed=view.generate_embed(), view=view)

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