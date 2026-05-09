import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

import app as core

PH_OFFSET = timedelta(hours=8)


def _same_user(left, right):
    if left is None or right is None:
        return False
    return str(left) == str(right)


def _user_can_edit_document(document):
    return bool(document) and _same_user(document["uploaded_by"], session.get("user_id"))


def _format_ph_time(value):
    if not value:
        return "-"
    raw = str(value).split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt) + PH_OFFSET
            return dt.strftime("%b %d, %Y %I:%M %p")
        except ValueError:
            continue
    return str(value)


def _create_notification(conn, document_id, holder_user_id, assigned_by, status):
    if not holder_user_id or status == "Settled" or _same_user(holder_user_id, assigned_by):
        return

    existing = conn.execute(
        """
        SELECT id
        FROM document_notifications
        WHERE user_id = ? AND document_id = ? AND seen = 0
        """,
        (holder_user_id, document_id),
    ).fetchone()
    if existing:
        return

    conn.execute(
        """
        INSERT INTO document_notifications (user_id, document_id, assigned_by)
        VALUES (?, ?, ?)
        """,
        (holder_user_id, document_id, assigned_by),
    )


def _mark_document_notifications_seen(conn, document_id):
    conn.execute(
        """
        UPDATE document_notifications
        SET seen = 1, seen_at = CURRENT_TIMESTAMP
        WHERE document_id = ? AND seen = 0
        """,
        (document_id,),
    )


def _ensure_notification_table():
    with core.create_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                assigned_by INTEGER NOT NULL,
                seen INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                seen_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(document_id) REFERENCES documents(id),
                FOREIGN KEY(assigned_by) REFERENCES users(id)
            )
            """
        )
        conn.commit()


def _dashboard():
    search = request.args.get("search", "").strip()
    open_modal = request.args.get("open_modal", "").strip()
    selected_category = request.args.get("analytics_category", core.app.config["CATEGORY_CHOICES"][0]).strip()
    status_view = request.args.get("status_view", "active").strip()
    page_data = _get_document_listing_data(search, open_modal, status_view)
    page_data.update(_get_category_analytics(selected_category))
    return render_template("dashboard.html", **page_data)


def _get_document_listing_data(search="", open_modal="", status_view="active"):
    conn = core.get_db()
    total_docs = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()["total"]
    process_docs = conn.execute(
        "SELECT COUNT(*) AS total FROM documents WHERE current_status = 'On Process'"
    ).fetchone()["total"]
    settled_docs = conn.execute(
        "SELECT COUNT(*) AS total FROM documents WHERE current_status = 'Settled'"
    ).fetchone()["total"]

    if status_view not in {"active", "settled", "all"}:
        status_view = "active"

    filters = []
    params = []
    if status_view == "active":
        filters.append("d.current_status != 'Settled'")
    elif status_view == "settled":
        filters.append("d.current_status = 'Settled'")

    if search:
        filters.append("(d.doc_no LIKE ? OR d.title LIKE ? OR d.category LIKE ? OR d.current_status LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    docs = conn.execute(
        f"""
        SELECT d.*, u.full_name AS uploaded_by_name, h.full_name AS holder_name
        FROM documents d
        LEFT JOIN users u ON d.uploaded_by = u.id
        LEFT JOIN users h ON d.holder_user_id = h.id
        {where_clause}
        ORDER BY d.updated_at DESC, d.id DESC
        """,
        params,
    ).fetchall()

    return {
        "total_docs": total_docs,
        "process_docs": process_docs,
        "settled_docs": settled_docs,
        "docs": docs,
        "users": core.get_active_users(conn),
        "search": search,
        "open_modal": open_modal,
        "status_view": status_view,
        "status_choices": core.app.config["STATUS_CHOICES"],
        "category_choices": core.app.config["CATEGORY_CHOICES"],
    }


def _get_category_analytics(category):
    conn = core.get_db()
    if category not in core.app.config["CATEGORY_CHOICES"]:
        category = core.app.config["CATEGORY_CHOICES"][0]

    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN current_status = 'On Process' THEN 1 ELSE 0 END) AS on_process,
            SUM(CASE WHEN current_status = 'Settled' THEN 1 ELSE 0 END) AS settled,
            SUM(CASE WHEN file_name IS NOT NULL AND file_name != '' THEN 1 ELSE 0 END) AS with_files
        FROM documents
        WHERE category = ?
        """,
        (category,),
    ).fetchone()
    recent_docs = conn.execute(
        """
        SELECT doc_no, title, current_status, updated_at
        FROM documents
        WHERE category = ? AND current_status != 'Settled'
        ORDER BY updated_at DESC, id DESC
        LIMIT 6
        """,
        (category,),
    ).fetchall()

    total = stats["total"] or 0
    settled = stats["settled"] or 0
    on_process = stats["on_process"] or 0
    return {
        "selected_category": category,
        "category_total": total,
        "category_on_process": on_process,
        "category_settled": settled,
        "category_with_files": stats["with_files"] or 0,
        "category_active_percent": round((on_process / total) * 100, 1) if total else 0,
        "category_settled_percent": round((settled / total) * 100, 1) if total else 0,
        "category_recent_docs": recent_docs,
    }


def _enhanced_add_document():
    if request.method == "POST":
        conn = core.get_db()
        doc_no = core.generate_document_number(conn)
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        current_status = request.form.get("current_status", "On Process").strip()
        holder_user_id = request.form.get("holder_user_id") or None

        if not title:
            flash("Document title is required.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))
        if category not in core.app.config["CATEGORY_CHOICES"]:
            flash("Please select a valid document category.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))
        if current_status not in core.app.config["STATUS_CHOICES"]:
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
                if not core.allowed_file(original_name):
                    allowed_list = ", ".join(sorted(core.app.config["ALLOWED_EXTENSIONS"]))
                    flash(f"Invalid file type. Allowed types: {allowed_list}.", "danger")
                    return redirect(url_for("dashboard", open_modal="add-document"))
                extension = original_name.rsplit(".", 1)[1].lower()
                saved_name = f"{uuid.uuid4().hex}.{extension}"
                uploaded_file.save(Path(core.app.config["UPLOAD_FOLDER"]) / saved_name)

            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO documents
                (doc_no, title, description, category, current_status, holder_user_id, file_name, original_file_name, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_no, title, description or None, category, current_status, holder_user_id, saved_name, original_name, session["user_id"]),
            )
            document_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO document_status_history
                (document_id, old_status, new_status, remarks, holder_user_id, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (document_id, None, current_status, "Document uploaded", holder_user_id, session["user_id"]),
            )
            _create_notification(conn, document_id, holder_user_id, session["user_id"], current_status)
            core.log_audit(
                "upload document",
                "document",
                document_id,
                {"doc_no": doc_no, "title": title, "status": current_status, "holder_user_id": holder_user_id},
                conn=conn,
            )
            conn.commit()
            flash("Document uploaded successfully.", "success")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            if saved_name:
                uploaded_path = Path(core.app.config["UPLOAD_FOLDER"]) / saved_name
                if uploaded_path.exists():
                    uploaded_path.unlink()
            conn.rollback()
            flash("A generated document number conflicted. Please try saving again.", "danger")
            return redirect(url_for("dashboard", open_modal="add-document"))
        except sqlite3.OperationalError as exc:
            if saved_name:
                uploaded_path = Path(core.app.config["UPLOAD_FOLDER"]) / saved_name
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
        users=core.get_active_users(),
        status_choices=core.app.config["STATUS_CHOICES"],
        category_choices=core.app.config["CATEGORY_CHOICES"],
    )


def _restricted_edit_document(id):
    conn = core.get_db()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()
    if not document:
        flash("Document not found.", "danger")
        return redirect(url_for("dashboard"))
    if not _user_can_edit_document(document):
        flash("Only the account that uploaded this document can edit it.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        holder_user_id = request.form.get("holder_user_id") or None
        if not title:
            flash("Document title is required.", "danger")
            return render_template("edit_document.html", document=document, users=core.get_active_users(conn), category_choices=core.app.config["CATEGORY_CHOICES"])
        if category not in core.app.config["CATEGORY_CHOICES"]:
            flash("Please select a valid document category.", "danger")
            return render_template("edit_document.html", document=document, users=core.get_active_users(conn), category_choices=core.app.config["CATEGORY_CHOICES"])

        previous_holder_user_id = document["holder_user_id"]
        try:
            conn.execute(
                """
                UPDATE documents
                SET title = ?, description = ?, category = ?, holder_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, description or None, category, holder_user_id, id),
            )
            if not _same_user(previous_holder_user_id, holder_user_id):
                _create_notification(conn, id, holder_user_id, session["user_id"], document["current_status"])
            core.log_audit("edit document", "document", id, {"doc_no": document["doc_no"], "title": title, "holder_user_id": holder_user_id}, conn=conn)
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

    return render_template("edit_document.html", document=document, users=core.get_active_users(conn), category_choices=core.app.config["CATEGORY_CHOICES"])


def _save_document_status(document_id, new_status, action_taken, holder_user_id):
    if new_status not in core.app.config["STATUS_CHOICES"]:
        return False, "Invalid status selected.", 400

    conn = core.get_db()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not document:
        return False, "Document not found.", 404

    old_status = document["current_status"]
    previous_holder_user_id = document["holder_user_id"]
    try:
        conn.execute(
            """
            UPDATE documents
            SET current_status = ?, holder_user_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_status, holder_user_id, document_id),
        )
        conn.execute(
            """
            INSERT INTO document_status_history
            (document_id, old_status, new_status, remarks, holder_user_id, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, old_status, new_status, action_taken or None, holder_user_id, session["user_id"]),
        )
        if new_status == "Settled":
            _mark_document_notifications_seen(conn, document_id)
        elif not _same_user(previous_holder_user_id, holder_user_id):
            _create_notification(conn, document_id, holder_user_id, session["user_id"], new_status)
        core.log_audit(
            "update document status",
            "document",
            document_id,
            {"old_status": old_status, "new_status": new_status, "holder_user_id": holder_user_id, "action_taken": action_taken},
            conn=conn,
        )
        conn.commit()
        return True, "Status updated successfully.", 200
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower():
            return False, "The database is busy. Please try again.", 503
        raise


def _enhanced_update_status(id):
    success, message, status = _save_document_status(
        id,
        request.form.get("new_status", "").strip(),
        request.form.get("remarks", "").strip(),
        request.form.get("holder_user_id") or None,
    )
    return jsonify({"success": success, "message": message}), status


def _notification_update_status(notification_id):
    conn = core.get_db()
    notification = conn.execute(
        """
        SELECT n.*, d.holder_user_id, d.current_status
        FROM document_notifications n
        JOIN documents d ON d.id = n.document_id
        WHERE n.id = ? AND n.user_id = ? AND n.seen = 0
        """,
        (notification_id, session["user_id"]),
    ).fetchone()
    if not notification:
        return jsonify({"success": False, "message": "Notification not found."}), 404
    if notification["current_status"] == "Settled":
        _mark_document_notifications_seen(conn, notification["document_id"])
        conn.commit()
        return jsonify({"success": False, "message": "This document is already settled."}), 400

    success, message, status = _save_document_status(
        notification["document_id"],
        request.form.get("new_status", "").strip(),
        request.form.get("remarks", "").strip(),
        request.form.get("holder_user_id") or session["user_id"],
    )
    if success:
        conn = core.get_db()
        conn.execute(
            "UPDATE document_notifications SET seen = 1, seen_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (notification_id, session["user_id"]),
        )
        conn.commit()
    return jsonify({"success": success, "message": message}), status


def _restricted_delete_document(id):
    conn = core.get_db()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()
    if not document:
        flash("Document not found.", "danger")
        return redirect(url_for("dashboard"))
    if not _user_can_edit_document(document):
        flash("Only the account that uploaded this document can delete it.", "danger")
        return redirect(url_for("dashboard"))

    file_path = Path(core.app.config["UPLOAD_FOLDER"]) / document["file_name"] if document["file_name"] else None
    try:
        core.log_audit(
            "delete document",
            "document",
            id,
            {"doc_no": document["doc_no"], "title": document["title"], "file_name": document["file_name"], "original_file_name": document["original_file_name"]},
            conn=conn,
        )
        conn.execute("DELETE FROM document_notifications WHERE document_id = ?", (id,))
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


def _pending_notifications():
    conn = core.get_db()
    rows = conn.execute(
        """
        SELECT n.id, n.created_at, d.id AS document_id, d.doc_no, d.title, d.category,
               d.current_status, d.holder_user_id, d.description, d.original_file_name,
               u.full_name AS assigned_by_name
        FROM document_notifications n
        JOIN documents d ON d.id = n.document_id
        LEFT JOIN users u ON u.id = n.assigned_by
        WHERE n.user_id = ?
          AND n.seen = 0
          AND d.current_status != 'Settled'
          AND d.holder_user_id = ?
        ORDER BY n.id ASC
        LIMIT 5
        """,
        (session["user_id"], session["user_id"]),
    ).fetchall()
    return jsonify([
        {
            "id": row["id"],
            "document_id": row["document_id"],
            "doc_no": row["doc_no"],
            "title": row["title"],
            "category": row["category"],
            "current_status": row["current_status"],
            "holder_user_id": row["holder_user_id"],
            "description": row["description"],
            "original_file_name": row["original_file_name"],
            "assigned_by_name": row["assigned_by_name"] or "Another user",
            "created_at": _format_ph_time(row["created_at"]),
        }
        for row in rows
    ])


def _document_details(id):
    conn = core.get_db()
    row = conn.execute(
        """
        SELECT d.*, u.full_name AS uploaded_by_name, h.full_name AS holder_name
        FROM documents d
        LEFT JOIN users u ON d.uploaded_by = u.id
        LEFT JOIN users h ON d.holder_user_id = h.id
        WHERE d.id = ?
        """,
        (id,),
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Document not found."}), 404
    return jsonify({
        "success": True,
        "document": {
            "id": row["id"],
            "doc_no": row["doc_no"],
            "title": row["title"],
            "description": row["description"] or "No description added.",
            "category": row["category"] or "-",
            "current_status": row["current_status"],
            "forwarded_to": row["holder_name"] or "Not Assigned",
            "uploaded_by": row["uploaded_by_name"] or "-",
            "original_file_name": row["original_file_name"] or "No file attached",
            "created_at": _format_ph_time(row["created_at"]),
            "updated_at": _format_ph_time(row["updated_at"]),
        },
    })


def _dashboard_counts():
    conn = core.get_db()
    category = request.args.get("category", "").strip()
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN current_status = 'On Process' THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN current_status = 'Settled' THEN 1 ELSE 0 END) AS settled
        FROM documents
        """
    ).fetchone()
    category_counts = None
    if category in core.app.config["CATEGORY_CHOICES"]:
        category_row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN current_status = 'On Process' THEN 1 ELSE 0 END) AS active,
                   SUM(CASE WHEN current_status = 'Settled' THEN 1 ELSE 0 END) AS settled,
                   SUM(CASE WHEN file_name IS NOT NULL AND file_name != '' THEN 1 ELSE 0 END) AS with_files
            FROM documents
            WHERE category = ?
            """,
            (category,),
        ).fetchone()
        category_counts = {
            "total": category_row["total"] or 0,
            "active": category_row["active"] or 0,
            "settled": category_row["settled"] or 0,
            "with_files": category_row["with_files"] or 0,
        }
    return jsonify({
        "total": row["total"] or 0,
        "active": row["active"] or 0,
        "settled": row["settled"] or 0,
        "category": category_counts,
        "server_time": _format_ph_time(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
    })


def _active_users_json():
    return jsonify([
        {"id": row["id"], "full_name": row["full_name"]}
        for row in core.get_active_users()
    ])


def _mark_notification_seen(notification_id):
    conn = core.get_db()
    conn.execute(
        """
        UPDATE document_notifications
        SET seen = 1, seen_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (notification_id, session["user_id"]),
    )
    conn.commit()
    return jsonify({"success": True})


def _document_history(id):
    conn = core.get_db()
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
    return jsonify([
        {
            "old_status": row["old_status"],
            "new_status": row["new_status"],
            "remarks": row["remarks"],
            "holder_name": row["holder_name"] or "Not Assigned",
            "updated_by_name": row["updated_by_name"],
            "updated_at": _format_ph_time(row["updated_at"]),
        }
        for row in history
    ])


def apply(app):
    _ensure_notification_table()
    app.jinja_env.filters["ph_time"] = _format_ph_time
    core.get_document_listing_data = _get_document_listing_data
    core.get_category_analytics = _get_category_analytics

    app.view_functions["dashboard"] = core.login_required(_dashboard)
    app.view_functions["add_document"] = core.login_required(_enhanced_add_document)
    app.view_functions["edit_document"] = core.login_required(_restricted_edit_document)
    app.view_functions["update_status"] = core.login_required(_enhanced_update_status)
    app.view_functions["document_history"] = core.login_required(_document_history)
    app.view_functions["delete_document"] = core.login_required(_restricted_delete_document)

    if "pending_notifications" not in app.view_functions:
        app.add_url_rule("/notifications/pending", "pending_notifications", core.login_required(_pending_notifications))
    if "mark_notification_seen" not in app.view_functions:
        app.add_url_rule(
            "/notifications/<int:notification_id>/seen",
            "mark_notification_seen",
            core.login_required(_mark_notification_seen),
            methods=["POST"],
        )
    if "notification_update_status" not in app.view_functions:
        app.add_url_rule(
            "/notifications/<int:notification_id>/update_status",
            "notification_update_status",
            core.login_required(_notification_update_status),
            methods=["POST"],
        )
    if "document_details" not in app.view_functions:
        app.add_url_rule("/documents/details/<int:id>", "document_details", core.login_required(_document_details))
    if "dashboard_counts" not in app.view_functions:
        app.add_url_rule("/dashboard/counts", "dashboard_counts", core.login_required(_dashboard_counts))
    if "active_users_json" not in app.view_functions:
        app.add_url_rule("/users/active-json", "active_users_json", core.login_required(_active_users_json))
