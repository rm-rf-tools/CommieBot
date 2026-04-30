"""film.py"""

import discord
from discord import app_commands
from discord.ext import commands
import logging

from database import DatabaseController

# Set up logging for Docker
logger = logging.getLogger("FilmCog")
logger.setLevel(logging.INFO)

# --- GUI / PAGINATION FOR SLIDES ---
class MoviePaginator(discord.ui.View):
    def __init__(self, movies: list):
        super().__init__(timeout=180)  # Expires after 3 mins
        self.movies = movies
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = self.current_page == 0
        self.next_btn.disabled = self.current_page == len(self.movies) - 1

    def generate_embed(self) -> discord.Embed:
        movie = self.movies[self.current_page]
        
        # Build Title with Year if available
        year = movie.release_date[:4] if movie.release_date else "Unknown Year"
        title_str = f"🎬 {movie.title} ({year})"
        
        embed = discord.Embed(
            title=title_str,
            description=movie.overview or "*No description available.*",
            color=discord.Color.purple(),
            url=movie.homepage if movie.homepage else f"https://www.imdb.com/title/{movie.imdb_id}/"
        )

        # Build TMDB Image URL
        if movie.poster_path:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{movie.poster_path}")
        if movie.backdrop_path:
            embed.set_image(url=f"https://image.tmdb.org/t/p/original{movie.backdrop_path}")

        # Adding fields
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


class FilmCog(commands.GroupCog, name="film"):
    def __init__(self, bot):
        self.bot = bot

    # --- ERROR HANDLING / PERMISSION LOGGING ---
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        logger.error(f"Error caught in FilmCog by {interaction.user}: {error}")
        
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message
            
        if isinstance(error, app_commands.MissingPermissions):
            await send("❌ **Permission Denied:** You do not have the right permissions to search the archives.", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            logger.warning(f"Bot missing permissions: {perms}")
            await send(f"❌ **Server Error:** I am missing the following permissions to run this command: `{perms}`. Please ask an admin to grant them.", ephemeral=True)
        else:
            await send(f"❌ An unexpected system error occurred while fetching the movie data: {error}", ephemeral=True)

    # --- AUTOCOMPLETE LOGIC ---
    async def movie_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Handles the live fuzzy-like searching as the user types."""
        if not current:
            return []
            
        movies = await DatabaseController.search_movies(current, limit=25)
        
        # Formats the dropdown as: "Inception (2010)"
        choices = []
        for m in movies:
            year = f" ({m.release_date[:4]})" if m.release_date else ""
            display_name = f"{m.title}{year}"
            # Discord choice names can max be 100 chars
            display_name = display_name[:100]
            choices.append(app_commands.Choice(name=display_name, value=str(m.title)))
            
        return choices

    # --- MOVIE SEARCH COMMAND ---
    @app_commands.command(name="search", description="Search for a movie and view a beautiful preview card!")
    @app_commands.describe(query="Type to search for movies (auto-completes as you type)")
    @app_commands.autocomplete(query=movie_autocomplete)
    # Require standard message sending perms so the bot doesn't crash on restrictive channels
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True) 
    async def film_search(self, interaction: discord.Interaction, query: str):
        logger.info(f"User {interaction.user} searched for movie: {query}")
        await interaction.response.defer()

        # Execute Search
        results = await DatabaseController.search_movies(query, limit=10)

        if not results:
            logger.info(f"No results found for '{query}'")
            return await interaction.followup.send(f"❌ No movies found matching **{query}**. The database might be empty or still loading.")

        # Initialize the slide paginator
        view = MoviePaginator(results)
        
        # Send the first "Card"
        logger.info(f"Successfully returned {len(results)} movies to {interaction.user}.")
        await interaction.followup.send(embed=view.generate_embed(), view=view)

async def setup(bot):
    await bot.add_cog(FilmCog(bot))
    logger.info("FilmCog loaded successfully.")