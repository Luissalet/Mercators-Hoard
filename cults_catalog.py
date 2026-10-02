"""Cults catalogue entries imported from other apps (Vulcan's listings), stored next to the folder scan.

The folder scan in ``mercator.products()`` stays as it was; imported entries are merged into its answer.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_items (
    ref TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'folder',
    title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]',
    price TEXT, currency TEXT, folder TEXT NOT NULL DEFAULT '', model_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT, source_updated_at TEXT, imported_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def _clean(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    title = str(entry.get("title") or "").strip()
    ref = str(entry.get("ref") or "").strip()
    if not title or not ref:
        return None
    tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
    ids = entry.get("model_ids") if isinstance(entry.get("model_ids"), list) else []
    price = entry.get("price")
    return {"ref": ref[:500], "kind": "model" if entry.get("kind") == "model" else "folder", "title": title[:300],
            "description": str(entry.get("description") or "")[:20000],
            "tags": [str(t).strip() for t in tags if str(t).strip()][:60],
            "price": None if price in (None, "") else str(price)[:40],
            "currency": (str(entry.get("currency")).upper()[:3] if entry.get("currency") else None),
            "folder": str(entry.get("folder") or "")[:1000], "model_ids": [i for i in ids if isinstance(i, int)][:500],
            "status": (str(entry.get("status"))[:20] if entry.get("status") else None),
            "source_updated_at": (str(entry.get("updated_at"))[:40] if entry.get("updated_at") else None)}


def upsert(conn, listings: list, source: str = "vulcan") -> dict:
    """Upsert entries by ``ref``. Returns ``{added, updated, unchanged, skipped}``."""
    counts = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for raw in listings:
        entry = _clean(raw)
        if entry is None:
            counts["skipped"] += 1
            continue
        stored = (json.dumps(entry["tags"], ensure_ascii=False), json.dumps(entry["model_ids"]))
        row = conn.execute("SELECT * FROM catalog_items WHERE ref=?", (entry["ref"],)).fetchone()
        values = (entry["kind"], entry["title"], entry["description"], stored[0], entry["price"], entry["currency"],
                  entry["folder"], stored[1], entry["status"], entry["source_updated_at"])
        if row is None:
            conn.execute("INSERT INTO catalog_items(ref, source, kind, title, description, tags, price, currency, folder, model_ids, "
                         "status, source_updated_at, imported_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (entry["ref"], source, *values, now, now))
            counts["added"] += 1
        elif tuple(row[k] for k in ("kind", "title", "description", "tags", "price", "currency", "folder", "model_ids",
                                    "status", "source_updated_at")) == values:
            counts["unchanged"] += 1
        else:
            conn.execute("UPDATE catalog_items SET kind=?, title=?, description=?, tags=?, price=?, currency=?, folder=?, model_ids=?, "
                         "status=?, source_updated_at=?, updated_at=? WHERE ref=?", (*values, now, entry["ref"]))
            counts["updated"] += 1
    return counts


def list_items(db_path) -> list[dict]:
    """Imported entries, read without writing (empty when the store or the table does not exist yet)."""
    try:
        if not db_path.is_file():
            return []
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM catalog_items ORDER BY title COLLATE NOCASE").fetchall()
    except sqlite3.Error:
        return []
    out = []
    for row in rows:
        out.append({"ref": row["ref"], "source": row["source"], "kind": row["kind"], "title": row["title"],
                    "description": row["description"], "tags": json.loads(row["tags"] or "[]"), "price": row["price"],
                    "currency": row["currency"], "folder": row["folder"], "model_ids": json.loads(row["model_ids"] or "[]"),
                    "status": row["status"], "updated_at": row["source_updated_at"] or row["updated_at"]})
    return out
