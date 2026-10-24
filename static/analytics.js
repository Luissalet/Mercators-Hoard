/* Uses the same handlers as the family API. Credentials remain in the service. */
(() => {
  const form = document.querySelector('#analytics-form'), status = document.querySelector('#analytics-status'), output = document.querySelector('#analytics-results');
  let revision = 0, requestId = 0, applied = null;
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
    revision++; applied = null; output.replaceChildren(); syncDates();
    status.textContent = 'Consulta modificada. Pulsa Consultar y guardar, o abre las consultas guardadas.';
  }
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  syncDates();
  window.mercatorCopilot?.register('analytics', {
    context() {
      if (location.hash !== '#analitica') return null;
      return {active_objects: [], view: {editor: {kind: 'analytics-query', object_id: null,
        fields: fields(), query: query()}, analytics: {applied}}};
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
  function show(rows) {
    output.replaceChildren();
    if (!rows.length) { output.append(node('p','No hay consultas guardadas.')); return; }
    for (const snapshot of rows) {
      const details = node('details'); details.open = rows.length === 1;
      details.append(node('summary',`${snapshot.project} · ${snapshot.query.site_id} · ${snapshot.observed_at}`));
      const identity = node('p', `Consulta guardada: ${snapshot.id}`); identity.style.overflowWrap = 'anywhere'; details.append(identity);
      details.append(node('p',`${snapshot.origin} · Periodo: ${JSON.stringify(snapshot.query.date_range)}`));
      const wrap = node('div'); wrap.className = 'table-wrap'; const table = node('table');
      table.append(node('caption','Valores devueltos por Plausible'));
      const head = node('tr'); for (const name of [...snapshot.query.dimensions,...snapshot.query.metrics]) head.append(node('th',name));
      const thead = node('thead'); thead.append(head); table.append(thead); const tbody = node('tbody');
      for (const row of snapshot.response.results) { const tr = node('tr'); for (const value of [...row.dimensions,...row.metrics]) tr.append(node('td',value === null ? 'No disponible' : typeof value === 'object' ? JSON.stringify(value) : String(value))); tbody.append(tr); }
      table.append(tbody); wrap.append(table); details.append(wrap);
      const raw = node('details'); raw.append(node('summary','Consulta y respuesta completas')); const pre = node('pre',JSON.stringify(snapshot,null,2)); pre.style.whiteSpace='pre-wrap'; pre.style.overflowWrap='anywhere'; raw.append(pre); details.append(raw);
      const download = node('button','Exportar JSON'); download.type='button'; download.onclick=()=>{ const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'})); const a=node('a'); a.href=url; a.download=`plausible-${snapshot.id}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }; details.append(download); output.append(details);
    }
  }
  async function work(mode, read) {
    const id = ++requestId, version = revision, submitted = query();
    applied = null; output.replaceChildren();
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    status.textContent = 'Consultando…';
    try {
      const rows = await read(submitted);
      if (id !== requestId || version !== revision) return;
      show(rows);
      applied = {mode, project: submitted.project, snapshots: rows.map(row => ({id: row.id, query: row.query, observed_at: row.observed_at, origin: row.origin}))};
      status.textContent = mode === 'history' ? 'Consultas guardadas cargadas; hasta 20 últimas del proyecto.' : 'Consulta completada y registrada.';
    } catch (error) { if (id === requestId && version === revision) status.textContent = error.message; }
    finally { if (id === requestId) for (const button of form.querySelectorAll('button')) button.disabled = false; }
  }
  const history = () => work('history', async submitted => (await request('/api/analytics/history?project=' + encodeURIComponent(submitted.project))).snapshots);
  form.onsubmit = event => { event.preventDefault(); void work('query', async submitted => [await request('/api/analytics/query', submitted)]); };
  document.querySelector('#analytics-history').onclick = history;
})();
