const $ = (selector, root = document) => root.querySelector(selector);
const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const STATUS_LABELS = {idea: "Idea", draft: "Borrador", scheduled: "Programada", published: "Publicada", archived: "Archivada"};
const METRIC_LABELS = {views: "Visualizaciones", likes: "Me gusta", comments: "Comentarios", shares: "Compartidos", saves: "Guardados", sales: "Ventas"};

const state = {meta: null, posts: [], view: "calendar", cal: "month", cursor: new Date(), platform: "", q: "", editing: null, csv: "", preview: null};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function number(value) { return new Intl.NumberFormat("es-ES").format(value); }
function money(value, currency) {
  try { return new Intl.NumberFormat("es-ES", {style: "currency", currency}).format(Number(value)); }
  catch { return `${value} ${currency}`; }
}
function pad(n) { return String(n).padStart(2, "0"); }
function dayKey(date) { return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`; }
function platformLabel(id) { return (state.meta.platforms.find(p => p.id === id) || {}).label || id; }
function platformMeta(id) { return state.meta.platforms.find(p => p.id === id) || {}; }
function postWhen(post) { return post.scheduled_at || post.published_at || ""; }
function postTime(post) { const w = postWhen(post); return w.length > 10 ? w.slice(11, 16) : ""; }
function toLocalInput(value) { return value ? (value.length > 10 ? value.slice(0, 16) : value + "T00:00") : ""; }
function say(text) { $("#pub-status").textContent = text; }

async function api(path, body, method) {
  const options = {method: method || (body === undefined ? "GET" : "POST"), headers: {}};
  if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.ok === false) throw new Error(result.error || "No se pudo completar la acción");
  return result;
}

function filtered() {
  const term = state.q.trim().toLocaleLowerCase("es");
  return state.posts.filter(post => (!state.platform || post.platform === state.platform)
    && (!term || [post.title, post.caption, post.hashtags.join(" "), post.notes].join(" ").toLocaleLowerCase("es").includes(term)));
}

async function load() {
  try {
    if (!state.meta) {
      state.meta = await api("/api/publishing/meta");
      for (const select of [$("#filter-platform"), $("[name=platform]", $("#editor-form")), $("#import-platform")]) {
        for (const platform of state.meta.platforms) select.append(new Option(platform.label, platform.id));
      }
      for (const status of state.meta.statuses) $("[name=status]", $("#editor-form")).append(new Option(STATUS_LABELS[status], status));
    }
    state.posts = (await api("/api/posts?limit=1000")).posts;
    say(`${number(state.posts.length)} publicaciones`);
    render();
  } catch (error) { say(error.message); }
}

function render() {
  for (const name of ["calendar", "board", "metrics"]) $("#view-" + name).hidden = state.view !== name;
  for (const button of document.querySelectorAll("[data-view]")) button.setAttribute("aria-selected", String(button.dataset.view === state.view));
  for (const button of document.querySelectorAll("[data-cal]")) button.setAttribute("aria-selected", String(button.dataset.cal === state.cal));
  if (state.view === "calendar") renderCalendar();
  else if (state.view === "board") renderBoard();
  else renderMetrics();
}

function chip(post) {
  const button = el("button", "chip st-" + post.status);
  button.type = "button";
  button.title = `${platformLabel(post.platform)} · ${STATUS_LABELS[post.status]}`;
  const time = postTime(post);
  if (time) button.append(el("small", "", time));
  button.append(document.createTextNode(post.title || post.caption.slice(0, 40) || post.media_ref || `#${post.id}`));
  button.addEventListener("click", () => openEditor(post));
  return button;
}

function monday(date) {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7));
  return copy;
}

function renderCalendar() {
  const grid = $("#cal-grid");
  grid.replaceChildren();
  grid.classList.toggle("week", state.cal === "week");
  const cursor = new Date(state.cursor.getFullYear(), state.cursor.getMonth(), state.cursor.getDate());
  let start, count;
  if (state.cal === "week") {
    start = monday(cursor); count = 7;
    const end = new Date(start); end.setDate(end.getDate() + 6);
    $("#cal-title").textContent = `${start.getDate()} ${start.toLocaleDateString("es-ES", {month: "short"})} – ${end.getDate()} ${end.toLocaleDateString("es-ES", {month: "short", year: "numeric"})}`;
  } else {
    start = monday(new Date(cursor.getFullYear(), cursor.getMonth(), 1)); count = 42;
    const title = cursor.toLocaleDateString("es-ES", {month: "long", year: "numeric"});
    $("#cal-title").textContent = title.charAt(0).toUpperCase() + title.slice(1);
  }
  for (const name of WEEKDAYS) grid.append(el("div", "cal-dow", name));
  const byDay = new Map();
  for (const post of filtered()) {
    const key = postWhen(post).slice(0, 10);
    if (key) (byDay.get(key) || byDay.set(key, []).get(key)).push(post);
  }
  const todayKey = dayKey(new Date());
  for (let i = 0; i < count; i++) {
    const day = new Date(start); day.setDate(start.getDate() + i);
    const key = dayKey(day);
    const cell = el("div", "cal-day" + (key === todayKey ? " today" : "") + (state.cal === "month" && day.getMonth() !== cursor.getMonth() ? " out" : ""));
    const top = el("div", "cal-top");
    top.append(el("span", "cal-num", String(day.getDate())));
    const add = el("button", "cal-add", "+");
    add.type = "button"; add.title = "Nueva publicación este día"; add.setAttribute("aria-label", `Nueva publicación el ${key}`);
    add.addEventListener("click", () => openEditor(null, {scheduled_at: key + "T10:00", status: "scheduled"}));
    top.append(add);
    cell.append(top);
    for (const post of (byDay.get(key) || []).sort((a, b) => postWhen(a).localeCompare(postWhen(b)))) cell.append(chip(post));
    grid.append(cell);
  }
}

function renderBoard() {
  const board = $("#board");
  board.replaceChildren();
  const order = state.meta.statuses;
  for (const status of order) {
    const column = el("div", "col");
    const posts = filtered().filter(post => post.status === status);
    const head = el("h3", "", STATUS_LABELS[status]);
    head.append(el("span", "", String(posts.length)));
    column.append(head);
    for (const post of posts) {
      const card = el("div", "card st-" + post.status);
      const title = el("h4", "", post.title || post.caption.slice(0, 60) || post.media_ref || `#${post.id}`);
      title.addEventListener("click", () => openEditor(post));
      const meta = el("div", "meta");
      meta.append(el("span", "badge-plat", platformLabel(post.platform)));
      const when = postWhen(post);
      if (when) meta.append(document.createTextNode(" " + when.replace("T", " ").slice(0, 16)));
      if (post.metrics_latest && post.metrics_latest.views != null) meta.append(document.createTextNode(` · ${number(post.metrics_latest.views)} visual.`));
      const move = el("div", "move");
      const index = order.indexOf(status);
      for (const [delta, label] of [[-1, "←"], [1, "→"]]) {
        const target = order[index + delta];
        const button = el("button", "ghost", label);
        button.type = "button"; button.disabled = !target;
        button.title = target ? `Mover a ${STATUS_LABELS[target]}` : "";
        button.addEventListener("click", () => moveTo(post, target));
        move.append(button);
      }
      card.append(title, meta, move);
      column.append(card);
    }
    board.append(column);
  }
}

async function moveTo(post, status) {
  if (status === "scheduled" && !post.scheduled_at) { openEditor(post, {status}); return; }
  try {
    const body = {post_id: post.id, status};
    if (status === "published" && !post.url) { openEditor(post, {status}); return; }
    await api("/api/posts", body);
    await load();
  } catch (error) { say(error.message); }
}

function bars(container, rows, labelOf) {
  container.replaceChildren();
  const max = Math.max(1, ...rows.map(row => row.avg_views));
  for (const row of rows) {
    const line = el("div", "bar-row");
    const track = el("div", "bar-track"), fill = el("div", "bar-fill");
    fill.style.width = `${row.avg_views / max * 100}%`;
    track.append(fill);
    line.append(el("span", "", labelOf(row)), track, el("span", "", `${number(row.avg_views)} · n=${row.posts}`));
    container.append(line);
  }
  if (!rows.length) container.append(el("p", "empty", "Aún no hay publicaciones publicadas con visualizaciones."));
}

function table(headers, rows, className) {
  const wrap = el("div", "table-wrap"), tableEl = el("table", className || "pub-table");
  const head = el("tr");
  for (const h of headers) head.append(el("th", "", h));
  const thead = el("thead"); thead.append(head); tableEl.append(thead);
  const body = el("tbody");
  for (const row of rows) { const tr = el("tr"); for (const cell of row) tr.append(el("td", "", cell)); body.append(tr); }
  tableEl.append(body); wrap.append(tableEl); return wrap;
}

async function renderMetrics() {
  try {
    const stats = await api("/api/posts/stats" + (state.platform ? `?platform=${state.platform}` : ""));
    const totals = $("#metrics-totals"); totals.replaceChildren();
    if (!stats.by_platform.length) totals.append(el("p", "empty", "Todavía no hay publicaciones. Crea una con «Nueva publicación» o importa un CSV."));
    else totals.append(table(["Plataforma", "Publicaciones", "Visualizaciones", "Me gusta", "Comentarios", "Compartidos", "Guardados", "Ventas", "Ingresos"],
      stats.by_platform.map(p => [p.label, `${p.published} / ${p.posts}`, number(p.views), number(p.likes), number(p.comments), number(p.shares), number(p.saves), number(p.sales),
        p.revenue.length ? p.revenue.map(r => money(r.amount, r.currency)).join(" · ") : "—"])));
    const hours = stats.best_hours;
    bars($("#best-weekday"), hours.by_weekday, row => WEEKDAYS[row.weekday]);
    bars($("#best-hour"), hours.by_hour, row => `${pad(row.hour)}:00`);
    $("#best-note").textContent = hours.sample
      ? `Media de visualizaciones de ${hours.sample} publicaciones publicadas, por día y hora de publicación.${hours.note === "few_posts" ? " Son pocas: tómalo como orientación, no como regla." : ""}`
      : "Hace falta publicar con visualizaciones registradas para calcular las mejores horas.";
    const slots = $("#best-slots"); slots.replaceChildren();
    if (hours.top_slots.length) slots.append(table(["Franja", "Visualizaciones (media)", "Publicaciones"],
      hours.top_slots.map(s => [`${WEEKDAYS[s.weekday]} ${pad(s.hour)}:00`, number(s.avg_views), String(s.posts)])));
    const top = $("#top-posts"); top.replaceChildren();
    top.append(stats.top_posts.length ? table(["Publicación", "Visualizaciones", "Plataforma"], stats.top_posts.map(p => [p.title || `#${p.id}`, number(p.views), platformLabel(p.platform)]))
      : el("p", "empty", "Sin visualizaciones registradas."));
  } catch (error) { say(error.message); }
}

// ---------------------------------------------------------------- editor

function editorForm() { return $("#editor-form"); }
function field(name) { return editorForm().elements[name]; }

function updateCounters() {
  const meta = platformMeta(field("platform").value);
  const tags = field("hashtags").value.split(/[\s,;]+/).map(t => t.replace(/^#+/, "")).filter(Boolean);
  const text = field("caption").value + (tags.length ? "\n\n" + tags.map(t => "#" + t).join(" ") : "");
  const set = (name, used, limit, unit) => {
    const node = $(`.counter[data-for=${name}]`);
    node.textContent = limit ? `${number(used)} / ${number(limit)} ${unit}` : `${number(used)} ${unit}`;
    node.classList.toggle("over", Boolean(limit) && used > limit);
  };
  set("caption", text.length, meta.caption_limit, "caracteres (texto + hashtags)");
  set("title", field("title").value.length, meta.title_limit, "caracteres");
  set("hashtags", tags.length, meta.hashtag_limit, "hashtags");
}

function showMedia(post) {
  const box = $("#media-preview"); box.replaceChildren(); box.hidden = true;
  const ref = field("media_ref").value.trim();
  if (!ref) return;
  box.hidden = false;
  const ext = ref.split(".").pop().toLowerCase();
  if (post && !ref.startsWith("hoard://")) {
    const url = `/api/posts/${post.id}/media?v=${encodeURIComponent(post.updated_at)}`;
    if (["png", "jpg", "jpeg", "webp", "gif"].includes(ext)) { const img = el("img"); img.src = url; img.alt = "Vista previa"; img.addEventListener("error", () => img.replaceWith(el("p", "ref", "No se puede mostrar el archivo (ruta no accesible desde este equipo).")), {once: true}); box.append(img); }
    else if (["mp4", "webm", "mov", "m4v"].includes(ext)) { const video = el("video"); video.src = url; video.controls = true; video.preload = "metadata"; box.append(video); }
    else box.append(el("p", "ref", ref));
  } else box.append(el("p", "ref", ref.startsWith("hoard://") ? `Referencia de otra app: ${ref}` : "La vista previa aparece al guardar."));
}

function openEditor(post, preset) {
  state.editing = post || null;
  const form = editorForm();
  form.reset();
  const values = post || {platform: state.platform || "instagram_reel", status: "idea", hashtags: [], ...(preset || {})};
  if (post && preset) Object.assign(values, preset);
  field("platform").value = values.platform;
  field("status").value = values.status;
  field("title").value = values.title || "";
  field("caption").value = values.caption || "";
  field("hashtags").value = (values.hashtags || []).map(t => "#" + t).join(" ");
  field("media_ref").value = values.media_ref || "";
  field("scheduled_at").value = toLocalInput(values.scheduled_at);
  field("published_at").value = toLocalInput(values.published_at);
  field("url").value = values.url || "";
  field("notes").value = values.notes || "";
  $("#editor-title").textContent = post ? `Publicación #${post.id}` : "Nueva publicación";
  $("#editor-message").textContent = "";
  $("#suggestions").hidden = true;
  for (const id of ["delete-post", "publish-post"]) $("#" + id).hidden = !post;
  $("#metrics-box").hidden = !post;
  updateCounters(); showMedia(post);
  if (post) loadMetrics(post.id);
  if (!$("#editor").open) $("#editor").showModal();
  if (post) history.replaceState(null, "", "#post-" + post.id);
}

function formBody() {
  const body = {platform: field("platform").value, status: field("status").value, title: field("title").value, caption: field("caption").value,
    hashtags: field("hashtags").value, media_ref: field("media_ref").value, scheduled_at: field("scheduled_at").value || null,
    published_at: field("published_at").value || null, url: field("url").value, notes: field("notes").value};
  if (state.editing) body.post_id = state.editing.id;
  return body;
}

async function savePost(extra) {
  const message = $("#editor-message");
  try {
    const result = await api("/api/posts", {...formBody(), ...(extra || {})});
    state.editing = result.post;
    message.textContent = "Guardado.";
    await load();
    openEditor(result.post);
    $("#editor-message").textContent = "Guardado.";
  } catch (error) { message.textContent = error.message; }
}

async function loadMetrics(postId) {
  const data = await api(`/api/posts/${postId}`);
  const rows = data.post.metrics;
  const body = $("#metric-rows"); body.replaceChildren();
  for (const m of rows.slice().reverse()) {
    const tr = el("tr");
    const cells = [new Date(m.ts).toLocaleString("es-ES", {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"}),
      ...["views", "likes", "comments", "shares", "saves", "sales"].map(k => m[k] == null ? "—" : number(m[k])),
      m.revenue == null ? "—" : money(m.revenue, m.currency || "EUR")];
    for (const c of cells) tr.append(el("td", "", c));
    body.append(tr);
  }
  if (!rows.length) { const tr = el("tr"), td = el("td", "empty", "Sin lecturas todavía."); td.colSpan = 8; tr.append(td); body.append(tr); }
  const pick = $("#metric-pick");
  if (!pick.options.length) for (const [key, label] of Object.entries(METRIC_LABELS)) pick.append(new Option(label, key));
  drawChart(rows, pick.value || "views");
}

function drawChart(rows, key) {
  const box = $("#metric-chart"); box.replaceChildren();
  const points = rows.filter(r => r[key] != null).map(r => ({t: new Date(r.ts).getTime(), v: r[key]}));
  if (points.length < 2) { box.append(el("p", "empty", points.length ? "Con una sola lectura no hay evolución que dibujar." : "Sin lecturas de esta métrica.")); return; }
  const ns = "http://www.w3.org/2000/svg", W = 600, H = 150, M = 24;
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `Evolución de ${METRIC_LABELS[key]}`);
  const t0 = points[0].t, t1 = points[points.length - 1].t || t0 + 1, vmax = Math.max(...points.map(p => p.v), 1);
  const x = t => M + (t - t0) / Math.max(1, t1 - t0) * (W - 2 * M), y = v => H - M - v / vmax * (H - 2 * M);
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", points.map(p => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" "));
  line.setAttribute("fill", "none"); line.setAttribute("stroke", "currentColor"); line.setAttribute("stroke-width", "2");
  svg.append(line);
  for (const p of points) {
    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", x(p.t)); dot.setAttribute("cy", y(p.v)); dot.setAttribute("r", "3"); dot.setAttribute("fill", "currentColor");
    const title = document.createElementNS(ns, "title"); title.textContent = `${number(p.v)} · ${new Date(p.t).toLocaleString("es-ES")}`;
    dot.append(title); svg.append(dot);
  }
  for (const [value, ypos] of [[vmax, M - 6], [0, H - M + 14]]) {
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", 4); label.setAttribute("y", ypos); label.setAttribute("font-size", "10"); label.setAttribute("fill", "currentColor"); label.textContent = number(value);
    svg.append(label);
  }
  svg.style.color = "var(--mint)";
  box.append(svg);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const area = el("textarea"); area.value = text; document.body.append(area); area.select();
    const ok = document.execCommand && document.execCommand("copy"); area.remove(); return Boolean(ok);
  }
}

// ---------------------------------------------------------------- import

function setupImport() {
  $("#open-import").addEventListener("click", () => {
    state.csv = ""; state.preview = null;
    $("#import-file").value = ""; $("#import-file-label").textContent = "Elegir archivo CSV";
    $("#import-mapping").hidden = true; $("#import-preset").textContent = ""; $("#import-message").textContent = ""; $("#import-go").disabled = true;
    $("#importer").showModal();
  });
  $("#import-close").addEventListener("click", () => $("#importer").close());
  $("#import-file").addEventListener("change", async event => {
    const file = event.target.files[0];
    if (!file) return;
    $("#import-message").textContent = "";
    if (file.size > 4_000_000) { $("#import-message").textContent = "El CSV supera el límite de 4 MB."; return; }
    state.csv = await file.text();
    $("#import-file-label").textContent = file.name;
    await previewImport();
  });
  $("#import-platform").addEventListener("change", () => { if (state.csv) previewImport(); });
  $("#import-form").addEventListener("submit", async event => {
    event.preventDefault();
    const mapping = {};
    for (const select of $("#import-mapping").querySelectorAll("select")) if (select.value) mapping[select.name] = select.value;
    if (state.preview && state.preview.mapping.currency_default && !mapping.currency) mapping.currency_default = state.preview.mapping.currency_default;
    const message = $("#import-message"); message.textContent = "Importando…"; $("#import-go").disabled = true;
    try {
      const r = await api("/api/posts/import", {csv: state.csv, platform: $("#import-platform").value, mapping});
      message.textContent = `${r.created} nuevas, ${r.updated} actualizadas, ${r.snapshots} lecturas guardadas, ${r.unchanged} sin cambios`
        + (r.skipped.length ? `, ${r.skipped.length} filas omitidas` : "") + (r.warnings.length ? `. Avisos: ${r.warnings.slice(0, 3).join("; ")}` : ".");
      await load();
    } catch (error) { message.textContent = error.message; }
    finally { $("#import-go").disabled = false; }
  });
}

async function previewImport() {
  try {
    const p = await api("/api/posts/import/preview", {csv: state.csv, platform: $("#import-platform").value});
    state.preview = p;
    const names = {youtube_studio: "YouTube Studio", instagram: "Instagram", tiktok: "TikTok", generic: "genérico"};
    $("#import-preset").textContent = `Formato reconocido: ${names[p.preset] || p.preset}. ${number(p.rows)} filas. Revisa la asignación de columnas.`;
    if (p.preset !== "generic" && !$("#import-platform").dataset.touched && p.platform) $("#import-platform").value = p.platform;
    const labels = {external_id: "Identificador", title: "Título", caption: "Texto", published_at: "Fecha de publicación", url: "URL", views: "Visualizaciones",
      likes: "Me gusta", comments: "Comentarios", shares: "Compartidos", saves: "Guardados", sales: "Ventas", revenue: "Ingresos", currency: "Moneda"};
    const box = $("#import-mapping"); box.replaceChildren();
    for (const [name, text] of Object.entries(labels)) {
      const label = el("label", "", text), select = el("select"); select.name = name;
      select.append(new Option("— no usar —", ""));
      for (const column of p.header) select.append(new Option(column, column));
      select.value = p.mapping[name] || "";
      label.append(select); box.append(label);
    }
    box.hidden = false; $("#import-go").disabled = false;
  } catch (error) { $("#import-message").textContent = error.message; $("#import-go").disabled = true; }
}

// ---------------------------------------------------------------- wiring

function wire() {
  for (const button of document.querySelectorAll("[data-view]")) button.addEventListener("click", () => { state.view = button.dataset.view; render(); });
  for (const button of document.querySelectorAll("[data-cal]")) button.addEventListener("click", () => { state.cal = button.dataset.cal; render(); });
  const shift = delta => {
    const c = state.cursor;
    state.cursor = state.cal === "week" ? new Date(c.getFullYear(), c.getMonth(), c.getDate() + 7 * delta) : new Date(c.getFullYear(), c.getMonth() + delta, 1);
    render();
  };
  $("#cal-prev").addEventListener("click", () => shift(-1));
  $("#cal-next").addEventListener("click", () => shift(1));
  $("#cal-today").addEventListener("click", () => { state.cursor = new Date(); render(); });
  $("#filter-platform").addEventListener("change", event => { state.platform = event.target.value; render(); });
  $("#filter-q").addEventListener("input", event => { state.q = event.target.value; render(); });
  $("#new-post").addEventListener("click", () => openEditor(null));
  $("#editor-close").addEventListener("click", () => $("#editor").close());
  $("#editor").addEventListener("close", () => { if (location.hash.startsWith("#post-")) history.replaceState(null, "", location.pathname); });
  $("#import-platform").addEventListener("change", () => { $("#import-platform").dataset.touched = "1"; });
  for (const name of ["platform", "title", "caption", "hashtags"]) field(name).addEventListener("input", updateCounters);
  field("media_ref").addEventListener("change", () => showMedia(state.editing));
  editorForm().addEventListener("submit", event => { event.preventDefault(); savePost(); });
  $("#copy-post").addEventListener("click", async () => {
    const tags = field("hashtags").value.split(/[\s,;]+/).map(t => t.replace(/^#+/, "")).filter(Boolean).map(t => "#" + t).join(" ");
    const text = [field("caption").value.trim(), tags].filter(Boolean).join("\n\n");
    $("#editor-message").textContent = (await copyText(text)) ? "Texto copiado." : "No se pudo copiar; selecciónalo a mano.";
  });
  $("#publish-post").addEventListener("click", () => {
    if (!field("url").value.trim() && !confirm("No has puesto la URL de la publicación. ¿Marcarla como publicada igualmente?")) return;
    savePost({status: "published", published_at: field("published_at").value || dayKey(new Date()) + "T" + pad(new Date().getHours()) + ":" + pad(new Date().getMinutes())});
  });
  $("#delete-post").addEventListener("click", async () => {
    if (!state.editing || !confirm("¿Borrar esta publicación y sus métricas? No se puede deshacer (puedes archivarla en su lugar).")) return;
    try { await api("/api/posts/delete", {post_id: state.editing.id}); $("#editor").close(); await load(); }
    catch (error) { $("#editor-message").textContent = error.message; }
  });
  $("#suggest-post").addEventListener("click", async () => {
    const message = $("#editor-message"), list = $("#suggestions");
    message.textContent = "Consultando un modelo local…";
    try {
      const body = state.editing ? {post_id: state.editing.id, platform: field("platform").value} : {title: field("title").value, platform: field("platform").value};
      if (state.editing && !field("title").value && !field("notes").value) throw new Error("Escribe un título o notas para dar contexto.");
      if (state.editing) { body.title = field("title").value; body.notes = field("notes").value; }
      const r = await api("/api/posts/caption", body);
      list.replaceChildren();
      for (const text of r.suggestions) {
        const item = el("li"), use = el("button", "ghost", "Usar este texto");
        use.type = "button";
        use.addEventListener("click", () => { field("caption").value = text; updateCounters(); });
        item.append(el("span", "", text), use); list.append(item);
      }
      list.hidden = false; message.textContent = r.note;
    } catch (error) { message.textContent = error.message; list.hidden = true; }
  });
  $("#metric-pick").addEventListener("change", () => { if (state.editing) loadMetrics(state.editing.id); });
  $("#metric-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget, body = {post_id: state.editing.id}, message = $("#metric-message");
    for (const input of form.querySelectorAll("input")) if (input.value.trim()) body[input.name] = input.value.trim();
    if (!body.revenue) delete body.currency;
    try {
      await api("/api/posts/metrics", body);
      for (const input of form.querySelectorAll("input")) if (input.name !== "currency") input.value = "";
      message.textContent = "Lectura añadida.";
      await loadMetrics(state.editing.id); await load();
    } catch (error) { message.textContent = error.message; }
  });
  setupImport();
  window.addEventListener("hashchange", openFromHash);
}

function openFromHash() {
  const match = location.hash.match(/^#post-(\d+)$/);
  if (!match) return;
  const post = state.posts.find(p => p.id === Number(match[1]));
  if (post && !$("#editor").open) openEditor(post);
}

wire();
load().then(openFromHash);
