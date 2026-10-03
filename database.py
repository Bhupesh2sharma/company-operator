import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parent / "operator.db"

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def initialize_database():
    connection = get_connection()

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS task_checkpoints (
                task_id TEXT PRIMARY KEY,
                history_json TEXT NOT NULL,
                completed_calls INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                legal_name_key TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                registered_address TEXT NOT NULL,
                service_category TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, legal_name_key)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_at TEXT
            )
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                one_pending_approval_per_task
            ON approvals (task_id)
            WHERE status = 'pending'
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS vendor_creation_receipts (
                approval_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                vendor_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        task_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tasks)")
        }

        if "task_type" not in task_columns:
            connection.execute("""
                ALTER TABLE tasks
                ADD COLUMN task_type TEXT NOT NULL DEFAULT 'general'
            """)

        if "target_vendor_id" not in task_columns:
            connection.execute("""
                ALTER TABLE tasks
                ADD COLUMN target_vendor_id TEXT
            """)
        connection.commit()
    finally:
        connection.close()