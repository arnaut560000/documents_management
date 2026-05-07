import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def resolve_path(value, fallback):
    path = Path(value or fallback)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


DATABASE_PATH = resolve_path(os.getenv("DATABASE_PATH"), INSTANCE_DIR / "neeco_dms.db")
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")


def create_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=float(os.getenv("SQLITE_TIMEOUT", "10")))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {int(os.getenv('SQLITE_BUSY_TIMEOUT_MS', '10000'))}")
    return conn


with create_connection() as conn:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_no TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            current_status TEXT NOT NULL DEFAULT 'On Process',
            holder_user_id INTEGER,
            file_name TEXT,
            original_file_name TEXT,
            uploaded_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(holder_user_id) REFERENCES users(id),
            FOREIGN KEY(uploaded_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS document_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            remarks TEXT,
            holder_user_id INTEGER,
            updated_by INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES documents(id),
            FOREIGN KEY(holder_user_id) REFERENCES users(id),
            FOREIGN KEY(updated_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "must_change_password" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

    existing_admin = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (DEFAULT_ADMIN_USERNAME,),
    ).fetchone()
    if not existing_admin:
        conn.execute(
            """
            INSERT INTO users (full_name, username, password, role, must_change_password)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "System Administrator",
                DEFAULT_ADMIN_USERNAME,
                generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                "admin",
                1,
            ),
        )

print("Database initialized successfully.")
print(f"SQLite file: {DATABASE_PATH}")
print(f"Default login: {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
print("Change the default admin password on first login.")
print("Fresh install: no staff users, documents, uploads, history, or audit data were seeded.")
