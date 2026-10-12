# API

The server is the standard library's `http.server` (`mercator.py`, class `Handler`); every request passes the family guard (loopback `Host`, same-port `Origin`, no cross-site fetches). Errors answer `{"error": "..."}`.

| Route | Purpose |
| --- | --- |
| `GET /api/health` | `{service: "mercator-hoard", status, hoard_link}` |
| `GET /api/summary`, `POST /api/refresh` | the dashboard figures and a fresh read of the sources |
| `POST /api/sales/import` | Cults sales CSV (`{csv, columns}`) |
| `GET /api/publishing/meta`, `GET/POST /api/posts`, `GET /api/posts/{id}`, `GET /api/posts/{id}/media`, `GET /api/posts/stats` | publishing; `POST /api/posts` creates or updates, and only the fields sent change |
| `POST /api/posts/{delete,schedule,publish,metrics,caption}`, `POST /api/posts/import[/preview]` | post actions and CSV metrics import |
| `GET /api/crm`, `/api/crm/get`, `/api/crm/summary`, `/api/crm/export`; `POST /api/crm/{company,deal,activity}` | the CRM; saving an existing record needs `expected_revision` and merges only the fields sent |
| `POST /api/analytics/query`, `GET /api/analytics/history` | Plausible queries with their provenance |
| `GET /api/agent/tools`, `POST /api/agent/call` | the shared agent contract (bearer token in `data/mcp-token`) |
| `GET /api/family/agenda` | scheduled posts and CRM follow-ups for the family agenda |

## Faustus copilot routes

Served by `mercator_copilot.Copilot` (`mercator.COPILOT`, set in `main()` unless `HOARD_COPILOT=0`) when the vendored `hoard_link` has the copilot modules. A thin local relay: the panel, conversation, model and tools live in Faustus.

| Route | Purpose |
| --- | --- |
| `GET /api/copilot/info` | `{app_id, app_name, data_space_id, panel_url, server, tool_server_id, settings_url}`; `503` when Faustus is not reachable. `data_space_id` is stored in `data/copilot-space-id`. |
| `GET /api/copilot/panel.js` | The Faustus chat component, relayed from Faustus. |
| `POST /api/copilot/proxy` | Forwards `/api/hoard-copilot/*`, `/api/chat/*` and `/api/session(s)` calls (SSE unbuffered, up to 64 MB of upload) to Faustus and forces `origin.app_id` / `data_space_id` into the context. Any other path is `400`. |
| `GET /api/copilot/launcher.js` | The floating button and panel host. The server adds its tag to the two HTML pages (`/`, `/publicacion`). |

The pages answer the launcher with `window.hoardCopilot.context()` (`static/copilot.js`; each script registers what it shows): `active_objects` (`tracked_project`, `sales_summary`, `catalog_item`, `analytics_snapshot`, `crm_deal`, `crm_company`, `post`) and `view` (`page` = `dashboard` or `publicacion`, `section`, per-page details, `editor` / `other_editors` for unsaved input). There is no `project`. `onTurnEnd` reloads the lists and merges the agent's changes into an open deal or post.
