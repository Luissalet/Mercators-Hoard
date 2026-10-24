const $ = (selector) => document.querySelector(selector);
let dashboard = null;
let csvText = "";
let dashboardRequest = 0;
let latestBatch = "", importedBatch = "", batchId = "", batchResult = null, batchPage = 0, batchRequest = 0;
const BATCH_PAGE_SIZE = 50;
const CATALOG_PAGE_SIZE = 50;
let catalogRequest = 0, catalogResult = null, catalogApplied = null, catalogAttempt = null;
let catalogDirty = false, catalogBusy = false;

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
  setLatestBatch(data.last_sales_import?.batch || "");
  $("#sales-batch-legacy").hidden = !data.last_sales_import || !!data.last_sales_import.batch;
  $("#sales-count").textContent = `${number(data.sales_count)} ventas`;
  $("#last-import").textContent = data.last_sales_import
    ? `Última importación: ${dateLabel(data.last_sales_import.imported_at)} · ${number(data.last_sales_import.added)} ${data.last_sales_import.added === 1 ? "venta nueva" : "nuevas ventas"}`
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
function closeSalesBatch() {
  batchRequest++; batchId = ""; batchResult = null; batchPage = 0;
  $("#sales-batch-panel").hidden = true;
  $("#sales-batch-result").replaceChildren();
}
function setLatestBatch(id) {
  if (id !== latestBatch) {
    latestBatch = id; importedBatch = "";
    $("#sales-batch-imported").hidden = true;
    closeSalesBatch();
  }
  $("#sales-batch-last").hidden = !id;
}
function renderSalesBatch() {
  const data = batchResult, result = $("#sales-batch-result");
  result.replaceChildren();
  const meta = el("p", "sales-batch-meta", `Fuente registrada: ${data.source} · Importado: ${dateLabel(data.imported_at)} · Filas procesadas del CSV: ${number(data.rows)} · Ventas añadidas: ${number(data.count)}`);
  meta.title = data.imported_at; result.append(meta);
  const totals = el("div", "sales-batch-currencies");
  for (const item of data.by_currency) totals.append(el("span", "", `${item.income} ${item.currency} añadidos`));
  result.append(totals, el("p", "sales-batch-note", "Sólo las ventas nuevas de esta importación; las ya registradas quedan fuera. Importes del CSV por moneda, sin conversión ni cálculo de beneficio o cobro."));
  const lines = data.lines.slice(batchPage * BATCH_PAGE_SIZE, (batchPage + 1) * BATCH_PAGE_SIZE);
  if (!data.count) result.append(el("p", "empty", "No se añadieron ventas nuevas en este lote."));
  else {
    const wrap = el("div", "table-wrap"), table = el("table", "sales-batch-table"), head = el("thead"), heading = el("tr"), body = el("tbody");
    wrap.tabIndex = 0; wrap.setAttribute("role", "region"); wrap.setAttribute("aria-label", "Ventas añadidas en este lote");
    table.append(el("caption", "", "Líneas del lote: el número no es la fila original del CSV; el ID es local, no el pedido de Cults."));
    for (const label of ["Línea del lote", "ID local", "Fecha de venta", "Producto", "Importe", "Moneda"]) heading.append(el("th", "", label));
    head.append(heading);
    for (const line of lines) {
      const row = el("tr"); row.dataset.batchLine = String(line.line);
      for (const value of [line.line, line.id, line.sold_at, line.product, line.amount, line.currency]) row.append(el("td", "", value));
      body.append(row);
    }
    table.append(head, body); wrap.append(table); result.append(wrap);
  }
  $("#sales-batch-pager").hidden = !data.count;
  $("#sales-batch-showing").textContent = lines.length ? `Líneas ${lines[0].line}–${lines.at(-1).line} de ${number(data.count)}` : "";
  $("#sales-batch-prev").disabled = batchPage === 0;
  $("#sales-batch-next").disabled = (batchPage + 1) * BATCH_PAGE_SIZE >= data.count;
}
async function openSalesBatch(id) {
  if (!id) return;
  const version = ++batchRequest;
  if (batchId !== id) { batchResult = null; batchPage = 0; $("#sales-batch-result").replaceChildren(); }
  batchId = id;
  $("#sales-batch-panel").hidden = false;
  $("#sales-batch-id").textContent = `Lote ${id}`;
  $("#sales-batch-status").textContent = "Leyendo el lote guardado…";
  $("#sales-batch-error").hidden = true; $("#sales-batch-retry").hidden = true; $("#sales-batch-pager").hidden = true;
  $("#sales-batch-title").focus();
  try {
    const response = await fetch("/api/sales/batch?" + new URLSearchParams({batch:id}));
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || "No se pudo leer el lote.");
    if (version !== batchRequest) return;
    batchResult = data; batchPage = 0; renderSalesBatch();
    $("#sales-batch-status").textContent = "Lote guardado consultado.";
  } catch (error) {
    if (version !== batchRequest) return;
    $("#sales-batch-status").textContent = "";
    $("#sales-batch-error").textContent = error.message; $("#sales-batch-error").hidden = false;
    $("#sales-batch-retry").hidden = false;
  }
}
$("#sales-batch-last").onclick = () => { void openSalesBatch(latestBatch); };
$("#sales-batch-imported").onclick = () => { void openSalesBatch(importedBatch); };
$("#sales-batch-close").onclick = () => { closeSalesBatch(); $("#sales-batch-last").focus(); };
$("#sales-batch-retry").onclick = () => { void openSalesBatch(batchId); };
$("#sales-batch-prev").onclick = () => { batchPage--; renderSalesBatch(); };
$("#sales-batch-next").onclick = () => { batchPage++; renderSalesBatch(); };
function renderCatalog(data) {
  const catalog = data.catalog;
  $("#catalog-count").textContent = catalog.state === "ok" ? `${number(catalog.count)} productos` : "Catálogo sin acceso";
  $("#catalog-breakdown").replaceChildren();
  if (catalog.state === "ok") {
    $("#catalog-breakdown").append(el("span", "", number(catalog.with_listing)), document.createTextNode(` con ficha Cults · ${number(catalog.count - catalog.with_listing)} pendientes`));
  } else $("#catalog-breakdown").textContent = "No se encuentra la carpeta de modelos.";
  if (!catalogDirty && !catalogBusy) void readCatalog(catalogAttempt?.args.offset || 0, catalogAttempt?.fields || catalogFields());
}
function catalogFields() { return {query: $("#catalog-search").value, mode: $("#catalog-mode").value}; }
function catalogButtons(busy) {
  catalogBusy = busy;
  $("#catalog-apply").disabled = busy;
  $("#catalog-prev").disabled = busy || !catalogResult || catalogResult.offset === 0;
  $("#catalog-next").disabled = busy || !catalogResult || catalogResult.offset + catalogResult.items.length >= catalogResult.total;
  $("#catalog-items").setAttribute("aria-busy", String(busy));
}
function clearCatalog(text) {
  catalogResult = null; catalogApplied = null;
  $("#catalog-items").replaceChildren(); $("#catalog-showing").textContent = "";
  $("#catalog-status").textContent = text; $("#catalog-retry").hidden = true;
  catalogButtons(false);
}
function changeCatalog() {
  catalogRequest++; catalogDirty = true; catalogAttempt = null;
  clearCatalog("Consulta modificada. Pulsa Filtrar para aplicar los cambios.");
}
function showCatalog(data) {
  const body = $("#catalog-items"); body.replaceChildren();
  for (const item of data.items) {
    const row = el("tr"), product = el("td", "", item.title);
    product.append(el("small", "catalog-id", `ID local: ${item.id}`));
    const label = item.invalid_listing ? "Formato dañado" : item.has_listing ? "Ficha local" : "Sin ficha";
    const changed = el("td", "", item.updated_at ? dateLabel(item.updated_at) : "—");
    if (item.updated_at) changed.title = item.updated_at;
    row.append(product, el("td", item.invalid_listing || !item.has_listing ? "pending" : "ok", label), el("td", "", item.tags ?? "—"), changed);
    body.append(row);
  }
  if (!data.items.length) {
    const row = el("tr"), cell = el("td", "empty", data.state !== "ok" ? "No hay acceso a la carpeta ni fichas importadas disponibles." : data.total ? "No hay filas en esta página. Vuelve a la anterior o aplica de nuevo los filtros." : "No hay productos que coincidan con esta consulta.");
    cell.colSpan = 4; row.append(cell); body.append(row);
  }
  $("#catalog-showing").textContent = data.items.length ? `Resultados ${number(data.offset + 1)}–${number(data.offset + data.items.length)} de ${number(data.total)}` : `${number(data.total)} coincidencias`;
}
async function readCatalog(offset = 0, fields = catalogFields()) {
  const request = ++catalogRequest;
  const args = {query: fields.query, untagged: fields.mode === "untagged", missing: fields.mode === "missing", offset, limit: CATALOG_PAGE_SIZE};
  catalogAttempt = {fields: {...fields}, args}; catalogDirty = false;
  clearCatalog("Leyendo las fichas locales…"); catalogButtons(true);
  try {
    const response = await fetch("/api/catalog?" + new URLSearchParams(args));
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || "No se pudo leer el catálogo.");
    if (request !== catalogRequest) return;
    catalogResult = data;
    catalogApplied = {fields: {...fields}, ...args, state: data.state, total: data.total, ids: data.items.map(item => item.id)};
    showCatalog(data);
    $("#catalog-status").textContent = data.state === "ok" ? "Consulta local completada." : "Catálogo sin acceso. Revisa la carpeta configurada o las fichas importadas y reintenta.";
    $("#catalog-retry").hidden = data.state === "ok";
  } catch (error) {
    if (request !== catalogRequest) return;
    $("#catalog-status").textContent = error.message;
    $("#catalog-retry").hidden = false;
  } finally { if (request === catalogRequest) catalogButtons(false); }
}
async function load() {
  const version = ++dashboardRequest;
  try {
    const response = await fetch("/api/summary");
    if (!response.ok) throw new Error("No se pudo leer el panel");
    const data = await response.json();
    if (version !== dashboardRequest) return;
    dashboard = data;
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
    message.textContent = `${number(result.added)} ${result.added === 1 ? "venta añadida" : "ventas añadidas"}; ${number(result.duplicates)} ${result.duplicates === 1 ? "ya estaba registrada" : "ya estaban registradas"}.`;
    setLatestBatch(result.batch); importedBatch = result.batch;
    $("#sales-batch-imported").hidden = !importedBatch;
    await load();
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
$("#catalog-filters").addEventListener("submit", event => { event.preventDefault(); void readCatalog(); });
$("#catalog-search").addEventListener("input", changeCatalog);
$("#catalog-mode").addEventListener("change", changeCatalog);
$("#catalog-retry").onclick = () => { if (catalogAttempt) void readCatalog(catalogAttempt.args.offset, catalogAttempt.fields); };
$("#catalog-prev").onclick = () => { if (catalogResult && catalogApplied) void readCatalog(Math.max(0, catalogResult.offset - CATALOG_PAGE_SIZE), catalogApplied.fields); };
$("#catalog-next").onclick = () => { if (catalogResult && catalogApplied) void readCatalog(catalogResult.offset + CATALOG_PAGE_SIZE, catalogApplied.fields); };
$("#refresh").addEventListener("click", async event => {
  const button = event.currentTarget; button.disabled = true; $("#overall-status").textContent = "Consultando fuentes…";
  try { const response = await fetch("/api/refresh", {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}); if (!response.ok) throw new Error("Falló la actualización"); await load(); }
  catch (error) { $("#overall-status").textContent = error.message; }
  finally { button.disabled = false; }
});
window.mercatorCopilot?.register('dashboard', {
  context() {
    if (location.hash === '#ventas') return {active_objects: [], view: {sales_batch: batchId && !$('#sales-batch-panel').hidden ? {batch:batchId,page:batchPage+1} : null, editor: {
      kind: 'sales-import', object_id: null, dirty: Boolean(csvText), fields: {
        filename: $("#sales-file").files[0]?.name || null,
        mapping: Object.fromEntries([...$("#column-mapping").querySelectorAll('select')]
          .map(select => [select.name, select.value]))}}}};
    if (location.hash === '#catalogo') return {active_objects: [],
      view: {catalog: {draft: catalogFields(), pending: catalogDirty, loading: catalogBusy, requested: catalogAttempt?.args || null, applied: catalogApplied}}};
    return null;
  },
  refresh() { void load(); },
});
load();
