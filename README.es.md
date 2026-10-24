# Mercator's Hoard

En **Catálogo**, busca por título o ID local y elige **Todos**, **Fichas sin
etiquetas** o **Sin ficha o formato dañado**. **Filtrar** aplica la consulta;
**Anterior/Siguiente** recorren páginas nativas de50 filas con rango y total.
Editar los criterios retira las filas anteriores; reintentar conserva la página
solicitada y los campos. El refresco mantiene criterios pendientes y borradores
de otros editores. `GET /api/catalog` delega `mercator_catalog` existente de
API/MCP25 sin recorte de respuesta para la UI, sin filtro paralelo en navegador.
El criterio nativo sin etiquetas exige ficha y cantidad0; el de ausencia/formato
incluye ficha ausente o indicador nativo de formato inválido. Un tipo de etiquetas
incorrecto puede coincidir con ambos; JSON no objeto conserva los valores nativos
de ficha ausente. Son indicadores locales, no prueba de publicación ni validez en
Cults. Cada página relee el catálogo actual, sin promesa de foto estable ante
cambios simultáneos. Consultar no modifica fichas, importa de Vulcan ni contacta
Cults.

En **Analítica web**, elige **Personalizado** y **Desde/Hasta** para consultar un
intervalo explícito con la API/MCP25 de Plausible existente. Se envían las dos
fechas ISO sin convertirlas; Plausible usa la zona de informes del sitio. Se
conservan los periodos, agrupación, histórico guardado y exportación JSON. Cambiar
los datos de consulta retira los resultados anteriores; un error conserva el
borrador para reintentar. El copilot distingue el borrador de la consulta aplicada.
Una petición ya enviada puede registrar su snapshot aunque cambie el formulario;
no se cancela remotamente.

En **Clientes**, abre una empresa guardada y pulsa **Ver sus oportunidades** para
delimitar lista, resumen completo y exportaciones JSON/CSV a su ID real. Se muestra
su nombre guardado al seleccionarla y su identidad; el nombre/notas sin guardar
siguen en el editor. **Todas las empresas** retira sólo ese ámbito y conserva
proyecto/responsable/etapa/texto. Los homónimos no se mezclan y cero coincidencias
sigue siendo cero. Aplicar o reintentar lecturas no guarda ni reconstruye la ficha
abierta. Cambiar filtros retira resultados antiguos; pulsa **Filtrar** para aplicar
o reintentar. Usa `company_id` nativo compartido con API/MCP25: resumen/exportación
incluyen todas las coincidencias, tabla de50porpágina. Importes estimados separados
por moneda; ganado no equivale a cobrado. El ámbito sólo vive en la página, sin
persistencia nueva ni servicio CRM externo.

**Publicación → Desde un medio** crea o localiza una publicación mediante `post_draft_from_media` existente. Referencia y título son obligatorios por su contrato API/MCP; la plataforma es opcional y usa la predeterminada nativa al crear. Título/plataforma sólo se aplican a un borrador nuevo. Una coincidencia no archivada por referencia exacta se devuelve intacta, aunque esté publicada o en otra plataforma; prevalece el menor ID coincidente. Si sólo hay archivadas, permite un borrador nuevo. El resultado muestra ID/título/plataforma/estado reales y ofrece **Abrir publicación** explícito. Abrir/cerrar el formulario no escribe; enviar puede guardar un borrador, y cerrar/cambiar campos no cancela una petición ya enviada. No resuelve/sube medios ni publica en redes. Un error conserva los campos; editarlos o refrescar retira resultados anteriores sin sustituir el borrador de un editor abierto.

En una oportunidad del CRM, el formulario de interacción admite fecha/hora ISO opcional con zona explícita (`Z` o un desfase como `+02:00`). Vacía usa la hora del servidor al guardar. La API/MCP `crm_activity_add` existente la registra como `observed_at` y guarda aparte la hora de registro `recorded_at`; el historial rotula ambas y mantiene su orden nativo por registro más reciente y su vista de 200 entradas. Anota una interacción ocurrida, sin enviar mensajes ni avisos. Un fallo conserva nota/fuente/fecha y reutiliza el ID nativo en el reintento idéntico. Guardar la interacción conserva los campos pendientes de la oportunidad y las ediciones posteriores de la interacción.

Desde **Publicación → Calendario**, **Descargar programadas (.ics)** exporta
las publicaciones programadas de las celdas visibles y los filtros actuales
de plataforma y búsqueda. Importa la copia en tu agenda; no sincroniza ni
publica. Las fechas sin hora son eventos de día completo, los desfases
explícitos conservan su instante en UTC y las horas sin zona mantienen la
hora local en la agenda de destino. La herramienta MCP de solo lectura
`posts_calendar_export` devuelve una URL local para descargar el archivo
completo. [Formato y API](docs/calendar-export.md).

[English](README.md)

Panel local para seguir WatchHoard y BookHoard, las fichas de productos de Cults y las ventas que importes desde Cults.

## Abrir

El icono de Faustus abre el copilot común en el panel y en publicación, también dentro de los editores y de la importación CSV. Faustus conserva chats, borradores, modelos y herramientas; Mercator guarda únicamente su identidad estable en `data/copilot-space-id`. `MERCATOR_DATA_DIR` elige otro espacio de datos. Configura el servicio global mediante HoardLink o `MERCATOR_FAUSTUS_URL`; el razonamiento usa las Sparks y la generación de contenido puede utilizar las GPU locales.

El contexto incluye la vista, los identificadores reales de empresas, oportunidades o publicaciones y los campos sin guardar. Las altas y los registros eliminados no inventan un objeto. Al terminar un turno se actualizan las listas, consultas guardadas y métricas sin rehacer el formulario ni perder su borrador. CRM y publicación guardan sólo lo cambiado, conservando los cambios concurrentes del agente en otros campos. `crm_patch {kind, id, fields}` aplica esa combinación dentro de la transacción; siguen disponibles las herramientas anteriores con revisión.

Contrato y rutas en [la API del copilot](docs/copilot.md).

Desde esta carpeta, ejecuta `python mercator.py` y abre [http://127.0.0.1:5195](http://127.0.0.1:5195). También puede arrancarse desde Hoard Hub mediante `faustus-plugin.json`. El panel conserva los históricos en `data/mercator.sqlite3`, únicamente en este equipo.

Al abrir Mercator, y después cada seis horas mientras siga funcionando, se consultan usuarios de Supabase Auth y peticiones/errores de Cloudflare Workers. Pulsa **Actualizar datos** para adelantar la consulta. La pantalla inicial muestra la última lectura guardada; una fuente sin acceso se marca como pendiente y no presenta como actual una cifra anterior.

## Accesos

Mercator lee `WatchHoard/watchhoard/.env` para WatchHoard. La clave pública de BookHoard no permite contar usuarios de Auth. Para activar esa lectura y las métricas de Workers, copia `.env.example` como `.env` y completa los valores. No pongas claves en la interfaz ni en Git.

Cloudflare requiere un token con permiso de lectura de Analytics para la cuenta que aloja los Workers `watchhoard` y `bookhoard`. Si están en cuentas distintas, `.env.example` permite indicar token y cuenta para cada proyecto.

## Ventas de Cults

Exporta un CSV de ventas desde Cults, elígelo en la sección **Ventas** y asigna las columnas de fecha, producto e ingreso. Puedes indicar moneda e ID de venta. La importación acepta coma, punto y coma o tabulador, y evita volver a contar la misma fila al importar el mismo archivo otra vez. Si no hay ID, distingue ventas idénticas repetidas dentro del archivo por su posición relativa entre iguales. Importes y fechas se leen con las reglas de la familia (`hoard_link.money` / `hoard_link.dates`): `1.234,56`, `1,234.56`, `(12.00)`, `12 €` y `28/09/2026`, `2026-09-28`, `5 sept 2026`, `Sep 14, 2026`; el separador decimal se toma de toda la columna, un `1.234` suelto vale 1234 (salvo que la moneda de la fila escriba los decimales con punto, como USD) y una fecha sin año se rechaza, no se adivina.

Los ingresos se muestran por moneda, sin sumar monedas diferentes ni asumir que el importe es beneficio neto. Mercator no consulta Cults en directo hasta disponer de un acceso y un esquema de ventas comprobados.

**Ver lote importado** muestra sólo las ventas nuevas guardadas en esa importación; **Ver último lote** conserva el acceso al último lote registrado después de recargar. El panel muestra identidad, fuente registrada, fecha de importación, filas procesadas del CSV, ventas añadidas e importes nativos exactos por moneda. La tabla presenta 50 líneas por página; su numeración pertenece al lote y los IDs locales no son pedidos de Cults. Reimportar un archivo ya registrado genera un lote vacío real. Las importaciones antiguas sin identificador de lote se indican expresamente. La lectura reutiliza `sales_batch_get {batch}` mediante `GET /api/sales/batch?batch=...`; abrir o reintentar no importa otra vez. No es un navegador de todo el histórico ni una confirmación de cobro.

## Catálogo

Lee, sin modificar, las subcarpetas de `Desktop/Modelos/Contornos pokemon` y detecta cuáles tienen `cults3d.json`. Puedes cambiar la ubicación con `MERCATOR_PRODUCTS_DIR` en `.env`.

## Publicación

La página **Publicación** (`/publicacion`) sirve para planificar y medir lo que publicas.

- **Posts** con plataforma (Reel o post de Instagram, TikTok, YouTube Short o vídeo, X, Cults3D, otra), título, pie, hashtags, referencia al material, estado (idea, borrador, programado, publicado, archivado), fechas de programación y publicación, URL y notas. La referencia al material es `hoard://lumiere/render/<id>`, `hoard://prospero/production/<id>`, `hoard://vulcan/model/<id>` o una ruta de archivo; si es una imagen o vídeo servible, se muestra una vista previa.
- **Calendario** (semana o mes) y **tablero** por estado. El editor muestra un contador de caracteres por plataforma (límites orientativos, no garantizados) y un botón para copiar el pie.
- **Usar como base** en una publicación guardada prepara otro borrador con el contenido visible: plataforma, título, pie, hashtags, referencia al material y notas. Muestra el origen y permite adaptar texto o plataforma antes de **Guardar**. Abrir o cancelar no escribe; guardar crea una publicación nueva mediante el alta nativa, sin modificar el original. No arrastra fechas, URL publicada, identificadores externos ni métricas; no publica en ninguna red. El copilot identifica el nuevo borrador sin objeto guardado y conserva su contenido al refrescar.
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

También puedes abrir una publicación guardada y pulsar **Métricas** en la cabecera del editor. En **Comparar crecimiento**, elige las fechas inicial y final en la zona horaria de tu navegador o pulsa **Primera a última**. La tabla muestra las lecturas utilizadas, seis métricas e ingresos, cambios con signo y porcentajes. Explica los datos ausentes, las bases cero y las monedas distintas. La página usa el mismo cálculo que Faustus mediante `POST /api/posts/metrics/compare`; consultar una comparación no modifica las lecturas.

`post_metrics_compare {post_id, from_ts, to_ts}` compara la última lectura completa guardada en o antes de cada extremo. Devuelve las dos lecturas reales, diferencias y porcentajes por métrica e ingresos exactos cuando coinciden las monedas. Los datos ausentes quedan en `null`; una base cero no tiene porcentaje y las bajadas conservan su signo. Son cambios entre observaciones guardadas, no sumas de actividad diaria, analítica en directo ni beneficio. Usa fechas ISO con zona horaria; sin zona se usa la de este ordenador. Las lecturas parciales no se rellenan con valores antiguos.

La herramienta reutiliza el historial local sin dependencias nuevas. Las [definiciones oficiales de métricas de YouTube](https://developers.google.com/youtube/analytics/metrics) y sus [rangos de informes](https://developers.google.com/youtube/analytics/reference/reports/query) sirvieron de referencia para distinguir observaciones de actividad por periodo; esta herramienta no consulta esas API.

## Verificar

`python -m unittest discover -s tests` comprueba importación, límites de acceso y comportamiento de la lectura. El servidor está limitado a `127.0.0.1` y aplica el guardia de peticiones de la familia (`hoard_link.guard`): el `Host` debe ser local y nombrar el puerto del servidor (otros nombres, en `MERCATOR_ALLOWED_HOSTS`), el `Origin` del navegador debe ser local con el mismo puerto y se rechazan las peticiones entre sitios y los envíos de formularios; no lo expongas a la red con claves de servidor cargadas.

## Ampliación de la familia · 2026-10-04

`plausible_query` consulta Plausible v2 y conserva consulta, respuesta, origen y fecha; `plausible_history` recupera el historial. La pestaña Analítica usa los mismos handlers, conserva dimensiones, monedas y nulos y exporta JSON. Configura `PLAUSIBLE_API_KEY` y opcionalmente `PLAUSIBLE_URL`. Hace falta acceso API de la edición/cuenta. Admite periodos, fechas, métricas y dimensiones, hasta 1000 filas; aún no expone filtros ni páginas adicionales. No instala rastreo ni inventa métricas.
