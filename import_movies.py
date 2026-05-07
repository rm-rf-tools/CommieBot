"""import_movies.py"""

import asyncio
import csv
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlmodel import SQLModel

from db.models import Movie

DB_PATH = "./data/mutual_aid.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.lstrip('./')}"

engine = create_async_engine(DATABASE_URL, echo=False)

async def import_data():
    print("Connecting to database...")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Clear existing movies to ensure a clean import
        print("Clearing old movie data...")
        await conn.execute(text("DELETE FROM movies"))
        
    csv_path = "./data/csv/TMDB_movie_dataset.csv"
    if not os.path.exists(csv_path):
        print(f"Error: CSV not found at {csv_path}")
        return

    print("Importing TMDB Movie Database. This may take a moment...")
    
    seen_ids = set() # <--- Tracks IDs to prevent UNIQUE constraint crashes
    
    async with AsyncSession(engine) as session:
        def safe_int(v):
            try: return int(float(v)) if v and str(v).strip() else 0
            except: return 0
            
        def safe_float(v):
            try: return float(v) if v and str(v).strip() else 0.0
            except: return 0.0
            
        movies_to_insert = []
        count = 0
        skipped = 0
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                movie_id = safe_int(row.get('id'))
                
                # Skip duplicate IDs and invalid IDs (0)
                if movie_id in seen_ids or movie_id == 0:
                    skipped += 1
                    continue
                    
                seen_ids.add(movie_id)
                
                movie = Movie(
                    id=movie_id,
                    title=row.get('title', 'Unknown')[:255],
                    vote_average=safe_float(row.get('vote_average')),
                    vote_count=safe_int(row.get('vote_count')),
                    status=row.get('status'),
                    release_date=row.get('release_date'),
                    revenue=safe_int(row.get('revenue')),
                    runtime=safe_int(row.get('runtime')),
                    adult=row.get('adult'),
                    backdrop_path=row.get('backdrop_path'),
                    budget=safe_int(row.get('budget')),
                    homepage=row.get('homepage'),
                    imdb_id=row.get('imdb_id'),
                    original_language=row.get('original_language'),
                    original_title=str(row.get('original_title'))[:255] if row.get('original_title') else None,
                    overview=row.get('overview'),
                    popularity=safe_float(row.get('popularity')),
                    poster_path=row.get('poster_path'),
                    tagline=row.get('tagline'),
                    genres=row.get('genres'),
                    production_companies=row.get('production_companies'),
                    production_countries=row.get('production_countries'),
                    spoken_languages=row.get('spoken_languages'),
                    keywords=row.get('keywords')
                )
                movies_to_insert.append(movie)
                count += 1
                
                # Batch commit
                if len(movies_to_insert) >= 5000:
                    session.add_all(movies_to_insert)
                    await session.commit()
                    print(f"Inserted {count} movies... (Skipped {skipped} duplicates)")
                    movies_to_insert.clear()
                    
        # Commit remaining
        if movies_to_insert:
            session.add_all(movies_to_insert)
            await session.commit()
            
        print(f"✅ TMDB Movie Database successfully imported! Inserted {count} total. (Skipped {skipped} duplicates)")

if __name__ == "__main__":
    asyncio.run(import_data())