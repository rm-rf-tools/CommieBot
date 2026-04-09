import aiosqlite
import os
import time
from typing import List, Optional
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
                    user_id TEXT,
                    amount_requested REAL,
                    amount_received REAL DEFAULT 0.0,
                    reason TEXT,
                    status TEXT DEFAULT 'active'
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS committees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    name TEXT,
                    description TEXT,
                    UNIQUE(guild_id, name COLLATE NOCASE)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS committee_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT,
                    user_id TEXT,
                    committee_id INTEGER,
                    role_type TEXT,
                    UNIQUE(guild_id, user_id, committee_id, role_type),
                    FOREIGN KEY(committee_id) REFERENCES committees(id) ON DELETE CASCADE
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS quote_templates (
                    name TEXT PRIMARY KEY,
                    file_path TEXT
                )
            ''')
            
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    guild_id TEXT,
                    user_id TEXT,
                    channel_id TEXT,
                    status TEXT DEFAULT 'active',
                    created_at INTEGER
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS ticket_staff_roles (
                    guild_id TEXT,
                    role_id TEXT,
                    PRIMARY KEY (guild_id, role_id)
                )
            ''')

            await db.commit()

            
            async with db.execute("PRAGMA table_info(server_configs)") as cursor:
                columns = [col[1] for col in await cursor.fetchall()]
                if "ticket_role_id" not in columns:
                    await db.execute("ALTER TABLE server_configs ADD COLUMN ticket_role_id TEXT")
            
            
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
        next_reminder = int(time.time()) + (86400 * 2)
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
                
# --- Commie Resource Planning ---

    @staticmethod
    async def setup_indexes():
        """Fixes the SQLite bug where multiple NULLs are allowed in UNIQUE constraints"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_global_roles 
                ON committee_assignments (guild_id, user_id, role_type) 
                WHERE committee_id IS NULL
            ''')
            await db.commit()

    @staticmethod
    async def create_committee(guild_id: str, name: str, description: str = "No description provided."):
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                cursor = await db.execute(
                    'INSERT INTO committees (guild_id, name, description) VALUES (?, ?, ?)', 
                    (guild_id, name, description)
                )
                await db.commit()
                return cursor.lastrowid
            except aiosqlite.IntegrityError:
                return None 

    @staticmethod
    async def get_all_committees(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, name, description FROM committees WHERE guild_id = ?', (guild_id,)) as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def get_committee_by_name(guild_id: str, name: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, name FROM committees WHERE guild_id = ? AND LOWER(name) = ?', (guild_id, name.lower())) as cursor:
                return await cursor.fetchone()

    @staticmethod
    async def get_user_committee_roles(guild_id: str, user_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT COALESCE(c.name, 'Global'), a.role_type 
                FROM committee_assignments a
                LEFT JOIN committees c ON a.committee_id = c.id
                WHERE a.guild_id = ? AND a.user_id = ?
            ''', (guild_id, user_id)) as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def assign_committee_role(guild_id: str, user_id: str, committee_id: int, role_type: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT OR IGNORE INTO committee_assignments (guild_id, user_id, committee_id, role_type) 
                VALUES (?, ?, ?, ?)
            ''', (guild_id, user_id, committee_id, role_type))
            await db.commit()

    @staticmethod
    async def get_committee_members(guild_id: str, committee_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT user_id, role_type 
                FROM committee_assignments 
                WHERE guild_id = ? AND committee_id = ?
            ''', (guild_id, committee_id)) as cursor:
                return await cursor.fetchall()
    @staticmethod
    async def update_committee_name(guild_id: str, committee_id: int, new_name: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE committees SET name = ? WHERE id = ? AND guild_id = ?', (new_name, committee_id, guild_id))
            await db.commit()

    @staticmethod
    async def delete_committee(guild_id: str, committee_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM committees WHERE id = ? AND guild_id = ?', (committee_id, guild_id))
            await db.commit()

    @staticmethod
    async def remove_assignment(guild_id: str, user_id: str, committee_id: Optional[int], role_type: str):
        async with aiosqlite.connect(DB_PATH) as db:
            if committee_id:
                await db.execute('''
                    DELETE FROM committee_assignments 
                    WHERE guild_id = ? AND user_id = ? AND committee_id = ? AND role_type = ?
                ''', (guild_id, user_id, committee_id, role_type))
            else:
                await db.execute('''
                    DELETE FROM committee_assignments 
                    WHERE guild_id = ? AND user_id = ? AND committee_id IS NULL AND role_type = ?
                ''', (guild_id, user_id, role_type))
            await db.commit()

    @staticmethod
    async def get_all_org_members(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT a.user_id, a.role_type, COALESCE(c.name, 'Global')
                FROM committee_assignments a
                LEFT JOIN committees c ON a.committee_id = c.id
                WHERE a.guild_id = ?
            ''', (guild_id,)) as cursor:
                return await cursor.fetchall()


    # --- TICKET METHODS ---
    @staticmethod
    async def create_ticket(ticket_id: str, guild_id: str, user_id: str, channel_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets (ticket_id, guild_id, user_id, channel_id, created_at) VALUES (?, ?, ?, ?, ?)', (ticket_id, guild_id, user_id, channel_id, int(time.time())))
            await db.commit()

    @staticmethod
    async def close_ticket_db(channel_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE tickets SET status = "closed" WHERE channel_id = ?', (channel_id,))
            await db.commit()

    @staticmethod
    async def close_all_active_tickets_db(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE tickets SET status = "closed" WHERE guild_id = ? AND status = "active"', (guild_id,))
            await db.commit()

    @staticmethod
    async def add_staff_role(guild_id: str, role_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO ticket_staff_roles (guild_id, role_id) VALUES (?, ?)', (guild_id, role_id))
            await db.commit()

    @staticmethod
    async def remove_staff_role(guild_id: str, role_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM ticket_staff_roles WHERE guild_id = ? AND role_id = ?', (guild_id, role_id))
            await db.commit()

    @staticmethod
    async def get_staff_roles(guild_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role_id FROM ticket_staff_roles WHERE guild_id = ?", (guild_id,)) as cursor:
                return [row[0] for row in await cursor.fetchall()]
