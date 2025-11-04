# database.py
import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "blocknet.db")

def get_conn():
    """
    Returns a fresh SQLite connection with safe settings.
    Each FastAPI request or async task should call this instead of sharing globals.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # write-ahead logging for concurrency
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    """Initialize database and create tables if they don’t exist."""
    conn = get_conn()
    cur = conn.cursor()

    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        address TEXT PRIMARY KEY,
        enc_pub TEXT NOT NULL,
        sign_pub TEXT NOT NULL,
        created_at INTEGER
    );
    """)

    # Messages table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cid TEXT NOT NULL,
        sender TEXT NOT NULL,
        recipient TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        delivered INTEGER DEFAULT 0,
        root_id TEXT,
        session_id TEXT,
        committed INTEGER DEFAULT 0
    );
    """)

    # Blocks table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        idx INTEGER PRIMARY KEY AUTOINCREMENT,
        previous_hash TEXT,
        merkle_root TEXT,
        cids TEXT,
        proposer TEXT,
        signature TEXT,
        timestamp INTEGER
    );
    """)

    # Indexes for performance
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recipient ON messages(recipient);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rootid ON messages(root_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cid ON messages(cid);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_committed ON messages(committed);")

    # Peers table for discovery/registration
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS peers (
            url TEXT PRIMARY KEY,
            last_seen INTEGER
        );
        """
    )

    conn.commit()
    conn.close()
    return get_conn()


def ensure_committed_column():
    """Safe migration: ensure 'committed' column exists in messages."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cols = [c[1] for c in cur.execute("PRAGMA table_info(messages)").fetchall()]
        if "committed" not in cols:
            cur.execute("ALTER TABLE messages ADD COLUMN committed INTEGER DEFAULT 0;")
            conn.commit()
            print("🧩 Added missing 'committed' column to messages table.")
    except Exception as e:
        print("⚠️ Migration check failed:", e)
    finally:
        conn.close()
