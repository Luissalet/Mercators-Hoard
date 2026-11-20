# Website publishing / Publicación de webs

## English

Open **Websites** from Mercator and enter a full path to a local folder or ZIP, plus a stable identifier. Use the same identifier when you update the package. The address stays fixed across updates, unpublish, undo and Mercator restarts. **Start Mercator with the Hub** adds Mercator to the Hub's keep-alive list. It applies to the app and is managed in the Hub. Mercator restores active sites when it starts and retains each site's form inbox after it is unpublished.

The package needs `index.html` at its root or under `public/`. A ZIP may wrap the package in a single folder. For deployments with a bundled server, put the publishable files under `public/` and place `website.json` at the package root. A manual publication can also specify the entry file without a manifest.

For a static booking export, keep `public/index.html` and the website assets together. Place the `website.json` form contract at the package root so `website_form_check` can verify a submission to the site's inbox. The `deployment-patterns` skill describes how to verify a publication and exercise its rollback.

A static site can POST a JSON object of text fields, or an HTML form encoded as application/x-www-form-urlencoded, to /api/forms on its own origin. The response contains a reference. A bundled Python server can keep its original form endpoint and write to the SQLite path Mercator supplied. For that route the inbox reads the commissions table with reference, created_at, name, email, category and details columns, or the Mercator submissions schema with reference, created_at and fields (JSON object). Use UTC for created_at. **Form submissions** lists the fields and reference from the same submission. Keep credentials and personal data outside the source package.

Agent tools use the existing Mercator MCP and Hub transport:

- **website_publish** takes slug, source, optional title, optional server, and start_with_hub (default true). Returns the local URL, package revision, Hub startup state and undo token.
- **website_status** takes an optional slug. Check state live and Hub startup state enabled for a publication managed by the Hub.
- **website_submissions** takes slug and optional limit and offset. It reads the inbox, including after unpublishing.
- **website_form_check** takes the live site URL. It posts the declared synthetic data to the form and compares the response reference with that record in the declared inbox schema. The receipt has a verdict, the marked record and an undo call. The Websites page and the inbox tool identify it as a test submission.
- **website_form_check_undo** takes the slug and the test's undo token. It removes the marked row and leaves ordinary submissions and other checks in place.
- **website_unpublish** takes slug and returns an undo token.
- **website_undo** takes slug and the current undo_token. Reverts the last change, retaining form submissions. An older token is refused after an intervening change.

The registered package revisions, private form databases and runtime logs live under the Mercator data directory in websites/. If a port is occupied, the site reports unavailable and retries that address.

For a public deployment, choose an HTTPS reverse proxy to the website's own port, or move the web files to a static host and connect the form to an appropriate backend. Configure the chosen public origin in the form server and verify storage and submission end to end. Mercator's management interface and inbox stay on a separate local origin. These destinations require the operator's actual domain, hosting and configuration.

## Español

Abre **Webs** en Mercator y escribe la ruta completa de una carpeta o un ZIP local y un identificador estable. Usa el mismo identificador para actualizar el paquete. La dirección se conserva al actualizar, despublicar, deshacer y reiniciar Mercator. **Arrancar Mercator con el Hub** añade Mercator a la lista de arranque del Hub. Es un ajuste de la app y se gestiona desde el Hub. Al arrancar, Mercator recupera las webs activas y conserva el buzón de formularios de cada web despublicada.

Incluye `index.html` en la raíz o en `public/`. El ZIP puede contener una única carpeta con el paquete. Si el paquete incluye un servidor, guarda en `public/` los archivos que se van a servir y declara el servidor en `website.json`, en la raíz del paquete. Para una publicación manual también puedes indicar la ruta relativa del archivo Python.

Para publicar una reserva como sitio estático, conserva `public/index.html` con los recursos de la web. Guarda el contrato del formulario en `website.json` en la raíz del paquete. La skill `deployment-patterns` explica cómo comprobar una publicación y deshacerla.

Una web estática puede enviar un objeto JSON con campos de texto o un formulario HTML application/x-www-form-urlencoded a /api/forms de su propio origen. La respuesta contiene una referencia. Si el paquete trae servidor, puede usar su propia ruta de formulario y escribir en la base SQLite que le pasa Mercator. El buzón lee la tabla commissions con las columnas reference, created_at, name, email, category y details, o la tabla submissions con reference, created_at y fields (objeto JSON). Usa UTC para created_at. **Formularios** muestra los campos y la referencia del mismo envío. Guarda las credenciales y los datos personales fuera del paquete.

Las herramientas para agentes están en el MCP de Mercator y en el Hub. Publica con website_publish, comprueba el estado con website_status y lee los envíos con website_submissions. Usa website_unpublish para dejar de servir una web y website_undo con el token del último cambio para recuperarla. Los envíos se conservan. El registro de versiones, los buzones y los registros de ejecución se guardan en websites/ dentro de los datos de Mercator. Si el puerto está ocupado, Mercator muestra la web como no disponible y vuelve a intentar la misma dirección.

`website_form_check {url}` envía los datos sintéticos declarados y coteja la referencia de la respuesta con el registro del buzón. Devuelve un veredicto, el envío marcado y cómo deshacerlo. **Formularios** y `website_submissions` identifican el envío como prueba. `website_form_check_undo` retira ese envío con su token y conserva el resto del buzón.

Para publicar fuera de este PC, elige un dominio con proxy HTTPS hacia el puerto de la web, o sube los archivos web a un alojamiento estático y conecta el formulario a un servidor. Configura el origen público elegido en el servidor del formulario y comprueba el envío y su almacenamiento. La gestión y el buzón de Mercator tienen su propio origen local. Cada destino requiere un dominio, alojamiento y configuración reales.

## Package contract / Contrato del paquete

```json
{
  "version": 1,
  "server": {"entry": "server.py", "origin": "port", "readiness": "/"},
  "form": {
    "path": "/api/encargos",
    "schema": "commissions",
    "fields": {
      "name": "Form test",
      "email": "test@example.invalid",
      "category": "personaje",
      "details": "Synthetic website check"
    },
    "marker_field": "details"
  }
}
```

- **Server / Servidor.** Mercator launches the trusted entry with `--port` and `--db`. Bind to `127.0.0.1`, serve the site at `/`, and answer the declared readiness GET with HTTP 200 when ready. With `origin: "port"`, derive the origin as `http://127.0.0.1:<port>`. With `origin: "argument"`, accept this address through `--origin`. Mercator passes a persistent SQLite path and uses the package's existing Python environment.
- **Servidor / Server.** Mercator arranca el archivo de confianza con `--port` y `--db`. Escucha en `127.0.0.1`, sirve la web en `/` y devuelve HTTP 200 al GET de comprobación cuando esté lista. Con `origin: "port"`, deduce el origen `http://127.0.0.1:<puerto>`. Con `origin: "argument"`, recíbelo en `--origin`. Mercator pasa una ruta SQLite persistente y usa el entorno Python disponible.
- **Form / Formulario.** Accept JSON at the declared same-origin path, commit the fields to the named inbox schema, then return a successful response with `{"reference":"…"}`. Use a fixture accepted by the site's validation. Choose a free-text field that can keep the appended ` [mercator-test:<id>]` marker intact. A site using Mercator's static server can declare a form with `/api/forms` and `submissions` and omit the server block. The form declaration is required to run the synthetic check.
- **Formulario / Form.** Acepta JSON en la ruta declarada del mismo origen, guarda los campos con el esquema indicado y devuelve una respuesta correcta con `{"reference":"…"}`. Usa datos sintéticos que admita el formulario y un campo de texto libre que conserve la marca añadida ` [mercator-test:<id>]`. En el servidor estático de Mercator, puedes declarar el formulario con `/api/forms` y `submissions` y omitir el bloque de servidor. La prueba sintética requiere la declaración del formulario.

The Hub's order handoff calls the same publisher with the registered source fingerprint. The published site's `provenance` retains the order ID and both piece identities, each with its revision and SHA-256.

El relevo de órdenes del Hub llama al mismo publicador con la huella del origen registrado. La publicación conserva en `provenance` el identificador de la orden y el de cada pieza con su revisión y SHA-256.
