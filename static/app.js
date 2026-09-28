const $ = (selector) => document.querySelector(selector);
let dashboard = null;
let csvText = "";

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}
function dateLabel(value) {
  if (!value) return "Sin lectura";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("es-ES", {day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(date);
}
function number(value) { return new Intl.NumberFormat("es-ES").format(value); }
function money(value, currency) {
  try { return new Intl.NumberFormat("es-ES", {style:"currency",currency}).format(Number(value)); }
  catch { return `${value} ${currency}`; }
}
function stateClass(value) { return value === "ok" ? "ok" : value === "error" ? "error" : "pending"; }
function stateLabel(value) { return value === "ok" ? "Conectado" : value === "error" ? "Error de lectura" : "Acceso pendiente"; }
function metric(data, project, source, name) { return data.metrics.find(item => item.project === project && item.source === source && item.metric === name); }
function status(data, project, source) { return data.statuses.find(item => item.project === project && item.source === source); }
function reading(label, item, sourceStatus, history) {
  const box = el("div", "reading");
  box.append(el("strong", "", item && sourceStatus?.state === "ok" ? number(item.value) : "—"));
  box.append(el("span", "", label));
  if (sourceStatus?.state === "ok" && item) {
    const snapshots = history.filter(row => row.project === item.project && row.source === item.source && row.metric === item.metric);
    const previous = snapshots.length > 1 ? snapshots[snapshots.length - 2] : null;
    const delta = previous ? item.value - previous.value : null;
    const change = delta === null ? "Primera lectura" : `${delta > 0 ? "+" : ""}${number(delta)} desde ${dateLabel(previous.observed_at)}`;
    box.append(el("small", "", `${change} · Leído ${dateLabel(item.observed_at)}`));
  } else box.append(el("small", "", "Sin cifra actual"));
  return box;
}
function renderProjects(data) {
  const list = $("#project-list"); list.replaceChildren();
  for (const project of data.projects) {
    const auth = status(data, project.id, "supabase");
    const cloud = status(data, project.id, "cloudflare");
    const card = el("article", "project");
    const top = el("div", "project-top"), identity = el("div");
    identity.append(el("h3", "", project.name), el("p", "worker", `Worker: ${project.worker}`));
    const connected = [auth, cloud].filter(item => item?.state === "ok").length;
    top.append(identity, el("span", `project-status ${connected === 2 ? "ok" : "pending"}`, `${connected}/2 fuentes`));
    const metrics = el("div", "metrics");
    metrics.append(
      reading("Usuarios totales", metric(data, project.id, "supabase", "users_total"), auth, data.history),
      reading("Altas · últimos 30 días", metric(data, project.id, "supabase", "signups_30d"), auth, data.history),
      reading("Peticiones al Worker · 7 días", metric(data, project.id, "cloudflare", "requests_7d"), cloud, data.history),
      reading("Errores · últimos 7 días", metric(data, project.id, "cloudflare", "errors_7d"), cloud, data.history)
    );
    const notes = el("div", "source-notes");
    for (const [name, item] of [["Supabase", auth], ["Cloudflare", cloud]]) {
      const note = el("div", "source-note");
      note.append(el("b", "", `${name} · `), el("span", stateClass(item?.state), `${stateLabel(item?.state)}. `));
      note.append(document.createTextNode(item?.detail || "Aún no se ha consultado."));
      if (item?.checked_at) note.append(document.createTextNode(` · ${dateLabel(item.checked_at)}`));
      notes.append(note);
    }
    card.append(top, metrics, notes); list.append(card);
  }
  const good = data.statuses.filter(item => data.projects.some(project => project.id === item.project) && item.state === "ok").length;
  $("#overall-status").textContent = `${good} de 4 conexiones disponibles`;
}
function renderSales(data) {
  $("#sales-count").textContent = `${number(data.sales_count)} ventas`;
  $("#last-import").textContent = data.last_sales_import
    ? `Última importación: ${dateLabel(data.last_sales_import.imported_at)} · ${number(data.last_sales_import.added)} nuevas ventas`
    : "Sin importaciones todavía";
  const summary = $("#sales-summary"); summary.replaceChildren();
  if (!data.sales_count) summary.append(el("p", "empty", "Todavía no hay ventas importadas. Usa el CSV de Cults para ver aquí los ingresos y los productos que más venden."));
  else {
    const totals = new Map();
    for (const row of data.product_sales) totals.set(row.currency, (totals.get(row.currency) || 0) + Number(row.income));
    for (const [currency, amount] of totals) {
      const block = el("div"); block.append(el("strong", "", money(amount, currency)), el("span", "", `Ingresos registrados en ${currency}`)); summary.append(block);
    }
  }
  const months = $("#sales-months"); months.replaceChildren();
  if (data.monthly_sales.length) {
    months.append(el("h3", "", "Evolución mensual"));
    const maxima = new Map();
    for (const row of data.monthly_sales) maxima.set(row.currency, Math.max(maxima.get(row.currency) || 0, Number(row.income)));
    for (const row of data.monthly_sales.slice(-12)) {
      const line = el("div", "month-line"), label = el("span", "", `${row.month} · ${row.currency}`), track = el("div", "month-track"), bar = el("div", "month-bar");
      bar.style.width = `${Math.max(0, Math.min(100, Number(row.income) / (maxima.get(row.currency) || 1) * 100))}%`;
      track.append(bar); line.append(label, track, el("strong", "", money(row.income, row.currency))); months.append(line);
    }
  }
  const body = $("#sales-products"); body.replaceChildren();
  for (const sale of data.product_sales.slice(0, 20)) {
    const row = el("tr"); row.append(el("td", "", sale.product), el("td", "", number(sale.sales)), el("td", "", money(sale.income, sale.currency))); body.append(row);
  }
  if (!data.product_sales.length) { const row = el("tr"); const cell = el("td", "empty", "Aún no hay datos de ventas."); cell.colSpan = 3; row.append(cell); body.append(row); }
}
function renderCatalog(data) {
  const catalog = data.catalog;
  $("#catalog-count").textContent = catalog.state === "ok" ? `${number(catalog.count)} productos` : "Catálogo sin acceso";
  $("#catalog-breakdown").replaceChildren();
  if (catalog.state === "ok") {
    $("#catalog-breakdown").append(el("span", "", number(catalog.with_listing)), document.createTextNode(` con ficha Cults · ${number(catalog.count - catalog.with_listing)} pendientes`));
  } else $("#catalog-breakdown").textContent = "No se encuentra la carpeta de modelos.";
  filterCatalog();
}
function filterCatalog() {
  if (!dashboard) return;
  const term = $("#catalog-search").value.trim().toLocaleLowerCase("es");
  const matches = dashboard.catalog.items.filter(item => item.title.toLocaleLowerCase("es").includes(term) || item.id.toLocaleLowerCase("es").includes(term));
  const body = $("#catalog-items"); body.replaceChildren();
  for (const item of matches.slice(0, 80)) {
    const row = el("tr"); const state = item.invalid_listing ? "Ficha dañada" : item.has_listing ? "Preparada" : "Pendiente";
    row.append(el("td", "", item.title), el("td", item.has_listing ? "ok" : "pending", state), el("td", "", item.updated_at ? dateLabel(item.updated_at) : "—")); body.append(row);
  }
  if (!matches.length) { const row = el("tr"), cell = el("td", "empty", "No hay productos con ese nombre."); cell.colSpan = 3; row.append(cell); body.append(row); }
  $("#catalog-showing").textContent = `Mostrando ${number(Math.min(matches.length, 80))} de ${number(matches.length)} resultados${matches.length > 80 ? ". Acota la búsqueda para ver más." : "."}`;
}
async function load() {
  try {
    const response = await fetch("/api/summary");
    if (!response.ok) throw new Error("No se pudo leer el panel");
    dashboard = await response.json();
    renderProjects(dashboard); renderSales(dashboard); renderCatalog(dashboard);
  } catch (error) { $("#overall-status").textContent = error.message; $("#project-list").textContent = "No se pudieron cargar los datos. Recarga la página."; }
}
function csvHeader(text) {
  const line = text.replace(/^\uFEFF/, "").split(/\r?\n/)[0] || "";
  const separator = (line.match(/;/g) || []).length > (line.match(/,/g) || []).length ? ";" : ",";
  const cells = []; let value = "", quoted = false;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"' && quoted && line[i + 1] === '"') { value += '"'; i++; }
    else if (char === '"') quoted = !quoted;
    else if (char === separator && !quoted) { cells.push(value.trim()); value = ""; }
    else value += char;
  }
  cells.push(value.trim()); return cells;
}
function suggest(header, kind) {
  const patterns = {date:/fecha|date|sold|venta/i,product:/producto|product|design|diseño|model|modelo|nombre|name/i,amount:/ingreso|revenue|earning|net|amount|importe|precio|price/i,currency:/moneda|currency|divisa/i,id:/^id$|order|pedido|transaction|transacci/i};
  return header.find(value => patterns[kind].test(value)) || "";
}
$("#sales-file").addEventListener("change", async event => {
  const file = event.target.files[0];
  $("#import-message").textContent = "";
  if (!file) return;
  if (file.size > 5_000_000) { $("#import-message").textContent = "El CSV supera el límite de 5 MB."; return; }
  csvText = await file.text();
  const header = csvHeader(csvText);
  $("#file-label").textContent = file.name;
  for (const select of $("#column-mapping").querySelectorAll("select")) {
    select.replaceChildren();
    select.append(new Option(select.required ? "Elige una columna" : "No disponible / EUR", ""));
    for (const column of header) select.append(new Option(column, column));
    select.value = suggest(header, select.name);
  }
  $("#column-mapping").hidden = false;
});
$("#sales-import").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  const columns = Object.fromEntries([...event.currentTarget.querySelectorAll("select")].map(select => [select.name, select.value]));
  const message = $("#import-message"); button.disabled = true; message.textContent = "Importando…";
  try {
    const response = await fetch("/api/sales/import", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({csv:csvText,columns})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "No se pudo importar");
    message.textContent = `${number(result.added)} ventas añadidas; ${number(result.duplicates)} ya estaban registradas.`;
    await load();
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
$("#catalog-search").addEventListener("input", filterCatalog);
$("#refresh").addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true; $("#overall-status").textContent = "Consultando fuentes…";
  try { const response = await fetch("/api/refresh", {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}); if (!response.ok) throw new Error("Falló la actualización"); await load(); }
  catch (error) { $("#overall-status").textContent = error.message; }
  finally { button.disabled = false; }
});
load();
