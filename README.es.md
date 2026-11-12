# Mercator's Hoard

Panel local que sigue el uso de WatchHoard y BookHoard, las fichas y ventas de Cults, las publicaciones y sus métricas, la analítica web y un pequeño CRM de empresas y oportunidades.

[Read in English](README.md)

## Qué es

Mercator reúne en un solo sitio las cifras de los proyectos, solo en este ordenador. El historial se guarda en `data/mercator.sqlite3`; nada sale a ningún sitio. Las etiquetas de la interfaz están en español. Las cifras se muestran siempre con su origen y su fecha, y una fuente que no se puede leer se marca como pendiente en lugar de presentar un valor antiguo como actual.

## Qué hace

**Proyectos activos**
- Al arrancar y cada seis horas lee el número de usuarios de Supabase Auth y las peticiones y errores de los Cloudflare Workers de WatchHoard y BookHoard. **Refresh data** adelanta la lectura.

**Ventas de Cults**
- Importa un CSV de ventas exportado de Cults: se asignan las columnas de fecha, producto e ingreso (moneda e ID de venta son opcionales); valen los separadores coma, punto y coma y tabulador. Reimportar el mismo fichero nunca cuenta las ventas dos veces.
- Importes y fechas siguen las reglas de la familia (`1.234,56`, `1,234.56`, `(12.00)`, `28/09/2026`, `2026-09-28`, `Sep 14, 2026`...). El separador decimal se toma de toda la columna; una fecha sin año se rechaza, nunca se adivina.
- Los ingresos se muestran por moneda. Las monedas nunca se suman y el ingreso no se presenta como beneficio.
- **Ver lote importado** / **Ver último lote** muestran las ventas añadidas por una importación: origen, hora, filas procesadas, ventas añadidas e importes por moneda, 50 líneas por página. Consultar nunca vuelve a importar.

**Catálogo de productos**
- Lee, sin modificar, las carpetas de producto de `Desktop/Modelos/Contornos pokemon` (o la carpeta indicada en `MERCATOR_PRODUCTS_DIR`) y detecta sus ficheros `cults3d.json`.
- Busca por título o ID local y filtra por todos, fichas sin etiquetas, o sin ficha / formato dañado, en páginas nativas de 50. Son indicadores locales de ficheros, no prueba de publicación.
- `catalog_from_vulcan` pide a Vulcan su catálogo de fichas y lo incorpora (requiere Vulcan en marcha).

**Publicación** (`/publicacion`)
- Publicaciones con plataforma (Instagram Reel/post, TikTok, YouTube Short/vídeo, X, Cults3D, otra), título, texto, hashtags, referencia al medio, estado (idea, borrador, programada, publicada, archivada), fechas, URL y notas. La referencia puede ser `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` o una ruta de fichero; las imágenes y vídeos tienen vista previa.
- Calendario semanal o mensual y tablero por estado; contador de caracteres por plataforma y botón para copiar el texto.
- **Desde un medio** crea o localiza el borrador de una referencia (si ya existe uno no archivado se devuelve sin cambios). **Usar como base** abre un borrador nuevo y editable a partir de una publicación guardada sin arrastrar fechas, URL ni métricas.
- **Descargar programadas (.ics)** exporta a tu agenda las publicaciones programadas del calendario visible y de los filtros; no sincroniza ni publica. Véase [docs/calendar-export.md](docs/calendar-export.md).
- Métricas: añade capturas a mano (visualizaciones, me gusta, comentarios, compartidos, guardados, ventas, ingresos) o importa un CSV por plataforma con asignación de columnas editable (los preajustes de YouTube Studio, Instagram y TikTok son heurísticos: revisa la asignación). Gráficas por publicación, totales por plataforma y mejores horas para publicar.
- **Comparar crecimiento**: compara la última captura completa en o antes de dos fechas (o de la primera a la última), con lecturas reales, cambios con signo y porcentajes. Los valores ausentes quedan vacíos, una base cero no tiene porcentaje y las monedas distintas se explican. Son cambios entre observaciones guardadas, no analítica en vivo de la plataforma ni beneficio.
- Las sugerencias de texto aparecen solo si ya hay un modelo de lenguaje accesible; nada depende de ello.

**Analítica web**
- Consulta la API Stats v2 de Plausible y guarda la consulta exacta, la respuesta, el origen y la hora. Admite periodos relativos o un intervalo explícito (**Personalizado**), métricas, dimensiones, filtros anidados, orden y paginación hasta 1000 filas. Las capturas guardadas se pueden volver a consultar con su consulta completa y exportar a JSON. No se instala ningún script de seguimiento. Requiere `PLAUSIBLE_API_KEY` (y opcionalmente `PLAUSIBLE_URL`, un origen HTTPS remoto o HTTP de bucle local).

**Clientes (CRM)**
- Empresas y oportunidades (etapas: lead, qualified, proposal, negotiation, won, lost, archived) de encargos de IA, desarrollo y 3D, con proyecto, responsable y referencias; filtro por proyecto, responsable, etapa y texto. **Ver sus oportunidades** limita lista, resumen y exportaciones a una empresa.
- Historial de interacciones por oportunidad: una fecha/hora ISO opcional con zona explícita se guarda como `observed_at`, aparte de la hora de registro. Anota una interacción que ocurrió; no envía nada.
- Resumen por etapa y moneda (estimaciones del responsable; ganado no es cobrado) y exportación JSON/CSV.
- Los formularios guardan solo los campos cambiados, así que los cambios simultáneos de un agente en otros campos se conservan.

## Cómo arrancarlo

Ejecuta `python mercator.py` y abre [http://127.0.0.1:5195](http://127.0.0.1:5195), o deja que Hoard Hub lo arranque y abra su propia ventana. El servidor escucha solo en `127.0.0.1` y aplica el guardián de peticiones de la familia (`Host` y `Origin` de bucle local con el puerto del servidor; otros nombres de host van en `MERCATOR_ALLOWED_HOSTS`).

Credenciales: Mercator lee `WatchHoard/watchhoard/.env` para WatchHoard. Para contar los usuarios Auth de BookHoard y leer las métricas de los Workers, copia `.env.example` a `.env` y rellena los valores locales (Cloudflare necesita un token de lectura de Analytics; WatchHoard y BookHoard tienen ajustes separados de cuenta y token). Nunca escribas credenciales en la interfaz ni las subas al repositorio.

Entorno: `MERCATOR_DATA_DIR`, `MERCATOR_PRODUCTS_DIR`, `MERCATOR_PORT`, `MERCATOR_FAUSTUS_URL`.

## Conexión con Faustus y el Hub

El manifiesto del plugin es `faustus-plugin.json` (contrato de la familia, `x-family`). Las herramientas se sirven en `GET /api/agent/tools` y `POST /api/agent/call` (token bearer en `data/mcp-token`, creado en el primer arranque) y por el puente stdio `python mcp_server.py`, que requiere `pip install -r requirements.txt`. El puente reenvía cada llamada al panel en marcha y arranca `python -m mercator` por su cuenta si nadie responde (`MERCATOR_BRIDGE_AUTOSTART=0` lo desactiva; `MERCATOR_URL`, `MERCATOR_PORT`, `MERCATOR_DATA_DIR`, `MERCATOR_TOKEN_FILE` indican dónde está el servidor).

Herramientas por grupos:
- Catálogo y ventas: `mercator_catalog`, `mercator_sales`, `sales_batch_get`, `catalog_from_vulcan`.
- Publicación: `posts_list`, `post_get`, `post_upsert`, `post_schedule`, `post_publish`, `post_draft_from_media`, `post_caption_suggest`, `post_metrics_add`, `post_metrics_compare`, `posts_stats`, `posts_calendar_export`.
- Analítica: `plausible_query`, `plausible_history`.
- CRM: `crm_list`, `crm_get`, `crm_company_save`, `crm_deal_save`, `crm_patch`, `crm_activity_add`, `crm_summary`, `crm_export`.

Las respuestas al asistente se recortan a 20 000 bytes (`truncated` indica lo omitido); la página web recibe todo. Los errores llegan como `{ok: false, error, code}`.

Eventos: `mercator.post.scheduled`, `mercator.post.published`, `mercator.post.drafted`, `mercator.sales.imported {batch}` (para que una regla del hub registre el ingreso). `GET /api/family/agenda` devuelve las publicaciones programadas (tipo `publish`) con el mismo token.

**Consultar desde Faustus.** El icono de Faustus abre el copiloto compartido en el panel y en la página de publicación, también dentro de los diálogos. Los chats, borradores, llamadas al modelo y herramientas se quedan en Faustus; Mercator solo guarda su `data/copilot-space-id` estable. El panel recibe la vista actual, los identificadores reales de los registros y los campos sin guardar de los editores; al terminar un turno se refrescan listas y métricas sin perder los borradores abiertos. Véase [docs/copilot.md](docs/copilot.md).

**Skills.** La app lleva `catalogue-and-sales-metrics` y `measured-improvement` de la biblioteca de skills de la familia para los agentes que se conectan, que se leen con `skills_list` y `skill_read` y se asignan en la página de skills (`/api/agent/skills/page`) o en la pestaña Skills del hub.

## Estructura del proyecto

| Ruta | Contenido |
|---|---|
| `mercator.py`, `mercator_family.py` | servidor e integración con la familia |
| `agent_tools.py`, `mcp_server.py` | herramientas y puente stdio |
| `crm.py`, `publishing.py`, `post_csv.py`, `calendar_export.py`, `cults_catalog.py`, `plausible_stats.py` | CRM, publicación, importación CSV, exportación de calendario, catálogo, Plausible |
| `hoard_link/` | biblioteca compartida de la familia, incluida sin cambios (solo biblioteca estándar) |
| `static/` | interfaz web |
| `docs/` | referencias de exportación de calendario y copiloto |
| `tests/` | pruebas de Python y JS |
| `data/` | base SQLite, token, espacio del copiloto (no versionado) |

Los datos se abren con `hoard_link.sqlkit.Database`: una conexión compartida, WAL, espera de 15 s por bloqueo y migraciones versionadas.

## Pruebas

```sh
python -m unittest discover -s tests   # o: python -m pytest tests
```

Las pruebas del puente necesitan el paquete `mcp` y se omiten sin él.
