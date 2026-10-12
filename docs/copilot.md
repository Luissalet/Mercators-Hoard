# Faustus copilot

Mercator mounts the shared HoardLink `CopilotRelay` on its standard-library HTTP server. It has no separate model loop or conversation store. Credentials remain in the service; the browser uses Mercator's same-origin relay.

| Route | Method | Result |
| --- | --- | --- |
| `/api/copilot/info` | GET, HEAD | Stable Mercator data-space identity, panel and settings endpoints |
| `/api/copilot/launcher.js` | GET, HEAD | Shared Faustus launcher |
| `/api/copilot/panel.js` | GET, HEAD | Faustus's normal chat component |
| `/api/copilot/proxy` | POST | Shared JSON/multipart and streaming transport to Faustus |
| `/api/crm/patch` | POST | `{kind: "company"|"deal", id, fields}` atomically merges only supplied editable fields |

The shared relay preserves upstream responses, streaming and uploaded bytes. HTML pages receive the launcher once; APIs and other static files retain their content. The same chat component moves into an open native dialog, preserving its session and draft, and returns to the page when the dialog closes.

`window.hoardCopilot.context(base)` returns current view/editor/filter state and `active_objects`. CRM identifiers are verified through `crm_get`'s native HTTP route; publications through `/api/posts/{id}`. New or missing records return an empty object list. Editor fields contain only user changes, with metrics, activity and CSV mapping drafts included where relevant. No project identity is inferred from an arbitrary CRM project label or an analytics query label.

`onTurnEnd` refreshes current lists and saved metrics without reopening editors, resetting forms or contacting analytics providers. Existing CRM revision-aware writes remain available; `crm_patch` and partial publication saves preserve other current fields within the store transaction. Changes to the same field follow normal save order.

The launcher follows the page locale. `MERCATOR_FAUSTUS_URL` overrides the globally configured Faustus URL, while the Faustus model service continues to own reasoning and tool execution. `data/copilot-space-id` belongs to the selected `MERCATOR_DATA_DIR` and survives app restarts.
