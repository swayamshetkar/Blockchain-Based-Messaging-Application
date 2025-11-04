# migrate.py
from database import init_db, ensure_committed_column

if __name__ == "__main__":
    print("🚀 Running schema migration...")
    init_db()
    ensure_committed_column()
    print("✅ Migration complete.")
