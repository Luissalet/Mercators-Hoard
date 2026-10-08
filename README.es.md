# Mercator's Hoard

[English](README.md)

Panel local para seguir WatchHoard y BookHoard, las fichas de productos de Cults y las ventas que importes desde Cults.

## Abrir

Desde esta carpeta, ejecuta `python mercator.py` y abre [http://127.0.0.1:5195](http://127.0.0.1:5195). También puede arrancarse desde Hoard Hub mediante `faustus-plugin.json`. El panel conserva los históricos en `data/mercator.sqlite3`, únicamente en este equipo.

Al abrir Mercator, y después cada seis horas mientras siga funcionando, se consultan usuarios de Supabase Auth y peticiones/errores de Cloudflare Workers. Pulsa **Actualizar datos** para adelantar la consulta. La pantalla inicial muestra la última lectura guardada; una fuente sin acceso se marca como pendiente y no presenta como actual una cifra anterior.

## Accesos

Mercator lee `WatchHoard/watchhoard/.env` para WatchHoard. La clave pública de BookHoard no permite contar usuarios de Auth. Para activar esa lectura y las métricas de Workers, copia `.env.example` como `.env` y completa los valores. No pongas claves en la interfaz ni en Git.

Cloudflare requiere un token con permiso de lectura de Analytics para la cuenta que aloja los Workers `watchhoard` y `bookhoard`. Si están en cuentas distintas, `.env.example` permite indicar token y cuenta para cada proyecto.

## Ventas de Cults

Exporta un CSV de ventas desde Cults, elígelo en la sección **Ventas** y asigna las columnas de fecha, producto e ingreso. Puedes indicar moneda e ID de venta. La importación acepta coma, punto y coma o tabulador, y evita volver a contar la misma fila al importar el mismo archivo otra vez. Si no hay ID, distingue ventas idénticas repetidas dentro del archivo por su posición relativa entre iguales. Importes y fechas se leen con las reglas de la familia (`hoard_link.money` / `hoard_link.dates`): `1.234,56`, `1,234.56`, `(12.00)`, `12 €` y `28/09/2026`, `2026-09-28`, `5 sept 2026`, `Sep 14, 2026`; el separador decimal se toma de toda la columna, un `1.234` suelto vale 1234 (salvo que la moneda de la fila escriba los decimales con punto, como USD) y una fecha sin año se rechaza, no se adivina.

Los ingresos se muestran por moneda, sin sumar monedas diferentes ni asumir que el importe es beneficio neto. Mercator no consulta Cults en directo hasta disponer de un acceso y un esquema de ventas comprobados.

## Catálogo

Lee, sin modificar, las subcarpetas de `Desktop/Modelos/Contornos pokemon` y detecta cuáles tienen `cults3d.json`. Puedes cambiar la ubicación con `MERCATOR_PRODUCTS_DIR` en `.env`.

## Publicación

La página **Publicación** (`/publicacion`) sirve para planificar y medir lo que publicas.

- **Posts** con plataforma (Reel o post de Instagram, TikTok, YouTube Short o vídeo, X, Cults3D, otra), título, pie, hashtags, referencia al material, estado (idea, borrador, programado, publicado, archivado), fechas de programación y publicación, URL y notas. La referencia al material es `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` o una ruta de archivo; si es una imagen o vídeo servible, se muestra una vista previa.
- **Calendario** (semana o mes) y **tablero** por estado. El editor muestra un contador de caracteres por plataforma (límites orientativos, no garantizados) y un botón para copiar el pie.
- **Métricas**: añade lecturas a mano (visualizaciones, me gusta, comentarios, compartidos, guardados, ventas, ingresos) o importa un CSV. Gráfica por post, totales por plataforma y **mejores horas** (media de visualizaciones por día de la semana y hora de los posts publicados; avisa cuando hay pocos posts).
- **Importación CSV** por plataforma con asignación de columnas editable. Los preajustes reconocen exportaciones de YouTube Studio, Instagram y TikTok por el nombre de las columnas. Son heurísticos y no se han comprobado con exportaciones reales: revisa la asignación en la vista previa. Importar dos veces el mismo archivo no añade lecturas.
- **Pies de foto**: las sugerencias solo aparecen si Hoard Link llega a un modelo de lenguaje ya cargado; nada depende de ello.

Los datos están en `data/mercator.sqlite3` (tablas `posts`, `post_metrics`, `catalog_items`), abierto con `hoard_link.sqlkit.Database` de la familia: una conexión compartida, WAL, 15 s de espera si el archivo está ocupado, migraciones con versión (`schema_version`) y checkpoint al parar el servidor.

## Familia

Mercator sigue el contrato de la familia Hoard (`faustus-plugin.json`, `x-family`):

- Herramientas por `GET /api/agent/tools` y `POST /api/agent/call` (token en `data/mcp-token`, creado en el primer arranque) y por el puente stdio: `posts_list`, `post_get`, `post_upsert`, `post_schedule`, `post_publish`, `post_metrics_add`, `post_metrics_compare`, `posts_stats`, `post_draft_from_media {media_ref, title}`, `post_caption_suggest`, `sales_batch_get {batch}`, `catalog_from_vulcan {}` (pide a Vulcan `listings_export_catalog` y lo guarda en el catálogo de Cults; Vulcan debe estar en marcha) y las dos de abajo.
- Eventos: `mercator.post.scheduled`, `mercator.post.published`, `mercator.post.drafted`, `mercator.sales.imported {batch}` (tras importar ventas que añadieron líneas, para que una regla del hub registre el ingreso).
- Agenda: `GET /api/family/agenda` responde con los posts programados (tipo `publish`); exige el mismo token.
- `hoard_link/` es la biblioteca compartida, incluida sin cambios (versión 0.8). Se importa solo con la biblioteca estándar, así que el panel sigue funcionando sin instalar nada. El token (`data/mcp-token`) se crea una vez y se conserva entre arranques. Las respuestas de las herramientas para el asistente se limitan a 20 000 bytes (`truncated` dice qué se dejó fuera); la página web recibe todo. Los errores llegan como `{ok: false, error, code}`: `unknown_tool` 404, `invalid` 400 o `internal` 500.

## Consultar desde Faustus

`python mcp_server.py` es el puente MCP por stdio (el puente de catálogo común de la familia; necesita `pip install -r requirements.txt`, es decir, el paquete `mcp`). Lista las herramientas del panel en marcha y le reenvía cada llamada con el token de `data/mcp-token`; si nada responde, arranca `python -m mercator` él mismo (`MERCATOR_BRIDGE_AUTOSTART=0` lo evita; `MERCATOR_URL`, `MERCATOR_PORT`, `MERCATOR_DATA_DIR` y `MERCATOR_TOKEN_FILE` dicen dónde está el servidor). Las dos originales son de solo lectura: `mercator_catalog` busca fichas y filtra las que no tienen etiquetas o tienen archivos pendientes/dañados; `mercator_sales` consulta ventas importadas por producto y separa los totales por moneda. Hoard Hub puede usar la entrada MCP de `faustus-plugin.json`. `MERCATOR_DATA_DIR` y `MERCATOR_PRODUCTS_DIR` permiten seleccionar datos locales distintos para pruebas aisladas.

## Comparar el crecimiento desde Faustus

`post_metrics_compare {post_id, from_ts, to_ts}` compara la última lectura completa guardada en o antes de cada extremo. Devuelve las dos lecturas reales, diferencias y porcentajes por métrica e ingresos exactos cuando coinciden las monedas. Los datos ausentes quedan en `null`; una base cero no tiene porcentaje y las bajadas conservan su signo. Son cambios entre observaciones guardadas, no sumas de actividad diaria, analítica en directo ni beneficio. Usa fechas ISO con zona horaria; sin zona se usa la de este ordenador. Las lecturas parciales no se rellenan con valores antiguos.

La herramienta reutiliza el historial local sin dependencias nuevas. Las [definiciones oficiales de métricas de YouTube](https://developers.google.com/youtube/analytics/metrics) y sus [rangos de informes](https://developers.google.com/youtube/analytics/reference/reports/query) sirvieron de referencia para distinguir observaciones de actividad por periodo; esta herramienta no consulta esas API.

## Verificar

`python -m unittest discover -s tests` comprueba importación, límites de acceso y comportamiento de la lectura. El servidor está limitado a `127.0.0.1` y aplica el guardia de peticiones de la familia (`hoard_link.guard`): el `Host` debe ser local y nombrar el puerto del servidor (otros nombres, en `MERCATOR_ALLOWED_HOSTS`), el `Origin` del navegador debe ser local con el mismo puerto y se rechazan las peticiones entre sitios y los envíos de formularios; no lo expongas a la red con claves de servidor cargadas.

## Ampliación de la familia · 2026-10-04

`plausible_query` consulta Plausible v2 y conserva consulta, respuesta, origen y fecha; `plausible_history` recupera el historial. La pestaña Analítica usa los mismos handlers, conserva dimensiones, monedas y nulos y exporta JSON. Configura `PLAUSIBLE_API_KEY` y opcionalmente `PLAUSIBLE_URL`. Hace falta acceso API de la edición/cuenta. Admite periodos, fechas, métricas y dimensiones, hasta 1000 filas; aún no expone filtros ni páginas adicionales. No instala rastreo ni inventa métricas.
