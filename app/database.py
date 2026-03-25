"""
SQLite database layer for storing searches, results, and column mappings.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bids_agent.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS searches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords    TEXT NOT NULL,
            search_types TEXT NOT NULL,
            sources     TEXT NOT NULL DEFAULT '[]',
            timestamp   TEXT NOT NULL,
            result_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id   INTEGER REFERENCES searches(id),
            title       TEXT,
            number      TEXT,
            site        TEXT,
            description TEXT,
            city        TEXT,
            state       TEXT,
            company     TEXT,
            due_date    TEXT,
            source_url  TEXT,
            source_name TEXT,
            raw_data    TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS column_mappings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            mapping_name    TEXT NOT NULL,
            field_mappings  TEXT NOT NULL,
            created_at      TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ─── Searches ────────────────────────────────────────────────────────────────

def save_search(keywords, search_types, sources):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO searches (keywords, search_types, sources, timestamp) VALUES (?,?,?,?)",
        (keywords, json.dumps(search_types), json.dumps(sources), datetime.utcnow().isoformat()),
    )
    search_id = cur.lastrowid
    conn.commit()
    conn.close()
    return search_id


def update_search_count(search_id, count):
    conn = get_connection()
    conn.execute("UPDATE searches SET result_count=? WHERE id=?", (count, search_id))
    conn.commit()
    conn.close()


def get_searches(limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM searches ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_search(search_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Results ─────────────────────────────────────────────────────────────────

def save_results(search_id, results):
    """Persist a list of result dicts; returns the inserted rows with IDs."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    saved = []
    for r in results:
        cur = conn.execute(
            """INSERT INTO results
               (search_id, title, number, site, description, city, state,
                company, due_date, source_url, source_name, raw_data, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                search_id,
                r.get("title"),
                r.get("number"),
                r.get("site"),
                r.get("description"),
                r.get("city"),
                r.get("state"),
                r.get("company"),
                r.get("due_date"),
                r.get("source_url"),
                r.get("source_name"),
                json.dumps(r.get("raw_data", {})),
                now,
            ),
        )
        saved.append({**r, "id": cur.lastrowid})
    conn.commit()
    conn.close()
    return saved


def get_results(search_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM results WHERE search_id=? ORDER BY id", (search_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_results(limit=200):
    conn = get_connection()
    rows = conn.execute(
        "SELECT r.*, s.keywords FROM results r JOIN searches s ON r.search_id=s.id ORDER BY r.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Column Mappings ─────────────────────────────────────────────────────────

def save_mapping(name, field_mappings):
    conn = get_connection()
    conn.execute(
        "INSERT INTO column_mappings (mapping_name, field_mappings, created_at) VALUES (?,?,?)",
        (name, json.dumps(field_mappings), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_mappings():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM column_mappings ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_mapping(mapping_id):
    conn = get_connection()
    conn.execute("DELETE FROM column_mappings WHERE id=?", (mapping_id,))
    conn.commit()
    conn.close()
