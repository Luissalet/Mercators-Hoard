# Mercator's Hoard

A local dashboard that follows WatchHoard and BookHoard usage, Cults product listings and sales, publications and their metrics, web analytics, and a small CRM of companies and opportunities.

[Leer en español](README.es.md)

## What it is

Mercator keeps the numbers of the projects in one place, on this computer only. History is stored in `data/mercator.sqlite3`; nothing is sent anywhere. The interface labels are in Spanish. Figures are always shown with their origin and date, and a source that cannot be read is marked pending instead of presenting an older value as current.

## What it does

**Active projects**
- On launch and every six hours, reads Supabase Auth user counts and Cloudflare Worker requests and errors for WatchHoard and BookHoard. **Refresh data** triggers an early read.

**Cults sales**
- Import a sales CSV exported from Cults: map the date, product and revenue columns (currency and sale ID are optional); comma, semicolon and tab separators work. Re-importing the same file never counts sales twice.
- Amounts and dates follow the family's rules (`1.234,56`, `1,234.56`, `(12.00)`, `28/09/2026`, `2026-09-28`, `Sep 14, 2026`...). The decimal mark is taken from the whole column; a date without a year is refused, never guessed.
- Revenue is shown per currency. Currencies are never summed and revenue is not presented as profit.
- **Ver lote importado** / **Ver último lote** show the sales added by one import: source, time, processed rows, added sales and amounts per currency, 50 lines per page. Viewing never imports again.

**Product catalogue**
- Reads, without modifying, the product folders under `Desktop/Modelos/Contornos pokemon` (or the folder set in `MERCATOR_PRODUCTS_DIR`) and detects their `cults3d.json` files.
- Search by title or local ID and filter by all, listings without tags, or missing listing / damaged format, in native pages of 50. These are local file indicators, not proof of publication.
- `catalog_from_vulcan` asks Vulcan for its listings catalogue and upserts it (needs Vulcan running).

**Publication** (`/publicacion`)
- Posts with platform (Instagram Reel/post, TikTok, YouTube Short/video, X, Cults3D, other), title, caption, hashtags, media reference, status (idea, draft, scheduled, published, archived), dates, URL and notes. The media reference can be `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` or a file path; images and videos get a preview.
- Week or month calendar and a board by status; per-platform character counter and a copy-caption button.
- **Desde un medio** creates or finds a draft for a media reference (an existing non-archived match is returned unchanged). **Usar como base** opens a new editable draft from a saved publication without carrying over dates, URL or metrics.
- **Descargar programadas (.ics)** exports the scheduled posts of the visible calendar and filters for your agenda; it does not synchronise or publish. See [docs/calendar-export.md](docs/calendar-export.md).
- Metrics: add snapshots by hand (views, likes, comments, shares, saves, sales, revenue) or import a CSV per platform with an editable column mapping (presets for YouTube Studio, Instagram and TikTok exports are heuristic: review the mapping). Charts per post, totals per platform and best hours to post.
- **Comparar crecimiento**: compares the latest whole snapshot at or before two dates (or first to last), with actual readings, signed changes and percentages. Missing values stay empty, zero baselines have no percentage, different currencies are explained. These are changes between saved observations, not live platform analytics or profit.
- Caption suggestions appear only when a language model is already reachable; nothing depends on it.

**Web analytics**
- Queries the Plausible Stats API v2 and saves the exact query, response, origin and time. Supports relative periods or an explicit date range (**Personalizado**), metrics, dimensions, nested filters, ordering and pagination up to 1000 rows. Saved snapshots can be queried again with their full stored query, and exported as JSON. No tracking script is installed. Needs `PLAUSIBLE_API_KEY` (and optionally `PLAUSIBLE_URL`, an HTTPS remote or HTTP loopback origin).

**Customers (CRM)**
- Companies and opportunities (stages: lead, qualified, proposal, negotiation, won, lost, archived) for AI, development and 3D commissions, with project, owner and references; filter by project, owner, stage and text. **Ver sus oportunidades** scopes the list, summary and exports to one company.
- Interaction history per opportunity: an optional ISO date/time with explicit zone is stored as `observed_at`, separately from the entry time. It logs an interaction that happened; it sends nothing.
- Summary by stage and currency (owner estimates; won is not collected cash) and JSON/CSV export.
- Forms save only the changed fields, so concurrent changes by an agent to other fields survive.

## How to run it

Run `python mercator.py` and open [http://127.0.0.1:5195](http://127.0.0.1:5195), or let Hoard Hub start it and open its own window. The server binds only to `127.0.0.1` and applies the family's request guard (loopback `Host` and `Origin` with the server's port; extra host names go in `MERCATOR_ALLOWED_HOSTS`).

Credentials: Mercator reads `WatchHoard/watchhoard/.env` for WatchHoard. To count BookHoard's Auth users and read Worker metrics, copy `.env.example` to `.env` and fill in the local values (Cloudflare needs an Analytics read token; WatchHoard and BookHoard have separate account and token settings). Never type credentials into the UI or commit them.

Environment: `MERCATOR_DATA_DIR`, `MERCATOR_PRODUCTS_DIR`, `MERCATOR_PORT`, `MERCATOR_FAUSTUS_URL`.

## Connection with Faustus and the Hub

The plugin manifest is `faustus-plugin.json` (family contract, `x-family`). Tools are served at `GET /api/agent/tools` and `POST /api/agent/call` (bearer token in `data/mcp-token`, created on first start) and through the stdio bridge `python mcp_server.py`, which needs `pip install -r requirements.txt`. The bridge forwards every call to the running dashboard and starts `python -m mercator` itself when nothing answers (`MERCATOR_BRIDGE_AUTOSTART=0` disables that; `MERCATOR_URL`, `MERCATOR_PORT`, `MERCATOR_DATA_DIR`, `MERCATOR_TOKEN_FILE` say where the server is).

Tools by group:
- Catalogue and sales: `mercator_catalog`, `mercator_sales`, `sales_batch_get`, `catalog_from_vulcan`.
- Publication: `posts_list`, `post_get`, `post_upsert`, `post_schedule`, `post_publish`, `post_draft_from_media`, `post_caption_suggest`, `post_metrics_add`, `post_metrics_compare`, `posts_stats`, `posts_calendar_export`.
- Analytics: `plausible_query`, `plausible_history`.
- CRM: `crm_list`, `crm_get`, `crm_company_save`, `crm_deal_save`, `crm_patch`, `crm_activity_add`, `crm_summary`, `crm_export`.

Assistant answers are capped at 20 000 bytes (`truncated` says what was left out); the web page gets everything. Errors come as `{ok: false, error, code}`.

Events: `mercator.post.scheduled`, `mercator.post.published`, `mercator.post.drafted`, `mercator.sales.imported {batch}` (so a hub rule can record the income). `GET /api/family/agenda` returns the scheduled posts (kind `publish`) with the same token.

**Ask Faustus.** The Faustus icon opens the shared copilot on the dashboard and the publication page, including inside dialogs. Chats, drafts, model calls and tools stay in Faustus; Mercator stores only its stable `data/copilot-space-id`. The panel receives the current view, real record identifiers and unsaved editor fields; a completed turn refreshes lists and metrics while keeping open drafts. See [docs/copilot.md](docs/copilot.md).

**Skills.** The app carries `catalogue-and-sales-metrics` and `measured-improvement` from the family's skill library for connecting agents, read with `skills_list` and `skill_read`, assigned on the skills page (`/api/agent/skills/page`) or in the hub's Skills tab.

## Project layout

| Path | Contents |
|---|---|
| `mercator.py`, `mercator_family.py` | server and family integration |
| `agent_tools.py`, `mcp_server.py` | tools and stdio bridge |
| `crm.py`, `publishing.py`, `post_csv.py`, `calendar_export.py`, `cults_catalog.py`, `plausible_stats.py` | CRM, publication, CSV import, calendar export, catalogue, Plausible |
| `hoard_link/` | shared family library, vendored unchanged (standard library only) |
| `static/` | web interface |
| `docs/` | calendar export and copilot references |
| `tests/` | Python and JS tests |
| `data/` | SQLite database, token, copilot space (not tracked) |

Data is opened with `hoard_link.sqlkit.Database`: one shared connection, WAL, 15 s busy timeout, versioned migrations.

## Tests

```sh
python -m unittest discover -s tests   # or: python -m pytest tests
```

The bridge tests need the `mcp` package and are skipped without it.
