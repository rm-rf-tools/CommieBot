import sqlite3
import os

DB_PATH = "data/mutual_aid.db"

def migrate_cooldown():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    print(f"🔍 Connecting to database at {DB_PATH}...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        print("⏳ Adding 'cooldown_days' column to 'form_templates' table...")
        cursor.execute("ALTER TABLE form_templates ADD COLUMN cooldown_days INTEGER DEFAULT 0")
        
        conn.commit()
        print("✅ Migration successful! The 'cooldown_days' column was added.")
        
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("⚠️ Migration skipped: The 'cooldown_days' column already exists.")
        else:
            print(f"❌ SQLite Error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    migrate_cooldown()