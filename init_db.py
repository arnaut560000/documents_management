import os
import random
import sqlite3
from datetime import datetime, timedelta
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

FAKE_PASSWORD = "password123"
FAKE_STAFF_USERS = [
    ("Maria Santos", "maria.santos"),
    ("Jose Reyes", "jose.reyes"),
    ("Ana Cruz", "ana.cruz"),
    ("Miguel Garcia", "miguel.garcia"),
    ("Liza Mendoza", "liza.mendoza"),
    ("Carlo Dela Pena", "carlo.delapena"),
    ("Nina Flores", "nina.flores"),
    ("Ramon Aquino", "ramon.aquino"),
]
STATUS_CHOICES = [
    "Pending",
    "Received",
    "Under Review",
    "On Process",
    "Approved",
    "Released",
    "Returned",
]
CATEGORIES = [
    "Billing",
    "Engineering",
    "Finance",
    "Human Resources",
    "Legal",
    "Maintenance",
    "Operations",
    "Procurement",
    "Service Request",
    "Technical Report",
]
TITLE_TEMPLATES = [
    "Service connection request",
    "Meter replacement order",
    "Billing adjustment memo",
    "Transformer inspection report",
    "Purchase requisition",
    "Incident response summary",
    "Right-of-way clearance",
    "Member account update",
    "Disbursement voucher",
    "Preventive maintenance schedule",
    "Load assessment form",
    "Customer complaint record",
]
DESCRIPTION_TEMPLATES = [
    "Generated sample record for dashboard testing and workflow review.",
    "Placeholder document used to validate search, filters, and status updates.",
    "Demo entry for training users on document monitoring procedures.",
    "Sample office transaction with assigned holder and status history.",
]
LOCATIONS = [
    "Bongabon",
    "Cabanatuan",
    "Cabiao",
    "Gabaldon",
    "Gapan",
    "General Tinio",
    "Laur",
    "Palayan",
    "Penaranda",
    "San Isidro",
    "San Leonardo",
    "Santa Rosa",
]
REQUEST_TYPES = [
    "field validation",
    "routing",
    "approval",
    "site inspection",
    "billing review",
    "technical review",
    "account verification",
]
STATUS_WEIGHTS = [18, 12, 14, 20, 16, 12, 8]


def create_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=float(os.getenv("SQLITE_TIMEOUT", "10")))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {int(os.getenv('SQLITE_BUSY_TIMEOUT_MS', '10000'))}")
    return conn


def ensure_fake_staff_users(conn):
    user_ids = []
    password_hash = generate_password_hash(FAKE_PASSWORD)

    for full_name, username in FAKE_STAFF_USERS:
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if existing_user:
            user_ids.append(existing_user["id"])
            continue

        cursor = conn.execute(
            """
            INSERT INTO users (full_name, username, password, role, must_change_password)
            VALUES (?, ?, ?, ?, ?)
            """,
            (full_name, username, password_hash, "staff", 1),
        )
        user_ids.append(cursor.lastrowid)

    return user_ids


def random_timestamp(days_back=90):
    now = datetime.now()
    random_days = random.randint(0, days_back)
    random_minutes = random.randint(0, 24 * 60)
    return (now - timedelta(days=random_days, minutes=random_minutes)).strftime("%Y-%m-%d %H:%M:%S")


def choose_holder(holder_user_ids):
    if not holder_user_ids or random.random() < 0.15:
        return None
    return random.choice(holder_user_ids)


def build_fake_document(index, holder_user_ids):
    created_at = random_timestamp()
    final_status = random.choices(STATUS_CHOICES, weights=STATUS_WEIGHTS, k=1)[0]
    updated_at = random_timestamp(30)
    if updated_at < created_at:
        updated_at = created_at

    title = f"{random.choice(TITLE_TEMPLATES)} - {random.choice(LOCATIONS)} #{random.randint(1000, 9999)}"
    description = (
        f"{random.choice(DESCRIPTION_TEMPLATES)} "
        f"Prepared for {random.choice(REQUEST_TYPES)} in {random.choice(LOCATIONS)}."
    )

    return {
        "doc_no": f"FAKE-DOC-{index:03d}",
        "title": title,
        "description": description,
        "category": random.choice(CATEGORIES),
        "current_status": final_status,
        "holder_user_id": choose_holder(holder_user_ids),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def build_fake_history(document_id, current_status, holder_user_id, updated_by, created_at, updated_at):
    status_index = STATUS_CHOICES.index(current_status)
    status_path = STATUS_CHOICES[: status_index + 1]
    if len(status_path) > 4:
        middle_statuses = random.sample(status_path[1:-1], 2)
        middle_statuses.sort(key=STATUS_CHOICES.index)
        status_path = [status_path[0], *middle_statuses, status_path[-1]]

    history_rows = []
    start_time = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
    total_seconds = max(int((end_time - start_time).total_seconds()), 0)

    for step, status in enumerate(status_path):
        old_status = status_path[step - 1] if step else None
        if len(status_path) == 1 or total_seconds == 0:
            activity_time = end_time
        else:
            offset = int(total_seconds * (step / (len(status_path) - 1)))
            activity_time = start_time + timedelta(seconds=offset)

        history_rows.append(
            (
                document_id,
                old_status,
                status,
                random.choice(
                    [
                        "Random sample workflow update.",
                        "Forwarded for normal processing.",
                        "Checked during seeded data refresh.",
                        "Assigned through sample routing.",
                    ]
                ),
                holder_user_id,
                updated_by,
                activity_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    return history_rows


def seed_fake_documents(conn, uploaded_by, holder_user_ids, count=106):
    inserted_count = 0
    refreshed_count = 0

    for index in range(1, count + 1):
        fake_document = build_fake_document(index, holder_user_ids)
        doc_no = fake_document["doc_no"]
        existing_document = conn.execute(
            "SELECT id FROM documents WHERE doc_no = ?",
            (doc_no,),
        ).fetchone()

        if existing_document:
            document_id = existing_document["id"]
            conn.execute(
                """
                UPDATE documents
                SET title = ?,
                    description = ?,
                    category = ?,
                    current_status = ?,
                    holder_user_id = ?,
                    uploaded_by = ?,
                    created_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    fake_document["title"],
                    fake_document["description"],
                    fake_document["category"],
                    fake_document["current_status"],
                    fake_document["holder_user_id"],
                    uploaded_by,
                    fake_document["created_at"],
                    fake_document["updated_at"],
                    document_id,
                ),
            )
            conn.execute("DELETE FROM document_status_history WHERE document_id = ?", (document_id,))
            refreshed_count += 1
        else:
            cursor = conn.execute(
                """
                INSERT INTO documents
                (doc_no, title, description, category, current_status, holder_user_id, uploaded_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_no,
                    fake_document["title"],
                    fake_document["description"],
                    fake_document["category"],
                    fake_document["current_status"],
                    fake_document["holder_user_id"],
                    uploaded_by,
                    fake_document["created_at"],
                    fake_document["updated_at"],
                ),
            )
            document_id = cursor.lastrowid
            inserted_count += 1

        conn.executemany(
            """
            INSERT INTO document_status_history
            (document_id, old_status, new_status, remarks, holder_user_id, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            build_fake_history(
                document_id,
                fake_document["current_status"],
                fake_document["holder_user_id"],
                uploaded_by,
                fake_document["created_at"],
                fake_document["updated_at"],
            ),
        )

    return inserted_count, refreshed_count


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
            current_status TEXT NOT NULL DEFAULT 'Pending',
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
        cursor = conn.execute(
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
        admin_id = cursor.lastrowid
    else:
        admin_id = existing_admin["id"]

    fake_staff_user_ids = ensure_fake_staff_users(conn)
    inserted_fake_documents, refreshed_fake_documents = seed_fake_documents(conn, admin_id, fake_staff_user_ids)

print("Database initialized successfully.")
print(f"SQLite file: {DATABASE_PATH}")
print(f"Default login: {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
print("Change the default admin password on first login.")
print(f"Fake documents added: {inserted_fake_documents}")
print(f"Fake documents randomized: {refreshed_fake_documents}")
