# Mercator's Hoard

[Español](README.es.md)

A local dashboard for WatchHoard and BookHoard usage, Cults product listings and sales imported from Cults. It stores history only on this computer in `data/mercator.sqlite3`.

## Open

Run `python mercator.py` and open [http://127.0.0.1:5195](http://127.0.0.1:5195). Hoard Hub can also start it from `faustus-plugin.json` and open a dedicated window.

On launch and every six hours while running, Mercator reads Supabase Auth user counts and Cloudflare Worker requests and errors. **Refresh data** triggers an early read. The dashboard shows the last stored reading; a source without access is marked pending instead of presenting an older value as current.

## Credentials

Mercator reads `WatchHoard/watchhoard/.env` for WatchHoard. BookHoard's public key cannot count Auth users. To enable that count and Worker metrics, copy `.env.example` to `.env` and fill in the local values. Do not enter credentials into the UI or commit them. Cloudflare requires an Analytics read token for the relevant account; separate account and token settings are supported for WatchHoard and BookHoard.

## Cults sales and catalogue

Export a sales CSV from Cults, select it in **Sales**, and map the date, product and revenue columns. Currency and sale ID are optional. Comma, semicolon and tab separators are supported. Reimporting the same file does not count sales twice, including repeated identical rows without IDs. Amounts and dates are read with the family's rules (`hoard_link.money` / `hoard_link.dates`): `1.234,56`, `1,234.56`, `(12.00)`, `12 €` and `28/09/2026`, `2026-09-28`, `5 sept 2026`, `Sep 14, 2026`; the decimal mark is taken from the whole column, a lone `1.234` is 1234 (unless the row's currency writes dots as decimals, like USD) and a date without a year is refused, never guessed.

Revenue is shown by currency. Different currencies are never summed, and revenue is not presented as net profit. Mercator does not fetch Cults sales directly because no verified API and sales schema are configured. It also reads, without modifying, product folders under `Desktop/Modelos/Contornos pokemon` and detects `cults3d.json` files. Set `MERCATOR_PRODUCTS_DIR` in `.env` to choose another folder.

## Publishing

The **Publication** page (`/publicacion`) plans and measures what you post.

- **Posts** have a platform (Instagram Reel/post, TikTok, YouTube Short/video, X, Cults3D, other), title, caption, hashtags, media reference, status (idea, draft, scheduled, published, archived), scheduled/published dates, URL and notes. The media reference is a `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` reference or a file path; a servable image or video path gets a preview.
- **Calendar** (week or month) and **board** by status. The editor shows a per-platform character counter (reference limits, not guarantees) and a copy-caption button.
- **Metrics**: add snapshots by hand (views, likes, comments, shares, saves, sales, revenue) or import a CSV. Charts per post, totals per platform and **best hours** (average views by weekday and hour of published posts; it says so when there are too few posts).
- **CSV import** per platform with a column mapping you can change. Presets recognise YouTube Studio, Instagram and TikTok exports by their column names. The presets are heuristic: they have not been checked against real exports, so review the mapping in the preview. Re-importing the same file adds no snapshots.
- **Captions**: suggestions appear only when Hoard Link can reach a language model that is already loaded; nothing depends on it.

Data stays in `data/mercator.sqlite3` (tables `posts`, `post_metrics`, `catalog_items`), opened with the family's `hoard_link.sqlkit.Database`: one shared connection, WAL, a 15 s busy timeout, versioned migrations (`schema_version`) and a checkpoint when the server stops.

## Family

Mercator follows the Hoard family contract (`faustus-plugin.json`, `x-family`):

- Tools through `GET /api/agent/tools` and `POST /api/agent/call` (bearer token in `data/mcp-token`, created on first start) and the stdio bridge: `posts_list`, `post_get`, `post_upsert`, `post_schedule`, `post_publish`, `post_metrics_add`, `posts_stats`, `post_draft_from_media {media_ref, title}`, `post_caption_suggest`, `sales_batch_get {batch}`, `catalog_from_vulcan {}` (asks Vulcan for `listings_export_catalog` and upserts the result into the Cults catalogue; needs Vulcan running) plus the two below.
- Events: `mercator.post.scheduled`, `mercator.post.published`, `mercator.post.drafted`, `mercator.sales.imported {batch}` (after a sales import that added lines, so a hub rule can record the income).
- Agenda: `GET /api/family/agenda` answers with the scheduled posts (kind `publish`); it needs the same bearer token.
- `hoard_link/` is the shared library, vendored unchanged (version 0.8). It imports with the standard library only, so the dashboard still runs without installing anything. The token (`data/mcp-token`) is created once and kept across restarts. Assistant answers from the tools are capped at 20 000 bytes (`truncated` says what was left out); the web page gets everything. Errors come as `{ok: false, error, code}` with `unknown_tool` 404, `invalid` 400 or `internal` 500.

## Ask Faustus

`python mcp_server.py` is the stdio MCP bridge (the family's shared `CatalogBridge`; it needs `pip install -r requirements.txt`, i.e. the `mcp` package). It lists the tools from the running dashboard and forwards every call to it with the token in `data/mcp-token`; when nothing answers it starts `python -m mercator` itself (`MERCATOR_BRIDGE_AUTOSTART=0` disables that; `MERCATOR_URL`, `MERCATOR_PORT`, `MERCATOR_DATA_DIR`, `MERCATOR_TOKEN_FILE` say where the server is). The original two are read-only: `mercator_catalog` searches product listings and filters listings without tags or missing/invalid files; `mercator_sales` looks up imported sales by product with totals per currency. Hoard Hub can use the MCP entry in `faustus-plugin.json`. Set `MERCATOR_DATA_DIR` and `MERCATOR_PRODUCTS_DIR` in the process environment to point an isolated test or custom local store elsewhere.

## Verify

```sh
python -m unittest discover -s tests   # or: python -m pytest tests (the bridge tests need the mcp package and are skipped without it)
```

The server binds only to `127.0.0.1` and runs the family's request guard (`hoard_link.guard`): the `Host` must be loopback and name the server's port (other names go in `MERCATOR_ALLOWED_HOSTS`), a browser `Origin` must be local with the same port, cross-site fetches and form posts are refused.
