"""
db_init.py — Initialize the SQLite database schema.

Run once on first deploy and whenever the schema changes.
Usage: python tools/db_init.py
"""

import sqlite3
import os
import sys
from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", ".tmp/salon.db")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set."""
    os.makedirs(os.path.dirname(DATABASE_PATH) if os.path.dirname(DATABASE_PATH) else ".", exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't already exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                phone       TEXT    UNIQUE NOT NULL,
                notes       TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_visit  TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                google_event_id         TEXT    UNIQUE NOT NULL,
                client_id               INTEGER REFERENCES clients(id),
                service                 TEXT,
                stylist                 TEXT,
                start_time              TIMESTAMP NOT NULL,
                end_time                TIMESTAMP,
                status                  TEXT NOT NULL DEFAULT 'pending',
                confirmation_sent_at    TIMESTAMP,
                reminder_sent_at        TIMESTAMP,
                upsell_sent_at          TIMESTAMP,
                client_response         TEXT,
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS message_log (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id       INTEGER REFERENCES appointments(id),
                client_id            INTEGER REFERENCES clients(id),
                direction            TEXT NOT NULL,
                message_type         TEXT NOT NULL,
                content              TEXT,
                whatsapp_message_id  TEXT UNIQUE,
                sent_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_clients_phone
                ON clients(phone);

            CREATE INDEX IF NOT EXISTS idx_appointments_status
                ON appointments(status);

            CREATE INDEX IF NOT EXISTS idx_appointments_start_time
                ON appointments(start_time);

            CREATE INDEX IF NOT EXISTS idx_appointments_event_id
                ON appointments(google_event_id);

            CREATE INDEX IF NOT EXISTS idx_message_log_wa_id
                ON message_log(whatsapp_message_id);
        """)
        conn.commit()

        # Migrations — add columns / tables introduced after initial deploy
        try:
            conn.execute("ALTER TABLE appointments ADD COLUMN reschedule_state TEXT")
            conn.commit()
        except Exception:
            pass  # column already exists

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS booking_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                phone       TEXT UNIQUE NOT NULL,
                client_id   INTEGER REFERENCES clients(id),
                step        TEXT NOT NULL,
                service     TEXT,
                slots_json  TEXT,
                offered_at  TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        print(f"[db_init] Database ready at: {DATABASE_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("[db_init] Done.")
