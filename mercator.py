"""Local project and sales dashboard. Run: python mercator.py."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
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


def db() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
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
    """)
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def status(conn: sqlite3.Connection, project: str, source: str, state: str, detail: str) -> None:
    conn.execute("INSERT INTO source_status VALUES (?,?,?,?,?) ON CONFLICT(project,source) DO UPDATE SET "
                 "state=excluded.state, detail=excluded.detail, checked_at=excluded.checked_at",
                 (project, source, state, detail[:240], utcnow()))


def metric(conn: sqlite3.Connection, project: str, source: str, name: str, value: int | float) -> None:
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


def supabase_users(conn: sqlite3.Connection, project: str, config: dict) -> None:
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


def cloudflare_worker(conn: sqlite3.Connection, project: str, config: dict) -> None:
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
        with closing(db()) as conn, conn:
            for project, config in PROJECTS.items():
                supabase_users(conn, project, config)
                cloudflare_worker(conn, project, config)
    return summary()


def parse_amount(value: str) -> Decimal:
    raw = str(value).strip().replace("€", "").replace("$", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        amount = Decimal(raw)
        if not amount.is_finite():
            raise ValueError(f"Importe no válido: {value}")
        return amount
    except InvalidOperation as exc:
        raise ValueError(f"Importe no válido: {value}") from exc


def parse_date(value: str) -> str:
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S",
                "%d-%m-%Y", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Fecha no reconocida: {value}") from exc


def import_sales(text: str, columns: dict[str, str]) -> dict:
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
    for index, row in enumerate(rows, start=2):
        sold_at = parse_date(row[columns["date"]])
        product = str(row[columns["product"]]).strip()
        if not sold_at or not product:
            raise ValueError(f"Fila {index}: falta fecha o producto")
        amount = parse_amount(row[columns["amount"]])
        currency = str(row.get(columns.get("currency", ""), "EUR") or "EUR").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(f"Fila {index}: moneda no válida")
        sale_id = str(row.get(columns.get("id", ""), "")).strip()
        if sale_id:
            identity = f"id:{sale_id}"
        else:
            basis = "|".join((sold_at, product, str(amount), currency))
            occurrences[basis] = occurrences.get(basis, 0) + 1
            identity = f"row:{basis}|{occurrences[basis]}"
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        parsed.append((fingerprint, sold_at, product, str(amount), currency))
    with closing(db()) as conn, conn:
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO sales(fingerprint,sold_at,product,amount,currency) VALUES (?,?,?,?,?)", parsed)
        added = conn.total_changes - before
        conn.execute("INSERT INTO sales_imports VALUES (?,?,?,?)",
                     (utcnow(), hashlib.sha256(text.encode("utf-8")).hexdigest(), len(parsed), added))
    return {"rows": len(parsed), "added": added, "duplicates": len(parsed) - added}


def products() -> dict:
    default = Path.home() / "Desktop" / "Modelos" / "Contornos pokemon"
    root = Path(secrets().get("MERCATOR_PRODUCTS_DIR") or default)
    if not root.is_dir():
        return {"state": "needs_access", "count": 0, "with_listing": 0, "items": []}
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
                    entry.update({"title": str(content.get("title") or folder.name),
                                  "has_listing": True, "tags": len(content.get("tags") or []),
                                  "updated_at": datetime.fromtimestamp(listing.stat().st_mtime, timezone.utc).isoformat()})
            except (OSError, ValueError):
                entry["invalid_listing"] = True
        items.append(entry)
    items.sort(key=lambda item: item["id"])
    return {"state": "ok", "count": len(items),
            "with_listing": sum(1 for item in items if item["has_listing"]), "items": items}


def summary() -> dict:
    with closing(db()) as conn, conn:
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

    def do_GET(self) -> None:
        if not self._trusted():
            self._json(403, {"error": "Origen no permitido"})
            return
        if self.path == "/api/health":
            self._json(200, {"service": "mercator-hoard", "status": "ok"})
        elif self.path == "/api/summary":
            self._json(200, summary())
        elif self.path == "/icon.svg":
            self._reply(200, (ROOT / "icon.svg").read_bytes(), "image/svg+xml")
        elif self.path == "/app-icon.png":
            self._reply(200, (ROOT / "app-icon.png").read_bytes(), "image/png")
        elif self.path in ("/", "/index.html", "/app.js", "/style.css"):
            name = "index.html" if self.path == "/" else self.path.lstrip("/")
            content_type = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                            "style.css": "text/css; charset=utf-8"}[name]
            self._reply(200, (ROOT / "static" / name).read_bytes(), content_type)
        else:
            self._json(404, {"error": "No encontrado"})

    def do_POST(self) -> None:
        if not self._trusted():
            self._json(403, {"error": "Origen no permitido"})
            return
        if self.path not in ("/api/refresh", "/api/sales/import"):
            self._json(404, {"error": "No encontrado"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 5_000_000:
                raise ValueError("Archivo demasiado grande (máximo 5 MB)")
            body = json.loads(self.rfile.read(length) or b"{}")
            result = refresh() if self.path == "/api/refresh" else import_sales(body.get("csv", ""), body.get("columns", {}))
            self._json(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        # Do not write request bodies, headers or credentials to logs.
        print(f"{self.address_string()} {fmt % args}")


def main() -> None:
    port = int(os.environ.get("MERCATOR_PORT", "5195"))
    db().close()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    stop = threading.Event()
    threading.Thread(target=background_refresh, args=(stop,), daemon=True).start()
    print(f"Mercator's Hoard: http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
