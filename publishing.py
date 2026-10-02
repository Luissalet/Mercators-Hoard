"""Publicación: the posts store, metrics snapshots and statistics.

Pure functions over a SQLite connection (``conn``), so the HTTP handler, the agent tools and the tests all
use the same code. ``connect()`` late-imports ``mercator`` for its ``db()``; nothing here imports the server
at import time.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

PLATFORMS: dict[str, dict[str, Any]] = {
    "instagram_reel": {"label": "Instagram Reel", "caption_limit": 2200, "title_limit": None, "hashtag_limit": 30, "media": "video"},
    "instagram_post": {"label": "Instagram", "caption_limit": 2200, "title_limit": None, "hashtag_limit": 30, "media": "image"},
    "tiktok": {"label": "TikTok", "caption_limit": 2200, "title_limit": None, "hashtag_limit": None, "media": "video"},
    "youtube_short": {"label": "YouTube Short", "caption_limit": 5000, "title_limit": 100, "hashtag_limit": None, "media": "video"},
    "youtube": {"label": "YouTube", "caption_limit": 5000, "title_limit": 100, "hashtag_limit": None, "media": "video"},
    "x": {"label": "X", "caption_limit": 280, "title_limit": None, "hashtag_limit": None, "media": "any"},
    "cults3d": {"label": "Cults3D", "caption_limit": None, "title_limit": None, "hashtag_limit": None, "media": "image"},
    "other": {"label": "Otra", "caption_limit": None, "title_limit": None, "hashtag_limit": None, "media": "any"},
}
STATUSES = ("idea", "draft", "scheduled", "published", "archived")
METRIC_FIELDS = ("views", "likes", "comments", "shares", "saves", "sales")
MEDIA_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                    ".gif": "image/gif", ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
DEFAULT_PLATFORM = "instagram_reel"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', caption TEXT NOT NULL DEFAULT '',
    hashtags TEXT NOT NULL DEFAULT '[]', media_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idea', scheduled_at TEXT, published_at TEXT,
    url TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', external_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS posts_scheduled ON posts(scheduled_at);
CREATE INDEX IF NOT EXISTS posts_media ON posts(media_ref);
CREATE TABLE IF NOT EXISTS post_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL, ts TEXT NOT NULL,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER, sales INTEGER,
    revenue TEXT, currency TEXT, source TEXT NOT NULL DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS post_metrics_post ON post_metrics(post_id, ts);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect():
    import mercator
    return mercator.db()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_local() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- normalisation

def norm_when(value: Any, field: str = "fecha") -> str | None:
    """A date or date-time as written by the person (local time), as ISO text; None for empty."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field}: fecha no válida ({text[:40]})") from exc
        return text
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        moment = None  # type: ignore[assignment]
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                moment = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if moment is None:
            raise ValueError(f"{field}: fecha no válida ({text[:40]})") from None
    return moment.replace(microsecond=0).isoformat()


def when_parts(text: str | None) -> datetime | None:
    """The naive local moment of a stored ``scheduled_at``/``published_at`` (offset dropped, hour as written)."""
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text + "T00:00:00")
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def norm_ts(value: Any) -> str:
    """A snapshot time as UTC ISO text (a naive value is local time); empty means now."""
    if value is None or str(value).strip() == "":
        return now_utc()
    text = str(value).strip()
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00").replace(" ", "T", 1))
    except ValueError as exc:
        raise ValueError(f"ts: fecha no válida ({text[:40]})") from exc
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def norm_hashtags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[\s,;]+", value)
    if not isinstance(value, (list, tuple)):
        raise ValueError("hashtags debe ser una lista o un texto")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        tag = re.sub(r"\s+", "", str(raw).strip().lstrip("#").strip())
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out[:100]


def _text(value: Any, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser texto")
    text = value.strip("\n ") if field in ("caption", "notes") else value.strip()
    if len(text) > limit:
        raise ValueError(f"{field} demasiado largo (máximo {limit} caracteres)")
    return text


def _int_metric(value: Any, field: str) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} no válido")
    try:
        number = int(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} no válido: {value}") from exc
    if number < 0:
        raise ValueError(f"{field} no puede ser negativo")
    return number


def _money(value: Any, field: str = "revenue") -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    import mercator
    try:
        return str(mercator.parse_amount(str(value)))
    except ValueError as exc:
        raise ValueError(f"{field} no válido: {value}") from exc


def caption_text(post: dict) -> str:
    tags = " ".join("#" + t for t in post.get("hashtags") or [])
    return "\n\n".join(part for part in (post.get("caption") or "", tags) if part)


def post_ref(post_id: int) -> str:
    return f"hoard://mercator/post/{post_id}"


# ---------------------------------------------------------------- rows

def _row_post(row) -> dict:
    post = {"id": row["id"], "ref": post_ref(row["id"]), "platform": row["platform"],
            "platform_label": PLATFORMS.get(row["platform"], {}).get("label", row["platform"]),
            "title": row["title"], "caption": row["caption"], "hashtags": json.loads(row["hashtags"] or "[]"),
            "media_ref": row["media_ref"], "status": row["status"], "scheduled_at": row["scheduled_at"],
            "published_at": row["published_at"], "url": row["url"], "notes": row["notes"],
            "external_id": row["external_id"], "created_at": row["created_at"], "updated_at": row["updated_at"]}
    post["text"] = caption_text(post)
    return post


def _row_metric(row) -> dict:
    return {key: row[key] for key in ("id", "post_id", "ts", *METRIC_FIELDS, "revenue", "currency", "source")}


def latest_metrics(conn, post_ids: list[int] | None = None) -> dict[int, dict]:
    wanted = set(post_ids) if post_ids is not None else None
    out: dict[int, dict] = {}
    counts: dict[int, int] = {}
    for row in conn.execute("SELECT * FROM post_metrics ORDER BY ts, id"):
        if wanted is not None and row["post_id"] not in wanted:
            continue
        out[row["post_id"]] = _row_metric(row)
        counts[row["post_id"]] = counts.get(row["post_id"], 0) + 1
    for key, value in out.items():
        value["snapshots"] = counts[key]
    return out


def _attach(conn, posts: list[dict]) -> list[dict]:
    latest = latest_metrics(conn, [p["id"] for p in posts])
    for post in posts:
        post["metrics_latest"] = latest.get(post["id"])
    return posts


def _post_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or str(value).strip() == "":
        raise ValueError("post_id no válido")
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError("post_id no válido") from exc
    if number < 1:
        raise ValueError("post_id no válido")
    return number


def get_post(conn, post_id: Any, *, metrics: bool = True) -> dict:
    row = conn.execute("SELECT * FROM posts WHERE id=?", (_post_id(post_id),)).fetchone()
    if row is None:
        raise ValueError(f"No existe la publicación {post_id}")
    post = _attach(conn, [_row_post(row)])[0]
    if metrics:
        post["metrics"] = [_row_metric(r) for r in conn.execute(
            "SELECT * FROM post_metrics WHERE post_id=? ORDER BY ts, id", (post["id"],))]
    return post


def list_posts(conn, status: str = "", platform: str = "", date_from: str = "", date_to: str = "",
               q: str = "", limit: int = 200, offset: int = 0) -> dict:
    if status and status not in STATUSES:
        raise ValueError("status no válido: " + ", ".join(STATUSES))
    if platform and platform not in PLATFORMS:
        raise ValueError("platform no válida: " + ", ".join(PLATFORMS))
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000 \
            or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("limit u offset no válidos")
    rows = [_row_post(r) for r in conn.execute(
        "SELECT * FROM posts ORDER BY COALESCE(scheduled_at, published_at, created_at) DESC, id DESC")]
    needle = (q or "").casefold().strip()
    lo = norm_when(date_from, "from") if date_from else None
    hi = norm_when(date_to, "to") if date_to else None
    out = []
    for post in rows:
        if status and post["status"] != status or platform and post["platform"] != platform:
            continue
        if needle and needle not in (post["title"] + " " + post["caption"] + " " + " ".join(post["hashtags"]) + " " + post["notes"]).casefold():
            continue
        when = (post["scheduled_at"] if post["status"] == "scheduled" else post["published_at"] or post["scheduled_at"]) or ""
        if (lo or hi) and not when:
            continue
        if lo and when[:10] < lo[:10] or hi and when[:10] > hi[:10]:
            continue
        out.append(post)
    return {"total": len(out), "offset": offset, "posts": _attach(conn, out[offset:offset + limit])}


# ---------------------------------------------------------------- writes

def upsert_post(conn, args: dict) -> tuple[dict, dict | None, bool]:
    """Create or update a post. Returns ``(post, previous, created)``; only keys present in ``args`` change."""
    if not isinstance(args, dict):
        raise ValueError("Argumentos no válidos")
    known = {"post_id", "platform", "title", "caption", "hashtags", "media_ref", "status", "scheduled_at",
             "published_at", "url", "notes", "external_id"}
    unknown = set(args) - known
    if unknown:
        raise ValueError("Campos desconocidos: " + ", ".join(sorted(unknown)))
    previous = get_post(conn, args["post_id"], metrics=False) if args.get("post_id") not in (None, "") else None
    if "platform" in args and args["platform"] not in PLATFORMS:
        raise ValueError("platform no válida: " + ", ".join(PLATFORMS))
    if "status" in args and args["status"] not in STATUSES:
        raise ValueError("status no válido: " + ", ".join(STATUSES))
    fields: dict[str, Any] = {}
    for name in ("platform", "status"):
        if name in args:
            fields[name] = args[name]
    for name, limit in (("title", 300), ("caption", 20000), ("media_ref", 2000), ("url", 2000), ("notes", 20000), ("external_id", 200)):
        if name in args:
            fields[name] = _text(args[name], name, limit)
    if "hashtags" in args:
        fields["hashtags"] = json.dumps(norm_hashtags(args["hashtags"]), ensure_ascii=False)
    for name in ("scheduled_at", "published_at"):
        if name in args:
            fields[name] = norm_when(args[name], name)
    if previous is None:
        if "platform" not in fields:
            raise ValueError("platform es obligatoria al crear una publicación")
        if not (fields.get("title") or fields.get("caption") or fields.get("media_ref")):
            raise ValueError("Indica al menos título, texto o media_ref")
    base = previous or {"status": "idea", "scheduled_at": None, "published_at": None}
    merged = {**base, **{k: v for k, v in fields.items() if k != "hashtags"}}
    if merged["status"] == "scheduled" and not merged.get("scheduled_at"):
        raise ValueError("Para programar hace falta scheduled_at")
    if merged["status"] == "published" and not merged.get("published_at"):
        fields["published_at"] = now_local()
    now = now_utc()
    if previous is None:
        defaults = {"title": "", "caption": "", "hashtags": "[]", "media_ref": "", "status": "idea", "scheduled_at": None,
                    "published_at": None, "url": "", "notes": "", "external_id": ""}
        row = {**defaults, **fields, "created_at": now, "updated_at": now}
        cursor = conn.execute(f"INSERT INTO posts({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
        post_id = cursor.lastrowid
    else:
        fields["updated_at"] = now
        post_id = previous["id"]
        conn.execute(f"UPDATE posts SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), post_id))
    return get_post(conn, post_id, metrics=False), previous, previous is None


def delete_post(conn, post_id: Any) -> dict:
    post = get_post(conn, post_id, metrics=False)
    conn.execute("DELETE FROM post_metrics WHERE post_id=?", (post["id"],))
    conn.execute("DELETE FROM posts WHERE id=?", (post["id"],))
    return post


def add_metrics(conn, args: dict, *, source: str = "manual") -> dict:
    if not isinstance(args, dict):
        raise ValueError("Argumentos no válidos")
    post = get_post(conn, args.get("post_id"), metrics=False)
    values = {name: _int_metric(args.get(name), name) for name in METRIC_FIELDS}
    revenue = _money(args.get("revenue"))
    if all(v is None for v in values.values()) and revenue is None:
        raise ValueError("Indica al menos una métrica (views, likes, comments, shares, saves, sales o revenue)")
    currency = None
    if revenue is not None:
        currency = str(args.get("currency") or "EUR").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency no válida")
    cursor = conn.execute(
        "INSERT INTO post_metrics(post_id, ts, views, likes, comments, shares, saves, sales, revenue, currency, source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (post["id"], norm_ts(args.get("ts")), *values.values(), revenue, currency, source))
    conn.execute("UPDATE posts SET updated_at=? WHERE id=?", (now_utc(), post["id"]))
    return _row_metric(conn.execute("SELECT * FROM post_metrics WHERE id=?", (cursor.lastrowid,)).fetchone())


def metrics_equal(a: dict | None, b: dict) -> bool:
    """True when snapshot ``b`` carries exactly the numbers of the latest snapshot ``a`` (a re-import changes nothing)."""
    if not a:
        return False
    return all(a.get(k) == b.get(k) for k in (*METRIC_FIELDS, "revenue", "currency"))


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def draft_from_media(conn, media_ref: Any, title: Any, platform: Any = None) -> tuple[dict, bool]:
    """A draft post for a media reference (a render, a production, a model); idempotent by ``media_ref``."""
    ref = _text(media_ref, "media_ref", 2000)
    if not ref:
        raise ValueError("media_ref es obligatorio")
    existing = conn.execute("SELECT id FROM posts WHERE media_ref=? AND status!='archived' ORDER BY id LIMIT 1", (ref,)).fetchone()
    if existing:
        return get_post(conn, existing["id"], metrics=False), False
    chosen = platform or get_setting(conn, "default_platform", DEFAULT_PLATFORM)
    if chosen not in PLATFORMS:
        chosen = DEFAULT_PLATFORM
    clean_title = _text(title, "title", 300) or ref.rstrip("/").rsplit("/", 1)[-1]
    post, _, _ = upsert_post(conn, {"platform": chosen, "title": clean_title, "media_ref": ref, "status": "draft"})
    return post, True


# ---------------------------------------------------------------- statistics

def _sum_money(items: list[tuple[str, str]]) -> list[dict]:
    totals: dict[str, Decimal] = {}
    for currency, amount in items:
        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(amount)
    return [{"currency": key, "amount": str(value)} for key, value in sorted(totals.items())]


def best_hours(posts: list[dict], latest: dict[int, dict]) -> dict:
    """Average views of published posts by weekday (0 = Monday) and by hour (as written, local time)."""
    samples: list[tuple[int, int | None, int]] = []
    for post in posts:
        moment = when_parts(post["published_at"])
        metric = latest.get(post["id"])
        if post["status"] != "published" or moment is None or not metric or metric.get("views") is None:
            continue
        hour = None if len(post["published_at"] or "") <= 10 else moment.hour   # a bare date has no hour
        samples.append((moment.weekday(), hour, int(metric["views"])))

    def bucket(index: int, keys, label: str) -> list[dict]:
        out = []
        for key in keys:
            values = [s[2] for s in samples if s[index] == key]
            if values:
                out.append({label: key, "posts": len(values), "avg_views": round(sum(values) / len(values), 1)})
        return out

    slots: dict[tuple[int, int], list[int]] = {}
    for weekday, hour, views in samples:
        if hour is not None:
            slots.setdefault((weekday, hour), []).append(views)
    top = sorted(({"weekday": k[0], "hour": k[1], "posts": len(v), "avg_views": round(sum(v) / len(v), 1)} for k, v in slots.items()),
                 key=lambda s: (-s["avg_views"], -s["posts"]))[:5]
    return {"sample": len(samples), "by_weekday": bucket(0, range(7), "weekday"), "by_hour": bucket(1, range(24), "hour"),
            "top_slots": top, "note": "few_posts" if len(samples) < 5 else ""}


def stats(conn, platform: str = "") -> dict:
    if platform and platform not in PLATFORMS:
        raise ValueError("platform no válida: " + ", ".join(PLATFORMS))
    posts = [_row_post(r) for r in conn.execute("SELECT * FROM posts")]
    if platform:
        posts = [p for p in posts if p["platform"] == platform]
    latest = latest_metrics(conn, [p["id"] for p in posts])
    by_status = {s: 0 for s in STATUSES}
    for post in posts:
        by_status[post["status"]] += 1
    by_platform = []
    for key, meta in PLATFORMS.items():
        group = [p for p in posts if p["platform"] == key]
        if not group:
            continue
        entry: dict[str, Any] = {"platform": key, "label": meta["label"], "posts": len(group),
                                 "published": sum(1 for p in group if p["status"] == "published"),
                                 "scheduled": sum(1 for p in group if p["status"] == "scheduled")}
        for name in METRIC_FIELDS:
            entry[name] = sum((latest.get(p["id"]) or {}).get(name) or 0 for p in group)
        money = [((latest[p["id"]].get("currency") or "EUR"), latest[p["id"]]["revenue"]) for p in group
                 if latest.get(p["id"]) and latest[p["id"]].get("revenue") is not None]
        entry["revenue"] = _sum_money(money)
        entry["engagement"] = (round((entry["likes"] + entry["comments"] + entry["shares"] + entry["saves"]) / entry["views"], 4)
                               if entry["views"] else None)
        by_platform.append(entry)
    ranked = sorted((p for p in posts if (latest.get(p["id"]) or {}).get("views") is not None),
                    key=lambda p: -latest[p["id"]]["views"])[:5]
    top = [{"id": p["id"], "title": p["title"] or p["caption"][:60], "platform": p["platform"],
            "views": latest[p["id"]]["views"], "url": p["url"]} for p in ranked]
    return {"posts": len(posts), "by_status": by_status, "by_platform": by_platform, "top_posts": top,
            "best_hours": best_hours(posts, latest),
            "metrics_note": "Cada cifra es la última lectura guardada de cada publicación."}


# ---------------------------------------------------------------- agenda

def agenda_items(conn, date_from: date, date_to: date, base_url: str) -> list[dict]:
    """Scheduled posts as agenda items (kind ``publish``)."""
    items = []
    now = datetime.now()
    for row in conn.execute("SELECT * FROM posts WHERE status='scheduled' AND scheduled_at IS NOT NULL ORDER BY scheduled_at"):
        post = _row_post(row)
        moment = when_parts(post["scheduled_at"])
        if moment is None or not date_from <= moment.date() <= date_to:
            continue
        label = post["title"] or post["caption"][:60] or post["media_ref"] or f"#{post['id']}"
        detail = post["platform_label"] + (f" · {post['caption'][:120]}" if post["caption"] else "")
        overdue = moment < now if len(post["scheduled_at"]) > 10 else moment.date() < now.date()
        items.append({"id": f"mercator:publish:{post['id']}", "title": f"Publicar: {label} ({post['platform_label']})",
                      "start": post["scheduled_at"], "kind": "publish", "priority": "high" if overdue else "normal",
                      "url": f"{base_url}/publicacion#post-{post['id']}", "detail": detail})
    return items
