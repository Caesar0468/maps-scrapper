"""SQLite database with WAL mode, FTS5 search, and migration logic."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "data" / "restaurants.db"


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")[:120]


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS restaurants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            rating REAL,
            review_count INTEGER,
            locality TEXT,
            address TEXT,
            latitude REAL,
            longitude REAL,
            phone TEXT,
            website TEXT,
            phone_source TEXT,
            website_source TEXT,
            google_maps_url TEXT,
            opening_hours_json TEXT,
            is_open_now INTEGER,
            raw_menu_json TEXT,
            menu_source TEXT,
            qr_menu_url TEXT,
            menu_images_json TEXT,
            metadata_sources_json TEXT,
            social_context_json TEXT,
            ai_analysis_json TEXT,
            place_id TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_restaurants_rating ON restaurants(rating);
        CREATE INDEX IF NOT EXISTS idx_restaurants_locality ON restaurants(locality);
        CREATE INDEX IF NOT EXISTS idx_restaurants_slug ON restaurants(slug);
        CREATE INDEX IF NOT EXISTS idx_restaurants_coords ON restaurants(latitude, longitude);

        CREATE VIRTUAL TABLE IF NOT EXISTS restaurants_fts USING fts5(
            name,
            locality,
            cuisines,
            must_try_items,
            tokenize='porter'
        );
        """
    )
    conn.commit()
    return conn


def _fts_sync(conn: sqlite3.Connection, row_id: int) -> None:
    row = conn.execute("SELECT * FROM restaurants WHERE id=?", (row_id,)).fetchone()
    if not row:
        return
    ai = {}
    try:
        ai = json.loads(row["ai_analysis_json"] or "{}")
    except json.JSONDecodeError:
        pass
    cuisines = ", ".join(ai.get("cuisines", [])) if ai.get("cuisines") else ""
    must_try = ", ".join(ai.get("must_try_items", [])) if ai.get("must_try_items") else ""
    conn.execute("DELETE FROM restaurants_fts WHERE rowid=?", (row_id,))
    conn.execute(
        "INSERT INTO restaurants_fts(rowid, name, locality, cuisines, must_try_items) VALUES (?,?,?,?,?)",
        (row_id, row["name"], row["locality"] or "", cuisines, must_try),
    )


def upsert_restaurant(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    slug = data.get("slug") or slugify(data["name"])
    metadata = data.get("metadata_sources") or {}
    ai = data.get("ai_analysis") or data.get("ai_analysis_json")
    if isinstance(ai, str):
        ai_json = ai
    else:
        ai_json = json.dumps(ai) if ai else None

    social = data.get("social_context")
    social_json = json.dumps(social) if social else data.get("social_context_json")

    raw_menu = data.get("raw_menu") or data.get("raw_menu_json") or []
    raw_menu_json = raw_menu if isinstance(raw_menu, str) else json.dumps(raw_menu)

    menu_images = data.get("menu_images") or data.get("menu_images_json") or []
    menu_images_json = menu_images if isinstance(menu_images, str) else json.dumps(menu_images)

    review_count = data.get("review_count")
    if review_count is None:
        review_count = data.get("reviews")

    existing = conn.execute(
        "SELECT id FROM restaurants WHERE slug=? OR place_id=?",
        (slug, data.get("place_id"))
    ).fetchone()

    fields = {
        "slug": slug,
        "name": data["name"],
        "rating": data.get("rating"),
        "review_count": review_count,
        "locality": data.get("locality"),
        "address": data.get("address"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "phone": data.get("phone"),
        "website": data.get("website"),
        "phone_source": (metadata.get("phone") or {}).get("source") or data.get("phone_source"),
        "website_source": (metadata.get("website") or {}).get("source") or data.get("website_source"),
        "google_maps_url": data.get("google_maps_url"),
        "opening_hours_json": json.dumps(data.get("opening_hours") or []),
        "is_open_now": 1 if data.get("is_open_now") else 0 if data.get("is_open_now") is False else None,
        "raw_menu_json": raw_menu_json,
        "menu_source": data.get("menu_source"),
        "qr_menu_url": data.get("qr_menu_url"),
        "menu_images_json": menu_images_json,
        "metadata_sources_json": json.dumps(metadata),
        "social_context_json": social_json,
        "ai_analysis_json": ai_json,
        "place_id": data.get("place_id"),
        "updated_at": now,
    }

    if existing:
        row_id = existing["id"]
        set_clause = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE restaurants SET {set_clause} WHERE id=?",
            list(fields.values()) + [row_id],
        )
    else:
        fields["created_at"] = now
        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" * len(fields))
        cur = conn.execute(
            f"INSERT INTO restaurants ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
        row_id = cur.lastrowid

    _fts_sync(conn, row_id)
    conn.commit()
    return row_id

def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    json_keys = (
        "opening_hours_json",
        "raw_menu_json",
        "menu_images_json",
        "metadata_sources_json",
        "social_context_json",
        "ai_analysis_json",
    )
    for key in json_keys:
        if key in d:
            raw = d.pop(key)
            clean_key = key.replace("_json", "")
            try:
                d[clean_key] = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                d[clean_key] = None
    if d.get("is_open_now") is not None:
        d["is_open_now"] = bool(d["is_open_now"])
    return d


def get_all_restaurants(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM restaurants ORDER BY review_count DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def get_restaurant_by_slug(conn: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM restaurants WHERE slug=?", (slug,)).fetchone()
    return row_to_dict(row) if row else None


def search_restaurants(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search using FTS5 with sanitized query; fallback to LIKE."""
    try:
        # Sanitize for FTS: wrap in double quotes and escape internal quotes
        safe_query = query.replace('"', '""')
        match_expr = f'"{safe_query}"'
        rows = conn.execute(
            """
            SELECT r.* FROM restaurants r
            JOIN restaurants_fts fts ON r.id = fts.rowid
            WHERE fts MATCH ?
            ORDER BY rank LIMIT ?
            """,
            (match_expr, limit),
        ).fetchall()
        if rows:
            return [row_to_dict(r) for r in rows]
        # If no FTS results, fall back to LIKE
        raise sqlite3.Error("No FTS results")
    except sqlite3.Error:
        like_query = f"%{query}%"
        rows = conn.execute(
            "SELECT * FROM restaurants WHERE name LIKE ? OR locality LIKE ? ORDER BY review_count DESC LIMIT ?",
            (like_query, like_query, limit),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def get_localities(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT locality FROM restaurants WHERE locality IS NOT NULL AND locality != '' ORDER BY locality"
    ).fetchall()
    return [r["locality"] for r in rows]


def get_unanalyzed(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM restaurants WHERE ai_analysis_json IS NULL OR ai_analysis_json=''"
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_distinct_cuisines(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT ai_analysis_json FROM restaurants WHERE ai_analysis_json IS NOT NULL AND ai_analysis_json != ''"
    ).fetchall()
    cuisine_set = set()
    for row in rows:
        try:
            ai = json.loads(row["ai_analysis_json"])
            for c in ai.get("cuisines", []):
                cuisine_set.add(c.strip())
        except (json.JSONDecodeError, TypeError):
            pass
    return sorted(cuisine_set)


def get_distinct_vibes(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT ai_analysis_json FROM restaurants WHERE ai_analysis_json IS NOT NULL AND ai_analysis_json != ''"
    ).fetchall()
    vibe_set = set()
    for row in rows:
        try:
            ai = json.loads(row["ai_analysis_json"])
            for v in ai.get("vibe_tags", []):
                vibe_set.add(v.strip())
        except (json.JSONDecodeError, TypeError):
            pass
    return sorted(vibe_set)