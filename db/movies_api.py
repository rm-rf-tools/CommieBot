import os
import asyncio
import tmdbsimple as tmdb
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from db.engine import engine, logger
from db.models import Movie
from db.base_controller import DatabaseController

load_dotenv()
tmdb.API_KEY = os.getenv('MOVIEDB_API_KEY')
tmdb.REQUESTS_TIMEOUT = 5

class MoviesDBController:
    @staticmethod
    async def search_and_cache(query: str, limit: int = 15):
        """Searches local DB first. If insufficient results, falls back to TMDB API and caches locally."""
        if not query:
            return[]
            
        local_results = await DatabaseController.search_movies(query, limit)
        
        # If we already have strong local results, return them immediately
        if len(local_results) >= 5:
            return local_results
            
        if not tmdb.API_KEY:
            logger.warning("No MOVIEDB_API_KEY set. Falling back to local only.")
            return local_results

        try:
            search = tmdb.Search()
            # tmdbsimple is synchronous, so we run it in a thread to prevent blocking the Discord event loop
            await asyncio.to_thread(search.movie, query=query)
            
            api_movies = search.results
            if not api_movies:
                return local_results
            
            # Extract all IDs returned by the API
            api_ids = [item.get('id') for item in api_movies if item.get('id')]
            
            async with AsyncSession(engine) as session:
                # VERY IMPORTANT: Check the massive 1.4M row database to see if these API movies already exist!
                existing_stmt = select(Movie.id).where(Movie.id.in_(api_ids))
                existing_ids = set((await session.execute(existing_stmt)).scalars().all())
                
                new_movies =[]
                for item in api_movies:
                    mid = item.get('id')
                    # If the movie already exists in the local database, skip inserting it
                    if not mid or mid in existing_ids:
                        continue
                    
                    movie = Movie(
                        id=mid,
                        title=item.get('title', 'Unknown')[:255],
                        vote_average=float(item.get('vote_average', 0.0) or 0.0),
                        vote_count=int(item.get('vote_count', 0) or 0),
                        release_date=item.get('release_date'),
                        adult=str(item.get('adult', False)),
                        backdrop_path=item.get('backdrop_path'),
                        original_language=item.get('original_language'),
                        original_title=item.get('original_title')[:255] if item.get('original_title') else None,
                        overview=item.get('overview'),
                        popularity=float(item.get('popularity', 0.0) or 0.0),
                        poster_path=item.get('poster_path')
                    )
                    session.add(movie)
                    new_movies.append(movie)
                    existing_ids.add(mid) # Add to set to prevent duplicates within the same API payload
                    
                if new_movies:
                    await session.commit()
                    
            # Re-query local to return the combined sorted list
            return await DatabaseController.search_movies(query, limit)
            
        except Exception as e:
            logger.error(f"TMDB API Error: {e}")
            return local_results