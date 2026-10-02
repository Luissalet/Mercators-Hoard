"""CSV import of post metrics, one export per platform.

The columns are matched by name (accents, case and punctuation folded) against lists of names the
platform exports are known to use in English and Spanish; the person can always change the mapping.
The presets are heuristics over recognisable column names, not a verified description of any export.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from typing import Any

import publishing

FIELDS = ("external_id", "title", "caption", "published_at", "url", "views", "likes", "comments", "shares",
          "saves", "sales", "revenue", "currency")

ALIASES: dict[str, tuple[str, ...]] = {
    "external_id": ("content", "contenido", "videoid", "idvideo", "postid", "idpublicacion", "idedelapublicacion", "id"),
    "title": ("videotitle", "titulodelvideo", "titulo", "title", "nombre", "name", "producto", "product", "design", "diseno"),
    "caption": ("description", "descripcion", "caption", "pie", "texto"),
    "published_at": ("videopublishtime", "horadepublicaciondelvideo", "publishtime", "posttime", "postdate",
                     "fechadepublicacion", "horadepublicacion", "publicado", "createtime", "datepublished", "fecha", "date"),
    "url": ("permalink", "videolink", "url", "link", "enlace", "videourl", "enlacepermanente"),
    "views": ("views", "visualizaciones", "videoviews", "totalviews", "reproducciones", "plays", "vistas"),
    "likes": ("likes", "megusta", "totallikes"),
    "comments": ("comments", "comentarios", "totalcomments", "commentsadded", "comentariosagregados"),
    "shares": ("shares", "compartidos", "totalshares", "vecesquesecompartio"),
    "saves": ("saves", "guardados", "totalbookmarks", "bookmarks", "addtofavorites", "favorites", "guardadosenfavoritos"),
    "sales": ("sales", "ventas", "downloads", "descargas"),
    "revenue": ("estimatedrevenue", "ingresosestimados", "revenue", "ingresos", "earnings", "importe", "amount"),
    "currency": ("currency", "moneda", "divisa"),
}
# Column names that identify an export; the first preset with a hit wins (a platform hint breaks ties).
PRESET_MARKERS: dict[str, tuple[str, ...]] = {
    "youtube_studio": ("watchtimehours", "tiempodevisualizacionhoras", "videopublishtime", "horadepublicaciondelvideo", "impressionsclickthroughrate"),
    "instagram": ("permalink", "postid", "reach", "alcance", "follows", "seguidores"),
    "tiktok": ("videolink", "totalbookmarks", "totalviews", "videoviews", "posttime"),
}
PRESET_PLATFORM = {"youtube_studio": "youtube", "instagram": "instagram_reel", "tiktok": "tiktok"}
PLATFORM_PRESET = {"youtube": "youtube_studio", "youtube_short": "youtube_studio", "instagram_reel": "instagram",
                   "instagram_post": "instagram", "tiktok": "tiktok"}
MONTHS = {"ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
          "sep": 9, "sept": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
TOTAL_LABELS = {"total", "totales", "totals"}


def fold(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def read_table(text: str) -> tuple[list[str], list[dict[str, str]], str]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("El archivo CSV está vacío")
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
    header = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    if not header or not rows:
        raise ValueError("El CSV no tiene cabecera o filas")
    return header, rows, dialect.delimiter


def detect_preset(header: list[str], platform: str = "") -> str:
    folded = {fold(h) for h in header}
    hits = {name: sum(1 for m in markers if m in folded) for name, markers in PRESET_MARKERS.items()}
    hinted = PLATFORM_PRESET.get(platform, "")
    if hinted and hits.get(hinted):
        return hinted
    best = max(hits, key=lambda k: hits[k])
    return best if hits[best] else "generic"


def suggest_mapping(header: list[str]) -> dict[str, str]:
    by_fold = {}
    for column in header:
        by_fold.setdefault(fold(column), column)
    for column in header:  # "Estimated revenue (USD)" also answers to "estimatedrevenue"
        by_fold.setdefault(fold(re.sub(r"\([^)]*\)", "", column)), column)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field in FIELDS:
        for alias in ALIASES[field]:
            column = by_fold.get(alias)
            if column and column not in used:
                mapping[field] = column
                used.add(column)
                break
    # "Estimated revenue (USD)": the currency is in the header.
    if "revenue" in mapping and "currency" not in mapping:
        match = re.search(r"\(([A-Za-z]{3})\)", mapping["revenue"])
        if match:
            mapping["currency_default"] = match.group(1).upper()
    return mapping


def preview(text: str, platform: str = "") -> dict:
    header, rows, delimiter = read_table(text)
    preset = detect_preset(header, platform)
    return {"header": header, "rows": len(rows), "delimiter": delimiter, "preset": preset,
            "platform": platform or PRESET_PLATFORM.get(preset, ""), "mapping": suggest_mapping(header),
            "sample": rows[:3]}


def parse_count(value: str) -> int | None:
    raw = str(value or "").strip().replace(" ", "")
    if not raw or raw in ("-", "—"):
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        raw = re.sub(r"[.,]", "", raw)
    elif re.fullmatch(r"\d+[.,]0+", raw):
        raw = re.split(r"[.,]", raw)[0]
    if not raw.isdigit():
        return None
    return int(raw)


def parse_when(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return publishing.norm_when(raw, "fecha")
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})\s+(?:de\s+)?([A-Za-zñ]{3,9})\.?,?\s+(?:de\s+)?(\d{4})", raw)
    if match and match.group(2)[:3].casefold() in MONTHS:
        try:
            return datetime(int(match.group(3)), MONTHS[match.group(2)[:3].casefold()], int(match.group(1))).date().isoformat()
        except ValueError:
            return None
    return None


def _norm_url(url: str) -> str:
    return re.sub(r"[?#].*$", "", url.strip()).rstrip("/").casefold()


def import_rows(conn, text: str, platform: str, mapping: dict[str, str], *, ts: str = "") -> dict:
    """Import a metrics CSV: rows are matched to existing posts (external id, URL, title) or create published posts."""
    if platform not in publishing.PLATFORMS:
        raise ValueError("platform no válida: " + ", ".join(publishing.PLATFORMS))
    if not isinstance(mapping, dict):
        raise ValueError("mapping no válido")
    header, rows, _ = read_table(text)
    mapping = {k: v for k, v in mapping.items() if v}
    for field, column in mapping.items():
        if field == "currency_default":
            continue
        if field not in FIELDS or column not in header:
            raise ValueError(f"Columna no válida para {field}: {column}")
    if not any(mapping.get(f) for f in ("external_id", "title", "url")):
        raise ValueError("Asigna al menos el identificador, el título o la URL")
    default_currency = (mapping.get("currency_default") or "EUR").upper()
    posts = [publishing._row_post(r) for r in conn.execute("SELECT * FROM posts WHERE platform=?", (platform,))]
    result = {"rows": len(rows), "created": 0, "updated": 0, "snapshots": 0, "unchanged": 0, "skipped": [], "warnings": []}
    snapshot_ts = publishing.norm_ts(ts)
    for number, row in enumerate(rows, start=2):
        def cell(field: str) -> str:
            return row.get(mapping[field], "") if mapping.get(field) else ""
        external, title, url = cell("external_id"), cell("title"), cell("url")
        if fold(external) in TOTAL_LABELS or (not external and fold(title) in TOTAL_LABELS):
            continue
        if not (external or title or url):
            result["skipped"].append({"row": number, "reason": "sin identificador, título ni URL"})
            continue
        found = None
        if external:
            found = next((p for p in posts if p["external_id"] and p["external_id"] == external), None)
        if not found and url:
            found = next((p for p in posts if p["url"] and _norm_url(p["url"]) == _norm_url(url)), None)
        label = title or cell("caption")[:80]  # exports without a title column are matched by caption start
        if not found and label:
            same = [p for p in posts if p["title"].casefold() == label.casefold()]
            found = same[0] if len(same) == 1 else None
        published = parse_when(cell("published_at")) if cell("published_at") else None
        if cell("published_at") and not published:
            result["warnings"].append(f"Fila {number}: fecha no reconocida ({cell('published_at')[:30]})")
        caption = cell("caption")
        if found is None:
            args: dict[str, Any] = {"platform": platform, "status": "published", "title": label or external,
                                    "caption": caption, "url": url, "external_id": external}
            if published:
                args["published_at"] = published
            found, _, _ = publishing.upsert_post(conn, args)
            posts.append(found)
            result["created"] += 1
        else:
            patch: dict[str, Any] = {"post_id": found["id"]}
            if external and not found["external_id"]:
                patch["external_id"] = external
            if url and not found["url"]:
                patch["url"] = url
            if published and not found["published_at"]:
                patch["published_at"] = published
            if len(patch) > 1:
                found, _, _ = publishing.upsert_post(conn, patch)
                posts[:] = [found if p["id"] == found["id"] else p for p in posts]
                result["updated"] += 1
        values: dict[str, Any] = {}
        for name in publishing.METRIC_FIELDS:
            if cell(name):
                count = parse_count(cell(name))
                if count is None:
                    result["warnings"].append(f"Fila {number}: {name} no numérico ({cell(name)[:20]})")
                values[name] = count
        if cell("revenue"):
            try:
                values["revenue"] = publishing._money(cell("revenue"))
                values["currency"] = (cell("currency") or default_currency).upper()
            except ValueError:
                result["warnings"].append(f"Fila {number}: importe no válido ({cell('revenue')[:20]})")
        if not any(v is not None for v in values.values()):
            continue
        latest = publishing.latest_metrics(conn, [found["id"]]).get(found["id"])
        candidate = {**{k: None for k in (*publishing.METRIC_FIELDS, "revenue", "currency")}, **values}
        if publishing.metrics_equal(latest, candidate):
            result["unchanged"] += 1
            continue
        publishing.add_metrics(conn, {"post_id": found["id"], "ts": snapshot_ts, **values}, source="csv")
        result["snapshots"] += 1
    return result
