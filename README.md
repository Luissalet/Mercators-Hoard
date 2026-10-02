# Mercator's Hoard

[Español](README.es.md)

A local dashboard for WatchHoard and BookHoard usage, Cults product listings and sales imported from Cults. It stores history only on this computer in `data/mercator.sqlite3`.

## Open

Run `python mercator.py` and open [http://127.0.0.1:5195](http://127.0.0.1:5195). Hoard Hub can also start it from `faustus-plugin.json` and open a dedicated window.

On launch and every six hours while running, Mercator reads Supabase Auth user counts and Cloudflare Worker requests and errors. **Refresh data** triggers an early read. The dashboard shows the last stored reading; a source without access is marked pending instead of presenting an older value as current.

## Credentials

Mercator reads `WatchHoard/watchhoard/.env` for WatchHoard. BookHoard's public key cannot count Auth users. To enable that count and Worker metrics, copy `.env.example` to `.env` and fill in the local values. Do not enter credentials into the UI or commit them. Cloudflare requires an Analytics read token for the relevant account; separate account and token settings are supported for WatchHoard and BookHoard.

## Cults sales and catalogue

Export a sales CSV from Cults, select it in **Sales**, and map the date, product and revenue columns. Currency and sale ID are optional. Comma, semicolon and tab separators are supported. Reimporting the same file does not count sales twice, including repeated identical rows without IDs.

Revenue is shown by currency. Different currencies are never summed, and revenue is not presented as net profit. Mercator does not fetch Cults sales directly because no verified API and sales schema are configured. It also reads, without modifying, product folders under `Desktop/Modelos/Contornos pokemon` and detects `cults3d.json` files. Set `MERCATOR_PRODUCTS_DIR` in `.env` to choose another folder.

## Publishing

The **Publication** page (`/publicacion`) plans and measures what you post.

- **Posts** have a platform (Instagram Reel/post, TikTok, YouTube Short/video, X, Cults3D, other), title, caption, hashtags, media reference, status (idea, draft, scheduled, published, archived), scheduled/published dates, URL and notes. The media reference is a `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` reference or a file path; a servable image or video path gets a preview.
- **Calendar** (week or month) and **board** by status. The editor shows a per-platform character counter (reference limits, not guarantees) and a copy-caption button.
- **Metrics**: add snapshots by hand (views, likes, comments, shares, saves, sales, revenue) or import a CSV. Charts per post, totals per platform and **best hours** (average views by weekday and hour of published posts; it says so when there are too few posts).
- **CSV import** per platform with a column mapping you can change. Presets recognise YouTube Studio, Instagram and TikTok exports by their column names. The presets are heuristic: they have not been checked against real exports, so review the mapping in the preview. Re-importing the same file adds no snapshots.
- **Captions**: suggestions appear only when Hoard Link can reach a language model that is already loaded; nothing depends on it.

Data stays in `data/mercator.sqlite3` (tables `posts`, `post_metrics`, `catalog_items`).

## Family

Mercator follows the Hoard family contract (`faustus-plugin.json`, `x-family`):

- Tools through `GET /api/agent/tools` and `POST /api/agent/call` (bearer token in `data/mcp-token`, created on first start) and the stdio bridge: `posts_list`, `post_get`, `post_upsert`, `post_schedule`, `post_publish`, `post_metrics_add`, `posts_stats`, `post_draft_from_media {media_ref, title}`, `post_caption_suggest`, `sales_batch_get {batch}`, `catalog_from_vulcan {}` (asks Vulcan for `listings_export_catalog` and upserts the result into the Cults catalogue; needs Vulcan running) plus the two below.
- Events: `mercator.post.scheduled`, `mercator.post.published`, `mercator.post.drafted`, `mercator.sales.imported {batch}` (after a sales import that added lines, so a hub rule can record the income).
- Agenda: `GET /api/family/agenda` answers with the scheduled posts (kind `publish`); it needs the same bearer token.
- `hoard_link/` is the shared library, vendored unchanged. Only its standard-library modules are loaded (through a private package name), so Mercator still runs without installing anything.

## Ask Faustus

`python mcp_server.py` exposes the tools above locally without starting the dashboard. The original two are read-only: `mercator_catalog` searches product listings and filters listings without tags or missing/invalid files; `mercator_sales` looks up imported sales by product with totals per currency. Hoard Hub can use the MCP entry in `faustus-plugin.json`. Set `MERCATOR_DATA_DIR` and `MERCATOR_PRODUCTS_DIR` in the process environment to point an isolated test or custom local store elsewhere.

## Verify

```sh
python -m unittest discover -s tests
```

The server binds only to `127.0.0.1`.
