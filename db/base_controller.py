"""base_controller.py"""

import os
import time
import csv
import asyncio
from typing import Optional
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, text
from .engine import engine, logger, DB_PATH
from .models import (
    ServerConfig, Aid, Committee, CommitteeAssignment, QuoteTemplate, Ticket, 
    TicketStaffRole, Profile, Skill, ProfileSkill, Event, EventAttendance,
    Applicant, FormTemplate, FormQuestion, FormSubmission, FormAnswer,
    ModWatch, ModLogConfig, FocusChannel, GrokReply, UserLastSeen, Movie,
    RolePlan, RolePlanItem, TrackedWord, WordGroup, TheoryResource, Fact, MovieListItem, MovieList
)

class DatabaseController:
    @staticmethod
    async def setup():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        from .engine import engine as e
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        
        # Trigger CSV Load on boot
        await DatabaseController.load_movies_from_csv()

    @staticmethod
    async def load_movies_from_csv():
        csv_path = "./data/csv/TMDB_movie_dataset.csv"
        if not os.path.exists(csv_path):
            logger.warning(f"Movie CSV not found at {csv_path}. Skipping movie load.")
            return

        async with AsyncSession(engine) as session:
            result = await session.execute(select(func.count(Movie.id)))
            count = result.scalar()
            
            if count and count > 0:
                logger.info(f"Database already contains {count} movies. Skipping CSV import.")
                return

            logger.info("Initializing TMDB Movie Database. This may take a moment...")
            try:
                def safe_int(v):
                    try: return int(float(v)) if v and str(v).strip() else 0
                    except: return 0
                
                def safe_float(v):
                    try: return float(v) if v and str(v).strip() else 0.0
                    except: return 0.0
                
                movies_to_insert = []
                seen_ids = set()
                skipped = 0
                
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        movie_id = safe_int(row.get('id'))
                        
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
                        
                        if len(movies_to_insert) >= 5000:
                            session.add_all(movies_to_insert)
                            await session.commit()
                            movies_to_insert.clear()
                            
                if movies_to_insert:
                    session.add_all(movies_to_insert)
                    await session.commit()
                    
                logger.info(f"✅ TMDB Movie Database successfully imported! Skipped {skipped} duplicate rows.")
            except Exception as e:
                logger.error(f"Failed to load movies: {e}")
                await session.rollback()

    @staticmethod
    async def search_movies(query: str, limit: int = 15):
        async with AsyncSession(engine) as session:
            if not query:
                return []
            terms = query.strip().split()
            stmt = select(Movie)
            for term in terms:
                stmt = stmt.where(Movie.title.ilike(f"%{term}%"))
            stmt = stmt.order_by(Movie.popularity.desc()).limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()

    # --- Movie List Methods ---
    @staticmethod
    async def create_movie_list(guild_id: str, user_id: str, name: str, description: str = None, is_default: bool = False) -> Optional[int]:
        async with AsyncSession(engine) as session:
            stmt = select(RolePlan).where(MovieList.guild_id == guild_id, func.lower(MovieList.name) == name.lower())
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                return None
            
            new_list = MovieList(guild_id=guild_id, user_id=user_id, name=name, description=description, is_default=is_default)
            session.add(new_list)
            await session.commit()
            await session.refresh(new_list)
            return new_list.id

    @staticmethod
    async def get_movie_lists(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(MovieList).where(MovieList.guild_id == guild_id).order_by(MovieList.name.asc())
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_movie_list_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(MovieList).where(MovieList.guild_id == guild_id, func.lower(MovieList.name) == name.lower())
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def get_movie_list_by_id(list_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(MovieList, list_id)

    @staticmethod
    async def edit_movie_list(list_id: int, new_name: str, new_description: str):
        async with AsyncSession(engine) as session:
            lst = await session.get(MovieList, list_id)
            if lst:
                lst.name = new_name
                lst.description = new_description
                await session.commit()

    @staticmethod
    async def delete_movie_list(list_id: int) -> bool:
        async with AsyncSession(engine) as session:
            lst = await session.get(MovieList, list_id)
            if lst:
                await session.delete(lst)
                await session.commit()
                return True
            return False

    @staticmethod
    async def add_movie_to_list(list_id: int, movie_id: int = None, custom_title: str = None, watch_date: str = None, host_id: str = None, order_index: int = 0):
        async with AsyncSession(engine) as session:
            item = MovieListItem(list_id=list_id, movie_id=movie_id, custom_title=custom_title, watch_date=watch_date, host_id=host_id, order_index=order_index)
            session.add(item)
            await session.commit()

    @staticmethod
    async def get_movie_list_items(list_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(MovieListItem, Movie).outerjoin(
                Movie, MovieListItem.movie_id == Movie.id
            ).where(MovieListItem.list_id == list_id).order_by(MovieListItem.order_index.asc(), MovieListItem.id.asc())
            result = await session.execute(stmt)
            return result.all()

    # --- Movie List Methods ---
    _populating_lists = set()

    @staticmethod
    async def clear_movie_list_items(list_id: int):
        """Wipes all movies currently in a specific list so it can be rebuilt clean."""
        async with AsyncSession(engine) as session:
            stmt = select(MovieListItem).where(MovieListItem.list_id == list_id)
            result = await session.execute(stmt)
            for item in result.scalars().all():
                await session.delete(item)
            await session.commit()

    @staticmethod
    async def ensure_default_movie_list(guild_id: str, bot_id: str):
        """Ensures the 'Movie Night' list exists and parses movielist.txt if newly created."""
        async with AsyncSession(engine) as session:
            stmt = select(MovieList).where(MovieList.guild_id == guild_id, MovieList.is_default == True)
            default_list = (await session.execute(stmt)).scalar_one_or_none()
            
            if not default_list:
                logger.info(f"Creating default Movie Night list for guild {guild_id}")
                default_list = MovieList(guild_id=guild_id, user_id=bot_id, name="Movie Night", description="Server default movie night list.", is_default=True)
                session.add(default_list)
                await session.commit()
                await session.refresh(default_list)
                
                import asyncio
                asyncio.create_task(DatabaseController._populate_default_list(default_list.id))
            else:
                # Check if it's completely empty, if so, trigger population just in case it failed before
                stmt_items = select(func.count(MovieListItem.id)).where(MovieListItem.list_id == default_list.id)
                count = (await session.execute(stmt_items)).scalar()
                if count == 0:
                    logger.info(f"Default list for guild {guild_id} is empty. Triggering population.")
                    import asyncio
                    asyncio.create_task(DatabaseController._populate_default_list(default_list.id))
            
            return default_list

    @staticmethod
    async def _populate_default_list(list_id: int):
        """Background task to populate the default list from CSV. Protected by a lock."""
        if list_id in DatabaseController._populating_lists:
            logger.warning(f"List {list_id} is already being populated. Skipping duplicate task.")
            return
            
        DatabaseController._populating_lists.add(list_id)
        import asyncio
        try:
            filepath = "data/csv/movielist.txt"
            if not os.path.exists(filepath):
                filepath = "data/csv/movieslist.txt"
                
            if not os.path.exists(filepath):
                logger.error(f"Could not find {filepath} to populate default list. Make sure the file exists!")
                return
                
            # Wipe existing items FIRST just to guarantee no duplicates if re-running
            await DatabaseController.clear_movie_list_items(list_id)
            
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            from .movies_api import MoviesDBController
            logger.info(f"Populating list ID {list_id} with {len(lines)} movies... This may take a minute.")
            
            for order, line in enumerate(lines):
                title = line.strip()
                if not title:
                    continue
                    
                # Clean up title: 'akira - 1988' -> 'akira'
                search_title = title.split("-")[0].strip()
                
                results = await MoviesDBController.search_and_cache(search_title, limit=1)
                movie_id = results[0].id if results else None
                custom_title = title if not movie_id else None
                
                await DatabaseController.add_movie_to_list(
                    list_id=list_id, 
                    movie_id=movie_id, 
                    custom_title=custom_title,
                    order_index=order
                )
                await asyncio.sleep(1.0) # Prevent TMDB rate limiting
                
            logger.info(f"✅ Finished populating default list ID {list_id}.")
        except Exception as e:
            logger.error(f"Error populating list: {e}", exc_info=True)
        finally:
            DatabaseController._populating_lists.discard(list_id)

    @staticmethod
    async def add_quote_template(name: str, file_path: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(QuoteTemplate, name)
            if obj:
                obj.file_path = file_path
            else:
                obj = QuoteTemplate(name=name, file_path=file_path)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_quote_template(name: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(QuoteTemplate, name)
            return obj.file_path if obj else None

    @staticmethod
    async def get_all_quote_templates():
        async with AsyncSession(engine) as session:
            stmt = select(QuoteTemplate).order_by(QuoteTemplate.name.asc())
            result = await session.execute(stmt)
            return [(obj.name,) for obj in result.scalars().all()]

    @staticmethod
    async def delete_quote_template(name: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(QuoteTemplate, name)
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def set_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.role_id if obj else None

    @staticmethod
    async def get_autorole_config(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                return obj.autorole_id, obj.autorole_enabled
            return None, False

    @staticmethod
    async def set_autorole(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.autorole_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, autorole_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def toggle_autorole(guild_id: str, enabled: bool):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.autorole_enabled = enabled
            else:
                obj = ServerConfig(guild_id=guild_id, autorole_enabled=enabled)
                session.add(obj)
            await session.commit()

    # --- Aid methods ---
    @staticmethod
    async def create_aid(guild_id: str, channel_id: str, user_id: str, name: str, amount: float, description: str):
        now = int(time.time())
        next_reminder = now + 86400
        obj = Aid(
            guild_id=guild_id, channel_id=channel_id, user_id=user_id, 
            name=name, amount_requested=amount, reason=description, 
            created_at=now, next_reminder_at=next_reminder
        )
        async with AsyncSession(engine) as session:
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def get_active_aid(aid_id: int, guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.id == aid_id,
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return (obj.amount_requested, obj.amount_received, obj.user_id)
            return None

    @staticmethod
    async def update_aid_progress(aid_id: int, new_total: float, status: str = 'active'):
        async with AsyncSession(engine) as session:
            obj = await session.get(Aid, aid_id)
            if obj:
                obj.amount_received = new_total
                obj.status = status
                await session.commit()

    @staticmethod
    async def get_all_active(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            return [(obj.id, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason) for obj in result.scalars().all()]

    @staticmethod
    async def delete_aid(aid_id: int, guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.id == aid_id,
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return False
            obj.status = 'deleted'
            await session.commit()
            return True

    @staticmethod
    async def clear_all_aids(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                obj.status = 'deleted'
            await session.commit()

    @staticmethod
    async def get_due_reminders():
        async with AsyncSession(engine) as session:
            now = int(time.time())
            stmt = select(Aid).where(
                Aid.status == 'active',
                Aid.next_reminder_at <= now,
                Aid.channel_id != None
            )
            result = await session.execute(stmt)
            return [(obj.id, obj.guild_id, obj.channel_id, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason) for obj in result.scalars().all()]

    @staticmethod
    async def reset_reminder(aid_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(Aid, aid_id)
            if obj:
                obj.next_reminder_at = int(time.time()) + 172800
                await session.commit()

    @staticmethod
    async def get_aid_by_id(aid_id: int, guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.id == aid_id,
                Aid.status == 'active',
                or_(Aid.guild_id == guild_id, Aid.guild_id == None)
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return (obj.id, obj.guild_id, obj.channel_id, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason)
            return None

    @staticmethod
    async def check_aid_name_exists(guild_id: str, name: str) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.guild_id == guild_id, 
                func.lower(Aid.name) == name.lower(),
                Aid.status == 'active'
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def search_aid_names(guild_id: str, query: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid.name).where(
                Aid.guild_id == guild_id,
                Aid.name.ilike(f"%{query}%")
            ).limit(25)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_aid_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.guild_id == guild_id,
                func.lower(Aid.name) == name.lower(),
                Aid.status == 'active'
            ).order_by(Aid.id.desc())
            result = await session.execute(stmt)
            obj = result.scalars().first()
            if not obj:
                stmt = select(Aid).where(Aid.guild_id == guild_id, func.lower(Aid.name) == name.lower()).order_by(Aid.id.desc())
                result = await session.execute(stmt)
                obj = result.scalars().first()
            if obj:
                return (obj.name, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason, obj.status)
            return None

    @staticmethod
    async def get_aid_name_by_id(aid_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(Aid, aid_id)
            return obj.name if obj else None

    @staticmethod
    async def update_aid_progress_by_name(guild_id: str, name: str, new_total: float, status: str = 'active'):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.guild_id == guild_id, 
                func.lower(Aid.name) == name.lower(),
                Aid.status == 'active'
            ).order_by(Aid.id.desc())
            result = await session.execute(stmt)
            obj = result.scalars().first()
            if not obj:
                stmt = select(Aid).where(Aid.guild_id == guild_id, func.lower(Aid.name) == name.lower()).order_by(Aid.id.desc())
                result = await session.execute(stmt)
                obj = result.scalars().first()
            if obj:
                obj.amount_received = new_total
                obj.status = status
                await session.commit()

    
    @staticmethod
    async def edit_aid(guild_id: str, old_name: str, new_name: str = None, amount: float = None, description: str = None):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.guild_id == guild_id, 
                func.lower(Aid.name) == old_name.lower(),
                Aid.status == 'active'
            ).order_by(Aid.id.desc())
            result = await session.execute(stmt)
            obj = result.scalars().first()
            if not obj:
                stmt = select(Aid).where(Aid.guild_id == guild_id, func.lower(Aid.name) == old_name.lower()).order_by(Aid.id.desc())
                result = await session.execute(stmt)
                obj = result.scalars().first()
            if obj:
                if new_name is not None: obj.name = new_name
                if amount is not None: obj.amount_requested = amount
                if description is not None: obj.reason = description
                await session.commit()
                return True
            return False

    
    @staticmethod
    async def delete_aid_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.guild_id == guild_id, 
                func.lower(Aid.name) == name.lower(),
                Aid.status == 'active'
            ).order_by(Aid.id.desc())
            result = await session.execute(stmt)
            obj = result.scalars().first()
            if not obj:
                stmt = select(Aid).where(Aid.guild_id == guild_id, func.lower(Aid.name) == name.lower()).order_by(Aid.id.desc())
                result = await session.execute(stmt)
                obj = result.scalars().first()
            if not obj:
                return False
            obj.status = 'deleted'
            await session.commit()
            return True

    @staticmethod
    async def get_aids_by_status(guild_id: str, status: str = None):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(or_(Aid.guild_id == guild_id, Aid.guild_id == None))
            if status:
                stmt = stmt.where(Aid.status == status)
            result = await session.execute(stmt)
            return [(obj.name, obj.user_id, obj.amount_requested, obj.amount_received, obj.reason, obj.status, obj.created_at) for obj in result.scalars().all()]

    @staticmethod
    async def get_user_aids(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Aid).where(
                Aid.guild_id == guild_id,
                Aid.user_id == user_id,
                Aid.status == 'active'
            ).order_by(Aid.id.desc())
            result = await session.execute(stmt)
            return[(obj.id, obj.name, obj.amount_requested, obj.amount_received, obj.reason) for obj in result.scalars().all()]
    
    # CRP 
    @staticmethod
    async def setup_indexes():
        pass

    @staticmethod
    async def create_committee(guild_id: str, name: str, description: str = "No description provided."):
        async with AsyncSession(engine) as session:
            obj = Committee(guild_id=guild_id, name=name, description=description)
            session.add(obj)
            try:
                await session.commit()
                await session.refresh(obj)
                return obj.id
            except IntegrityError:
                return None

    @staticmethod
    async def get_all_committees(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(Committee.guild_id == guild_id)
            result = await session.execute(stmt)
            return [(obj.id, obj.name, obj.description) for obj in result.scalars().all()]

    @staticmethod
    async def get_committee_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(
                Committee.guild_id == guild_id,
                func.lower(Committee.name) == name.lower()
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return (obj.id, obj.name)
            return None

    @staticmethod
    async def get_user_committee_roles(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee.name, CommitteeAssignment.role_type).select_from(CommitteeAssignment).outerjoin(
                Committee, CommitteeAssignment.committee_id == Committee.id
            ).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.user_id == user_id
            )
            result = await session.execute(stmt)
            return [(row[0] if row[0] is not None else 'Global', row[1]) for row in result.all()]

    @staticmethod
    async def assign_committee_role(guild_id: str, user_id: str, committee_id: int, role_type: str):
        async with AsyncSession(engine) as session:
            obj = CommitteeAssignment(guild_id=guild_id, user_id=user_id, committee_id=committee_id, role_type=role_type)
            session.add(obj)
            try:
                await session.commit()
            except IntegrityError:
                pass

    @staticmethod
    async def get_committee_members(guild_id: str, committee_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.committee_id == committee_id
            )
            result = await session.execute(stmt)
            return [(obj.user_id, obj.role_type) for obj in result.scalars().all()]

    @staticmethod
    async def update_committee_name(guild_id: str, committee_id: int, new_name: str):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(Committee.id == committee_id, Committee.guild_id == guild_id)
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                obj.name = new_name
                await session.commit()

    @staticmethod
    async def delete_committee(guild_id: str, committee_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(Committee).where(Committee.id == committee_id, Committee.guild_id == guild_id)
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def remove_assignment(guild_id: str, user_id: str, committee_id: Optional[int], role_type: str):
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.user_id == user_id,
                CommitteeAssignment.role_type == role_type
            )
            if committee_id:
                stmt = stmt.where(CommitteeAssignment.committee_id == committee_id)
            else:
                stmt = stmt.where(CommitteeAssignment.committee_id == None)
                
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                await session.delete(obj)
            await session.commit()

    @staticmethod
    async def get_all_org_members(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment.user_id, CommitteeAssignment.role_type, Committee.name).select_from(CommitteeAssignment).outerjoin(
                Committee, CommitteeAssignment.committee_id == Committee.id
            ).where(CommitteeAssignment.guild_id == guild_id)
            result = await session.execute(stmt)
            return [(row[0], row[1], row[2] if row[2] is not None else 'Global') for row in result.all()]

    @staticmethod
    async def create_ticket(ticket_id: str, guild_id: str, user_id: str, channel_id: str):
        async with AsyncSession(engine) as session:
            obj = Ticket(ticket_id=ticket_id, guild_id=guild_id, user_id=user_id, channel_id=channel_id, created_at=int(time.time()))
            session.add(obj)
            await session.commit()

    @staticmethod
    async def close_ticket_db(channel_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Ticket).where(Ticket.channel_id == channel_id)
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                obj.status = "closed"
            await session.commit()

    @staticmethod
    async def close_all_active_tickets_db(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Ticket).where(Ticket.guild_id == guild_id, Ticket.status == "active")
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                obj.status = "closed"
            await session.commit()

    @staticmethod
    async def add_staff_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = TicketStaffRole(guild_id=guild_id, role_id=role_id)
            session.add(obj)
            try:
                await session.commit()
            except IntegrityError:
                pass

    @staticmethod
    async def remove_staff_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(TicketStaffRole, (guild_id, role_id))
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_staff_roles(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(TicketStaffRole).where(TicketStaffRole.guild_id == guild_id)
            result = await session.execute(stmt)
            return [obj.role_id for obj in result.scalars().all()]

    @staticmethod
    async def set_crp_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.crp_role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, crp_role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_crp_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.crp_role_id if obj else None

    @staticmethod
    async def is_crp_member(guild_id: str, user_id: str) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(CommitteeAssignment).where(
                CommitteeAssignment.guild_id == guild_id,
                CommitteeAssignment.user_id == user_id
            ).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def create_skill(guild_id: str, name: str, description: str, is_wanted: bool) -> bool:
        async with AsyncSession(engine) as session:
            obj = Skill(guild_id=guild_id, name=name.strip(), description=description, is_wanted=1 if is_wanted else 0)
            session.add(obj)
            try:
                await session.commit()
                return True
            except IntegrityError:
                return False

    @staticmethod
    async def delete_skill(guild_id: str, name: str) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(Skill).where(Skill.guild_id == guild_id, func.lower(Skill.name) == name.lower())
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                return False
            stmt2 = select(ProfileSkill).where(ProfileSkill.guild_id == guild_id, ProfileSkill.skill_id == obj.id)
            result2 = await session.execute(stmt2)
            for ps in result2.scalars().all():
                await session.delete(ps)
            await session.delete(obj)
            await session.commit()
            return True

    @staticmethod
    async def get_all_server_skills(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Skill).where(Skill.guild_id == guild_id).order_by(Skill.is_wanted.desc(), Skill.name.asc())
            result = await session.execute(stmt)
            return [(obj.id, obj.name, obj.description, obj.is_wanted) for obj in result.scalars().all()]

    @staticmethod
    async def set_profile_skill(guild_id: str, user_id: str, skill_id: int, proficiency: str):
        async with AsyncSession(engine) as session:
            prof = await session.get(Profile, (guild_id, user_id))
            if not prof:
                session.add(Profile(guild_id=guild_id, user_id=user_id))
                try:
                    await session.commit()
                except IntegrityError:
                    pass
            ps = await session.get(ProfileSkill, (guild_id, user_id, skill_id))
            if ps:
                ps.proficiency = proficiency
            else:
                session.add(ProfileSkill(guild_id=guild_id, user_id=user_id, skill_id=skill_id, proficiency=proficiency))
            await session.commit()

    @staticmethod
    async def remove_profile_skill(guild_id: str, user_id: str, skill_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(ProfileSkill, (guild_id, user_id, skill_id))
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_user_skills(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Skill.name, ProfileSkill.proficiency).select_from(ProfileSkill).join(
                Skill, ProfileSkill.skill_id == Skill.id
            ).where(
                ProfileSkill.guild_id == guild_id,
                ProfileSkill.user_id == user_id
            ).order_by(Skill.name.asc())
            result = await session.execute(stmt)
            return [(row[0], row[1]) for row in result.all()]

    @staticmethod
    async def get_users_by_skill(guild_id: str, skill_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(ProfileSkill).where(
                ProfileSkill.guild_id == guild_id,
                ProfileSkill.skill_id == skill_id
            )
            result = await session.execute(stmt)
            return [(obj.user_id, obj.proficiency) for obj in result.scalars().all()]

    @staticmethod
    async def edit_skill(guild_id: str, name: str, description: str, is_wanted: bool) -> bool:
        async with AsyncSession(engine) as session:
            stmt = select(Skill).where(Skill.guild_id == guild_id, func.lower(Skill.name) == name.lower())
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                obj.description = description
                obj.is_wanted = 1 if is_wanted else 0
                await session.commit()
                return True
            return False

    @staticmethod
    async def get_skill_tree(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Skill.name, Skill.is_wanted, ProfileSkill.user_id, ProfileSkill.proficiency).select_from(Skill).outerjoin(
                ProfileSkill, Skill.id == ProfileSkill.skill_id
            ).where(Skill.guild_id == guild_id).order_by(Skill.is_wanted.desc(), Skill.name.asc(), ProfileSkill.proficiency.desc())
            result = await session.execute(stmt)
            return [(row[0], row[1], row[2], row[3]) for row in result.all()]

    @staticmethod
    async def update_skill_by_id(guild_id: str, skill_id: int, new_name: str, new_desc: str, is_wanted: bool) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(Skill, skill_id)
            if obj and obj.guild_id == guild_id:
                obj.name = new_name.strip()
                obj.description = new_desc
                obj.is_wanted = 1 if is_wanted else 0
                try:
                    await session.commit()
                    return True
                except IntegrityError:
                    return False
            return False

    @staticmethod
    async def delete_skill_by_id(guild_id: str, skill_id: int) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(Skill, skill_id)
            if obj and obj.guild_id == guild_id:
                stmt = select(ProfileSkill).where(ProfileSkill.guild_id == guild_id, ProfileSkill.skill_id == skill_id)
                result = await session.execute(stmt)
                for ps in result.scalars().all():
                    await session.delete(ps)
                await session.delete(obj)
                await session.commit()
                return True
            return False

    # --- Event / Attendance ---
    @staticmethod
    async def get_or_create_event(guild_id: str, name: str) -> int:
        async with AsyncSession(engine) as session:
            stmt = select(Event).where(
                Event.guild_id == guild_id,
                func.lower(Event.name) == name.lower()
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj:
                return obj.id
            
            now = int(time.time())
            obj = Event(guild_id=guild_id, name=name, created_at=now)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def log_attendance(event_id: int, user_ids: list[str]) -> int:
        added_count = 0
        async with AsyncSession(engine) as session:
            now = int(time.time())
            for uid in user_ids:
                obj = EventAttendance(event_id=event_id, user_id=uid, check_in_time=now)
                session.add(obj)
                try:
                    await session.commit()
                    added_count += 1
                except IntegrityError:
                    await session.rollback()
        return added_count

    # --- Forms ---
    @staticmethod
    async def get_applicant(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Applicant).where(
                Applicant.guild_id == guild_id, 
                Applicant.user_id == user_id
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def create_applicant(guild_id: str, user_id: str, username: str, preferred_name: str, pronouns: str):
        async with AsyncSession(engine) as session:
            obj = Applicant(
                guild_id=guild_id, user_id=user_id, username=username, 
                preferred_name=preferred_name, pronouns=pronouns
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

    @staticmethod
    async def get_all_forms(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormTemplate).where(FormTemplate.guild_id == guild_id)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_form_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormTemplate).where(
                FormTemplate.guild_id == guild_id,
                func.lower(FormTemplate.name) == name.lower()
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def get_form_by_id(form_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(FormTemplate, form_id)

    @staticmethod
    async def delete_form(form_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormTemplate, form_id)
            if obj:
                q_stmt = select(FormQuestion).where(FormQuestion.form_id == form_id)
                questions = await session.execute(q_stmt)
                for q in questions.scalars().all():
                    await session.delete(q)
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def add_form_question(form_id: int, text: str, q_type: str, options: str = None):
        async with AsyncSession(engine) as session:
            obj = FormQuestion(form_id=form_id, question_text=text, question_type=q_type, options=options)
            session.add(obj)
            await session.commit()

    @staticmethod
    async def delete_form_question(question_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormQuestion, question_id)
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_form_questions(form_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(FormQuestion).where(FormQuestion.form_id == form_id).order_by(FormQuestion.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def save_form_submission(form_id: int, applicant_id: int, answers: dict) -> int:
        async with AsyncSession(engine) as session:
            submission = FormSubmission(
                form_id=form_id, 
                applicant_id=applicant_id, 
                submitted_at=int(time.time()), 
                status="pending"
            )
            session.add(submission)
            await session.flush()
            sub_id = submission.id
            
            for q_id, ans_text in answers.items():
                ans_obj = FormAnswer(
                    submission_id=sub_id,
                    question_id=q_id,
                    answer_text=ans_text
                )
                session.add(ans_obj)
                
            await session.commit()
            return sub_id

    @staticmethod
    async def get_pending_submissions(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormSubmission, FormTemplate, Applicant).join(
                FormTemplate, FormSubmission.form_id == FormTemplate.id
            ).join(
                Applicant, FormSubmission.applicant_id == Applicant.id
            ).where(
                FormTemplate.guild_id == guild_id,
                FormSubmission.status == "pending"
            ).order_by(FormSubmission.submitted_at.asc())
            result = await session.execute(stmt)
            return result.all()

    @staticmethod
    async def get_submission_answers(submission_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(FormQuestion.question_text, FormAnswer.answer_text).join(
                FormAnswer, FormQuestion.id == FormAnswer.question_id
            ).where(FormAnswer.submission_id == submission_id).order_by(FormQuestion.id.asc())
            result = await session.execute(stmt)
            return result.all()

    @staticmethod
    async def update_submission_status(submission_id: int, status: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormSubmission, submission_id)
            if obj:
                obj.status = status
                await session.commit()

    @staticmethod
    async def create_form(guild_id: str, name: str, description: str, cooldown_days: int = 0):
        async with AsyncSession(engine) as session:
            obj = FormTemplate(
                guild_id=guild_id, name=name, description=description, 
                created_at=int(time.time()), cooldown_days=cooldown_days
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def check_recent_submission(form_id: int, applicant_id: int, cooldown_days: int) -> bool:
        if cooldown_days <= 0:
            return False
        async with AsyncSession(engine) as session:
            cutoff_time = int(time.time()) - (cooldown_days * 24 * 60 * 60)
            stmt = select(FormSubmission).where(
                FormSubmission.form_id == form_id,
                FormSubmission.applicant_id == applicant_id,
                FormSubmission.submitted_at >= cutoff_time
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def update_form_details(form_id: int, name: str, description: str, cooldown_days: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormTemplate, form_id)
            if obj:
                obj.name = name
                obj.description = description
                obj.cooldown_days = cooldown_days
                await session.commit()

    @staticmethod
    async def get_form_question_by_id(question_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(FormQuestion, question_id)

    @staticmethod
    async def update_form_question(question_id: int, text: str, q_type: str, options: str = None):
        async with AsyncSession(engine) as session:
            obj = await session.get(FormQuestion, question_id)
            if obj:
                obj.question_text = text
                obj.question_type = q_type
                obj.options = options
                await session.commit()

    @staticmethod
    async def set_forms_role(guild_id: str, role_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.forms_role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, forms_role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_forms_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.forms_role_id if obj else None

    @staticmethod
    async def get_historical_submissions(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FormSubmission, FormTemplate, Applicant).join(
                FormTemplate, FormSubmission.form_id == FormTemplate.id
            ).join(
                Applicant, FormSubmission.applicant_id == Applicant.id
            ).where(
                FormTemplate.guild_id == guild_id,
                FormSubmission.status != "pending"
            ).order_by(FormSubmission.submitted_at.desc())
            result = await session.execute(stmt)
            return result.all()

    @staticmethod
    async def add_to_watch_list(guild_id: str, user_id: str, reason: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ModWatch, (guild_id, user_id))
            if obj:
                obj.reason = reason
            else:
                obj = ModWatch(guild_id=guild_id, user_id=user_id, reason=reason)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def remove_from_watch_list(guild_id: str, user_id: str) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(ModWatch, (guild_id, user_id))
            if obj:
                await session.delete(obj)
                await session.commit()
                return True
            return False

    @staticmethod
    async def get_watch_list(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(ModWatch).where(ModWatch.guild_id == guild_id)
            result = await session.execute(stmt)
            return result.scalars().all()
    
    @staticmethod
    async def log_channel_audit(guild_id: str, channel_id: str, channel_name: str, user_id: str, action: str, changes: str):
        async with AsyncSession(engine) as session:
            try:
                from .models import ChannelAuditLog
                now = int(time.time())
                obj = ChannelAuditLog(
                    guild_id=guild_id, channel_id=channel_id, channel_name=channel_name,
                    user_id=user_id, action=action, changes=changes, timestamp=now
                )
                session.add(obj)
                await session.commit()
            except ImportError:
                pass

    @staticmethod
    async def get_channel_audit_logs(guild_id: str, user_id: Optional[str] = None, action: Optional[str] = None, limit: int = 50):
        async with AsyncSession(engine) as session:
            try:
                from .models import ChannelAuditLog
                stmt = select(ChannelAuditLog).where(ChannelAuditLog.guild_id == guild_id)
                if user_id:
                    stmt = stmt.where(ChannelAuditLog.user_id == user_id)
                if action:
                    stmt = stmt.where(ChannelAuditLog.action == action)
                stmt = stmt.order_by(ChannelAuditLog.timestamp.desc()).limit(limit)
                result = await session.execute(stmt)
                return result.scalars().all()
            except ImportError:
                return []

    @staticmethod
    async def get_modlog_config(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ModLogConfig, guild_id)
            if not obj:
                obj = ModLogConfig(guild_id=guild_id)
                session.add(obj)
                await session.commit()
                await session.refresh(obj)
            return obj

    @staticmethod
    async def set_modlog_channel(guild_id: str, channel_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ModLogConfig, guild_id)
            if not obj:
                obj = ModLogConfig(guild_id=guild_id, log_channel_id=channel_id)
                session.add(obj)
            else:
                obj.log_channel_id = channel_id
            await session.commit()

    @staticmethod
    async def toggle_modlog_event(guild_id: str, event: str, state: bool):
        async with AsyncSession(engine) as session:
            obj = await session.get(ModLogConfig, guild_id)
            if not obj:
                obj = ModLogConfig(guild_id=guild_id)
                session.add(obj)
            setattr(obj, event, state)
            await session.commit()

    @staticmethod
    async def update_tracked_words(guild_id: str, words: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ModLogConfig, guild_id)
            if not obj:
                obj = ModLogConfig(guild_id=guild_id, tracked_words=words)
                session.add(obj)
            else:
                obj.tracked_words = words
            await session.commit()
            
    # Focus Mode
    @staticmethod
    async def set_focus_role(guild_id: str, role_id: Optional[str]):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.focus_role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, focus_role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_focus_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.focus_role_id if obj else None

    @staticmethod
    async def add_focus_channel(guild_id: str, channel_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(FocusChannel, (guild_id, channel_id))
            if not obj:
                obj = FocusChannel(guild_id=guild_id, channel_id=channel_id)
                session.add(obj)
                await session.commit()

    @staticmethod
    async def remove_focus_channel(guild_id: str, channel_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(FocusChannel, (guild_id, channel_id))
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def get_focus_channels(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(FocusChannel).where(FocusChannel.guild_id == guild_id)
            result = await session.execute(stmt)
            return [obj.channel_id for obj in result.scalars().all()]

    # --- GROK COMMANDS ---
    @staticmethod
    async def add_grok_reply(guild_id: str, text: str, category: str = "general", keywords: str = None, intent: str = "neutral"):
        async with AsyncSession(engine) as session:
            obj = GrokReply(
                guild_id=guild_id, 
                reply_text=text, 
                category=category, 
                keywords=keywords, 
                intent=intent
            )
            session.add(obj)
            await session.commit()

    @staticmethod
    async def get_grok_replies(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(GrokReply).where(GrokReply.guild_id == guild_id)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def edit_grok_reply(reply_id: int, new_text: str = None, category: str = None, keywords: str = None, intent: str = None) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(GrokReply, reply_id)
            if obj:
                if new_text is not None:
                    obj.reply_text = new_text
                if category is not None:
                    obj.category = category
                if keywords is not None:
                    obj.keywords = keywords
                if intent is not None:
                    obj.intent = intent
                await session.commit()
                return True
            return False

    @staticmethod
    async def delete_grok_reply(reply_id: int) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(GrokReply, reply_id)
            if obj:
                await session.delete(obj)
                await session.commit()
                return True
            return False

    @staticmethod
    async def clear_all_grok_replies(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(GrokReply).where(GrokReply.guild_id == guild_id)
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                await session.delete(obj)
            await session.commit()

    # --- LAST SEEN TRACKING ---
    @staticmethod
    async def update_last_seen(guild_id: str, user_id: str, timestamp: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(UserLastSeen, (guild_id, user_id))
            if obj:
                obj.last_seen_at = timestamp
            else:
                obj = UserLastSeen(guild_id=guild_id, user_id=user_id, last_seen_at=timestamp)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_last_seen(guild_id: str, user_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(UserLastSeen, (guild_id, user_id))
            return obj.last_seen_at if obj else None

    # --- TOTAL RAISED ---
    @staticmethod
    async def get_total_raised(guild_id: Optional[str] = None):
        async with AsyncSession(engine) as session:
            stmt = select(func.sum(Aid.amount_received))
            if guild_id:
                stmt = stmt.where(Aid.guild_id == guild_id)
            result = await session.execute(stmt)
            total = result.scalar_one_or_none()
            return total if total is not None else 0.0

    # --- REACT ROLES ---
    @staticmethod
    async def create_role_plan(guild_id: str, name: str) -> Optional[int]:
        async with AsyncSession(engine) as session:
            stmt = select(RolePlan).where(RolePlan.guild_id == guild_id, func.lower(RolePlan.name) == name.lower())
            res = await session.execute(stmt)
            if res.scalar_one_or_none():
                return None 
            plan = RolePlan(guild_id=guild_id, name=name)
            session.add(plan)
            await session.commit()
            await session.refresh(plan)
            return plan.id

    @staticmethod
    async def get_role_plan_by_name(guild_id: str, name: str):
        async with AsyncSession(engine) as session:
            stmt = select(RolePlan).where(RolePlan.guild_id == guild_id, func.lower(RolePlan.name) == name.lower())
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    @staticmethod
    async def delete_role_plan(plan_id: int):
        async with AsyncSession(engine) as session:
            # Manually cascade delete to fix SQLite leaving ghost rows
            items_stmt = select(RolePlanItem).where(RolePlanItem.plan_id == plan_id)
            items = await session.execute(items_stmt)
            for item in items.scalars().all():
                await session.delete(item)
            obj = await session.get(RolePlan, plan_id)
            if obj:
                await session.delete(obj)
            await session.commit()

    @staticmethod
    async def add_role_plan_item(plan_id: int, role_name: str, category: str, color: int, emoji: str, description: str):
        async with AsyncSession(engine) as session:
            item = RolePlanItem(plan_id=plan_id, role_name=role_name, category=category, role_color=color, emoji=emoji, description=description)
            session.add(item)
            await session.commit()

    @staticmethod
    async def get_role_plan_items(plan_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(RolePlanItem).where(RolePlanItem.plan_id == plan_id).order_by(RolePlanItem.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()
            
    @staticmethod
    async def get_all_role_plans(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(RolePlan).where(RolePlan.guild_id == guild_id).order_by(RolePlan.name.asc())
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def delete_role_plan_item(item_id: int):
        async with AsyncSession(engine) as session:
            obj = await session.get(RolePlanItem, item_id)
            if obj:
                await session.delete(obj)
                await session.commit()

    @staticmethod
    async def update_role_plan_item(item_id: int, role_name: str, category: str, color: int, emoji: str, description: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(RolePlanItem, item_id)
            if obj:
                obj.role_name = role_name
                obj.category = category
                obj.role_color = color
                obj.emoji = emoji
                obj.description = description
                await session.commit()

    # --- Tracked Words ---
    @staticmethod
    async def add_tracked_word(guild_id: str, pattern: str, is_regex: bool = False, action: str = "notify", group_id: int = None, name: str = None) -> int:
        async with AsyncSession(engine) as session:
            obj = TrackedWord(guild_id=guild_id, name=name, pattern=pattern, is_regex=is_regex, action=action, group_id=group_id)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def get_tracked_words(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(TrackedWord).where(TrackedWord.guild_id == guild_id).order_by(TrackedWord.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_tracked_word_by_id(word_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(TrackedWord, word_id)

    @staticmethod
    async def update_tracked_word(word_id: int, pattern: str = None, is_regex: bool = None, action: str = None, name: str = None) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(TrackedWord, word_id)
            if not obj:
                return False
            if name is not None:
                obj.name = name
            if pattern is not None:
                obj.pattern = pattern
            if is_regex is not None:
                obj.is_regex = is_regex
            if action is not None:
                obj.action = action
            await session.commit()
            return True

    @staticmethod
    async def delete_tracked_word(word_id: int) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(TrackedWord, word_id)
            if not obj:
                return False
            await session.delete(obj)
            await session.commit()
            return True

    # --- Word Groups ---
    @staticmethod
    async def create_word_group(guild_id: str, name: str, action: str = "notify") -> int:
        async with AsyncSession(engine) as session:
            obj = WordGroup(guild_id=guild_id, name=name, action=action, created_at=int(time.time()))
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def get_word_groups(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(WordGroup).where(WordGroup.guild_id == guild_id).order_by(WordGroup.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_word_group_by_id(group_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(WordGroup, group_id)

    @staticmethod
    async def update_word_group_action(group_id: int, action: str):
        """Update the group's action and cascade to all words in the group."""
        async with AsyncSession(engine) as session:
            obj = await session.get(WordGroup, group_id)
            if not obj:
                return False
            obj.action = action
            stmt = select(TrackedWord).where(TrackedWord.group_id == group_id)
            result = await session.execute(stmt)
            for word in result.scalars().all():
                word.action = action
            await session.commit()
            return True

    @staticmethod
    async def delete_word_group(group_id: int, delete_words: bool = True):
        """Delete a group. If delete_words, also delete all words in it; otherwise unlink them."""
        async with AsyncSession(engine) as session:
            stmt = select(TrackedWord).where(TrackedWord.group_id == group_id)
            result = await session.execute(stmt)
            for word in result.scalars().all():
                if delete_words:
                    await session.delete(word)
                else:
                    word.group_id = None
            obj = await session.get(WordGroup, group_id)
            if obj:
                await session.delete(obj)
            await session.commit()
            return True

    @staticmethod
    async def get_words_by_group(group_id: int):
        async with AsyncSession(engine) as session:
            stmt = select(TrackedWord).where(TrackedWord.group_id == group_id).order_by(TrackedWord.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_word_group_count(group_id: int) -> int:
        async with AsyncSession(engine) as session:
            stmt = select(func.count(TrackedWord.id)).where(TrackedWord.group_id == group_id)
            result = await session.execute(stmt)
            return result.scalar() or 0

    @staticmethod
    async def bulk_add_tracked_words(guild_id: str, patterns: list[str], is_regex: bool = False, action: str = "notify", group_id: int = None, names: list[str] = None) -> int:
        """Add multiple tracked words at once. Returns count of words added."""
        added = 0
        async with AsyncSession(engine) as session:
            for idx, pattern in enumerate(patterns):
                pattern = pattern.strip()
                if not pattern:
                    continue
                word_name = names[idx] if names and idx < len(names) else None
                obj = TrackedWord(guild_id=guild_id, name=word_name, pattern=pattern, is_regex=is_regex, action=action, group_id=group_id)
                session.add(obj)
                added += 1
            await session.commit()
        return added

    @staticmethod
    async def delete_all_tracked_words(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(TrackedWord).where(TrackedWord.guild_id == guild_id)
            result = await session.execute(stmt)
            for obj in result.scalars().all():
                await session.delete(obj)
            await session.commit()

    @staticmethod
    async def cleanup_orphaned_role_items():
        async with AsyncSession(engine) as session:
            valid_plans = await session.execute(select(RolePlan.id))
            valid_plan_ids = [r for r in valid_plans.scalars().all()]
            stmt = select(RolePlanItem)
            if valid_plan_ids:
                stmt = stmt.where(RolePlanItem.plan_id.not_in(valid_plan_ids))
            orphans = await session.execute(stmt)
            count = 0
            for orphan in orphans.scalars().all():
                await session.delete(orphan)
                count += 1
            if count > 0:
                await session.commit()
            return count
    # Theory Resources
    @staticmethod
    async def add_theory_resource(title: str, resource_type: str, url: str = None, file_data: bytes = None, file_name: str = None, description: str = None, tags: str = None):
        async with AsyncSession(engine) as session:
            resource = TheoryResource(
                title=title, 
                resource_type=resource_type, 
                url=url, 
                file_data=file_data, 
                file_name=file_name, 
                description=description, 
                tags=tags
            )
            session.add(resource)
            await session.commit()
            return resource

    @staticmethod
    async def edit_theory_resource(resource_id: int, title: str = None, url: str = None, description: str = None, tags: str = None):
        async with AsyncSession(engine) as session:
            resource = await session.get(TheoryResource, resource_id)
            if not resource:
                return False
            if title is not None:
                resource.title = title
            if url is not None:
                resource.url = url
            if description is not None:
                resource.description = description
            if tags is not None:
                resource.tags = tags
            await session.commit()
            return True

    @staticmethod
    async def get_theory_resource_by_id(resource_id: int):
        async with AsyncSession(engine) as session:
            return await session.get(TheoryResource, resource_id)

    @staticmethod
    async def delete_theory_resource(resource_id: int):
        async with AsyncSession(engine) as session:
            resource = await session.get(TheoryResource, resource_id)
            if resource:
                await session.delete(resource)
                await session.commit()
                return True
            return False

    @staticmethod
    async def get_all_theory_resources():
        async with AsyncSession(engine) as session:
            result = await session.execute(select(TheoryResource))
            return result.scalars().all()

    @staticmethod
    async def search_theory_resources(query: str, limit: int = 500): # Increased default limit
        async with AsyncSession(engine) as session:
            if not query:
                # Remove the .limit(25) to allow browsing the whole library
                stmt = select(TheoryResource).order_by(TheoryResource.title.asc())
                result = await session.execute(stmt)
                return result.scalars().all()

            terms = query.strip().split()
            stmt = select(TheoryResource)
            
            for term in terms:
                # For every word in the search, it must appear in either Title, Tags, or Description
                term_filter = f"%{term}%"
                stmt = stmt.where(
                    or_(
                        TheoryResource.title.ilike(term_filter),
                        TheoryResource.tags.ilike(term_filter),
                        TheoryResource.description.ilike(term_filter)
                    )
                )
            
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_all_theory_tags():
        async with AsyncSession(engine) as session:
            result = await session.execute(select(TheoryResource.tags))
            tags_raw = result.scalars().all()
            unique_tags = set()
            for tr in tags_raw:
                if tr:
                    for t in tr.split(','):
                        t_clean = t.strip().lower()
                        if t_clean: 
                            unique_tags.add(t_clean)
            return sorted(list(unique_tags))

    @staticmethod
    async def get_theory_resources_by_tag(tag: str):
        async with AsyncSession(engine) as session:
            stmt = select(TheoryResource).where(TheoryResource.tags.icontains(tag))
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def clear_all_theory_resources():
        async with AsyncSession(engine) as session:
            # This generates the DELETE statement programmatically
            await session.execute(delete(TheoryResource))
            await session.commit()

    @staticmethod
    async def bulk_add_theory_resources(resources_data: list):
        async with AsyncSession(engine) as session:
            added = 0
            for item in resources_data:
                stmt = select(TheoryResource).where(TheoryResource.title == item['title'])
                existing = (await session.execute(stmt)).first()
                if not existing:
                    new_res = TheoryResource(**item)
                    session.add(new_res)
                    added += 1
            await session.commit()
            return added

    @staticmethod
    async def set_facts_role(guild_id: str, role_id: Optional[str]):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.facts_role_id = role_id
            else:
                obj = ServerConfig(guild_id=guild_id, facts_role_id=role_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_facts_role(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.facts_role_id if obj else None

    @staticmethod
    async def set_facts_channel(guild_id: str, channel_id: Optional[str]):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            if obj:
                obj.facts_channel_id = channel_id
            else:
                obj = ServerConfig(guild_id=guild_id, facts_channel_id=channel_id)
                session.add(obj)
            await session.commit()

    @staticmethod
    async def get_facts_channel(guild_id: str):
        async with AsyncSession(engine) as session:
            obj = await session.get(ServerConfig, guild_id)
            return obj.facts_channel_id if obj else None

    @staticmethod
    async def add_fact(guild_id: str, content: str, added_by: str) -> int:
        async with AsyncSession(engine) as session:
            obj = Fact(guild_id=guild_id, content=content, added_by=added_by)
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj.id

    @staticmethod
    async def delete_fact(fact_id: int) -> bool:
        async with AsyncSession(engine) as session:
            obj = await session.get(Fact, fact_id)
            if obj:
                await session.delete(obj)
                await session.commit()
                return True
            return False

    @staticmethod
    async def get_random_fact(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Fact).where(Fact.guild_id == guild_id).order_by(func.random()).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
            
    @staticmethod
    async def search_facts(guild_id: str, query: str):
        async with AsyncSession(engine) as session:
            stmt = select(Fact).where(
                Fact.guild_id == guild_id,
                Fact.content.ilike(f"%{query}%")
            ).limit(25)
            result = await session.execute(stmt)
            return result.scalars().all()
            
    @staticmethod
    async def get_all_facts(guild_id: str):
        async with AsyncSession(engine) as session:
            stmt = select(Fact).where(Fact.guild_id == guild_id).order_by(Fact.id.asc())
            result = await session.execute(stmt)
            return result.scalars().all()