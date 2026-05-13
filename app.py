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
def parse_tags(raw):
    """Turn 'cross-team, mentoring,leadership' into ['cross-team', 'mentoring', 'leadership']."""
    if not raw:
        return []
    seen = set()
    result = []
    for t in raw.split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def set_tags(db, accomplishment_id, tag_names):
    """Replace the tags on an accomplishment with the given list."""
    db.execute(
        "DELETE FROM accomplishment_tags WHERE accomplishment_id = ?",
        (accomplishment_id,),
    )
    for name in tag_names:
        # Insert the tag if it doesn't exist, then look up its id
        db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        tag_id = db.execute(
            "SELECT id FROM tags WHERE name = ?", (name,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO accomplishment_tags (accomplishment_id, tag_id) VALUES (?, ?)",
            (accomplishment_id, tag_id),
        )


def get_tags_for(db, accomplishment_id):
    """Return a list of tag name strings for an entry."""
    rows = db.execute(
        """SELECT t.name FROM tags t
           JOIN accomplishment_tags at ON at.tag_id = t.id
           WHERE at.accomplishment_id = ?
           ORDER BY t.name""",
        (accomplishment_id,),
    ).fetchall()
    return [r[0] for r in rows]

# --- Routes ---
@app.route('/health')
def health():
    try:
        db = get_db()
        db.execute('SELECT 1')
        return 'ok', 200
    except Exception:
        return 'database unreachable', 503


@app.route("/")
def index():
    """List view with optional filters."""
    db = get_db()
    category = request.args.get("category", "")
    quarter = request.args.get("quarter", "")
    year = request.args.get("year", "")
    tag = request.args.get("tag", "").strip().lower()

    query = """
        SELECT a.* FROM accomplishments a
        WHERE 1=1
    """
    params = []

    if tag:
        query = """
            SELECT a.* FROM accomplishments a
            JOIN accomplishment_tags at ON at.accomplishment_id = a.id
            JOIN tags t ON t.id = at.tag_id
            WHERE t.name = ?
        """
        params.append(tag)

    if category:
        query += " AND a.category = ?"
        params.append(category)
    if year:
        query += " AND strftime('%Y', a.date) = ?"
        params.append(year)
    if quarter:
        quarters = {"Q1": ("01", "03"), "Q2": ("04", "06"),
                    "Q3": ("07", "09"), "Q4": ("10", "12")}
        if quarter in quarters:
            start, end = quarters[quarter]
            query += " AND strftime('%m', a.date) BETWEEN ? AND ?"
            params.extend([start, end])

    query += " ORDER BY a.date DESC, a.id DESC"
    entries = db.execute(query, params).fetchall()

    entries_with_counts = []
    for entry in entries:
        count = db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE accomplishment_id = ?",
            (entry["id"],)
        ).fetchone()[0]
        entries_with_counts.append({**dict(entry), "artifact_count": count})

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
        selected_tag=tag,
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
        set_tags(db, accomplishment_id, parse_tags(request.form.get("tags", "")))
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
    tags = get_tags_for(db, entry_id)
    return render_template("view.html", entry=entry, artifacts=artifacts, tags=tags)

@app.route("/entry/<int:entry_id>/edit", methods=["GET", "POST"])
def edit_entry(entry_id):
    """Edit an existing accomplishment, with optional new file uploads."""
    db = get_db()
    entry = db.execute(
        "SELECT * FROM accomplishments WHERE id = ?", (entry_id,)
    ).fetchone()
    if not entry:
        abort(404)

    if request.method == "POST":
        db.execute(
            """UPDATE accomplishments
               SET date = ?, title = ?, description = ?,
                   category = ?, impact = ?, links = ?
               WHERE id = ?""",
            (
                request.form["date"] or date.today().isoformat(),
                request.form["title"].strip(),
                request.form.get("description", "").strip(),
                request.form.get("category", "Other"),
                request.form.get("impact", "Medium"),
                request.form.get("links", "").strip(),
                entry_id,
            ),
        )
        set_tags(db, entry_id, parse_tags(request.form.get("tags", "")))
        # Handle any newly uploaded artifacts
        files = request.files.getlist("artifacts")
        for f in files:
            if f and f.filename:
                save_artifact(db, entry_id, f)

        db.commit()
        flash("Accomplishment updated.", "success")
        return redirect(url_for("view_entry", entry_id=entry_id))

    artifacts = db.execute(
        "SELECT * FROM artifacts WHERE accomplishment_id = ? ORDER BY uploaded_at",
        (entry_id,)
    ).fetchall()
    return render_template(
        "edit.html",
        entry=entry,
        artifacts=artifacts,
        tags=get_tags_for(db, entry_id),
        categories=CATEGORIES,
        impact_levels=IMPACT_LEVELS,
    )

@app.route("/artifact/<int:artifact_id>/delete", methods=["POST"])
def delete_artifact(artifact_id):
    """Remove a single artifact from an entry."""
    db = get_db()
    artifact = db.execute(
        "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if not artifact:
        abort(404)
    accomplishment_id = artifact["accomplishment_id"]
    try:
        (UPLOAD_DIR / artifact["stored_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    db.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    db.commit()
    flash("Artifact removed.", "success")
    return redirect(url_for("edit_entry", entry_id=accomplishment_id))

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
