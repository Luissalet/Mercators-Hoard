# Website publishing / Publicación de webs

## English

Open **Websites** from Mercator and enter a full path to a local folder or ZIP, plus a stable identifier. Use the same identifier when you update the package. The address stays fixed across updates, unpublish, undo and Mercator restarts. **Start Mercator with the Hub** adds Mercator to the Hub's keep-alive list. It applies to the app and is managed in the Hub. Mercator restores active sites when it starts and retains each site's form inbox after it is unpublished.

The package needs an index.html at its root or under public/. A ZIP may wrap the package in a single folder. Keep the publishable files in public/ when the package contains private working files. Use a relative Python entry file, such as server.py, to run a trusted bundled server. That server must bind to 127.0.0.1, serve public/index.html at /, and accept --port and --db. Mercator starts it from the stored package with Python, without installing dependencies, and supplies a separate persistent SQLite path for that website.

A static site can POST a JSON object of text fields, or an HTML form encoded as application/x-www-form-urlencoded, to /api/forms on its own origin. The response contains a reference. A bundled Python server can keep its original form endpoint and write to the SQLite path Mercator supplied. For that route the inbox reads the commissions table with reference, created_at, name, email, category and details columns, or the Mercator submissions schema with reference, created_at and fields (JSON object). Use UTC for created_at. **Form submissions** lists the fields and reference from the same submission. Keep credentials and personal data outside the source package.

Agent tools use the existing Mercator MCP and Hub transport:

- **website_publish** takes slug, source, optional title, optional server, and start_with_hub (default true). Returns the local URL, package revision, Hub startup state and undo token.
- **website_status** takes an optional slug. Check state live and Hub startup state enabled for a publication managed by the Hub.
- **website_submissions** takes slug and optional limit and offset. It reads the inbox, including after unpublishing.
- **website_unpublish** takes slug and returns an undo token.
- **website_undo** takes slug and the current undo_token. Reverts the last change, retaining form submissions. An older token is refused after an intervening change.

The registered package revisions, private form databases and runtime logs live under the Mercator data directory in websites/. If a port is occupied, the site reports unavailable and retries that address.

For a public deployment, choose an HTTPS reverse proxy to the website's own port, or move the web files to a static host and connect the form to an appropriate backend. Configure the chosen public origin in the form server and verify storage and submission end to end. Mercator's management interface and inbox stay on a separate local origin. These destinations require the operator's actual domain, hosting and configuration.

## Español

Abre **Webs** en Mercator y escribe la ruta completa de una carpeta o un ZIP local y un identificador estable. Usa el mismo identificador para actualizar el paquete. La dirección se conserva al actualizar, despublicar, deshacer y reiniciar Mercator. **Arrancar Mercator con el Hub** añade Mercator a la lista de arranque del Hub. Es un ajuste de la app y se gestiona desde el Hub. Al arrancar, Mercator recupera las webs activas y conserva el buzón de formularios de cada web despublicada.

Incluye index.html en la raíz o en public/. El ZIP puede contener una única carpeta con el paquete. Guarda en public/ los archivos que se van a servir cuando haya otros archivos de trabajo. Si el paquete incluye un servidor de confianza, indica la ruta relativa de su archivo Python, por ejemplo server.py. El servidor debe escuchar en 127.0.0.1, servir public/index.html en / y aceptar --port y --db. Mercator lo arranca con Python desde el paquete guardado, sin instalar dependencias, y le pasa una ruta SQLite persistente para esa web.

Una web estática puede enviar un objeto JSON con campos de texto o un formulario HTML application/x-www-form-urlencoded a /api/forms de su propio origen. La respuesta contiene una referencia. Si el paquete trae servidor, puede usar su propia ruta de formulario y escribir en la base SQLite que le pasa Mercator. El buzón lee la tabla commissions con las columnas reference, created_at, name, email, category y details, o la tabla submissions con reference, created_at y fields (objeto JSON). Usa UTC para created_at. **Formularios** muestra los campos y la referencia del mismo envío. Guarda las credenciales y los datos personales fuera del paquete.

Las herramientas para agentes están en el MCP de Mercator y en el Hub. Publica con website_publish, comprueba el estado con website_status y lee los envíos con website_submissions. Usa website_unpublish para dejar de servir una web y website_undo con el token del último cambio para recuperarla. Los envíos se conservan. El registro de versiones, los buzones y los registros de ejecución se guardan en websites/ dentro de los datos de Mercator. Si el puerto está ocupado, Mercator muestra la web como no disponible y vuelve a intentar la misma dirección.

Para publicar fuera de este PC, elige un dominio con proxy HTTPS hacia el puerto de la web, o sube los archivos web a un alojamiento estático y conecta el formulario a un servidor. Configura el origen público elegido en el servidor del formulario y comprueba el envío y su almacenamiento. La gestión y el buzón de Mercator tienen su propio origen local. Cada destino requiere un dominio, alojamiento y configuración reales.
