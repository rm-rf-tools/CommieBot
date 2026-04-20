import sqlite3
import os

DB_PATH = "./data/mutual_aid.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}.")
        print("Make sure you are running this from the root of your CommieBot folder.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("Migrating server_configs table...")

    # 1. Add autorole_id column
    try:
        cursor.execute("ALTER TABLE server_configs ADD COLUMN autorole_id VARCHAR;")
        print("✅ Successfully added 'autorole_id' column.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("⚠️ 'autorole_id' column already exists. Skipping.")
        else:
            print(f"❌ Error adding 'autorole_id': {e}")

    # 2. Add autorole_enabled column (Defaulting to 0 / False)
    try:
        cursor.execute("ALTER TABLE server_configs ADD COLUMN autorole_enabled BOOLEAN NOT NULL DEFAULT 0;")
        print("✅ Successfully added 'autorole_enabled' column.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("⚠️ 'autorole_enabled' column already exists. Skipping.")
        else:
            print(f"❌ Error adding 'autorole_enabled': {e}")

    conn.commit()
    conn.close()
    print("🚀 Migration complete! You can now start the bot.")

if __name__ == "__main__":
    migrate()