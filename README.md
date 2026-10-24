# Mercator's Hoard

In **Customers**, open a saved company and choose **Ver sus oportunidades** to
scope the opportunity list, full native summary and JSON/CSV exports to its actual
ID. The visible company name is the saved name at selection time, with its ID;
unsaved name/notes stay in the editor. **Todas las empresas** removes only this
scope and retains project/owner/stage/text filters. Matching is by identity, so
same-named companies remain separate; no matches stay empty. Applying or retrying
reads does not save or rebuild an open editor. Changed filters clear old results;
press **Filtrar** to apply or retry. The existing native `company_id` filter is
shared by API/MCP25; summary/export cover all matches, while the table pages50.
Amounts remain owner estimates, separated by currency; won is not collected cash.
The scope is local to this page, with no new persistence or external CRM service.

**Publication → From media** (**Desde un medio**) creates or locates a publication using the existing `post_draft_from_media` capability. Media reference and title are required by its API/MCP contract; platform is optional and uses the native default when creating. Title/platform apply only to a new draft. An existing non-archived exact-reference match is returned unchanged, even if published or on another platform; the lowest matching ID wins. An archived-only match allows a new draft. The result shows its actual ID/title/platform/status and offers **Open publication** explicitly. Opening/closing the form writes nothing; submitting can create a saved draft, and closing/changing fields cannot cancel an already sent request. No media resolution/upload or social publication occurs. Errors keep the fields; changing fields or refreshing clears old results without replacing an open editor's draft.

In a CRM opportunity, the interaction form accepts an optional ISO date/time with an explicit zone (`Z` or an offset such as `+02:00`). Leave it empty to use server time when saving. The existing `crm_activity_add` API/MCP records this as `observed_at` and records entry time separately as `recorded_at`; the history labels both and keeps its native newest-recorded-first order and 200-entry view. This logs an interaction that occurred; it sends no message or reminder. Failed saves retain note/source/date and reuse the native request ID for an unchanged retry. Saving an interaction preserves unsaved opportunity fields and later interaction edits.

[Español](README.es.md)

A local dashboard for WatchHoard and BookHoard usage, Cults product listings and sales imported from Cults. It stores history only on this computer in `data/mercator.sqlite3`.

## Open

Run `python mercator.py` and open [http://127.0.0.1:5195](http://127.0.0.1:5195). Hoard Hub can also start it from `faustus-plugin.json` and open a dedicated window.

On launch and every six hours while running, Mercator reads Supabase Auth user counts and Cloudflare Worker requests and errors. **Refresh data** triggers an early read. The dashboard shows the last stored reading; a source without access is marked pending instead of presenting an older value as current.

## Credentials

Mercator reads `WatchHoard/watchhoard/.env` for WatchHoard. BookHoard's public key cannot count Auth users. To enable that count and Worker metrics, copy `.env.example` to `.env` and fill in the local values. Do not enter credentials into the UI or commit them. Cloudflare requires an Analytics read token for the relevant account; separate account and token settings are supported for WatchHoard and BookHoard.

## Cults sales and catalogue

Export a sales CSV from Cults, select it in **Sales**, and map the date, product and revenue columns. Currency and sale ID are optional. Comma, semicolon and tab separators are supported. Reimporting the same file does not count sales twice, including repeated identical rows without IDs. Amounts and dates are read with the family's rules (`hoard_link.money` / `hoard_link.dates`): `1.234,56`, `1,234.56`, `(12.00)`, `12 â‚¬` and `28/09/2026`, `2026-09-28`, `5 sept 2026`, `Sep 14, 2026`; the decimal mark is taken from the whole column, a lone `1.234` is 1234 (unless the row's currency writes dots as decimals, like USD) and a date without a year is refused, never guessed.

Revenue is shown by currency. Different currencies are never summed, and revenue is not presented as net profit. Mercator does not fetch Cults sales directly because no verified API and sales schema are configured. It also reads, without modifying, product folders under `Desktop/Modelos/Contornos pokemon` and detects `cults3d.json` files. Set `MERCATOR_PRODUCTS_DIR` in `.env` to choose another folder.

**View imported batch** (**Ver lote importado**) shows only the new sales saved by that import; **View latest batch** (**Ver último lote**) keeps the latest recorded batch available after reload. The panel shows its identity, registered source, import time, processed CSV rows, added sales and exact native amounts by currency. Its table displays 50 lines per page; line numbers belong to the batch, and local IDs are not Cults order numbers. Reimporting an already registered file creates a genuine empty batch. Older imports without a batch identifier say so. Reads use the existing `sales_batch_get {batch}` calculation through `GET /api/sales/batch?batch=...`; viewing or retrying does not import again. This is not a general import-history browser or proof of payment.

## Publishing

The **Publication** page (`/publicacion`) plans and measures what you post.

- **Posts** have a platform (Instagram Reel/post, TikTok, YouTube Short/video, X, Cults3D, other), title, caption, hashtags, media reference, status (idea, draft, scheduled, published, archived), scheduled/published dates, URL and notes. The media reference is a `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` reference or a file path; a servable image or video path gets a preview.
- **Calendar** (week or month) and **board** by status. The editor shows a per-platform character counter (reference limits, not guarantees) and a copy-caption button.
- **Calendar download**: **Descargar programadas (.ics)** exports scheduled posts in the visible calendar cells and current platform/search filters. Import the copy into your agenda; it does not synchronise or publish. Date-only entries are all-day, explicit offsets preserve their instant in UTC, and times without a zone stay floating local times. The read-only `posts_calendar_export` MCP tool returns a local URL for the complete file. See [the format and API](docs/calendar-export.md).
- **Metrics**: add snapshots by hand (views, likes, comments, shares, saves, sales, revenue) or import a CSV. Charts per post, totals per platform and **best hours** (average views by weekday and hour of published posts; it says so when there are too few posts).
- **Growth through Faustus**: `post_metrics_compare {post_id, from_ts, to_ts}` compares the latest whole snapshot at or before each endpoint. It returns both actual readings, changes and percentage changes for each metric, plus exact revenue differences when the currencies match. Missing values remain `null`, a zero baseline has no percentage, and decreases are retained. These are changes between saved observations, not sums of daily activity, live platform analytics or profit. Use ISO timestamps with UTC offsets; naive timestamps use this computer's timezone. Sparse readings are not filled from older rows.
- **Compare growth in the editor**: open a saved post and click **Metrics** (**Métricas**) in the editor header to reach **Compare growth** (**Comparar crecimiento**). Choose the start and end dates in your browser's local timezone, or use **First to last** (**Primera a última**). The table shows the actual saved readings used, all six metrics and revenue, signed changes and percentages. Missing readings, zero baselines and different currencies are explained in place. It uses the same calculation as Faustus through `POST /api/posts/metrics/compare`; comparing never changes the stored readings.
- **CSV import** per platform with a column mapping you can change. Presets recognise YouTube Studio, Instagram and TikTok exports by their column names. The presets are heuristic: they have not been checked against real exports, so review the mapping in the preview. Re-importing the same file adds no snapshots.
- **Captions**: suggestions appear only when Hoard Link can reach a language model that is already loaded; nothing depends on it.

Data stays in `data/mercator.sqlite3` (tables `posts`, `post_metrics`, `catalog_items`), opened with the family's `hoard_link.sqlkit.Database`: one shared connection, WAL, a 15 s busy timeout, versioned migrations (`schema_version`) and a checkpoint when the server stops.

## Family

**Use as a base** (**Usar como base**) in a saved publication opens an editable new draft using only its visible platform, title, caption, hashtags, media reference and notes. The origin is shown; adapt the text or platform before saving. Opening/cancelling writes nothing; saving uses native post creation with a new identity, leaving the source unchanged. Dates, published URL, external IDs and metrics are not carried over, and no social-network publishing occurs. Copilot sees an unsaved object and retains the draft content across refresh.

Mercator follows the Hoard family contract (`faustus-plugin.json`, `x-family`):

- Tools through `GET /api/agent/tools` and `POST /api/agent/call` (bearer token in `data/mcp-token`, created on first start) and the stdio bridge: `posts_list`, `post_get`, `post_upsert`, `post_schedule`, `post_publish`, `post_metrics_add`, `post_metrics_compare`, `posts_stats`, `post_draft_from_media {media_ref, title}`, `post_caption_suggest`, `sales_batch_get {batch}`, `catalog_from_vulcan {}` (asks Vulcan for `listings_export_catalog` and upserts the result into the Cults catalogue; needs Vulcan running) plus the two below.
- Events: `mercator.post.scheduled`, `mercator.post.published`, `mercator.post.drafted`, `mercator.sales.imported {batch}` (after a sales import that added lines, so a hub rule can record the income).
- Agenda: `GET /api/family/agenda` answers with the scheduled posts (kind `publish`); it needs the same bearer token.
- `hoard_link/` is the shared library, vendored unchanged (version 0.8). It imports with the standard library only, so the dashboard still runs without installing anything. The token (`data/mcp-token`) is created once and kept across restarts. Assistant answers from the tools are capped at 20 000 bytes (`truncated` says what was left out); the web page gets everything. Errors come as `{ok: false, error, code}` with `unknown_tool` 404, `invalid` 400 or `internal` 500.

## Ask Faustus

The Faustus icon opens the shared copilot on the dashboard and publication page, including inside publication and CSV import dialogs. Chats, drafts, model calls and tools remain in Faustus. Mercator stores only its stable `data/copilot-space-id`; `MERCATOR_DATA_DIR` selects another data space. Configure the global Faustus service through HoardLink or `MERCATOR_FAUSTUS_URL`. Model reasoning uses the global Sparks service; local GPUs remain available for content generation.

The panel receives the current view, real CRM/publication identifiers and unsaved editor fields. New or removed records have no active object. A completed turn refreshes lists, saved analytics and publication metrics while keeping the editor and its draft. Existing CRM and publication forms save only changed fields, so an agent's concurrent changes to other fields survive. Native `crm_patch {kind, id, fields}` performs that merge in the database transaction; existing revision-aware save tools remain available.

See [the copilot API](docs/copilot.md) for the shared relay endpoints and context contract.

`python mcp_server.py` is the stdio MCP bridge (the family's shared `CatalogBridge`; it needs `pip install -r requirements.txt`, i.e. the `mcp` package). It lists the tools from the running dashboard and forwards every call to it with the token in `data/mcp-token`; when nothing answers it starts `python -m mercator` itself (`MERCATOR_BRIDGE_AUTOSTART=0` disables that; `MERCATOR_URL`, `MERCATOR_PORT`, `MERCATOR_DATA_DIR`, `MERCATOR_TOKEN_FILE` say where the server is). The original two are read-only: `mercator_catalog` searches product listings and filters listings without tags or missing/invalid files; `mercator_sales` looks up imported sales by product with totals per currency. Hoard Hub can use the MCP entry in `faustus-plugin.json`. Set `MERCATOR_DATA_DIR` and `MERCATOR_PRODUCTS_DIR` in the process environment to point an isolated test or custom local store elsewhere.

## Snapshot comparison references

The comparison capability reuses the local metrics history without a new dependency. [YouTube's official metric definitions](https://developers.google.com/youtube/analytics/metrics) and [report date ranges](https://developers.google.com/youtube/analytics/reference/reports/query) informed the distinction between observations and period activity; Mercator does not call those APIs for this tool.

## Verify

```sh
python -m unittest discover -s tests   # or: python -m pytest tests (the bridge tests need the mcp package and are skipped without it)
```

The server binds only to `127.0.0.1` and runs the family's request guard (`hoard_link.guard`): the `Host` must be loopback and name the server's port (other names go in `MERCATOR_ALLOWED_HOSTS`), a browser `Origin` must be local with the same port, cross-site fetches and form posts are refused.

## Family expansion · 2026-10-04

`plausible_query` reads [Plausible Stats API v2](https://plausible.io/docs/stats-api) and saves the exact query, response, origin and observation time; `plausible_history` lists saved snapshots. The Analytics tab uses the same handlers, keeps dimensions/currencies/null values and exports JSON. Configure `PLAUSIBLE_API_KEY` and optionally `PLAUSIBLE_URL` (HTTPS remote or HTTP loopback origin). Account/edition must provide API access. Queries support periods or date pairs, metrics, dimensions and up to 1000 rows; nested filters, ordering and explicit pagination are supported; each snapshot preserves its offset. No tracking script or fabricated website metrics is installed.
