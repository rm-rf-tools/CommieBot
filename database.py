import aiosqlite
import os
import time

DB_PATH = "./data/mutual_aid.db"

class DatabaseController:
    @staticmethod
    async def setup():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS server_configs (
                    guild_id TEXT PRIMARY KEY,
                    role_id TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS aids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT,
                    amount_requested REAL,
                    amount_received REAL DEFAULT 0.0,
                    reason TEXT,
                    status TEXT DEFAULT 'active'
                )
            ''')
            # NEW: Quote Templates table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS quote_templates (
                    name TEXT PRIMARY KEY,
                    file_path TEXT
                )
            ''')
            # Migrations
            async with db.execute("PRAGMA table_info(aids)") as cursor:
                columns = [col[1] for col in await cursor.fetchall()]
                if "guild_id" not in columns:
                    await db.execute("ALTER TABLE aids ADD COLUMN guild_id TEXT")
                if "channel_id" not in columns:
                    await db.execute("ALTER TABLE aids ADD COLUMN channel_id TEXT")
                if "created_at" not in columns:
                    await db.execute("ALTER TABLE aids ADD COLUMN created_at INTEGER")
                if "next_reminder_at" not in columns:
                    await db.execute("ALTER TABLE aids ADD COLUMN next_reminder_at INTEGER")
            await db.commit()

    # --- QUOTE MAKER METHODS ---
    @staticmethod
    async def add_quote_template(name: str, file_path: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO quote_templates (name, file_path) VALUES (?, ?)', (name, file_path))
            await db.commit()

    @staticmethod
    async def get_quote_template(name: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT file_path FROM quote_templates WHERE name = ?', (name,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    @staticmethod
    async def get_all_quote_templates():
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT name FROM quote_templates ORDER BY name ASC') as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def delete_quote_template(name: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM quote_templates WHERE name = ?", (name,))
            await db.commit()
            
    # --- MUTUAL AID METHODS ---
    @staticmethod
    async def set_role(guild_id: str, role_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO server_configs (guild_id, role_id) VALUES (?, ?)', (guild_id, role_id))
            await db.commit()

    @staticmethod
    async def get_role(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role_id FROM server_configs WHERE guild_id = ?", (guild_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    @staticmethod
    async def create_aid(guild_id: str, channel_id: str, user_id: str, amount: float, description: str):
        now = int(time.time())
        next_reminder = now + 86400 
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('''
                INSERT INTO aids (guild_id, channel_id, user_id, amount_requested, reason, created_at, next_reminder_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (guild_id, channel_id, user_id, amount, description, now, next_reminder))
            await db.commit()
            return cursor.lastrowid

    @staticmethod
    async def get_active_aid(aid_id: int, guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT amount_requested, amount_received, user_id 
                FROM aids WHERE id = ? AND status = 'active' AND (guild_id = ? OR guild_id IS NULL)
            ''', (aid_id, guild_id)) as cursor:
                return await cursor.fetchone()

    @staticmethod
    async def update_aid_progress(aid_id: int, new_total: float, status: str = 'active'):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE aids SET amount_received = ?, status = ? WHERE id = ?", (new_total, status, aid_id))
            await db.commit()

    @staticmethod
    async def get_all_active(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT id, user_id, amount_requested, amount_received, reason 
                FROM aids WHERE status = 'active' AND (guild_id = ? OR guild_id IS NULL)
            ''', (guild_id,)) as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def delete_aid(aid_id: int, guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id FROM aids WHERE id = ? AND status = 'active' AND (guild_id = ? OR guild_id IS NULL)", (aid_id, guild_id)) as cursor:
                if not await cursor.fetchone():
                    return False
            await db.execute("UPDATE aids SET status = 'deleted' WHERE id = ?", (aid_id,))
            await db.commit()
            return True

    @staticmethod
    async def clear_all(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE aids SET status = 'deleted' WHERE status = 'active' AND (guild_id = ? OR guild_id IS NULL)", (guild_id,))
            await db.commit()

    @staticmethod
    async def get_due_reminders():
        now = int(time.time())
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT id, guild_id, channel_id, user_id, amount_requested, amount_received, reason 
                FROM aids WHERE status = 'active' AND next_reminder_at <= ? AND channel_id IS NOT NULL
            ''', (now,)) as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def reset_reminder(aid_id: int):
        next_reminder = int(time.time()) + 86400
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE aids SET next_reminder_at = ? WHERE id = ?", (next_reminder, aid_id))
            await db.commit()

    @staticmethod
    async def get_aid_by_id(aid_id: int, guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT id, guild_id, channel_id, user_id, amount_requested, amount_received, reason 
                FROM aids WHERE id = ? AND status = 'active' AND (guild_id = ? OR guild_id IS NULL)
            ''', (aid_id, guild_id)) as cursor:
                return await cursor.fetchone()