import json
import os
import secrets
import sqlite3
import tempfile
import uuid
from pathlib import Path
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
IS_VERCEL = bool(os.getenv("VERCEL"))
VERCEL_TMP_DIR = Path(tempfile.gettempdir())
DEFAULT_DATABASE_PATH = VERCEL_TMP_DIR / "neeco_dms.db" if IS_VERCEL else INSTANCE_DIR / "neeco_dms.db"
DEFAULT_UPLOAD_FOLDER = VERCEL_TMP_DIR / "uploads" if IS_VERCEL else BASE_DIR / "uploads"


def _resolve_path(value, fallback, base_dir=BASE_DIR):
    raw_value = value or str(fallback)
    path = Path(raw_value)
    if not path.is_absolute():
        path = base_dir / path
    return path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    WRITABLE_BASE_DIR = VERCEL_TMP_DIR if IS_VERCEL else BASE_DIR
    DATABASE = str(_resolve_path(os.getenv("DATABASE_PATH"), DEFAULT_DATABASE_PATH, WRITABLE_BASE_DIR))
    UPLOAD_FOLDER = str(_resolve_path(os.getenv("UPLOAD_FOLDER"), DEFAULT_UPLOAD_FOLDER, WRITABLE_BASE_DIR))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
    SQLITE_TIMEOUT = float(os.getenv("SQLITE_TIMEOUT", "10"))
    SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "10000"))
    ALLOWED_EXTENSIONS = {
        ext.strip().lower().lstrip(".")
        for ext in os.getenv(
            "ALLOWED_EXTENSIONS",
            "pdf,doc,docx,xls,xlsx,jpg,jpeg,png",
        ).split(",")
        if ext.strip()
    }
    STATUS_CHOICES = ["On Process", "Settled"]
    CATEGORY_CHOICES = ["Net Metering", "Survey", "Interruption", "Others"]
    DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")


app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config["SECRET_KEY"]

Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)


def create_connection():
    conn = sqlite3.connect(
        app.config["DATABASE"],
        timeout=app.config["SQLITE_TIMEOUT"],
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {app.config['SQLITE_BUSY_TIMEOUT_MS']}")
    return conn


def get_db():
    if "db" not in g:
        g.db = create_connection()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_column(conn, table_name, column_name, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def initialize_database():
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

        ensure_column(conn, "users", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            UPDATE documents
            SET current_status = CASE
                WHEN current_status IN ('Approved', 'Released', 'Settled') THEN 'Settled'
                ELSE 'On Process'
            END
            WHERE current_status NOT IN ('On Process', 'Settled')
            """
        )

        existing_admin = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (app.config["DEFAULT_ADMIN_USERNAME"],),
        ).fetchone()

        if not existing_admin:
            conn.execute(
                """
                INSERT INTO users (full_name, username, password, role, must_change_password)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "System Administrator",
                    app.config["DEFAULT_ADMIN_USERNAME"],
                    generate_password_hash(app.config["DEFAULT_ADMIN_PASSWORD"]),
                    "admin",
                    0 if IS_VERCEL else 1,
                ),
            )
        elif IS_VERCEL:
            conn.execute(
                """
                UPDATE users
                SET password = ?, role = 'admin', is_active = 1, must_change_password = 0
                WHERE username = ?
                """,
                (
                    generate_password_hash(app.config["DEFAULT_ADMIN_PASSWORD"]),
                    app.config["DEFAULT_ADMIN_USERNAME"],
                ),
            )


def log_audit(action, target_type=None, target_id=None, details=None, user_id=None, conn=None):
    active_conn = conn or get_db()
    payload = json.dumps(details, ensure_ascii=True) if details is not None else None
    active_conn.execute(
        """
        INSERT INTO audit_logs (user_id, action, target_type, target_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id if user_id is not None else session.get("user_id"),
            action,
            target_type,
            target_id,
            payload,
        ),
    )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]


def get_active_users(conn=None):
    active_conn = conn or get_db()
    return active_conn.execute(
        "SELECT id, full_name FROM users WHERE is_active = 1 ORDER BY full_name ASC"
    ).fetchall()


def generate_document_number(conn):
    for _ in range(20):
        doc_no = str(secrets.randbelow(90000000) + 10000000)
        existing = conn.execute("SELECT id FROM documents WHERE doc_no = ?", (doc_no,)).fetchone()
        if not existing:
            return doc_no
    return uuid.uuid4().hex[:12].upper()


def get_document_listing_data(search="", open_modal=""):
    conn = get_db()
    total_docs = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()["total"]
    process_docs = conn.execute(
        "SELECT COUNT(*) AS total FROM documents WHERE current_status = 'On Process'"
    ).fetchone()["total"]
    settled_docs = conn.execute(
        "SELECT COUNT(*) AS total FROM documents WHERE current_status = 'Settled'"
    ).fetchone()["total"]

    if search:
        docs = conn.execute(
            """
            SELECT d.*, u.full_name AS uploaded_by_name, h.full_name AS holder_name
            FROM documents d
            LEFT JOIN users u ON d.uploaded_by = u.id
            LEFT JOIN users h ON d.holder_user_id = h.id
            WHERE d.doc_no LIKE ? OR d.title LIKE ? OR d.category LIKE ? OR d.current_status LIKE ?
            ORDER BY d.id DESC
            """,
            (f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        docs = conn.execute(
            """
            SELECT d.*, u.full_name AS uploaded_by_name, h.full_name AS holder_name
            FROM documents d
            LEFT JOIN users u ON d.uploaded_by = u.id
            LEFT JOIN users h ON d.holder_user_id = h.id
            ORDER BY d.id DESC
            """
        ).fetchall()

    listing_data = {
        "total_docs": total_docs,
        "process_docs": process_docs,
        "settled_docs": settled_docs,
        "docs": docs,
        "users": get_active_users(conn),
        "search": search,
        "open_modal": open_modal,
        "status_choices": app.config["STATUS_CHOICES"],
        "category_choices": app.config["CATEGORY_CHOICES"],
    }
    return listing_data


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Access denied.", "danger")
            return redirect(url_for("dashboard"))
        return view_func(*args, **kwargs)

    return wrapped_view


@app.before_request
def enforce_password_change():
    if not session.get("user_id") or not session.get("force_password_change"):
        return None

    allowed_endpoints = {"change_password", "logout", "static"}
    if request.endpoint not in allowed_endpoints:
        flash("Please change your password before continuing.", "warning")
        return redirect(url_for("change_password"))
    return None


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(error):
    flash(
        f"File is too large. Maximum allowed size is {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB.",
        "danger",
    )
    return redirect(url_for("dashboard", open_modal="add-document"))


@app.route("/")
@login_required
def dashboard():
    search = request.args.get("search", "").strip()
    open_modal = request.args.get("open_modal", "").strip()
    return render_template("dashboard.html", **get_document_listing_data(search, open_modal))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,),
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            session["force_password_change"] = bool(user["must_change_password"])

            log_audit("login", "user", user["id"], {"username": user["username"]}, user_id=user["id"], conn=conn)
            conn.commit()

            flash("Login successful.", "success")
            if user["must_change_password"]:
                flash("Your account is using an initial password. Please change it now.", "warning")
                return redirect(url_for("change_password"))
            return redirect(url_for("dashboard"))

        flash("Invalid username or password, or your account is inactive.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    conn = get_db()
    log_audit("logout", "user", session.get("user_id"), {"username": session.get("full_name")}, conn=conn)
    conn.commit()
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

        if not user or not check_password_hash(user["password"], current_password):
            flash("Current password is incorrect.", "danger")
            return render_template("change_password.html")

        if len(new_password) < 8:
            flash("New password must be at least 8 characters long.", "danger")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "danger")
            return render_template("change_password.html")

        if check_password_hash(user["password"], new_password):
            flash("Choose a different password from the current one.", "danger")
            return render_template("change_password.html")

        conn.execute(
            "UPDATE users SET password = ?, must_change_password = 0 WHERE id = ?",
            (generate_password_hash(new_password), session["user_id"]),
        )
        log_audit(
            "change password",
            "user",
            session["user_id"],
            {"forced_change_completed": True},
            conn=conn,
        )
        conn.commit()

        session["force_password_change"] = False
        flash("Password updated successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("change_password.html")


@app.route("/documents")
@login_required
def documents():
    search = request.args.get("search", "").strip()
    return redirect(url_for("dashboard", search=search))


@app.route("/documents/add", methods=["GET", "POST"])
@login_required
def add_document():
    if request.method == "POST":
        conn = get_db()
        doc_no = generate_document_number(conn)
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        current_status = request.form.get("current_status", "On Process").strip()
        holder_user_id = request.form.get("holder_user_id") or None

        if not title:
            flash("Document title is required.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))

        if category not in app.config["CATEGORY_CHOICES"]:
            flash("Please select a valid document category.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))

        if current_status not in app.config["STATUS_CHOICES"]:
            flash("Please select a valid document status.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))

        uploaded_file = request.files.get("file")
        saved_name = None
        original_name = None

        try:
            if uploaded_file and uploaded_file.filename:
                original_name = secure_filename(uploaded_file.filename)
                if not original_name:
                    flash("Uploaded file name is not valid.", "danger")
                    return redirect(url_for("dashboard", open_modal="add-document"))

                if not allowed_file(original_name):
                    allowed_list = ", ".join(sorted(app.config["ALLOWED_EXTENSIONS"]))
                    flash(f"Invalid file type. Allowed types: {allowed_list}.", "danger")
                    return redirect(url_for("dashboard", open_modal="add-document"))

                extension = original_name.rsplit(".", 1)[1].lower()
                saved_name = f"{uuid.uuid4().hex}.{extension}"
                destination = Path(app.config["UPLOAD_FOLDER"]) / saved_name
                uploaded_file.save(destination)

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO documents
                (doc_no, title, description, category, current_status, holder_user_id, file_name, original_file_name, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_no,
                    title,
                    description or None,
                    category,
                    current_status,
                    holder_user_id,
                    saved_name,
                    original_name,
                    session["user_id"],
                ),
            )
            document_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO document_status_history
                (document_id, old_status, new_status, remarks, holder_user_id, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    None,
                    current_status,
                    "Document uploaded",
                    holder_user_id,
                    session["user_id"],
                ),
            )

            log_audit(
                "upload document",
                "document",
                document_id,
                {
                    "doc_no": doc_no,
                    "title": title,
                    "status": current_status,
                    "holder_user_id": holder_user_id,
                    "original_file_name": original_name,
                    "saved_file_name": saved_name,
                },
                conn=conn,
            )
            conn.commit()
            flash("Document uploaded successfully.", "success")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            if saved_name:
                uploaded_path = Path(app.config["UPLOAD_FOLDER"]) / saved_name
                if uploaded_path.exists():
                    uploaded_path.unlink()
            conn.rollback()
            flash("A generated document number conflicted. Please try saving again.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))
        except sqlite3.OperationalError as exc:
            if saved_name:
                uploaded_path = Path(app.config["UPLOAD_FOLDER"]) / saved_name
                if uploaded_path.exists():
                    uploaded_path.unlink()
            conn.rollback()
            if "locked" in str(exc).lower():
                flash("The system is busy. Please try uploading the document again in a moment.", "danger")
                return redirect(url_for("dashboard", open_modal="add-document"))
            raise
        except OSError:
            flash("The document file could not be saved. Please try again.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))

    return render_template(
        "add_document.html",
        users=get_active_users(),
        status_choices=app.config["STATUS_CHOICES"],
        category_choices=app.config["CATEGORY_CHOICES"],
    )


@app.route("/documents/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_document(id):
    conn = get_db()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()

    if not document:
        flash("Document not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        holder_user_id = request.form.get("holder_user_id") or None

        if not title:
            flash("Document title is required.", "danger")
            return render_template(
                "edit_document.html",
                document=document,
                users=get_active_users(conn),
                category_choices=app.config["CATEGORY_CHOICES"],
            )

        if category not in app.config["CATEGORY_CHOICES"]:
            flash("Please select a valid document category.", "danger")
            return render_template(
                "edit_document.html",
                document=document,
                users=get_active_users(conn),
                category_choices=app.config["CATEGORY_CHOICES"],
            )

        try:
            conn.execute(
                """
                UPDATE documents
                SET title = ?, description = ?, category = ?, holder_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, description or None, category, holder_user_id, id),
            )
            log_audit(
                "edit document",
                "document",
                id,
                {
                    "doc_no": document["doc_no"],
                    "title": title,
                    "holder_user_id": holder_user_id,
                },
                conn=conn,
            )
            conn.commit()
            flash("Document updated successfully.", "success")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("Document number already exists. Please use a different value.", "danger")
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower():
                flash("The system is busy. Please try saving the document again.", "danger")
            else:
                raise

        document = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()

    return render_template(
        "edit_document.html",
        document=document,
        users=get_active_users(conn),
        category_choices=app.config["CATEGORY_CHOICES"],
    )


@app.route("/documents/update_status/<int:id>", methods=["POST"])
@login_required
def update_status(id):
    new_status = request.form.get("new_status", "").strip()
    remarks = request.form.get("remarks", "").strip()
    holder_user_id = request.form.get("holder_user_id") or None

    if new_status not in app.config["STATUS_CHOICES"]:
        return jsonify({"success": False, "message": "Invalid status selected."}), 400

    conn = get_db()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()

    if not document:
        return jsonify({"success": False, "message": "Document not found."}), 404

    old_status = document["current_status"]

    try:
        conn.execute(
            """
            UPDATE documents
            SET current_status = ?, holder_user_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_status, holder_user_id, id),
        )

        conn.execute(
            """
            INSERT INTO document_status_history
            (document_id, old_status, new_status, remarks, holder_user_id, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (id, old_status, new_status, remarks or None, holder_user_id, session["user_id"]),
        )

        log_audit(
            "update document status",
            "document",
            id,
            {
                "old_status": old_status,
                "new_status": new_status,
                "holder_user_id": holder_user_id,
                "remarks": remarks,
            },
            conn=conn,
        )
        conn.commit()
        return jsonify({"success": True, "message": "Status updated successfully."})
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower():
            return jsonify({"success": False, "message": "The database is busy. Please try again."}), 503
        raise


@app.route("/documents/history/<int:id>")
@login_required
def document_history(id):
    conn = get_db()
    history = conn.execute(
        """
        SELECT h.*, u.full_name AS updated_by_name, holder.full_name AS holder_name
        FROM document_status_history h
        LEFT JOIN users u ON h.updated_by = u.id
        LEFT JOIN users holder ON h.holder_user_id = holder.id
        WHERE h.document_id = ?
        ORDER BY h.id DESC
        """,
        (id,),
    ).fetchall()

    result = []
    for row in history:
        result.append(
            {
                "old_status": row["old_status"],
                "new_status": row["new_status"],
                "remarks": row["remarks"],
                "holder_name": row["holder_name"] or "Not Assigned",
                "updated_by_name": row["updated_by_name"],
                "updated_at": row["updated_at"],
            }
        )

    return jsonify(result)


@app.route("/documents/download/<filename>")
@login_required
def download_file(filename):
    conn = get_db()
    document = conn.execute(
        "SELECT id, title, file_name FROM documents WHERE file_name = ?",
        (filename,),
    ).fetchone()

    if not document:
        flash("Requested file could not be found.", "danger")
        return redirect(url_for("dashboard"))

    file_path = Path(app.config["UPLOAD_FOLDER"]) / filename
    if not file_path.exists():
        flash("Stored file is missing from the uploads folder.", "danger")
        return redirect(url_for("dashboard"))

    log_audit(
        "download document",
        "document",
        document["id"],
        {"title": document["title"], "file_name": filename},
        conn=conn,
    )
    conn.commit()
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@app.route("/documents/delete/<int:id>", methods=["POST"])
@login_required
def delete_document(id):
    conn = get_db()
    document = conn.execute(
        "SELECT * FROM documents WHERE id = ?",
        (id,),
    ).fetchone()

    if not document:
        flash("Document not found.", "danger")
        return redirect(url_for("dashboard"))

    file_path = None
    if document["file_name"]:
        file_path = Path(app.config["UPLOAD_FOLDER"]) / document["file_name"]

    try:
        log_audit(
            "delete document",
            "document",
            id,
            {
                "doc_no": document["doc_no"],
                "title": document["title"],
                "file_name": document["file_name"],
                "original_file_name": document["original_file_name"],
            },
            conn=conn,
        )
        conn.execute("DELETE FROM document_status_history WHERE document_id = ?", (id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (id,))
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower():
            flash("The database is busy. Please try deleting the document again.", "danger")
            return redirect(url_for("dashboard"))
        raise

    if file_path and file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            flash("Document deleted, but the stored file could not be removed automatically.", "warning")
            return redirect(url_for("dashboard"))

    flash("Document deleted successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/users")
@login_required
@admin_required
def users():
    all_users = get_db().execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    return render_template("users.html", users=all_users)


@app.route("/users/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_user():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "staff").strip()

        if not full_name or not username or not password:
            flash("Full name, username, and password are required.", "danger")
            return render_template("add_user.html")

        if role not in {"admin", "staff"}:
            flash("Invalid role selected.", "danger")
            return render_template("add_user.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "danger")
            return render_template("add_user.html")

        conn = get_db()
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing_user:
            flash("Username already exists. Please choose another one.", "danger")
            return render_template("add_user.html")

        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (full_name, username, password, role, must_change_password)
                VALUES (?, ?, ?, ?, ?)
                """,
                (full_name, username, generate_password_hash(password), role, 1),
            )
            user_id = cursor.lastrowid
            log_audit(
                "add user",
                "user",
                user_id,
                {"username": username, "role": role},
                conn=conn,
            )
            conn.commit()
            flash("User added successfully. They will be required to change their password on first login.", "success")
            return redirect(url_for("users"))
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower():
                flash("The database is busy. Please try adding the user again.", "danger")
                return render_template("add_user.html")
            raise

    return render_template("add_user.html")


@app.route("/users/edit/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (id,)).fetchone()

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("users"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "").strip()
        is_active = 1 if request.form.get("is_active") == "1" else 0
        password = request.form.get("password", "").strip()

        if not full_name or not username:
            flash("Full name and username are required.", "danger")
            return render_template("edit_user.html", user=user)

        if role not in {"admin", "staff"}:
            flash("Invalid role selected.", "danger")
            return render_template("edit_user.html", user=user)

        duplicate = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (username, id),
        ).fetchone()
        if duplicate:
            flash("Username already exists. Please choose another one.", "danger")
            return render_template("edit_user.html", user=user)

        if session["user_id"] == id and is_active == 0:
            flash("You cannot deactivate your own account while logged in.", "danger")
            return render_template("edit_user.html", user=user)

        try:
            if password:
                if len(password) < 8:
                    flash("New password must be at least 8 characters long.", "danger")
                    return render_template("edit_user.html", user=user)
                conn.execute(
                    """
                    UPDATE users
                    SET full_name = ?, username = ?, password = ?, role = ?, is_active = ?, must_change_password = 1
                    WHERE id = ?
                    """,
                    (full_name, username, generate_password_hash(password), role, is_active, id),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET full_name = ?, username = ?, role = ?, is_active = ?
                    WHERE id = ?
                    """,
                    (full_name, username, role, is_active, id),
                )

            log_audit(
                "edit user",
                "user",
                id,
                {
                    "username": username,
                    "role": role,
                    "is_active": is_active,
                    "password_reset_by_admin": bool(password),
                },
                conn=conn,
            )
            conn.commit()
            flash("User updated successfully.", "success")
            return redirect(url_for("users"))
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower():
                flash("The database is busy. Please try updating the user again.", "danger")
            else:
                raise

        user = conn.execute("SELECT * FROM users WHERE id = ?", (id,)).fetchone()

    return render_template("edit_user.html", user=user)


initialize_database()


if __name__ == "__main__":
    app.run(host=os.getenv("FLASK_HOST", "0.0.0.0"), port=int(os.getenv("FLASK_PORT", "5000")), debug=False)
