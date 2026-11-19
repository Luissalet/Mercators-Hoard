"use strict";

const dictionary = {
  es: {
    nav: "Secciones", dashboard: "Panel", posts: "Publicación", websites: "Webs", language: "Idioma",
    intro: "Publica una carpeta o un ZIP en este PC y consulta los envíos de su formulario.",
    published: "Publicaciones", refresh: "Actualizar", loading: "Cargando webs…",
    destinations: "Destinos públicos", https: "Dominio con proxy HTTPS. Aloja la web y el formulario desde un origen público de tu elección.",
    staticHost: "Alojamiento estático. Sube los archivos web y conecta el formulario a un servidor si lo necesita.",
    setup: "Publicar una web", source: "Carpeta o ZIP", sourceHelp: "Copia la ruta completa del archivo o carpeta.",
    slug: "Identificador", title: "Título", slugHelp: "Para actualizar una web, usa el mismo identificador.",
    runtime: "Servidor del paquete", entry: "Archivo Python",
    entryHelp: "Indica la ruta relativa si el paquete incluye un servidor de confianza que acepta --port y --db. Deja el campo vacío para que Mercator sirva los archivos.",
    autostart: "Arrancar Mercator con el Hub", publish: "Publicar en este PC",
    live: "Publicada", unpublished: "Despublicada", unavailable: "No disponible",
    enabled: "Mercator arranca con el Hub.", disabled: "Mercator arranca bajo demanda.",
    paused: "El arranque de Mercator con el Hub está en pausa.",
    hubUnavailable: "El Hub no ha confirmado el arranque de Mercator.",
    empty: "Las webs que publiques aparecerán aquí.", stop: "Despublicar", undo: "Deshacer",
    inbox: "Formularios", more: "Ver más", noSubmissions: "Todavía no hay envíos.",
    busy: "Guardando…", publishedNotice: "Web publicada.", unpublishedNotice: "Web despublicada. Puedes deshacer el cambio.",
    restoredNotice: "Cambio deshecho.", readFailed: "No se han podido leer los datos. Pulsa Actualizar para reintentar.",
    internal: "No se ha podido completar la operación. Comprueba el estado y vuelve a intentarlo.",
    invalid_slug: "Usa letras minúsculas, números y guiones simples en el identificador.",
    invalid_source: "Elige la ruta completa de una carpeta o ZIP local accesible, fuera del almacén de publicaciones.",
    invalid_package: "Revisa el contenido del paquete. Puede contener enlaces, rutas duplicadas o inválidas, o superar el tamaño admitido.",
    missing_index: "Incluye index.html en la raíz del paquete o en public/.",
    invalid_server: "Incluye el archivo Python indicado y public/index.html.",
    invalid_options: "Revisa el título y la opción de arranque.",
    start_failed: "La web no ha respondido en su dirección local. Comprueba que el puerto esté libre y que el servidor pueda arrancar.",
    stale_undo: "Hay un cambio posterior en esta web. Actualiza la lista para ver qué puedes deshacer.",
    unknown_site: "La web no está en el registro.",
    name: "Nombre", email: "Correo", category: "Categoría", details: "Detalles",
  },
  en: {
    nav: "Sections", dashboard: "Dashboard", posts: "Publishing", websites: "Websites", language: "Language",
    intro: "Publish a folder or ZIP on this PC and read its form submissions.",
    published: "Publications", refresh: "Refresh", loading: "Loading websites…",
    destinations: "Public destinations", https: "Domain with HTTPS reverse proxy. Serve the website and form at a public origin you choose.",
    staticHost: "Static hosting. Upload the web files and connect the form to a server if needed.",
    setup: "Publish a website", source: "Folder or ZIP", sourceHelp: "Copy the full path to the file or folder.",
    slug: "Identifier", title: "Title", slugHelp: "Use the same identifier to update a website.",
    runtime: "Bundled server", entry: "Python entry file",
    entryHelp: "Enter a relative path if the package has a trusted server that accepts --port and --db. Leave it blank to let Mercator serve the files.",
    autostart: "Start Mercator with the Hub", publish: "Publish on this PC",
    live: "Published", unpublished: "Unpublished", unavailable: "Unavailable",
    enabled: "Mercator starts with the Hub.", disabled: "Mercator starts on demand.",
    paused: "Mercator startup with the Hub is paused.",
    hubUnavailable: "The Hub has not confirmed Mercator startup.",
    empty: "Your published websites appear here.", stop: "Unpublish", undo: "Undo",
    inbox: "Form submissions", more: "Show more", noSubmissions: "There are no submissions yet.",
    busy: "Saving…", publishedNotice: "Website published.", unpublishedNotice: "Website unpublished. You can undo this change.",
    restoredNotice: "Change undone.", readFailed: "Could not load the data. Select Refresh to retry.",
    internal: "Could not complete the operation. Check the state and try again.",
    invalid_slug: "Use lowercase letters, numbers and single hyphens for the identifier.",
    invalid_source: "Choose the full path to an accessible local folder or ZIP outside the publication store.",
    invalid_package: "Check the package. It may contain links, duplicate or invalid paths, or exceed the size limit.",
    missing_index: "Include index.html at the package root or in public/.",
    invalid_server: "Include the specified Python entry file and public/index.html.",
    invalid_options: "Check the title and startup option.",
    start_failed: "The website did not respond at its local address. Check the port is free and the server can start.",
    stale_undo: "A newer change was made to the website. Refresh the list to see which change can be undone.",
    unknown_site: "This website is not in the registry.",
    name: "Name", email: "Email", category: "Category", details: "Details",
  },
};

const $ = id => document.getElementById(id);
const language = $("language");
language.value = localStorage.getItem("mercator-websites-language") === "en" || new URLSearchParams(location.search).get("lang") === "en" ? "en" : "es";
const words = key => dictionary[language.value][key] ?? key;
const list = $("sites");
const actionMessage = $("action-message");
let snapshot;
let selection;
let receiptOffset = 0;
let receiptItems = [];
let receiptRequest = 0;
let listRequest = 0;
let busy = false;

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

function action(text, callback) {
  const button = element("button", words(text));
  button.type = "button";
  button.addEventListener("click", callback);
  return button;
}

async function api(path, body) {
  const response = await fetch("/api/websites" + path, body ? {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  } : {cache: "no-store"});
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.code || "internal");
  return data;
}

function renderList() {
  if (!snapshot) return;
  const hubState = snapshot.hub_startup.state;
  $("hub-state").textContent = words(hubState === "unavailable" ? "hubUnavailable" : hubState);
  $("list-message").textContent = snapshot.sites.length ? "" : words("empty");
  list.replaceChildren(...snapshot.sites.map(site => {
    const row = element("li", "", "site-row");
    const name = element("span", site.title, "site-name");
    const state = element("span", words(site.state), "site-state");
    state.dataset.state = site.state;
    const heading = element("div", "", "site-heading");
    heading.append(name, state);
    const address = element("p");
    if (site.state === "live") {
      const link = element("a", site.url, "site-url");
      link.href = site.url;
      link.target = "_blank";
      link.rel = "noopener";
      address.append(link);
    } else {
      address.textContent = site.url;
    }
    const controls = element("div", "", "site-actions");
    controls.append(action("inbox", () => openInbox(site)));
    if (site.active) controls.append(action("stop", () => change("/unpublish", {slug: site.slug}, "unpublishedNotice")));
    if (site.undo_token) {
      controls.append(action("undo", () => change("/undo", {slug: site.slug, undo_token: site.undo_token}, "restoredNotice")));
    }
    row.append(heading, address, controls);
    return row;
  }));
}

async function refresh() {
  const request = ++listRequest;
  list.setAttribute("aria-busy", "true");
  try {
    const current = await api("");
    if (request !== listRequest) return;
    snapshot = current;
    renderList();
    $("list-message").classList.remove("website-error");
  } catch {
    if (request !== listRequest) return;
    $("list-message").textContent = words("readFailed");
    $("list-message").classList.add("website-error");
  } finally {
    if (request === listRequest) list.setAttribute("aria-busy", "false");
  }
}

function message(key, isError = false) {
  actionMessage.dataset.messageKey = key;
  actionMessage.textContent = words(key);
  actionMessage.classList.toggle("website-error", isError);
}

async function change(route, body, notice) {
  if (busy) return;
  busy = true;
  const buttons = [...$("publish").querySelectorAll("button"), ...list.querySelectorAll("button")];
  buttons.forEach(button => { button.disabled = true; });
  message("busy");
  try {
    const result = await api(route, body);
    message(notice);
    if (result.hub_startup?.state === "unavailable" || result.hub_startup?.state === "paused") {
      message(result.hub_startup.state === "paused" ? "paused" : "hubUnavailable", true);
    }
    await refresh();
  } catch (error) {
    message(Object.hasOwn(dictionary.en, error.message) ? error.message : "internal", true);
  } finally {
    busy = false;
    buttons.forEach(button => { button.disabled = false; });
  }
}

function renderInbox() {
  if (!selection) return;
  $("inbox-title").textContent = words("inbox") + " · " + selection.title;
  $("submissions").replaceChildren(...receiptItems.map(record => {
    const row = element("li", "", "submission-row");
    const heading = element("div", "", "site-heading");
    heading.append(element("strong", record.reference), element("span", record.created_at + " UTC", "website-muted"));
    const fields = element("dl");
    Object.entries(record.fields).forEach(([key, value]) => {
      fields.append(element("dt", Object.hasOwn(dictionary.en, key) ? words(key) : key), element("dd", value));
    });
    row.append(heading, fields);
    return row;
  }));
}

async function loadInbox(more = false) {
  if (!selection) return;
  const request = ++receiptRequest;
  const message = $("inbox-message");
  const extra = $("more-submissions");
  message.textContent = words("loading");
  extra.disabled = true;
  try {
    const query = new URLSearchParams({slug: selection.slug, offset: more ? receiptOffset : 0});
    const result = await api("/submissions?" + query);
    if (request !== receiptRequest) return;
    receiptOffset = result.next_offset;
    receiptItems = more ? receiptItems.concat(result.submissions) : result.submissions;
    renderInbox();
    message.textContent = receiptItems.length ? "" : words("noSubmissions");
    extra.hidden = receiptOffset === null;
  } catch {
    if (request === receiptRequest) message.textContent = words("readFailed");
  } finally {
    if (request === receiptRequest) extra.disabled = false;
  }
}

function openInbox(site) {
  selection = site;
  receiptItems = [];
  $("more-submissions").hidden = true;
  renderInbox();
  $("inbox").hidden = false;
  $("inbox-title").focus();
  loadInbox();
}

function translate() {
  document.documentElement.lang = language.value;
  document.title = words("websites") + " · Mercator's Hoard";
  document.querySelectorAll("[data-text]").forEach(node => { node.textContent = words(node.dataset.text); });
  document.querySelectorAll("[data-label]").forEach(node => { node.setAttribute("aria-label", words(node.dataset.label)); });
  if (actionMessage.dataset.messageKey) actionMessage.textContent = words(actionMessage.dataset.messageKey);
  renderList();
  renderInbox();
}

language.addEventListener("change", () => {
  localStorage.setItem("mercator-websites-language", language.value);
  translate();
  if (selection && !receiptItems.length) loadInbox();
});
$("reload").addEventListener("click", refresh);
$("reload-inbox").addEventListener("click", () => loadInbox());
$("more-submissions").addEventListener("click", () => loadInbox(true));
$("publish").addEventListener("submit", event => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const body = {source: data.get("source").trim().replace(/^"([^"]+)"$/, "$1"), slug: data.get("slug").trim(),
    server: data.get("server").trim(), start_with_hub: data.has("start_with_hub")};
  if (data.get("title").trim()) body.title = data.get("title").trim();
  change("/publish", body, "publishedNotice");
});

translate();
refresh();
