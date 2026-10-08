"""The tools Mercator offers to the assistant and to the other apps. One catalogue feeds the stdio MCP bridge
(``mcp_server.py``) and the family agent contract (``GET /api/agent/tools``, ``POST /api/agent/call``)."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable

import cults_catalog
import mercator_family
import publishing
from hoard_link.agentkit import cap_result

INSTRUCTIONS = (
    "Mercator's Hoard keeps the owner's publishing plan (reels, shorts, videos, Cults3D listings), the metrics of each post, "
    "the Cults3D catalogue and the sales imported from Cults. Use posts_list / post_get to look before changing anything. "
    "Never invent metrics: post_metrics_add only records numbers the owner or a platform export gave. A post is marked "
    "published only with post_publish (it takes the real URL). Revenue is shown per currency and is not profit."
)

STRING = {"type": "string"}
INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}
NULLABLE_STRING = {"type": ["string", "null"]}
PLATFORM = {"type": "string", "enum": list(publishing.PLATFORMS)}
STATUS = {"type": "string", "enum": list(publishing.STATUSES)}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    out: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


def _ann(read_only: bool, idempotent: bool | None = None) -> dict:
    return {"readOnlyHint": read_only, "destructiveHint": False,
            "idempotentHint": read_only if idempotent is None else idempotent, "openWorldHint": False}


# ------------------------------------------------------------------ handlers

def _configure() -> None:
    import mercator
    mercator_family.configure(mercator.DATA)


def _after_write(post: dict, previous: dict | None) -> None:
    status_before = previous["status"] if previous else None
    data = {"post_id": post["id"], "ref": post["ref"], "platform": post["platform"], "title": post["title"][:120]}
    if post["status"] != status_before:
        if post["status"] == "scheduled":
            mercator_family.emit("mercator.post.scheduled", {**data, "scheduled_at": post["scheduled_at"]})
        elif post["status"] == "published":
            mercator_family.emit("mercator.post.published", {**data, "url": post["url"], "published_at": post["published_at"]})
    if post["media_ref"].startswith("hoard://") and (previous is None or previous["media_ref"] != post["media_ref"]):
        mercator_family.link_ref(post["ref"], post["media_ref"], "publishes", from_label=post["title"][:80])


def _store(fn: Callable[[Any], Any], *, write: bool = True) -> Any:
    """Run ``fn(conn)`` on the store: in one transaction (committed, or rolled back when it raises) or, for a read, under its lock."""
    import mercator
    with (mercator.session() if write else mercator.reading()) as conn:
        return fn(conn)


def posts_list(args: dict) -> dict:
    return _store(lambda c: publishing.list_posts(
        c, args.get("status") or "", args.get("platform") or "", args.get("from") or "", args.get("to") or "",
        args.get("q") or "", args.get("limit", 50), args.get("offset", 0)), write=False)


def post_get(args: dict) -> dict:
    return _store(lambda c: {"post": publishing.get_post(c, args.get("post_id"))}, write=False)


def post_upsert(args: dict) -> dict:
    def run(conn):
        post, previous, created = publishing.upsert_post(conn, args)
        return post, previous, created
    post, previous, created = _store(run)
    _after_write(post, previous)
    return {"ok": True, "created": created, "post": post}


def post_schedule(args: dict) -> dict:
    if not args.get("scheduled_at"):
        raise ValueError("scheduled_at es obligatorio")
    post, previous, _ = _store(lambda c: publishing.upsert_post(
        c, {"post_id": args.get("post_id"), "scheduled_at": args["scheduled_at"], "status": "scheduled"}))
    _after_write(post, previous)
    return {"ok": True, "post": post}


def post_publish(args: dict) -> dict:
    fields: dict[str, Any] = {"post_id": args.get("post_id"), "status": "published"}
    if args.get("url"):
        fields["url"] = args["url"]
    if args.get("published_at"):
        fields["published_at"] = args["published_at"]
    post, previous, _ = _store(lambda c: publishing.upsert_post(c, fields))
    _after_write(post, previous)
    return {"ok": True, "post": post}


def post_metrics_add(args: dict) -> dict:
    metric = _store(lambda c: publishing.add_metrics(c, args))
    return {"ok": True, "metrics": metric}


def posts_stats(args: dict) -> dict:
    return {"ok": True, **_store(lambda c: publishing.stats(c, args.get("platform") or ""), write=False)}


def post_metrics_compare(args: dict) -> dict:
    return {"ok": True, **_store(lambda c: publishing.compare_metrics(
        c, args.get("post_id"), args.get("from_ts"), args.get("to_ts")), write=False)}


def post_draft_from_media(args: dict) -> dict:
    post, created = _store(lambda c: publishing.draft_from_media(c, args.get("media_ref"), args.get("title"), args.get("platform")))
    if created:
        mercator_family.emit("mercator.post.drafted", {"post_id": post["id"], "ref": post["ref"], "media_ref": post["media_ref"],
                                                       "title": post["title"][:120]})
        _after_write(post, None)
    return {"ok": True, "created": created, "post_id": post["id"], "post": post}


def sales_batch_get(args: dict) -> dict:
    import mercator
    return mercator.sales_batch(args.get("batch"))


def catalog_from_vulcan(args: dict) -> dict:
    call_args = {"folder": args["folder"]} if args.get("folder") else {}
    answer = mercator_family.call("vulcan", "listings_export_catalog", call_args, timeout=120.0)
    if not answer.get("ok"):
        return {"ok": False, "error": "Vulcan no respondió: " + str(answer.get("error") or "¿está Vulcan arrancado?")[:200]}
    payload = answer.get("result")
    if isinstance(payload, dict) and payload.get("ok") is False:
        return {"ok": False, "error": "Vulcan: " + str(payload.get("error") or "error")[:200]}
    listings = payload.get("listings") if isinstance(payload, dict) else None
    if not isinstance(listings, list):
        return {"ok": False, "error": "Vulcan devolvió un formato de catálogo desconocido"}
    counts = _store(lambda c: cults_catalog.upsert(c, listings, "vulcan"))
    return {"ok": True, "received": len(listings), **counts}


def catalog_search(args: dict) -> dict:
    import mercator
    return mercator.catalog_query(**args)


def sales_search(args: dict) -> dict:
    import mercator
    return mercator.sales_query(**args)


#: Replaced in tests; ``(system, user) -> text | None``.
llm: Callable[[str, str], str | None] | None = None


def _default_llm(system: str, user: str) -> str | None:
    try:
        from hoard_link import config as cfg_mod
        from hoard_link import link as link_mod
    except Exception:  # noqa: BLE001 - no httpx (the model backend needs it): no suggestions
        return None

    async def run() -> str | None:
        base = cfg_mod.LinkConfig.load(None, app="mercator")
        cfg = cfg_mod.LinkConfig(app="mercator", only_resident=True, faustus_urls=base.faustus_urls, faustus_token=base.faustus_token,
                                 comfy_url=base.comfy_url, capabilities=base.capabilities, gpu_lease=False)
        async with link_mod.Link(cfg) as link:
            res = await link.resolve("llm")
            if not res.resolved or res.details.get("resident") is False:
                return None
            out = await link.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                  max_tokens=500, temperature=0.7, effort="off")
            return out.text

    try:
        return asyncio.run(asyncio.wait_for(run(), timeout=60))
    except Exception:  # noqa: BLE001
        return None


def post_caption_suggest(args: dict) -> dict:
    """Up to three caption proposals from a language model that is already loaded; never loads one."""
    def read(conn):
        if args.get("post_id"):
            return publishing.get_post(conn, args["post_id"], metrics=False)
        return None
    post = _store(read, write=False)
    platform = args.get("platform") or (post["platform"] if post else publishing.DEFAULT_PLATFORM)
    if platform not in publishing.PLATFORMS:
        raise ValueError("platform no válida: " + ", ".join(publishing.PLATFORMS))
    title = args.get("title") or (post["title"] if post else "")
    notes = args.get("notes") or (post["notes"] if post else "")
    if not title and not notes:
        raise ValueError("Indica post_id, title o notes")
    meta = publishing.PLATFORMS[platform]
    limit = meta["caption_limit"] or 1000
    system = (f"Escribe 3 propuestas de texto para una publicación de {meta['label']} en el idioma del título, "
              f"de como máximo {limit} caracteres cada una. Usa SOLO los datos dados; no inventes características, cifras ni fechas. "
              "Devuelve una propuesta por línea, numeradas 1., 2., 3., sin comentarios.")
    user = f"Título: {title}\nNotas: {notes or '(sin notas)'}"
    text = (llm or _default_llm)(system, user)
    if not text:
        return {"ok": False, "error": "No hay un modelo de lenguaje residente al que llegar (Hoard Link); el texto se escribe a mano."}
    options = [re.sub(r"^\s*\d+[.)]\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\s*\d+[.)]", ln)]
    options = [o[:limit] for o in options if o][:3] or [text.strip()[:limit]]
    return {"ok": True, "platform": platform, "suggestions": options, "note": "Propuestas sin verificar: revisa los datos antes de publicar."}


# ------------------------------------------------------------------ catalogue

def plausible_query(args):
    """Read external statistics, then store the exact source response and query."""
    import plausible_stats as stats
    body = stats.query_body(args)
    project = args.get('project') or 'website'
    if not isinstance(project, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', project):
        raise ValueError('Invalid project identifier')
    response, origin = stats.fetch(body)
    return _store(lambda conn: stats.capture(conn, project, body, response, origin))

def plausible_history(args):
    import plausible_stats as stats
    return _store(lambda conn: stats.list_snapshots(conn, args.get('project',''), args.get('limit',20)))

TOOLS: list[dict[str, Any]] = [
    {"name": "mercator_catalog",
     "description": "Search local Cults listings by name; find the ones without tags or listing. Read-only.\n"
                    "Buscar fichas locales de Cults por nombre y revisar cuáles carecen de etiquetas o ficha. Solo lectura; "
                    "sinónimos: catálogo, modelos, productos, tags.",
     "inputSchema": _schema({"query": STRING, "untagged": BOOLEAN, "missing": BOOLEAN, "offset": INTEGER, "limit": INTEGER}),
     "annotations": {"readOnlyHint": True, "openWorldHint": False}, "run": catalog_search},
    {"name": "mercator_sales",
     "description": "Imported Cults sales by product, totals per currency. Read-only.\n"
                    "Consultar ventas de Cults importadas por producto, con totales separados por moneda. Solo lectura; "
                    "sinónimos: ventas, ingresos, qué vende.",
     "inputSchema": _schema({"product": STRING, "limit": INTEGER}),
     "annotations": {"readOnlyHint": True, "openWorldHint": False}, "run": sales_search},
    {"name": "posts_list",
     "description": "List publishing posts (reels, shorts, videos, Cults listings) by status, platform, date.\n"
                    "Lista las publicaciones del plan de publicación. Sinónimos: calendario de publicaciones, reels programados, "
                    "borradores, qué toca publicar, shorts, vídeos, Cults3D.",
     "inputSchema": _schema({"status": STATUS, "platform": PLATFORM, "from": STRING, "to": STRING, "q": STRING,
                             "limit": INTEGER, "offset": INTEGER}),
     "annotations": _ann(True), "run": posts_list},
    {"name": "post_get",
     "description": "One post with caption, hashtags, media and metric snapshots.\n"
                    "Una publicación con su texto, hashtags, media y lecturas de métricas. Sinónimos: ver publicación, detalle, métricas.",
     "inputSchema": _schema({"post_id": INTEGER}, ["post_id"]), "annotations": _ann(True), "run": post_get},
    {"name": "post_upsert",
     "description": "Create or edit a post: platform, title, caption, hashtags, media_ref, status, dates (write).\n"
                    "Crea o edita una publicación (idea, borrador, programada, publicada, archivada). Sinónimos: apunta un reel, "
                    "guarda el texto del post, añade hashtags, nueva publicación.",
     "inputSchema": _schema({"post_id": INTEGER, "platform": PLATFORM, "title": STRING, "caption": STRING,
                             "hashtags": {"type": "array", "items": STRING}, "media_ref": STRING, "status": STATUS,
                             "scheduled_at": NULLABLE_STRING, "published_at": NULLABLE_STRING, "url": STRING,
                             "notes": STRING, "external_id": STRING}),
     "annotations": _ann(False, False), "run": post_upsert},
    {"name": "post_schedule",
     "description": "Schedule a post for a date and time (write); it appears in the family agenda.\n"
                    "Programa una publicación para una fecha y hora. Sinónimos: agendar reel, programar post, publicar el día.",
     "inputSchema": _schema({"post_id": INTEGER, "scheduled_at": STRING}, ["post_id", "scheduled_at"]),
     "annotations": _ann(False, True), "run": post_schedule},
    {"name": "post_publish",
     "description": "Mark a post as published with its real URL (write).\n"
                    "Marca una publicación como publicada con su enlace real. Sinónimos: ya está subido, publicado, poner la URL.",
     "inputSchema": _schema({"post_id": INTEGER, "url": STRING, "published_at": STRING}, ["post_id"]),
     "annotations": _ann(False, True), "run": post_publish},
    {"name": "post_metrics_add",
     "description": "Record a metrics snapshot for a post: views, likes, comments, shares, saves, sales, revenue (write).\n"
                    "Anota una lectura de métricas de una publicación. Sinónimos: visualizaciones, me gusta, guardados, ventas, ingresos.",
     "inputSchema": _schema({"post_id": INTEGER, "ts": STRING, "views": INTEGER, "likes": INTEGER, "comments": INTEGER,
                             "shares": INTEGER, "saves": INTEGER, "sales": INTEGER, "revenue": STRING, "currency": STRING},
                            ["post_id"]),
     "annotations": _ann(False, False), "run": post_metrics_add},
    {"name": "posts_stats",
     "description": "Publishing totals per platform, best weekdays and hours, top posts. Read-only.\n"
                    "Estadísticas de publicación: totales por plataforma, mejores horas y días, publicaciones que más funcionan. "
                    "Sinónimos: cuándo publicar, mejores horas, rendimiento de reels.",
     "inputSchema": _schema({"platform": PLATFORM}), "annotations": _ann(True), "run": posts_stats},
    {"name": "post_metrics_compare",
     "description": "Compare a post's saved metric snapshots between two instants: deltas and growth. Read-only.\n"
                    "Latest whole snapshot at or before each instant; omitted metrics stay unknown, no backfill. "
                    "ISO timestamps: offsets recommended; naive times use the machine's local timezone. "
                    "Returns actual endpoint snapshots, per-metric deltas and percent change. Read-only. "
                    "Missing values stay null; revenues are compared only in the same currency. "
                    "Observed changes, not sums of daily activity or profit. Negative changes are preserved.\n"
                    "Compara la evolución de una publicación entre dos fechas: visitas, interacciones, ventas e ingresos. "
                    "Sinónimos: crecimiento, diferencia de métricas, cuánto ha subido, variación de visitas.",
     "inputSchema": _schema({"post_id": INTEGER, "from_ts": STRING, "to_ts": STRING},
                            ["post_id", "from_ts", "to_ts"]),
     "annotations": _ann(True), "run": post_metrics_compare},
    {"name": "post_draft_from_media",
     "description": "Create a draft post from a media reference (render, production, model) (write).\n"
                    "Crea un borrador de publicación a partir de un vídeo o modelo de otra app. Sinónimos: preparar post del render, "
                    "borrador desde Lumiere, Prospero o Vulcan.",
     "inputSchema": _schema({"media_ref": STRING, "title": STRING, "platform": PLATFORM}, ["media_ref", "title"]),
     "annotations": _ann(False, True), "run": post_draft_from_media},
    {"name": "post_caption_suggest",
     "description": "Suggest up to three captions with a language model already loaded; fails clearly without one.\n"
                    "Propone textos para una publicación solo si hay un modelo ya cargado. Sinónimos: sugerir texto, redactar caption, pie de foto.",
     "inputSchema": _schema({"post_id": INTEGER, "title": STRING, "notes": STRING, "platform": PLATFORM}),
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
     "run": post_caption_suggest},
    {"name": "sales_batch_get",
     "description": "The sales lines added by one Cults CSV import (a batch). Read-only.\n"
                    "Las ventas que añadió una importación de CSV de Cults (un lote). Sinónimos: lote de ventas, ingresos importados.",
     "inputSchema": _schema({"batch": STRING}, ["batch"]), "annotations": _ann(True), "run": sales_batch_get},
    {"name": "catalog_from_vulcan",
     "description": "Pull Vulcan's listings into the Cults catalogue (write; needs Vulcan running).\n"
                    "Trae las fichas de Vulcan al catálogo de Cults. Sinónimos: sincronizar catálogo, importar fichas de modelos.",
     "inputSchema": _schema({"folder": STRING}), "annotations": _ann(False, True), "run": catalog_from_vulcan},
]
TOOLS.extend([
    {"name":"plausible_query", "description":"Query Plausible v2 and store source-backed website statistics. Requires configured API key.\nConsultar analítica web, páginas, fuentes, conversiones y visitantes reales con procedencia.",
     "inputSchema":_schema({"project":STRING,"site_id":STRING,"date_range":{"oneOf":[STRING,{"type":"array","items":STRING,"minItems":2,"maxItems":2}]},"metrics":{"type":"array","items":STRING},"dimensions":{"type":"array","items":STRING},"filters":{"type":"array","maxItems":50},"order_by":{"type":"array","maxItems":8},"page_size":{"type":"integer","minimum":1,"maximum":1000},"offset":{"type":"integer","minimum":0,"maximum":1000000}},["site_id"]),
     "annotations":{"readOnlyHint":False,"destructiveHint":False,"idempotentHint":True,"openWorldHint":True},"run":plausible_query},
    {"name":"plausible_history", "description":"Read saved website-statistics snapshots without network access. Read-only.\nLeer históricos de analítica web con consulta, fecha, origen y valores exactos.",
     "inputSchema":_schema({"project":STRING,"limit":INTEGER}),"annotations":_ann(True),"run":plausible_history},
])
TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def tool_catalog() -> list[dict]:
    return [{k: v for k, v in tool.items() if k != "run"} for tool in TOOLS]


def call_tool(name: str, arguments: dict | None, *, cap: bool = True) -> Any:
    """Run a tool. The answer an assistant reads is capped at 20 000 bytes of JSON (the largest list is halved and ``truncated`` says
    what was left out); the web page calls with ``cap=False`` and gets everything."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise KeyError(f"Unknown tool: {name}")
    args = arguments if arguments is not None else {}
    if not isinstance(args, dict):
        raise ValueError("Argumentos no válidos")
    allowed = set(tool["inputSchema"]["properties"])
    unknown = set(args) - allowed
    if unknown:
        raise ValueError("Argumentos desconocidos: " + ", ".join(sorted(unknown)))
    for field in tool["inputSchema"].get("required", []):
        if args.get(field) in (None, ""):
            raise ValueError(f"Falta el argumento {field}")
    _configure()
    result = tool["run"](args)
    return cap_result(result) if cap else result
