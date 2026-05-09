"""SQLite connection management for Flask."""
import sqlite3
from pathlib import Path
from flask import g, current_app


def get_db():
    """Get a database connection, reusing one per request."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_=None):
    """Close the database connection at the end of a request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db_path):
    """Initialize the database from schema.sql."""
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    conn = sqlite3.connect(db_path)
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
