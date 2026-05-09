"""
Accomplishments tracker — a personal log of work wins, organized for quarterly reviews.
"""
import os
import uuid
from datetime import date, datetime
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, abort, flash, Response
)
from werkzeug.utils import secure_filename

from db import get_db, init_db, close_db

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", BASE_DIR / "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-key-change-me"),
    DATABASE=os.environ.get("DATABASE", str(BASE_DIR / "accomplishments.db")),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25MB upload cap
)
app.teardown_appcontext(close_db)

CATEGORIES = ["Project", "Mentorship", "Process", "Learning", "Leadership", "Other"]
IMPACT_LEVELS = ["Low", "Medium", "High"]


# --- Routes ---
@app.route("/")
def index():
    """List view with optional filters."""
    db = get_db()
    category = request.args.get("category", "")
    quarter = request.args.get("quarter", "")
    year = request.args.get("year", "")

    query = "SELECT * FROM accomplishments WHERE 1=1"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if year:
        query += " AND strftime('%Y', date) = ?"
        params.append(year)
    if quarter:
        # Map Q1-Q4 to month ranges
        quarters = {"Q1": ("01", "03"), "Q2": ("04", "06"),
                    "Q3": ("07", "09"), "Q4": ("10", "12")}
        if quarter in quarters:
            start, end = quarters[quarter]
            query += " AND strftime('%m', date) BETWEEN ? AND ?"
            params.extend([start, end])

    query += " ORDER BY date DESC, id DESC"
    entries = db.execute(query, params).fetchall()

    # Attach artifact counts to each entry
    entries_with_counts = []
    for entry in entries:
        count = db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE accomplishment_id = ?",
            (entry["id"],)
        ).fetchone()[0]
        entries_with_counts.append({**dict(entry), "artifact_count": count})

    # For the year filter dropdown
    years = [r["y"] for r in db.execute(
        "SELECT DISTINCT strftime('%Y', date) AS y FROM accomplishments ORDER BY y DESC"
    ).fetchall()]

    return render_template(
        "list.html",
        entries=entries_with_counts,
        categories=CATEGORIES,
        years=years,
        selected_category=category,
        selected_quarter=quarter,
        selected_year=year,
    )


@app.route("/new", methods=["GET", "POST"])
def new_entry():
    """Create a new accomplishment, optionally with file uploads."""
    if request.method == "POST":
        db = get_db()
        cur = db.execute(
            """INSERT INTO accomplishments (date, title, description, category, impact, links)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                request.form["date"] or date.today().isoformat(),
                request.form["title"].strip(),
                request.form.get("description", "").strip(),
                request.form.get("category", "Other"),
                request.form.get("impact", "Medium"),
                request.form.get("links", "").strip(),
            ),
        )
        accomplishment_id = cur.lastrowid

        # Handle file uploads
        files = request.files.getlist("artifacts")
        for f in files:
            if f and f.filename:
                save_artifact(db, accomplishment_id, f)

        db.commit()
        flash("Accomplishment saved.", "success")
        return redirect(url_for("view_entry", entry_id=accomplishment_id))

    return render_template(
        "new.html",
        categories=CATEGORIES,
        impact_levels=IMPACT_LEVELS,
        today=date.today().isoformat(),
    )


@app.route("/entry/<int:entry_id>")
def view_entry(entry_id):
    """View a single accomplishment with its artifacts."""
    db = get_db()
    entry = db.execute(
        "SELECT * FROM accomplishments WHERE id = ?", (entry_id,)
    ).fetchone()
    if not entry:
        abort(404)
    artifacts = db.execute(
        "SELECT * FROM artifacts WHERE accomplishment_id = ? ORDER BY uploaded_at",
        (entry_id,)
    ).fetchall()
    return render_template("view.html", entry=entry, artifacts=artifacts)


@app.route("/entry/<int:entry_id>/delete", methods=["POST"])
def delete_entry(entry_id):
    """Delete an accomplishment and its artifacts."""
    db = get_db()
    artifacts = db.execute(
        "SELECT stored_path FROM artifacts WHERE accomplishment_id = ?",
        (entry_id,)
    ).fetchall()
    for a in artifacts:
        try:
            (UPLOAD_DIR / a["stored_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    db.execute("DELETE FROM artifacts WHERE accomplishment_id = ?", (entry_id,))
    db.execute("DELETE FROM accomplishments WHERE id = ?", (entry_id,))
    db.commit()
    flash("Entry deleted.", "success")
    return redirect(url_for("index"))


@app.route("/artifacts/<path:stored_path>")
def download_artifact(stored_path):
    """Serve an uploaded file."""
    # send_from_directory protects against path traversal
    return send_from_directory(UPLOAD_DIR, stored_path, as_attachment=True)


@app.route("/export")
def export():
    """Export entries in a date range as Markdown for pasting into a self-review."""
    quarter = request.args.get("quarter", "")
    year = request.args.get("year", str(date.today().year))

    if not quarter:
        # Show the export form
        db = get_db()
        years = [r["y"] for r in db.execute(
            "SELECT DISTINCT strftime('%Y', date) AS y FROM accomplishments ORDER BY y DESC"
        ).fetchall()]
        if not years:
            years = [str(date.today().year)]
        return render_template("export.html", years=years)

    db = get_db()
    quarters = {"Q1": ("01", "03"), "Q2": ("04", "06"),
                "Q3": ("07", "09"), "Q4": ("10", "12"),
                "All": ("01", "12")}
    start, end = quarters.get(quarter, ("01", "12"))

    entries = db.execute(
        """SELECT * FROM accomplishments
           WHERE strftime('%Y', date) = ?
             AND strftime('%m', date) BETWEEN ? AND ?
           ORDER BY date""",
        (year, start, end)
    ).fetchall()

    # Build Markdown
    lines = [f"# Accomplishments — {quarter} {year}\n"]
    by_category = {}
    for e in entries:
        by_category.setdefault(e["category"], []).append(e)

    for cat in CATEGORIES:
        if cat not in by_category:
            continue
        lines.append(f"\n## {cat}\n")
        for e in by_category[cat]:
            lines.append(f"- **{e['title']}** ({e['date']}, impact: {e['impact']})")
            if e["description"]:
                lines.append(f"  - {e['description']}")
            if e["links"]:
                lines.append(f"  - Links: {e['links']}")

    md = "\n".join(lines)
    return Response(
        md,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=accomplishments-{year}-{quarter}.md"},
    )


# --- Helpers ---
def save_artifact(db, accomplishment_id, file_storage):
    """Save an uploaded file to disk and record it in the database."""
    original_name = secure_filename(file_storage.filename)
    if not original_name:
        return
    # Store as <accomplishment_id>/<uuid>-<filename> to avoid collisions
    subdir = UPLOAD_DIR / str(accomplishment_id)
    subdir.mkdir(exist_ok=True)
    stored_filename = f"{uuid.uuid4().hex[:8]}-{original_name}"
    stored_path = f"{accomplishment_id}/{stored_filename}"
    full_path = UPLOAD_DIR / stored_path
    file_storage.save(full_path)

    db.execute(
        """INSERT INTO artifacts
           (accomplishment_id, filename, stored_path, mime_type, size_bytes, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            accomplishment_id,
            original_name,
            stored_path,
            file_storage.mimetype or "application/octet-stream",
            full_path.stat().st_size,
            datetime.utcnow().isoformat(),
        ),
    )


# --- CLI: initialize the database ---
@app.cli.command("init-db")
def init_db_command():
    """Create database tables. Run once: `flask --app app init-db`."""
    init_db(app.config["DATABASE"])
    print("Database initialized.")


if __name__ == "__main__":
    app.run(debug=True)
