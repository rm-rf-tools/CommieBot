import sqlite3
import os

DB_PATH = "data/mutual_aid.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}. Are you running this from the main bot directory?")
        return

    print(f"🔍 Connecting to database at {DB_PATH}...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        print("⏳ Adding 'status' column to 'form_submissions' table...")
        # Add the status column with 'pending' as the default value
        cursor.execute("ALTER TABLE form_submissions ADD COLUMN status VARCHAR DEFAULT 'pending'")
        
        conn.commit()
        print("✅ Migration successful! The 'status' column was added.")
        
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("⚠️ Migration skipped: The 'status' column already exists in 'form_submissions'.")
        elif "no such table" in str(e).lower():
            print("❌ Error: The 'form_submissions' table does not exist yet. Ensure the bot has run at least once with the new models.")
        else:
            print(f"❌ SQLite Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    migrate()