"""Local project and sales dashboard. Run: python mercator.py."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

if __name__ == "__main__":  # modules that ``import mercator`` must get this running copy, not a second one
    sys.modules.setdefault("mercator", sys.modules["__main__"])

import cults_catalog
import mercator_family
import post_csv
import publishing
from hoard_link import money as hl_money
from hoard_link.sqlkit import Database

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("MERCATOR_DATA_DIR") or ROOT / "data")
DB = DATA / "mercator.sqlite3"
PROJECTS = {
    "watchhoard": {
        "name": "WatchHoard", "worker": "watchhoard",
        "env": ROOT.parent / "WatchHoard" / "watchhoard" / ".env",
        "public_env": ROOT.parent / "WatchHoard" / "watchhoard" / "apps" / "mobile" / ".env",
    },
    "bookhoard": {
        "name": "BookHoard", "worker": "bookhoard",
        "env": ROOT.parent / "MyBookHoard" / "bookhoard-v2" / "apps" / "mobile" / ".env",
    },
}
_refresh_lock = threading.Lock()


def env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def secrets() -> dict[str, str]:
    return {**env_file(ROOT / ".env"), **os.environ}


CORE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS metrics (
        project TEXT NOT NULL, source TEXT NOT NULL, metric TEXT NOT NULL,
        value REAL NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY (project, source, metric, observed_at)
    );
    CREATE TABLE IF NOT EXISTS source_status (
        project TEXT NOT NULL, source TEXT NOT NULL, state TEXT NOT NULL,
        detail TEXT NOT NULL, checked_at TEXT NOT NULL,
        PRIMARY KEY (project, source)
    );
    CREATE TABLE IF NOT EXISTS sales (
        fingerprint TEXT PRIMARY KEY, sold_at TEXT NOT NULL,
        product TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'cults-csv'
    );
    CREATE TABLE IF NOT EXISTS sales_imports (
        imported_at TEXT NOT NULL, file_hash TEXT NOT NULL,
        rows INTEGER NOT NULL, added INTEGER NOT NULL
    );
"""


def _add_batch_columns(conn: sqlite3.Connection) -> None:
    for table in ("sales", "sales_imports"):  # stores created before batches existed
        if "batch" not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN batch TEXT")


# Every step is idempotent (``IF NOT EXISTS``, a column added only when missing), so a store created by an older version, which
# has no ``schema_version`` table, simply runs both and ends at version 2.
MIGRATIONS = [CORE_SCHEMA + publishing.SCHEMA + cults_catalog.SCHEMA, _add_batch_columns]

_databases: dict[str, Database] = {}
_databases_lock = threading.Lock()


def database() -> Database:
    """The store of ``DB``: one connection shared by every thread behind one lock (WAL, a 15 s busy timeout, versioned migrations)."""
    key = str(DB)
    with _databases_lock:
        found = _databases.get(key)
        if found is None or found.closed:
            found = _databases[key] = Database(DB, migrations=MIGRATIONS)
        return found


def close_databases() -> None:
    """Close every open store (checkpoints the WAL). The server calls it when it stops; tests call it before deleting their folder."""
    with _databases_lock:
        opened = list(_databases.values())
        _databases.clear()
    for found in opened:
        found.close()


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """A write transaction on the store: committed when the block ends, rolled back when it raises."""
    with database().tx() as conn:
        yield conn


@contextmanager
def reading() -> Iterator[sqlite3.Connection]:
    """The store's connection for reading several tables consistently (no other thread writes while the block runs)."""
    found = database()
    with found.lock:
        yield found.conn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def status(conn: sqlite3.Connection | Database, project: str, source: str, state: str, detail: str) -> None:
    conn.execute("INSERT INTO source_status VALUES (?,?,?,?,?) ON CONFLICT(project,source) DO UPDATE SET "
                 "state=excluded.state, detail=excluded.detail, checked_at=excluded.checked_at",
                 (project, source, state, detail[:240], utcnow()))


def metric(conn: sqlite3.Connection | Database, project: str, source: str, name: str, value: int | float) -> None:
    conn.execute("INSERT INTO metrics VALUES (?,?,?,?,?)",
                 (project, source, name, value, utcnow()))


def request_json(url: str, headers: dict[str, str], body: dict | None = None) -> dict:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, payload, headers=headers,
                                 method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=12) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("Respuesta del proveedor no reconocida")
    return result


def supabase_users(conn: sqlite3.Connection | Database, project: str, config: dict) -> None:
    local = {**env_file(config.get("public_env", config["env"])), **env_file(config["env"])}
    url = local.get("SUPABASE_URL") or local.get("EXPO_PUBLIC_SUPABASE_URL")
    key = (secrets().get(f"{project.upper()}_SUPABASE_SERVICE_ROLE_KEY")
           or local.get("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        status(conn, project, "supabase", "needs_access", "Hace falta una clave de servidor para contar usuarios reales")
        return
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co"):
        status(conn, project, "supabase", "error", "URL de Supabase no válida")
        return
    users = []
    try:
        for page in range(1, 101):
            result = request_json(f"{url.rstrip('/')}/auth/v1/admin/users?page={page}&per_page=1000",
                                  {"apikey": key, "Authorization": f"Bearer {key}"})
            batch = result.get("users", [])
            if not isinstance(batch, list):
                raise ValueError("Respuesta de usuarios no reconocida")
            users.extend(batch)
            if len(batch) < 1000:
                break
        else:
            raise ValueError("Más de 100 páginas de usuarios; ampliar paginación")
        now = datetime.now(timezone.utc)
        recent = sum(1 for user in users if _within(user.get("created_at"), now, 30))
        metric(conn, project, "supabase", "users_total", len(users))
        metric(conn, project, "supabase", "signups_30d", recent)
        status(conn, project, "supabase", "ok", "Usuarios de Auth, no perfiles visibles")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        status(conn, project, "supabase", "error", _safe_error(exc))


def _within(value: str | None, now: datetime, days: int) -> bool:
    try:
        created = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return created.tzinfo is not None and now - timedelta(days=days) <= created <= now
    except ValueError:
        return False


CF_QUERY = """query($account: string, $script: string, $start: string, $end: string) {
  viewer { accounts(filter: {accountTag: $account}) {
    workersInvocationsAdaptive(limit: 1, filter: {
      scriptName: $script, datetime_geq: $start, datetime_leq: $end
    }) { sum { requests errors } }
  } }
}"""


def cloudflare_worker(conn: sqlite3.Connection | Database, project: str, config: dict) -> None:
    env = secrets()
    prefix = project.upper()
    token = env.get(f"{prefix}_CLOUDFLARE_API_TOKEN") or env.get("CLOUDFLARE_API_TOKEN")
    account = env.get(f"{prefix}_CLOUDFLARE_ACCOUNT_ID") or env.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        status(conn, project, "cloudflare", "needs_access", "Faltan token de Analytics y cuenta de Cloudflare")
        return
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    try:
        payload = request_json("https://api.cloudflare.com/client/v4/graphql",
                               {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                               {"query": CF_QUERY, "variables": {"account": account,
                               "script": config["worker"], "start": start.isoformat(), "end": end.isoformat()}})
        if payload.get("errors"):
            raise ValueError("Cloudflare rechazó la consulta de Analytics")
        accounts = payload.get("data", {}).get("viewer", {}).get("accounts", [])
        if not accounts:
            raise ValueError("Cuenta de Cloudflare no encontrada")
        rows = accounts[0].get("workersInvocationsAdaptive", [])
        if len(rows) > 1:
            raise ValueError("Cloudflare no devolvió el agregado esperado")
        metric(conn, project, "cloudflare", "requests_7d", sum(int(row.get("sum", {}).get("requests") or 0) for row in rows))
        metric(conn, project, "cloudflare", "errors_7d", sum(int(row.get("sum", {}).get("errors") or 0) for row in rows))
        status(conn, project, "cloudflare", "ok", "Invocaciones del Worker en los últimos 7 días")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        status(conn, project, "cloudflare", "error", _safe_error(exc))


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}; revisa permisos y configuración"
    if isinstance(exc, OSError):
        return "Servicio no disponible o error de red"
    return str(exc)[:180]


def refresh() -> dict:
    with _refresh_lock:
        store = database()      # one statement at a time: a slow provider never holds the store while the dashboard is being read
        for project, config in PROJECTS.items():
            supabase_users(store, project, config)
            cloudflare_worker(store, project, config)
    return summary()


def import_sales(text: str, columns: dict[str, str]) -> dict:
    """Import a sales CSV; the answer keeps its original three counters (see :func:`import_sales_batch`)."""
    result = import_sales_batch(text, columns)
    return {key: result[key] for key in ("rows", "added", "duplicates")}


def import_sales_batch(text: str, columns: dict[str, str]) -> dict:
    """Import a sales CSV. The lines this import adds form a batch (``batch``) that other apps can read with
    :func:`sales_batch`; rows that were already registered are not part of any new batch."""
    if not isinstance(text, str) or not isinstance(columns, dict):
        raise ValueError("Archivo o columnas no válidos")
    text = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    required = ("date", "product", "amount")
    if not rows or any(not columns.get(key) or columns[key] not in rows[0] for key in required):
        raise ValueError("Elige columnas de fecha, producto e ingreso")
    parsed = []
    occurrences: dict[str, int] = {}
    decimal = hl_money.detect_decimal(row[columns["amount"]] for row in rows)    # the column tells which mark is the decimal one
    for index, row in enumerate(rows, start=2):
        sold_at = publishing.day_of(row[columns["date"]])
        if sold_at is None:
            raise ValueError(f"Fecha no reconocida: {row[columns['date']]}")
        product = str(row[columns["product"]]).strip()
        if not product:
            raise ValueError(f"Fila {index}: falta fecha o producto")
        currency = str(row.get(columns.get("currency", ""), "EUR") or "EUR").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(f"Fila {index}: moneda no válida")
        typed = str(row[columns["amount"]])
        try:
            value = publishing.parse_amount(typed, decimal=decimal, currency=currency)
        except ValueError:      # a cell that disagrees with the rest of its column is read on its own
            value = publishing.parse_amount(typed, currency=currency)
        amount = publishing.amount_text(value, typed)
        sale_id = str(row.get(columns.get("id", ""), "")).strip()
        if sale_id:
            identity = f"id:{sale_id}"
        else:
            basis = "|".join((sold_at, product, amount, currency))
            occurrences[basis] = occurrences.get(basis, 0) + 1
            identity = f"row:{basis}|{occurrences[basis]}"
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        parsed.append((fingerprint, sold_at, product, amount, currency))
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    batch = "imp-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f") + "-" + file_hash[:6]
    with session() as conn:
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO sales(fingerprint,sold_at,product,amount,currency,batch) VALUES (?,?,?,?,?,?)",
                         [(*row, batch) for row in parsed])
        added = conn.total_changes - before
        conn.execute("INSERT INTO sales_imports(imported_at,file_hash,rows,added,batch) VALUES (?,?,?,?,?)",
                     (utcnow(), file_hash, len(parsed), added, batch))
    if added:
        mercator_family.emit("mercator.sales.imported", {"batch": batch, "rows": len(parsed), "added": added, "source": "cults-csv"})
    return {"rows": len(parsed), "added": added, "duplicates": len(parsed) - added, "batch": batch}


def sales_batch(batch: str) -> dict:
    """The sales lines one import added, in file order, for apps that book them (``line`` is 1-based and stable)."""
    if not isinstance(batch, str) or not batch.strip():
        raise ValueError("batch no válido")
    with reading() as conn:
        meta = conn.execute("SELECT imported_at, rows, added FROM sales_imports WHERE batch=? ORDER BY imported_at LIMIT 1",
                            (batch.strip(),)).fetchone()
        if meta is None:
            raise ValueError(f"No existe el lote de ventas {batch}")
        rows = conn.execute("SELECT fingerprint, sold_at, product, amount, currency FROM sales WHERE batch=? ORDER BY rowid",
                            (batch.strip(),)).fetchall()
    lines = [{"line": number, "id": row["fingerprint"][:16], "sold_at": row["sold_at"], "product": row["product"],
              "amount": row["amount"], "currency": row["currency"]} for number, row in enumerate(rows, start=1)]
    totals: dict[str, Decimal] = {}
    for line in lines:
        totals[line["currency"]] = totals.get(line["currency"], Decimal("0")) + Decimal(line["amount"])
    return {"ok": True, "batch": batch.strip(), "source": "cults-csv", "imported_at": meta["imported_at"], "rows": meta["rows"],
            "count": len(lines), "lines": lines,
            "by_currency": [{"currency": key, "income": str(value)} for key, value in sorted(totals.items())]}


def products() -> dict:
    """Product folders on disk (read-only) plus the listings imported from other apps (``catalog_from_vulcan``)."""
    items, folder_ok = _scan_products()
    imported = cults_catalog.list_items(DB)
    by_id = {item["id"].casefold(): item for item in items}
    for entry in imported:
        key = (entry["folder"].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or entry["title"]).casefold()
        match = by_id.get(key)
        if match is not None:
            match["catalog"] = {"ref": entry["ref"], "status": entry["status"], "price": entry["price"], "currency": entry["currency"]}
            continue
        items.append({"id": entry["folder"].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or entry["ref"], "title": entry["title"],
                      "has_listing": bool(entry["description"]), "tags": len(entry["tags"]), "updated_at": entry["updated_at"],
                      "source": entry["source"], "catalog": {"ref": entry["ref"], "status": entry["status"], "price": entry["price"],
                                                             "currency": entry["currency"]}})
    if not folder_ok and not imported:
        return {"state": "needs_access", "count": 0, "with_listing": 0, "items": []}
    items.sort(key=lambda item: item["id"])
    return {"state": "ok", "count": len(items), "with_listing": sum(1 for item in items if item["has_listing"]), "items": items}


def _scan_products() -> tuple[list[dict], bool]:
    default = Path.home() / "Desktop" / "Modelos" / "Contornos pokemon"
    root = Path(secrets().get("MERCATOR_PRODUCTS_DIR") or default)
    if not root.is_dir():
        return [], False
    items = []
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        listing = folder / "cults3d.json"
        entry = {"id": folder.name, "title": folder.name, "has_listing": False, "tags": 0,
                 "updated_at": None}
        if listing.is_file():
            try:
                content = json.loads(listing.read_text(encoding="utf-8-sig"))
                if isinstance(content, dict):
                    tags = content.get("tags") or []
                    entry.update({"title": str(content.get("title") or folder.name),
                                  "has_listing": True, "tags": len(tags) if isinstance(tags, list) else 0,
                                  "updated_at": datetime.fromtimestamp(listing.stat().st_mtime, timezone.utc).isoformat()})
                    if not isinstance(tags, list):
                        entry["invalid_listing"] = True
            except (OSError, ValueError):
                entry["invalid_listing"] = True
        items.append(entry)
    return items, True


def catalog_query(query: str = "", untagged: bool = False, missing: bool = False,
                  offset: int = 0, limit: int = 25) -> dict:
    if not isinstance(query, str) or not isinstance(untagged, bool) or not isinstance(missing, bool):
        raise ValueError("Filtros no válidos")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("offset o limit no válidos")
    catalog = products()
    matches = [item for item in catalog["items"] if
               (not query or query.casefold() in item["title"].casefold() or query.casefold() in item["id"].casefold()) and
               (not untagged or item["has_listing"] and item["tags"] == 0) and
               (not missing or not item["has_listing"] or item.get("invalid_listing"))]
    return {"state": catalog["state"], "total": len(matches), "offset": offset,
            "items": matches[offset:offset + limit]}


def sales_query(product: str = "", limit: int = 20) -> dict:
    if not isinstance(product, str) or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("Consulta de ventas no válida")
    if not DB.is_file():
        return {"total": 0, "by_currency": [], "sales": []}
    with reading() as conn:
        rows = [dict(row) for row in conn.execute("SELECT sold_at, product, amount, currency FROM sales ORDER BY sold_at DESC")]
    matches = [row for row in rows if product.casefold() in row["product"].casefold()]
    totals: dict[str, Decimal] = {}
    for row in matches:
        totals[row["currency"]] = totals.get(row["currency"], Decimal("0")) + Decimal(row["amount"])
    return {"total": len(matches), "by_currency": [{"currency": key, "income": str(value)} for key, value in sorted(totals.items())],
            "sales": matches[:limit]}


def summary() -> dict:
    with reading() as conn:
        states = [dict(row) for row in conn.execute("SELECT * FROM source_status ORDER BY project,source")]
        metrics = [dict(row) for row in conn.execute("""
            SELECT m.* FROM metrics m JOIN (
                SELECT project,source,metric,MAX(observed_at) AS last_at FROM metrics
                GROUP BY project,source,metric
            ) x ON x.project=m.project AND x.source=m.source AND x.metric=m.metric AND x.last_at=m.observed_at
            ORDER BY m.project,m.source,m.metric
        """)]
        history = [dict(row) for row in conn.execute("""
            SELECT project,source,metric,value,observed_at FROM metrics
            WHERE observed_at >= ? ORDER BY observed_at
        """, ((datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),))]
        all_sales = [dict(row) for row in conn.execute("SELECT * FROM sales ORDER BY sold_at DESC")]
        last_import_row = conn.execute("SELECT imported_at, rows, added FROM sales_imports ORDER BY imported_at DESC LIMIT 1").fetchone()
    aggregates_by_key: dict[tuple[str, str], dict] = {}
    monthly_by_key: dict[tuple[str, str], dict] = {}
    for sale in all_sales:
        amount = Decimal(sale["amount"])
        product_key = (sale["currency"], sale["product"])
        monthly_key = (sale["sold_at"][:7], sale["currency"])
        for bucket, key, label in ((aggregates_by_key, product_key, "product"),
                                   (monthly_by_key, monthly_key, "month")):
            entry = bucket.setdefault(key, {"currency": sale["currency"], label: key[1] if label == "product" else key[0],
                                            "sales": 0, "income": Decimal("0")})
            entry["sales"] += 1
            entry["income"] += amount
    aggregates = sorted(({**entry, "income": str(entry["income"])} for entry in aggregates_by_key.values()),
                        key=lambda entry: Decimal(entry["income"]), reverse=True)
    monthly = sorted(({**entry, "income": str(entry["income"])} for entry in monthly_by_key.values()),
                     key=lambda entry: entry["month"])
    return {"projects": [{"id": key, "name": item["name"], "worker": item["worker"]}
                         for key, item in PROJECTS.items()], "statuses": states,
            "metrics": metrics, "history": history, "sales": all_sales[:100], "sales_count": len(all_sales),
            "product_sales": aggregates, "monthly_sales": monthly,
            "last_sales_import": dict(last_import_row) if last_import_row else None,
            "catalog": products()}


def background_refresh(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            refresh()
        except Exception as exc:
            # Keep the local dashboard alive if a provider returns unexpected data.
            print(f"Actualización en segundo plano fallida: {type(exc).__name__}")
        stop.wait(6 * 60 * 60)


STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/publicacion": ("publicacion.html", "text/html; charset=utf-8"), "/publicacion.html": ("publicacion.html", "text/html; charset=utf-8"),
    "/publicacion.js": ("publicacion.js", "text/javascript; charset=utf-8"), "/publicacion.css": ("publicacion.css", "text/css; charset=utf-8"),
}
MAX_BODY = 5_000_000


def base_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('MERCATOR_PORT', '5195')}"


def agenda_provider(date_from, date_to, sphere):
    """Scheduled posts for the family agenda."""
    with reading() as conn:
        return publishing.agenda_items(conn, date_from, date_to, base_url())


def publishing_meta() -> dict:
    return {"platforms": [{"id": key, **meta} for key, meta in publishing.PLATFORMS.items()],
            "statuses": list(publishing.STATUSES), "presets": list(post_csv.PRESET_MARKERS)}


def post_media_file(post_id: int) -> tuple[Path, str] | None:
    """The image or video a post's ``media_ref`` points to, when it is an absolute local file of a servable type."""
    with reading() as conn:
        post = publishing.get_post(conn, post_id, metrics=False)
    ref = post["media_ref"]
    if not ref or ref.startswith("hoard://"):
        return None
    path = Path(ref)
    kind = publishing.MEDIA_EXTENSIONS.get(path.suffix.lower())
    if kind is None or not path.is_absolute() or not path.is_file():
        return None
    return path, kind


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, value: dict) -> None:
        self._reply(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _trusted(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        return not origin or urlsplit(origin).netloc == self.headers.get("Host")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_BODY:
            raise ValueError("Archivo demasiado grande (máximo 5 MB)")
        body = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("Cuerpo no válido")
        return body

    def _serve_media(self, post_id: int) -> None:
        found = post_media_file(post_id)
        if found is None:
            self._json(404, {"error": "Sin vista previa para este media"})
            return
        path, kind = found
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if match and (match.group(1) or match.group(2)) and size:
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            left = end - start + 1 if size else 0
            while left > 0:
                block = handle.read(min(1 << 20, left))
                if not block:
                    break
                self.wfile.write(block)
                left -= len(block)

    def do_GET(self) -> None:
        if not self._trusted():
            self._json(403, {"error": "Origen no permitido"})
            return
        parts = urlsplit(self.path)
        path, query = parts.path, {key: values[0] for key, values in parse_qs(parts.query).items()}
        try:
            if path == "/api/health":
                self._json(200, {"service": "mercator-hoard", "status": "ok", "hoard_link": mercator_family.health_block()})
            elif path == "/api/summary":
                self._json(200, summary())
            elif path == "/api/publishing/meta":
                self._json(200, publishing_meta())
            elif path == "/api/posts":
                with reading() as conn:
                    listing = publishing.list_posts(conn, query.get("status", ""), query.get("platform", ""), query.get("from", ""),
                                                    query.get("to", ""), query.get("q", ""), int(query.get("limit", 500)),
                                                    int(query.get("offset", 0)))
                self._json(200, listing)
            elif path == "/api/posts/stats":
                with reading() as conn:
                    totals = publishing.stats(conn, query.get("platform", ""))
                self._json(200, totals)
            elif re.fullmatch(r"/api/posts/\d+(/media)?", path):
                post_id = int(path.split("/")[3])
                if path.endswith("/media"):
                    self._serve_media(post_id)
                else:
                    with reading() as conn:
                        post = publishing.get_post(conn, post_id)
                    self._json(200, {"post": post})
            elif path == "/api/agent/tools":
                import agent_tools
                self._json(200, {"instructions": agent_tools.INSTRUCTIONS, "tools": agent_tools.tool_catalog()})
            elif path == "/api/family/agenda":
                if not mercator_family.bearer_ok(self.headers.get("Authorization", "")):
                    self._json(401, {"ok": False, "error": "a family bearer token is required", "items": []})
                else:
                    self._json(200, mercator_family.agenda(agenda_provider, query.get("from"), query.get("to"), query.get("sphere", "")))
            elif path == "/icon.svg":
                self._reply(200, (ROOT / "icon.svg").read_bytes(), "image/svg+xml")
            elif path == "/app-icon.png":
                self._reply(200, (ROOT / "app-icon.png").read_bytes(), "image/png")
            elif path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                self._reply(200, (ROOT / "static" / name).read_bytes(), content_type)
            else:
                self._json(404, {"error": "No encontrado"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})

    def _post_agent_call(self) -> None:
        import agent_tools
        if not mercator_family.bearer_ok(self.headers.get("Authorization", "")):
            self._json(401, {"ok": False, "error": "Invalid MCP token."})
            return
        started = time.monotonic()
        body, name, ok, error = {}, "", False, ""
        try:
            body = self._body()
            name = str(body.get("name") or body.get("tool") or "")
            arguments = body.get("arguments") if body.get("arguments") is not None else body.get("args")
            result = agent_tools.call_tool(name, arguments)
            ok = True
            self._json(200, result)
        except KeyError as exc:
            error = str(exc.args[0]) if exc.args else "Unknown tool"
            self._json(404, {"ok": False, "error": error, "code": "unknown_tool"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            error = str(exc)
            self._json(400, {"ok": False, "error": error, "code": "invalid"})
        except (sqlite3.Error, OSError) as exc:      # a failure of the store or the disk answers, instead of dropping the connection
            error = f"{type(exc).__name__}: {exc}"[:200]
            self._json(500, {"ok": False, "error": error, "code": "internal"})
        finally:
            mercator_family.record_call(name or "?", ok, int((time.monotonic() - started) * 1000),
                                        caller=str(body.get("caller") or ""), error=error)

    def do_POST(self) -> None:
        if not self._trusted():
            self._json(403, {"error": "Origen no permitido"})
            return
        path = urlsplit(self.path).path
        if path == "/api/agent/call":
            self._post_agent_call()
            return
        routes = {"/api/refresh", "/api/sales/import", "/api/posts", "/api/posts/delete", "/api/posts/schedule", "/api/posts/publish",
                  "/api/posts/metrics", "/api/posts/import/preview", "/api/posts/import", "/api/posts/caption", "/api/catalog/from-vulcan"}
        if path not in routes:
            self._json(404, {"error": "No encontrado"})
            return
        try:
            import agent_tools
            body = {} if path == "/api/refresh" else self._body()
            if path == "/api/refresh":
                self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                result = refresh()
            elif path == "/api/sales/import":
                result = import_sales_batch(body.get("csv", ""), body.get("columns", {}))
            elif path == "/api/posts":
                result = agent_tools.call_tool("post_upsert", body, cap=False)
            elif path == "/api/posts/delete":
                with session() as conn:
                    result = {"ok": True, "deleted": publishing.delete_post(conn, body.get("post_id"))["id"]}
            elif path == "/api/posts/schedule":
                result = agent_tools.call_tool("post_schedule", body, cap=False)
            elif path == "/api/posts/publish":
                result = agent_tools.call_tool("post_publish", body, cap=False)
            elif path == "/api/posts/metrics":
                result = agent_tools.call_tool("post_metrics_add", body, cap=False)
            elif path == "/api/posts/import/preview":
                result = {"ok": True, **post_csv.preview(body.get("csv", ""), body.get("platform", ""))}
            elif path == "/api/posts/import":
                with session() as conn:
                    result = {"ok": True, **post_csv.import_rows(conn, body.get("csv", ""), body.get("platform", ""), body.get("mapping", {}))}
            elif path == "/api/posts/caption":
                result = agent_tools.call_tool("post_caption_suggest", body, cap=False)
            else:
                result = agent_tools.call_tool("catalog_from_vulcan", body, cap=False)
            self._json(200, result)
        except (ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        # Do not write request bodies, headers or credentials to logs.
        print(f"{self.address_string()} {fmt % args}")


def main() -> None:
    port = int(os.environ.get("MERCATOR_PORT", "5195"))
    database()
    mercator_family.configure(DATA)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    stop = threading.Event()
    threading.Thread(target=background_refresh, args=(stop,), daemon=True).start()
    print(f"Mercator's Hoard: http://127.0.0.1:{port}")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # a stop request closes the store like Ctrl+C does
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        stop.set()
        server.server_close()
        close_databases()


if __name__ == "__main__":
    main()
