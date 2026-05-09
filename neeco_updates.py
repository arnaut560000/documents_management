import sqlite3
from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, session, url_for

import app as core


def _same_user(left, right):
    if left is None or right is None:
        return False
    return str(left) == str(right)


def _user_can_edit_document(document):
    return bool(document) and _same_user(document["uploaded_by"], session.get("user_id"))


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
            return render_template(
                "edit_document.html",
                document=document,
                users=core.get_active_users(conn),
                category_choices=core.app.config["CATEGORY_CHOICES"],
            )

        if category not in core.app.config["CATEGORY_CHOICES"]:
            flash("Please select a valid document category.", "danger")
            return render_template(
                "edit_document.html",
                document=document,
                users=core.get_active_users(conn),
                category_choices=core.app.config["CATEGORY_CHOICES"],
            )

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

            core.log_audit(
                "edit document",
                "document",
                id,
                {"doc_no": document["doc_no"], "title": title, "holder_user_id": holder_user_id},
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
        users=core.get_active_users(conn),
        category_choices=core.app.config["CATEGORY_CHOICES"],
    )


def _enhanced_update_status(id):
    new_status = request.form.get("new_status", "").strip()
    action_taken = request.form.get("remarks", "").strip()
    holder_user_id = request.form.get("holder_user_id") or None

    if new_status not in core.app.config["STATUS_CHOICES"]:
        return jsonify({"success": False, "message": "Invalid status selected."}), 400

    conn = core.get_db()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()

    if not document:
        return jsonify({"success": False, "message": "Document not found."}), 404

    old_status = document["current_status"]
    previous_holder_user_id = document["holder_user_id"]

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
            (id, old_status, new_status, action_taken or None, holder_user_id, session["user_id"]),
        )

        if new_status == "Settled":
            _mark_document_notifications_seen(conn, id)
        elif not _same_user(previous_holder_user_id, holder_user_id):
            _create_notification(conn, id, holder_user_id, session["user_id"], new_status)

        core.log_audit(
            "update document status",
            "document",
            id,
            {
                "old_status": old_status,
                "new_status": new_status,
                "holder_user_id": holder_user_id,
                "action_taken": action_taken,
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
            {
                "doc_no": document["doc_no"],
                "title": document["title"],
                "file_name": document["file_name"],
                "original_file_name": document["original_file_name"],
            },
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
        SELECT n.id, n.created_at, d.doc_no, d.title, d.category, d.current_status,
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
            "doc_no": row["doc_no"],
            "title": row["title"],
            "category": row["category"],
            "current_status": row["current_status"],
            "assigned_by_name": row["assigned_by_name"] or "Another user",
            "created_at": row["created_at"],
        }
        for row in rows
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


def apply(app):
    _ensure_notification_table()

    app.view_functions["edit_document"] = core.login_required(_restricted_edit_document)
    app.view_functions["update_status"] = core.login_required(_enhanced_update_status)
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

