/* Uses the same handlers as the family API. Credentials remain in the service. */
(() => {
  const form = document.querySelector('#analytics-form'), status = document.querySelector('#analytics-status'), output = document.querySelector('#analytics-results');
  let revision = 0, requestId = 0, applied = null, repeatDraft = null;
  const fields = () => ({...Object.fromEntries(new FormData(form)), date_from: form.elements.date_from.value, date_to: form.elements.date_to.value});
  const query = () => {
    const values = fields();
    return {project: values.project, site_id: values.site_id,
      date_range: values.date_range === 'custom' ? [values.date_from, values.date_to] : values.date_range,
      metrics: ['visitors', 'pageviews'], dimensions: values.dimension ? [values.dimension] : []};
  };
  function syncDates() {
    const custom = form.elements.date_range.value === 'custom';
    document.querySelector('#analytics-custom-dates').hidden = !custom;
    document.querySelector('#analytics-date-note').hidden = !custom;
    for (const input of [form.elements.date_from, form.elements.date_to]) { input.disabled = !custom; input.required = custom; }
  }
  function invalidate() {
    revision++; applied = null; repeatDraft = null; output.replaceChildren(); syncDates();
    status.textContent = 'Consulta modificada. Pulsa Consultar y guardar, o abre las consultas guardadas.';
  }
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  window.addEventListener('hashchange', () => { if (location.hash !== '#analitica') invalidate(); });
  syncDates();
  window.mercatorCopilot?.register('analytics', {
    context() {
      if (location.hash !== '#analitica') return null;
      return {active_objects: [], view: {editor: {kind: 'analytics-query', object_id: null,
        fields: fields(), query: query()}, analytics: {applied, repeating: repeatDraft ? {id: repeatDraft.id, project: repeatDraft.project, origin: repeatDraft.origin, query: repeatDraft.query} : null}}};
    },
    refresh() {
      if (location.hash === '#analitica') void history();
    },
  });
  const node = (tag, text) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; };
  async function request(path, body) {
    const response = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data;
  }
  function savedArgs(snapshot) {
    const {pagination = {}, ...body} = snapshot.query;
    return {...body, project: snapshot.project, page_size: pagination.limit ?? 1000, offset: pagination.offset ?? 0};
  }
  function repeatInfo(snapshot) {
    const info = node('p', `Captura de partida: ${snapshot.id} · ${snapshot.project} · Origen guardado: ${snapshot.origin}`);
    info.className = 'table-note'; info.style.overflowWrap = 'anywhere'; return info;
  }
  function repeat(snapshot) {
    repeatDraft = snapshot;
    return work('repeat', async args => [await request('/api/analytics/query', args)], savedArgs(snapshot), snapshot);
  }
  function show(rows) {
    output.replaceChildren();
    if (!rows.length) { output.append(node('p','No hay consultas guardadas.')); return; }
    for (const snapshot of rows) {
      const details = node('details'); details.open = rows.length === 1;
      details.append(node('summary',`${snapshot.project} · ${snapshot.query.site_id} · ${snapshot.observed_at}`));
      const identity = node('p', `Consulta guardada: ${snapshot.id}`); identity.style.overflowWrap = 'anywhere'; details.append(identity);
      details.append(node('p',`Origen de la captura: ${snapshot.origin} · Periodo: ${JSON.stringify(snapshot.query.date_range)}`));
      const wrap = node('div'); wrap.className = 'table-wrap'; const table = node('table');
      table.style.minWidth = `${(snapshot.query.dimensions.length + snapshot.query.metrics.length) * 120}px`;
      table.append(node('caption','Valores devueltos por Plausible'));
      const head = node('tr'); for (const name of [...snapshot.query.dimensions,...snapshot.query.metrics]) head.append(node('th',name));
      const thead = node('thead'); thead.append(head); table.append(thead); const tbody = node('tbody');
      for (const row of snapshot.response.results) { const tr = node('tr'); for (const value of [...row.dimensions,...row.metrics]) tr.append(node('td',value === null ? 'No disponible' : typeof value === 'object' ? JSON.stringify(value) : String(value))); tbody.append(tr); }
      table.append(tbody); wrap.append(table); details.append(wrap);
      const raw = node('details'); raw.append(node('summary','Consulta y respuesta completas')); const pre = node('pre',JSON.stringify(snapshot,null,2)); pre.style.whiteSpace='pre-wrap'; pre.style.overflowWrap='anywhere'; raw.append(pre); details.append(raw);
      const download = node('button','Exportar JSON'); download.type='button'; download.onclick=()=>{ const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'})); const a=node('a'); a.href=url; a.download=`plausible-${snapshot.id}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }; details.append(download);
      const again = node('button','Volver a consultar y guardar'); again.type = 'button'; again.className = 'batch-button'; again.onclick = () => void repeat(snapshot); details.append(again);
      const hint = node('p', 'Repetir usa la fuente configurada actualmente y puede consultar su API. Los periodos relativos se evalúan de nuevo; las fechas fijas se conservan. No cambia tu formulario.'); hint.className = 'table-note'; details.append(hint); output.append(details);
    }
  }
  async function work(mode, read, submitted = query(), source = null) {
    const id = ++requestId, version = revision;
    if (mode !== 'repeat') repeatDraft = null;
    applied = null; output.replaceChildren();
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    status.textContent = 'Consultando…';
    try {
      const rows = await read(submitted);
      if (id !== requestId || version !== revision) return;
      show(rows);
      if (source) output.append(repeatInfo(source));
      applied = {mode, project: submitted.project, ...(source ? {source_snapshot_id: source.id} : {}), snapshots: rows.map(row => ({id: row.id, query: row.query, observed_at: row.observed_at, origin: row.origin}))};
      status.textContent = mode === 'history' ? 'Consultas guardadas cargadas; hasta 20 últimas del proyecto.' : mode === 'repeat'
        ? rows[0].added ? 'Consulta repetida. Se ha guardado una captura distinta con el origen y la fecha indicados.' : 'Consulta repetida. Coincide con una captura existente: se conservan su ID y fecha originales, sin crear otro registro.'
        : 'Consulta completada y registrada.';
    } catch (error) {
      if (id === requestId && version === revision) {
        status.textContent = error.message;
        if (source) {
          output.append(repeatInfo(source));
          const retry = node('button', 'Reintentar consulta guardada'); retry.type = 'button'; retry.className = 'batch-button'; retry.onclick = () => void repeat(source); output.append(retry);
        }
      }
    }
    finally { if (id === requestId) for (const button of form.querySelectorAll('button')) button.disabled = false; }
  }
  const history = () => work('history', async submitted => (await request('/api/analytics/history?project=' + encodeURIComponent(submitted.project))).snapshots);
  form.onsubmit = event => { event.preventDefault(); void work('query', async submitted => [await request('/api/analytics/query', submitted)]); };
  document.querySelector('#analytics-history').onclick = history;
})();
